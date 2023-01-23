import base64
import uuid

from .pg_connection import PgConnection


class PgConnectionMWSTProfiles(PgConnection):
    """Postgres connection in MultiWalletSingeTable
    management mode."""

    DB_TYPE = "pgsql_mwst_profiles"

    def __init__(
        self,
        path: str,
    ):
        """Initialize a PgConnectionMWSTProfiles instance."""
        self._path: str = path
        super().__init__(path)

    async def retrieve_entries(self, sql: str, optional: bool = False):
        """Retrieve entries from a table."""
        return await self._conn.fetch(sql)

    async def create_config(self, pass_key: str, name: str = str(uuid.uuid4())):
        await self._conn.executemany(
            """
                INSERT INTO config (name, value) VALUES($1, $2)
            """,
            (("default_profile", name), ("key", pass_key)),
        )

    async def insert_profile(self, name: str = str(uuid.uuid4()), key: bytes = None):
        """Insert the initial profile."""
        async with self._conn.transaction():
            id = await self._conn.fetch(
                """
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                    ON CONFLICT DO NOTHING RETURNING id
                """,
                name,
                key,
            )
            return id[0][0]

    async def find_wallet_ids(self) -> set:
        """Retrieve set of wallet ids."""
        wallet_id_list = await self._conn.fetch(
            """
            SELECT wallet_id FROM metadata
            """
        )
        return [wallet_id[0] for wallet_id in wallet_id_list]

    async def fetch_multiple(self, sql: str, args, optional: bool = False):
        """Fetch a single row from the database."""
        stmt: str = await self._conn.fetch(sql, args)
        fetched = []
        if len(stmt) > 0:
            for row in stmt:
                decoded = base64.b64decode(bytes.decode(row[1]))
                wallet_id = row[0]
                fetched.append(
                    (wallet_id, decoded),
                )

        if len(fetched) > 0:
            return fetched
        else:
            raise Exception("Row not found")

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items by wallet_id."""
        raise NotImplementedError("Not implemented; use ProfileConnection.")

    async def update_items(self, items):
        """Update items in the database."""
        raise NotImplementedError("Not implemented; use ProfileConnection.")


class ProfileConnection(PgConnectionMWSTProfiles):
    def __init__(self, wallet_id: str, profile_id: int):
        self._wallet_id = wallet_id
        self._profile_id = profile_id

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items by wallet_id."""
        return await self._conn.fetch(
            """
            SELECT i.wallet_id, i.id, i.type, i.name, i.value, i.key,
            (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
            (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
            FROM items_old i WHERE i.wallet_id = $2 LIMIT $1;
            """,  # noqa
            limit,
            self._wallet_id,
        )

    async def update_items(self, items):
        """Update items in the database."""
        del_ids = []
        for item in items:
            del_ids = item["id"]
            async with self._conn.transaction():
                ins = await self._conn.fetch(
                    """
                        INSERT INTO items (profile_id, kind, category, name, value)
                        VALUES ($1, 2, $2, $3, $4) RETURNING id
                    """,
                    self._profile_id,
                    item["category"],
                    item["name"],
                    item["value"],
                )
                item_id = ins[0][0]
                if item["tags"]:
                    await self._conn.executemany(
                        """
                            INSERT INTO items_tags (item_id, plaintext, name, value)
                            VALUES ($1, $2, $3, $4)
                        """,
                        ((item_id, *tag) for tag in item["tags"]),
                    )
                await self._conn.execute(
                    "DELETE FROM items_old WHERE id IN ($1)", del_ids
                )
