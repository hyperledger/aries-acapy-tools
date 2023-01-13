import asyncpg
import base64
import pprint

from urllib.parse import urlparse

from .pg_connection import PgConnection
from .error import UpgradeError


class PgConnectionMWST(PgConnection):
    """Postgres connection in MultiWalletSingeTable
    management mode."""

    DB_TYPE = "pgsql_mwst"

    def __init__(
        self,
        db_host: str,
        db_name: str,
        db_user: str,
        db_pass: str,
        path: str,
    ) -> "PgConnectionMWST":
        """Initialize a PgConnectionMWST instance."""
        super().__init__(
            db_host,
            db_name,
            db_user,
            db_pass,
            path,
        )

    async def find_wallet_ids(self) -> set:
        """Retrieve set of wallet ids."""
        wallet_id_list = await self._conn.fetch(
            """
            SELECT wallet_id FROM items
            """
        )
        return set([wallet_id[0] for wallet_id in wallet_id_list])

    async def pre_upgrade(self) -> dict:
        """Add new tables and columns."""
        print(" ")
        print("fx pre_upgrade(self)")
        print(" ")

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
            await self.find_table("config")
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

        if not await self.find_table("profiles"):
            async with self._conn.transaction():
                await self._conn.execute(
                    """
                        CREATE TABLE profiles (
                            wallet_id VARCHAR(64) NOT NULL,
                            id BIGSERIAL,
                            name TEXT NOT NULL,
                            reference TEXT NULL,
                            profile_key BYTEA NULL,
                            PRIMARY KEY (id)
                        );
                        CREATE UNIQUE INDEX ix_profile_name ON profiles (name);
                    """
                )

        if not await self.find_table("items_old"):
            async with self._conn.transaction():
                await self._conn.execute(
                    """
                        ALTER TABLE items RENAME TO items_old;
                        CREATE TABLE items (
                            wallet_id VARCHAR(64) NOT NULL,
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
                    """
                )

        if not await self.find_table("items_tags"):
            async with self._conn.transaction():
                await self._conn.execute(
                    """
                        CREATE TABLE items_tags (
                            wallet_id VARCHAR(64) NOT NULL,
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
                        CREATE INDEX ix_items_tags_name_enc ON items_tags(name, SUBSTR(value, 1, 12)) include (item_id) WHERE plaintext=0;
                        CREATE INDEX ix_items_tags_name_plain ON items_tags(name, value) include (item_id) WHERE plaintext=1;
                    """
                )

        return {}

    async def insert_profile(
        self, pass_key: str, wallet_id: str, name: str, key: bytes
    ):
        """Insert the initial profile."""
        print(" ")
        print("fx insert_profile(self, pass_key, name, key)")
        print("wallet_id: ")
        pprint.pprint(wallet_id, indent=2)
        print("pass_key: ")
        pprint.pprint(pass_key, indent=2)
        print("name: ")
        pprint.pprint(name, indent=2)
        print("key: ")
        pprint.pprint(key, indent=2)
        print(" ")
        async with self._conn.transaction():
            await self._conn.executemany(
                """
                    INSERT INTO config (name, value) VALUES($1, $2)
                """,
                (("default_profile", name), ("key", pass_key)),
            )

            await self._conn.execute(
                """
                    INSERT INTO profiles (wallet_id, name, profile_key) VALUES($1, $2, $3)
                """,
                wallet_id,
                name,
                key,
            )

    async def fetch_multiple(self, sql: str, optional: bool = False):
        """Fetch a single row from the database."""
        print(" ")
        print(f"fx fetch_one(self, sql: {sql}, optional: {optional})")

        stmt: str = await self._conn.fetch(sql)
        print("stmt here!", stmt)
        fetched = []
        if len(stmt) > 0:
            for row in stmt:
                decoded = (base64.b64decode(bytes.decode(row[0])),)
                fetched.append(decoded)

        print("fetched now: ", fetched)
        if len(fetched) > 0:
            print("fetched: ")
            pprint.pprint(fetched, indent=2)
            print(" ")
            return fetched
        else:
            raise Exception("Row not found")

    async def update_items(self, items):
        """Update items in the database."""
        print(" ")
        print("fx update_items(self, items)")
        print("items: ")
        pprint.pprint(items, indent=2)
        del_ids = []
        for item in items:
            del_ids = item["id"]
            async with self._conn.transaction():
                ins = await self._conn.fetch(
                    """
                        INSERT INTO items (profile_id, kind, category, name, value)
                        VALUES (1, 2, $1, $2, $3) RETURNING id
                    """,
                    item["category"],
                    item["name"],
                    item["value"],
                )
                item_id = ins[0][0]
                print(f"item_id: {item_id}")
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
