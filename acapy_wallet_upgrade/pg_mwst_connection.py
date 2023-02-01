import base64
from typing import Optional

from asyncpg import Connection
import asyncpg

from .error import UpgradeError
from .pg_connection import PgConnection, PgWallet


class PgMWSTConnection(PgConnection):
    """Postgres connection in MultiWalletSingeTable
    management mode."""

    DB_TYPE = "pgsql_mwst"

    async def connect(self):
        """Accessor for the connection pool instance."""
        if not self._conn:
            self._conn = await self.connect_create_if_not_exists(self.parsed_url)

    async def connect_create_if_not_exists(self, parts):
        try:
            conn = await asyncpg.connect(
                host=parts.hostname,
                port=parts.port or 5432,
                user=parts.username,
                password=parts.password,
                database=parts.path[1:],
            )
        except asyncpg.InvalidCatalogNameError:
            # Database does not exist, create it.
            sys_conn = await asyncpg.connect(
                host=parts.hostname,
                port=parts.port or 5432,
                user=parts.username,
                password=parts.password,
                database="template1",
            )
            await sys_conn.execute(
                f'CREATE DATABASE "{parts.path[1:]}" OWNER "{parts.username}"'
            )
            await sys_conn.close()

            # Connect to the newly created database.
            conn = await asyncpg.connect(
                host=parts.hostname,
                port=parts.port or 5432,
                user=parts.username,
                password=parts.password,
                database=parts.path[1:],
            )

        return conn

    async def pre_upgrade(self):
        """Add new tables and columns."""
        await self._conn.execute(
            """
            BEGIN TRANSACTION;
            CREATE TABLE config (
                name TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (name)
            );
            CREATE TABLE profiles (
                id BIGSERIAL,
                name TEXT NOT NULL,
                reference TEXT NULL,
                profile_key BYTEA NULL,
                PRIMARY KEY (id)
            );
            CREATE UNIQUE INDEX ix_profile_name ON profiles (name);
            CREATE TABLE items (
                id BIGSERIAL,
                profile_id BIGINT NOT NULL,
                kind SMALLINT NOT NULL,
                category BYTEA NOT NULL,
                name BYTEA NOT NULL,
                value BYTEA NOT NULL,
                expiry TIMESTAMP NULL,
                PRIMARY KEY(id),
                FOREIGN KEY (profile_id) REFERENCES profiles (id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            );
            CREATE UNIQUE INDEX ix_items_uniq ON items
                (profile_id, kind, category, name);
            CREATE TABLE items_tags (
                id BIGSERIAL,
                item_id BIGINT NOT NULL,
                name BYTEA NOT NULL,
                value BYTEA NOT NULL,
                plaintext SMALLINT NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY (item_id) REFERENCES items (id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            );
            CREATE INDEX ix_items_tags_item_id ON items_tags(item_id);
            CREATE INDEX ix_items_tags_name_enc
                ON items_tags(name, SUBSTR(value, 1, 12)) include (item_id)
                WHERE plaintext=0;
            CREATE INDEX ix_items_tags_name_plain
                ON items_tags(name, value) include (item_id)
                WHERE plaintext=1;
            COMMIT;
            """
        )

    async def finish_upgrade(self):
        """Complete the upgrade."""

        await self._conn.execute(
            """
            INSERT INTO config (name, value) VALUES ('version', 1);
            """
        )

    def get_wallet(
        self, old_conn: Connection, wallet_id: str
    ) -> "PgMWSTProfilesWallet":
        return PgMWSTProfilesWallet(old_conn, self._conn, wallet_id, "items")


