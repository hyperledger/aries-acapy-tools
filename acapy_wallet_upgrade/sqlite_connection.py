import aiosqlite

from .db_connection import DbConnection, Wallet
from .error import UpgradeError


class SqliteConnection(DbConnection, Wallet):
    """Sqlite connection."""

    DB_TYPE = "sqlite"

    def __init__(self, path: str) -> "SqliteConnection":
        """Initialize a SqliteConnection instance."""
        self._path = path
        self._conn: aiosqlite.Connection = None
        self._protocol: str = "sqlite"

    async def connect(self):
        """Accessor for the connection pool instance."""
        if not self._conn:
            self._conn = await aiosqlite.connect(self._path)

    async def find_table(self, name: str) -> bool:
        """Check for existence of a table."""
        found = await self._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
            (name,),
        )
        return (await found.fetchone())[0]

    async def pre_upgrade(self) -> dict:
        """Add new tables and columns."""

        if not await self.find_table("metadata"):
            raise UpgradeError("No metadata table found: not an Indy wallet database")

        if await self.find_table("config"):
            stmt = await self._conn.execute("SELECT name, value FROM config")
            config = {}
            async for row in stmt:
                config[row[0]] = row[1]
            return config

        await self._conn.executescript(
            """
            BEGIN EXCLUSIVE TRANSACTION;

            CREATE TABLE config (
                name TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (name)
            );

            CREATE TABLE profiles (
                id INTEGER NOT NULL,
                name TEXT NOT NULL,
                reference TEXT NULL,
                profile_key BLOB NULL,
                PRIMARY KEY (id)
            );
            CREATE UNIQUE INDEX ix_profile_name ON profiles (name);

            ALTER TABLE items RENAME TO items_old;
            CREATE TABLE items (
                id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                kind INTEGER NOT NULL,
                category BLOB NOT NULL,
                name BLOB NOT NULL,
                value BLOB NOT NULL,
                expiry DATETIME NULL,
                PRIMARY KEY (id),
                FOREIGN KEY (profile_id) REFERENCES profiles (id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            );
            CREATE UNIQUE INDEX ix_items_uniq ON items
                (profile_id, kind, category, name);

            CREATE TABLE items_tags (
                id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                name BLOB NOT NULL,
                value BLOB NOT NULL,
                plaintext BOOLEAN NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY (item_id) REFERENCES items (id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            );
            CREATE INDEX ix_items_tags_item_id ON items_tags (item_id);
            CREATE INDEX ix_items_tags_name_enc ON items_tags
                (name, SUBSTR(value, 1, 12)) WHERE plaintext=0;
            CREATE INDEX ix_items_tags_name_plain ON items_tags
                (name, value) WHERE plaintext=1;

            COMMIT;
        """,
        )
        return {}

    async def create_config(self, pass_key: str, name: str):
        """Insert the initial profile."""
        await self._conn.executemany(
            "INSERT INTO config (name, value) VALUES (?1, ?2)",
            (
                ("default_profile", name),
                ("key", pass_key),
            ),
        )
        await self._conn.commit()

    async def finish_upgrade(self):
        """Complete the upgrade."""
        await self._conn.executescript(
            """
            BEGIN EXCLUSIVE TRANSACTION;
            DROP TABLE items_old;
            DROP TABLE metadata;
            DROP TABLE tags_encrypted;
            DROP TABLE tags_plaintext;
            INSERT INTO config (name, value) VALUES ("version", "1");
            COMMIT;
        """
        )

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""
        await self._conn.execute(
            "INSERT INTO profiles (name, profile_key) VALUES (?1, ?2)", (name, key)
        )
        await self._conn.commit()

    async def get_metadata(self):
        stmt = await self._conn.execute("SELECT value FROM metadata")
        found = None
        async for row in stmt:
            if found is None:
                found = row[0]
            else:
                raise Exception("Found duplicate row")

        return found

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items."""
        stmt = await self._conn.execute(
            """
            SELECT i.id, i.type, i.name, i.value, i.key,
            (SELECT GROUP_CONCAT(HEX(te.name) || ':' || HEX(te.value))
                FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
            (SELECT GROUP_CONCAT(HEX(tp.name) || ':' || HEX(tp.value))
                FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
            FROM items_old i LIMIT ?1
            """,
            (limit,),
        )
        return await stmt.fetchall()

    async def update_items(self, items):
        """Update items in the database."""
        del_ids = []
        for item in items:
            del_ids = item["id"]
            ins = await self._conn.execute(
                """
                INSERT INTO items (profile_id, kind, category, name, value)
                VALUES (1, 2, ?1, ?2, ?3)
                """,
                (item["category"], item["name"], item["value"]),
            )
            item_id = ins.lastrowid
            if item["tags"]:
                await self._conn.executemany(
                    """
                    INSERT INTO items_tags (item_id, plaintext, name, value)
                    VALUES (?1, ?2, ?3, ?4)
                    """,
                    ((item_id, *tag) for tag in item["tags"]),
                )
        await self._conn.execute("DELETE FROM items_old WHERE id IN (?1)", (del_ids,))
        await self._conn.commit()
