from urllib.parse import unquote, urlparse

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
                user=unquote(parts.username),
                password=unquote(parts.password),
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

    async def create_database(self, admin_wallet_name, sub_wallet_name):
        """Create an postgres database."""
        await self._conn.execute(
            f"""
            CREATE DATABASE "{sub_wallet_name}";
            """
        )

    async def database_exists(self, admin_wallet_name, sub_wallet_name) -> bool:
        """Check whether a postgres database exists."""
        found = await self._conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = $1);",
            sub_wallet_name,
        )
        return bool(found)

    async def remove_database(self, admin_wallet_name, sub_wallet_name):
        """Remove the postgres wallet."""
        # Kill any connections to the database
        await self._conn.execute(
            f"""
            SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE datname = '{sub_wallet_name}';
            """
        )
        # Drop the database
        await self._conn.execute(
            f"""
            DROP DATABASE "{sub_wallet_name}";
            """
        )