class PgMWSTWallet(PgWallet):
    def __init__(
        self, conn: Connection, wallet_id: str, profile_id: Optional[str] = None
    ):
        self._conn = conn
        self._wallet_id = wallet_id
        self._profile_id = profile_id

    @property
    def profile_id(self):
        if not self._profile_id:
            raise UpgradeError("Profile has not been initialized")
        return self._profile_id

    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""
        async with self._conn.transaction():
            id_row = await self._conn.fetch(
                """
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                    ON CONFLICT DO NOTHING RETURNING id
                """,
                name,
                key,
            )
            self._profile_id = id_row[0][0]
            return self._profile_id

    async def get_metadata(self):
        stmt = await self._conn.fetch(
            "SELECT value FROM metadata WHERE wallet_id = $1", (self._wallet_id)
        )
        found = None
        if stmt != "":
            for row in stmt:
                decoded = base64.b64decode(bytes.decode(row[0]))
                if found is None:
                    found = decoded
                else:
                    raise Exception("Found duplicate row")
            return found

        else:
            raise Exception("Row not found")

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items by wallet_id."""
        while True:
            stmt = await self._conn.fetch(
                """
                SELECT i.id, i.type, i.name, i.value, i.key,
                (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                    FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
                (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                    FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
                FROM items_old i WHERE i.wallet_id = $2 LIMIT $1;
                """,  # noqa
                limit,
                self._wallet_id,
            )
            if not stmt:
                break
            yield stmt

    async def update_items(self, items):
        """Update items in the database."""
        del_ids = []
        for item in items:
            del_ids = item["id"]
            async with self._conn.transaction():
                ins = await self._conn.fetch(
                    """
                        INSERT INTO items (profile_id, kind, category, name, value)
                        VALUES ($1, 2, $2, $3, $4) RETURNING id
                    """,
                    self._profile_id,
                    item["category"],
                    item["name"],
                    item["value"],
                )
                item_id = ins[0][0]
                if item["tags"]:
                    await self._conn.executemany(
                        """
                            INSERT INTO items_tags (item_id, plaintext, name, value)
                            VALUES ($1, $2, $3, $4)
                        """,
                        ((item_id, *tag) for tag in item["tags"]),
                    )
                await self._conn.execute(
                    "DELETE FROM items_old WHERE id IN ($1)", del_ids
                )


class PgMWSTProfilesWallet(PgWallet):
    def __init__(
        self,
        old_conn: asyncpg.Connection,
        new_conn: asyncpg.Connection,
        wallet_id: str,
        items_table: str,
    ):
        self._old_conn = old_conn
        self._new_conn = new_conn
        self._wallet_id = wallet_id
        self._items_table = items_table
        self._profile_id = None

    @property
    def profile_id(self):
        if not self._profile_id:
            raise UpgradeError("Profile has not been initialized")
        return self._profile_id

    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""
        async with self._new_conn.transaction():
            id_row = await self._new_conn.fetch(
                """
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                    ON CONFLICT DO NOTHING RETURNING id
                """,
                name,
                key,
            )
            self._profile_id = id_row[0][0]
            return self._profile_id

    async def get_metadata(self):
        stmt = await self._old_conn.fetch(
            "SELECT value FROM metadata WHERE wallet_id = $1", (self._wallet_id)
        )
        found = None
        if stmt != "":
            for row in stmt:
                decoded = base64.b64decode(bytes.decode(row[0]))
                if found is None:
                    found = decoded
                else:
                    raise Exception("Found duplicate row")
            return found

        else:
            raise Exception("Row not found")

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items by wallet_id."""
        while True:
            rows = await self._old_conn.fetch(
                f"""
                SELECT i.id, i.type, i.name, i.value, i.key,
                (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                    FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
                (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                    FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
                FROM {self._items_table} i WHERE i.wallet_id = $1 LIMIT $2;
                """,  # noqa
                self._wallet_id,
                limit,
            )
            if not rows:
                break
            yield rows

    async def update_items(self, items):
        """Update items in the database.

        Differences from PgMWSTWallet:
        """
        for item in items:
            del_ids = item["id"]
            async with self._new_conn.transaction():
                ins = await self._new_conn.fetch(
                    """
                        INSERT INTO items (profile_id, kind, category, name, value)
                        VALUES ($1, 2, $2, $3, $4) RETURNING id
                    """,
                    self.profile_id,
                    item["category"],
                    item["name"],
                    item["value"],
                )
                item_id = ins[0][0]
                if item["tags"]:
                    await self._new_conn.executemany(
                        """
                            INSERT INTO items_tags (item_id, plaintext, name, value)
                            VALUES ($1, $2, $3, $4)
                        """,
                        ((item_id, *tag) for tag in item["tags"]),
                    )
                await self._old_conn.execute(
                    f"DELETE FROM {self._items_table} WHERE id IN ($1)", del_ids
                )
