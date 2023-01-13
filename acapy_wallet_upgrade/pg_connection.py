import asyncpg
import base64
import pprint

from urllib.parse import urlparse

from .db_connection import DbConnection
from .error import UpgradeError
from .sql_commands import PostgresqlCommands as sql_commands


class PgConnection(DbConnection):
    """Postgres connection."""

    DB_TYPE = "pgsql"

    def __init__(
        self,
        db_host: str,
        db_name: str,
        db_user: str,
        db_pass: str,
        path: str,
    ):
        """Initialize a PgConnection instance."""
        self._config = {
            "host": db_host,
            "db": db_name,
            "user": db_user,
            "password": db_pass,
        }
        self._conn: asyncpg.Connection = None
        self._path: str = (path,)
        self._protocol: str = "postgres"

    @property
    def parsed_url(self):
        """Accessor for the parsed database URL."""
        url = self._config["host"]
        if "://" not in url:
            url = f"http://{url}"
        return urlparse(url)

    async def connect(self):
        """Accessor for the connection pool instance."""
        if not self._conn:
            parts = self.parsed_url
            self._conn = await asyncpg.connect(
                host=parts.hostname,
                port=parts.port or 5432,
                user=self._config["user"],
                password=self._config["password"],
                database=self._config["db"],
            )

    async def find_table(self, name: str) -> bool:
        """Check for existence of a table."""
        print(f"\nfx find_table(self, name: {name})")

        found = await self._conn.fetch(sql_commands.find_table, name)

        print(f"found: {found[0][0]}\n")

        return found[0][0]

    async def pre_upgrade(self) -> dict:
        """Add new tables and columns."""
        print("\nfx pre_upgrade(self)\n")

        if not await self.find_table("metadata"):
            raise UpgradeError("No metadata table found: not an Indy wallet database")

        if await self.find_table("config"):
            stmt = await self._conn.fetch(sql_commands.config_names)
            config = {}
            if len(stmt) > 0:
                for row in stmt:
                    config[row[0]] = row[1]
            return config
        else:
            await self.find_table("config")
            async with self._conn.transaction():
                await self._conn.execute(sql_commands.create_config)

        if not await self.find_table("profiles"):
            async with self._conn.transaction():
                await self._conn.execute(sql_commands.create_profiles)

        if not await self.find_table("items_old"):
            async with self._conn.transaction():
                await self._conn.execute(sql_commands.create_items)

        if not await self.find_table("items_tags"):
            async with self._conn.transaction():
                await self._conn.execute(sql_commands.create_items_tags)

        return {}

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
                """
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                """,
                name,
                key,
            )

    async def finish_upgrade(self):
        """Complete the upgrade."""
        print("\nfx finish_upgrade(self)\n")

        await self._conn.execute(sql_commands.drop_tables)

    async def fetch_one(self, sql: str, optional: bool = False):
        """Fetch a single row from the database."""
        print(f"\nfx fetch_one(self, sql: {sql}, optional: {optional})")

        stmt: str = await self._conn.fetch(sql)
        found = None
        if stmt != "":
            for row in stmt:
                decoded = (base64.b64decode(bytes.decode(row[0])),)
                if found is None:
                    found = decoded
                else:
                    raise Exception("Found duplicate row")

        if optional or found:
            print("found: ")
            pprint.pprint(found, indent=2)
            print(" ")
            return found
        else:
            raise Exception("Row not found")

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items."""
        print(" ")
        print(f"fx fetch_pending_items(self, limit: {limit})")

        stmt = await self._conn.fetch(sql_commands.pending_items, limit)

        print("stmt: ")
        print(" ")
        return stmt

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def update_items(self, items):
        """Update items in the database."""
        print("\nfx update_items(self, items)")
        print("items: ")
        pprint.pprint(items, indent=2)
        del_ids = []
        for item in items:
            del_ids = item["id"]
            async with self._conn.transaction():
                ins = await self._conn.fetch(
                    sql_commands.insert_into_items,
                    item["category"],
                    item["name"],
                    item["value"],
                )
                item_id = ins[0][0]
                print(f"item_id: {item_id}")
                if item["tags"]:
                    await self._conn.executemany(
                        sql_commands.insert_into_items_tags,
                        ((item_id, *tag) for tag in item["tags"]),
                    )
                await self._conn.execute(sql_commands.delete_item_in_items_old, del_ids)
