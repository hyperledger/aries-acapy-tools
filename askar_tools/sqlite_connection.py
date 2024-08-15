from urllib.parse import urlparse

import aiosqlite

from .db_connection import DbConnection


class SqliteConnection(DbConnection):
    """Sqlite connection."""

    DB_TYPE = "sqlite"

    def __init__(self, uri: str):
        """Initialize a SqliteConnection instance."""
        self.uri = uri
        parsed = urlparse(uri)
        self._path = parsed.path
        self._conn: aiosqlite.Connection = None
        self._protocol: str = "sqlite"

    async def connect(self):
        """Accessor for the connection pool instance."""
        if not self._conn:
            try:
                self._conn = await aiosqlite.connect(self._path)
            except aiosqlite.Error as e:
                print("ERROR: Cannot connect to the database. Check the uri exists.")
                raise e

    async def find_table(self, name: str) -> bool:
        """Check for existence of a table."""
        found = await self._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
            (name,),
        )
        return (await found.fetchone())[0]

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def get_root_config(self):
        """Get the root config table of the wallet."""
        query = await self._conn.execute("SELECT * FROM config;")
        result = []
        async for row in query:
            result.append({row[0]: row[1]})

        return result

    async def get_profiles(self):
        """Get the sqlite profiles without private keys."""
        query = await self._conn.execute("SELECT * FROM profiles;")
        result = []
        async for row in query:
            result.append({row[0]: [row[1], row[2]]})

        return result
