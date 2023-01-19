import base64
import pprint
import uuid

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

    async def retrieve_entries(self, sql: str, optional: bool = False):
        """Retrieve entries from a table."""
        print(f"\nfx retrieve_entries(self, sql: {sql}")
        return await self._conn.fetch(sql)

    async def create_config(self, pass_key: str, name: str = str(uuid.uuid4())):
        print("pass_key: ")
        pprint.pprint(pass_key, indent=2)

        await self._conn.executemany(
            sql_commands.insert_into_config,
            (("default_profile", name), ("key", pass_key)),
        )

    async def insert_profile(self, name: str = str(uuid.uuid4()), key: bytes = None):
        """Insert the initial profile."""
        print("\nfx insert_profile(self, pass_key, name, key)")
        print("name: ")
        pprint.pprint(name, indent=2)
        print("key: ")
        pprint.pprint(key, indent=2)
        print(" ")
        async with self._conn.transaction():
            id = await self._conn.fetch(
                sql_commands.insert_into_profiles,
                name,
                key,
            )
            return id[0][0]

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
        fetched = []
        if len(stmt) > 0:
            for row in stmt:
                decoded = base64.b64decode(bytes.decode(row[1]))
                wallet_id = row[0]
                fetched.append(
                    (wallet_id, decoded),
                )

        if len(fetched) > 0:
            print("fetched: ")
            pprint.pprint(fetched, indent=2)
            print(" ")
            return fetched
        else:
            raise Exception("Row not found")

    async def fetch_pending_items(self, limit: int, wallet_id: str):
        """Fetch un-updated items by wallet_id."""
        print(" ")
        print(f"fx fetch_pending_items(self, limit: {limit}, wallet_id: {wallet_id}")
        return await self._conn.fetch(
            sql_commands.pending_items_by_wallet_id, limit, wallet_id
        )

    async def update_items(self, items, profile_id: int = 1):
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
                        VALUES ($1, 2, $2, $3, $4) RETURNING id
                    """,
                    profile_id,
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
