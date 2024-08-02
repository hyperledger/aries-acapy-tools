import os
import shutil
import sqlite3
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
        for row in query:
            result.append({row[0]: row[1]})

        return result

    async def get_profiles(self):
        """Get the sqlite profiles without private keys."""
        query = await self._conn.execute("SELECT * FROM profiles;")
        result = []
        for row in query:
            result.append({row[0]: [row[1], row[2]]})

        return result

    async def create_database(self, admin_wallet_name, sub_wallet_name):
        """Create an sqlite database."""
        directory = (
            urlparse(self.uri)
            .path.replace("/sqlite.db", "")
            .replace(admin_wallet_name, sub_wallet_name)
        )
        if not os.path.exists(directory):
            os.makedirs(directory)

        db_path = os.path.join(directory, "sqlite.db")
        conn = None
        try:
            conn = sqlite3.connect(db_path)
        except sqlite3.Error as e:
            print("*****************8")
            print(e)
        finally:
            if conn:
                conn.close()

    async def remove_wallet(self, admin_wallet_name, sub_wallet_name):
        """Remove the sqlite wallet."""
        directory = (
            urlparse(self.uri)
            .path.replace("/sqlite.db", "")
            .replace(admin_wallet_name, sub_wallet_name)
        )
        try:
            shutil.rmtree(directory)
            print(f"Successfully deleted {directory}")
        except FileNotFoundError:
            print(f"Directory {directory} does not exist")
        except PermissionError:
            print(f"Permission denied to delete {directory}")
        except Exception as e:
            print(f"An error occurred: {e}")
