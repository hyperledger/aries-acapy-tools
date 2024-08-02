from urllib.parse import urlparse

import asyncpg

from .db_connection import DbConnection


class PgConnection(DbConnection):
    """Postgres connection."""

    DB_TYPE = "pgsql"

    def __init__(
        self,
        uri: str,
    ):
        """Initialize a PgConnection instance."""
        self.uri = uri
        self.parsed_url = urlparse(uri)
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

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def get_root_config(self):
        """Get the root config table of the wallet."""
        query = await self._conn.fetch(
            """
                SELECT * FROM config;
            """
        )
        result = []
        if len(query) > 0:
            for row in query:
                result.append({row[0]: row[1]})

        return result

    async def get_profiles(self):
        """Get the postgres profiles without private keys."""
        query = await self._conn.fetch(
            """
                SELECT * FROM profiles;
            """
        )
        result = []
        if len(query) > 0:
            for row in query:
                result.append(
                    {
                        row[0]: [
                            row[1],
                            row[2],
                        ]
                    }
                )

        return result

    async def create_database(self, base_wallet_name, sub_wallet_name):
        """Create an postgres database."""
        await self._conn.execute(
            f"""
            CREATE DATABASE {sub_wallet_name};
            """
        )

    async def remove_wallet(self, base_wallet_name, sub_wallet_name):
        """Remove the postgres wallet."""
        await self._conn.execute(
            f"""
            DROP DATABASE {sub_wallet_name};
            """
        )
