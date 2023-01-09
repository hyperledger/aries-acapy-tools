import asyncpg
import base64
import pprint

from urllib.parse import urlparse

from .db_connection import DbConnection
from .error import UpgradeError



class PgConnection(DbConnection):
    """Postgres connection."""

    DB_TYPE = "pgsql"

    def __init__(
            self, db_host: str, db_name: str, db_user: str, db_pass: str
    ) -> "PgConnection":
        """Initialize a PgConnection instance."""
        self._config = {
            "host": db_host,
            "db": db_name,
            "user": db_user,
            "password": db_pass,
        }
        self._conn: asyncpg.Connection = None

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
        print(" ")
        print(f"fx find_table(self, name: {name})")

        found = await self._conn.fetch(f'''
                    SELECT EXISTS (
                       SELECT FROM information_schema.tables 
                       WHERE  table_schema = 'public'
                       AND    table_name   = '{name}'
                       );
                ''')

        print(f"found: {found[0][0]}")
        print(" ")

        return found[0][0]

    async def pre_upgrade(self) -> dict:
        """Add new tables and columns."""
        print(" ")
        print("fx pre_upgrade(self)")
        print(" ")

        if not await self.find_table("metadata"):
            raise UpgradeError("No metadata table found: not an Indy wallet database")

        if await self.find_table("config"):
            stmt = await self._conn.fetch('''
                    SELECT name, value FROM config
                ''')
            config = {}
            if len(stmt) > 0:
                for row in stmt:
                    config[row[0]] = row[1]
            return config
        else:
            await self.find_table("config")
            async with self._conn.transaction():
                await self._conn.execute('''
                        CREATE TABLE config (
                            name TEXT NOT NULL,
                            value TEXT,
                            PRIMARY KEY (name)
                        );
                    ''')

        if not await self.find_table("profiles"):
            async with self._conn.transaction():
                await self._conn.execute('''
                        CREATE TABLE profiles (
                            id SERIAL NOT NULL,
                            name TEXT NOT NULL,
                            reference TEXT NULL,
                            profile_key BYTEA NULL,
                            PRIMARY KEY (id)
                        );
                        CREATE UNIQUE INDEX ix_profile_name ON profiles (name);
                    ''')

        if not await self.find_table("items_old"):
            async with self._conn.transaction():
                await self._conn.execute('''
                        ALTER TABLE items RENAME TO items_old;
                        CREATE TABLE items (
                            id SERIAL PRIMARY KEY,
                            profile_id INTEGER NOT NULL,
                            kind INTEGER NOT NULL,
                            category BYTEA NOT NULL,
                            name BYTEA NOT NULL,
                            value BYTEA NOT NULL,
                            expiry DATE NULL,
                            FOREIGN KEY (profile_id) REFERENCES profiles (id)
                                ON DELETE CASCADE ON UPDATE CASCADE
                        );
                        CREATE UNIQUE INDEX ix_items_uniq ON items
                            (profile_id, kind, category, name);
                    ''')

        if not await self.find_table("items_tags"):
            async with self._conn.transaction():
                await self._conn.execute('''
                        CREATE TABLE items_tags (
                            id BIGINT NOT NULL,
                            item_id BIGINT NOT NULL,
                            name BYTEA NOT NULL,
                            value BYTEA NOT NULL,
                            plaintext BOOLEAN NOT NULL,
                            PRIMARY KEY (id),
                            FOREIGN KEY (item_id) REFERENCES items (id)
                                ON DELETE CASCADE ON UPDATE CASCADE
                        );
                        CREATE INDEX ix_items_tags_item_id ON items_tags (item_id);
                        CREATE INDEX ix_items_tags_name_enc ON items_tags (name, SUBSTR(value, 1, 12)) WHERE plaintext=FALSE;
                        CREATE INDEX ix_items_tags_name_plain ON items_tags (name, value) WHERE plaintext=TRUE;
                    ''')

        return {}

    async def insert_profile(self, pass_key: str, name: str, key: bytes):
        """Insert the initial profile."""
        print(" ")
        print("fx insert_profile(self, pass_key, name, key)")
        print("pass_key: ")
        pprint.pprint(pass_key, indent=2)
        print("name: ")
        pprint.pprint(name, indent=2)
        print("key: ")
        pprint.pprint(key, indent=2)
        print(" ")
        # await self._conn.executemany(
        #     "INSERT INTO config (name, value) VALUES (?1, ?2)",
        #     (
        #         ("default_profile", name),
        #         ("key", pass_key),
        #     ),
        # )
        # await self._conn.execute(
        #     "INSERT INTO profiles (name, profile_key) VALUES (?1, ?2)", (name, key)
        # )
        # await self._conn.commit()
        async with self._conn.transaction():
            await self._conn.executemany('''
                    INSERT INTO config (name, value) VALUES($1, $2)
                ''', (("default_profile", name), ("key", pass_key)))

            await self._conn.execute('''
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                ''', name, key)

    async def finish_upgrade(self):
        """Complete the upgrade."""
        print(" ")
        print("fx finish_upgrade(self)")
        print(" ")

        await self._conn.executescript(
            """
            BEGIN TRANSACTION;
            DROP TABLE items_old;
            DROP TABLE metadata;
            DROP TABLE tags_encrypted;
            DROP TABLE tags_plaintext;
            INSERT INTO config (name, value) VALUES ("version", "1");
            COMMIT;
        """
        )

    async def fetch_one(self, sql: str, optional: bool = False):
        """Fetch a single row from the database."""
        print(" ")
        print(f"fx fetch_one(self, sql: {sql}, optional: {optional})")

        stmt: str = await self._conn.fetch(sql)
        found = None
        if len(stmt) > 0:
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

        stmt = await self._conn.fetch('''
            SELECT i.id, i.type, i.name, i.value, i.key,
            (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
            (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
            FROM items_old i LIMIT $1;
            ''', limit)

        print("stmt: ")
        pprint.pprint(stmt[0], indent=2)
        print(" ")
        # return await stmt.fetchall()
        return stmt

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

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
                    item["category"], item["name"], item["value"])
                item_id = ins[0][0]
                print(f"item_id: {item_id}")
                if item["tags"]:
                    await self._conn.executemany(
                        """
                            INSERT INTO items_tags (item_id, plaintext, name, value)
                            VALUES ($1, $2, $3, $4)
                        """,
                        ((item_id, *tag) for tag in item["tags"]))
                await self._conn.execute("DELETE FROM items_old WHERE id IN ($1)", del_ids)

            # ins = await self._conn.execute(
            #     """
            #     INSERT INTO items (profile_id, kind, category, name, value)
            #     VALUES (1, 2, $1, $2, $3)
            #     """,
            #     item["category"], item["name"], item["value"],
            # )
            # item_id = ins.lastrowid
            # if item["tags"]:
            #     await self._conn.executemany(
            #         """
            #         INSERT INTO items_tags (item_id, plaintext, name, value)
            #         VALUES ($1, $2, $3, $4)
            #         """,
            #         ((item_id, *tag) for tag in item["tags"]),
            #     )
        # await self._conn.execute("DELETE FROM items_old WHERE id IN ($1)", (del_ids,))
        # await self._conn.commit()
