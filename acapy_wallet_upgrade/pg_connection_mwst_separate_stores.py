import base64
import pprint
from .pg_connection import PgConnection


class PgConnectionMWSTSeparateStores(PgConnection):
    """Postgres connection in MultiWalletSingeTable
    management mode."""

    DB_TYPE = "pgsql_mwst_separate_stores"

    def __init__(
        self,
        path: str,
    ):
        """Initialize a PgConnectionMWSTSeparateStores instance."""
        self._path: str = path
        super().__init__(path)

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
