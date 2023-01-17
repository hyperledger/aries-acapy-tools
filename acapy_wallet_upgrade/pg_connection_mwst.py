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
        path: str,
    ):
        """Initialize a PgConnectionMWST instance."""
        self._path: str = path
        super().__init__(path)

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

    # async def update_items(self, items):
    #     """Update items in the database."""
    #     print(" ")
    #     print("fx update_items(self, items)")
    #     print("items: ")
    #     pprint.pprint(items, indent=2)
    #     del_ids = []
    #     for item in items:
    #         del_ids = item["id"]
    #         async with self._conn.transaction():
    #             ins = await self._conn.fetch(
    #                 """
    #                     INSERT INTO items (profile_id, kind, category, name, value)
    #                     VALUES (1, 2, $1, $2, $3) RETURNING id
    #                 """,
    #                 item["category"],
    #                 item["name"],
    #                 item["value"],
    #             )
    #             item_id = ins[0][0]
    #             print(f"item_id: {item_id}")
    #             if item["tags"]:
    #                 await self._conn.executemany(
    #                     """
    #                         INSERT INTO items_tags (item_id, plaintext, name, value)
    #                         VALUES ($1, $2, $3, $4)
    #                     """,
    #                     ((item_id, *tag) for tag in item["tags"]),
    #                 )
    #             await self._conn.execute(
    #                 "DELETE FROM items_old WHERE id IN ($1)", del_ids
    #             )
