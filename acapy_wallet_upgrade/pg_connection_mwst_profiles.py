import base64
import pprint

from .pg_connection import PgConnection
from .sql_commands import PostgresqlCommands as sql_commands


class PgConnectionMWSTProfiles(PgConnection):
    """Postgres connection in MultiWalletSingeTable
    management mode."""

    DB_TYPE = "pgsql_mwst_profiles"

    def __init__(
        self,
        path: str,
    ):
        """Initialize a PgConnectionMWSTProfiles instance."""
        self._path: str = path
        super().__init__(path)

    async def retrieve_metadata_info(self) -> dict:
        """Returns a list of wallet names and keys"""
        if await self.find_table("metadata"):
            stmt = await self._conn.fetch("SELECT wallet_id, value FROM metadata")
            metadata_info = {}
            if len(stmt) > 0:
                for row in stmt:
                    metadata_info[row[0]] = bytes.decode(
                        base64.b64decode(bytes.decode(row[1]))
                    )

    async def insert_profile(self, pass_key: str, name: str, key: bytes):
        """Insert the initial profile."""
        print("\nfx insert_profile(self, pass_key, name, key)")
        print("pass_key: ")
        pprint.pprint(pass_key, indent=2)
        print("name: ")
        pprint.pprint(name, indent=2)
        print("key: ")
        pprint.pprint(key, indent=2)
        print(" ")
        async with self._conn.transaction():
            await self._conn.executemany(
                sql_commands.insert_into_config,
                (("default_profile", name), ("key", pass_key)),
            )

            await self._conn.execute(
                sql_commands.insert_into_profiles,
                name,
                key,
            )

    async def add_profile(self, name, key):
        """Accommodate the insertion of multiple profiles
        all encrypted with the same store key.
        """
        await self._conn.execute(
            """INSERT INTO profiles (name, profile_key) VALUES($1, $2)""",
            name,
            key,
        )

    async def find_wallet_ids(self) -> set:
        """Retrieve set of wallet ids."""
        wallet_id_list = await self._conn.fetch(
            """
            SELECT wallet_id FROM metadata
            """
        )
        return [wallet_id[0] for wallet_id in wallet_id_list]

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
