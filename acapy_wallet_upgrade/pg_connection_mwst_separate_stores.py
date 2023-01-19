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

    # add method to query metadata table rows - need a list of wallet names and keys

    # add overwrite of insert_profile
    #    accommodate the insertion of multiple profiles all encrypted with the same store key

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
