import base64
from urllib.parse import urlparse

import asyncpg

from .db_connection import DbConnection, Wallet
from .error import UpgradeError


class PgConnection(DbConnection, Wallet):
    """Postgres connection."""

    DB_TYPE = "pgsql"

    def __init__(
        self,
        path: str,
    ):
        """Initialize a PgConnection instance."""
        self._path: str = path
        self.parsed_url = urlparse(path)
        self._conn: asyncpg.Connection = None

    async def connect(self):
        """Accessor for the connection pool instance."""
        if not self._conn:
            parts = self.parsed_url
            self._conn = await asyncpg.connect(
                host=parts.hostname,
                port=parts.port or 5432,
                user=parts.username,
                password=parts.password,
                database=parts.path[1:],
            )

    async def find_table(self, name: str) -> bool:
        """Check for existence of a table."""
        found = await self._conn.fetch(
            """
            SELECT EXISTS (
               SELECT FROM information_schema.tables
               WHERE  table_schema = 'public'
               AND    table_name   = $1
            );
            """,
            name,
        )
        return found[0][0]

    async def _create_table(self, table, cmd):
        if not await self.find_table(table):
            async with self._conn.transaction():
                await self._conn.execute(cmd)

    async def pre_upgrade(self) -> dict:
        """Add new tables and columns."""
        if not await self.find_table("metadata"):
            raise UpgradeError("No metadata table found: not an Indy wallet database")

        if await self.find_table("config"):
            stmt = await self._conn.fetch(
                """
                SELECT name, value FROM config
                """
            )
            config = {}
            if len(stmt) > 0:
                for row in stmt:
                    config[row[0]] = row[1]
            return config
        else:
            async with self._conn.transaction():
                await self._conn.execute(
                    """
                    CREATE TABLE config (
                        name TEXT NOT NULL,
                        value TEXT,
                        PRIMARY KEY (name)
                    );
                    """
                )

        await self._create_table(
            "profiles",
            """
            CREATE TABLE profiles (
                id BIGSERIAL,
                name TEXT NOT NULL,
                reference TEXT NULL,
                profile_key BYTEA NULL,
                PRIMARY KEY (id)
            );
            CREATE UNIQUE INDEX ix_profile_name ON profiles (name);
            """,
        )
        await self._create_table(
            "items_old",
            """
            ALTER TABLE items RENAME TO items_old;
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
            """,
        )
        await self._create_table(
            "items_tags",
            """
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
            """,
        )

        return {}

    async def create_config(self, pass_key: str, name: str):
        """Insert the initial profile."""
        async with self._conn.transaction():
            await self._conn.executemany(
                """
                    INSERT INTO config (name, value) VALUES($1, $2)
                """,
                (("default_profile", name), ("key", pass_key)),
            )

    async def finish_upgrade(self):
        """Complete the upgrade."""

        await self._conn.execute(
            """
            BEGIN TRANSACTION;
            DROP TABLE items_old CASCADE;
            DROP TABLE metadata;
            DROP TABLE tags_encrypted;
            DROP TABLE tags_plaintext;
            INSERT INTO config (name, value) VALUES ('version', 1);
            COMMIT;
            """
        )

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""
        async with self._conn.transaction():

            await self._conn.execute(
                """
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                    ON CONFLICT DO NOTHING RETURNING id
                """,
                name,
                key,
            )

    async def get_metadata(self):
        stmt = await self._conn.fetch("SELECT value FROM metadata")
        found = None
        if stmt != "":
            for row in stmt:
                decoded = base64.b64decode(bytes.decode(row[0]))
                if found is None:
                    found = decoded
                else:
                    raise Exception("Found duplicate row")

        else:
            raise Exception("Row not found")

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items."""
        stmt = await self._conn.fetch(
            """
            SELECT i.id, i.type, i.name, i.value, i.key,
            (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
            (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
            FROM items_old i LIMIT $1;
            """,  # noqa
            limit,
        )
        return stmt

    async def update_items(self, items):
        """Update items in the database."""
        del_ids = []
        for item in items:
            del_ids = item["id"]
            async with self._conn.transaction():
                ins = await self._conn.fetch(
                    """
                        INSERT INTO items (profile_id, kind, category, name, value)
                        VALUES (1, 2, $1, $2, $3) RETURNING id
                    """,  # TODO update profile_id to be a parameter
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
