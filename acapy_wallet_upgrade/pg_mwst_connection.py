import base64
from typing import Optional

from asyncpg import Connection

from .error import UpgradeError, MissingWalletError
from .pg_connection import PgConnection, PgWallet


class PgMWSTConnection(PgConnection):
    """Postgres connection in MultiWalletSingeTable
    management mode."""

    DB_TYPE = "pgsql_mwst"

    async def check_wallet_alignment(self, wallet_keys):
        """Verify that the wallet names passed in align with
        the wallet names found in the database.
        """
        wallet_id_list = await self._conn.fetch(
            """
            SELECT wallet_id FROM metadata
            """
        )
        retrieved_wallet_keys = [wallet_id[0] for wallet_id in wallet_id_list]

        for wallet_id in wallet_keys.keys():
            if wallet_id not in retrieved_wallet_keys:
                raise UpgradeError(f"Wallet {wallet_id} not found in database")
        for wallet_id in retrieved_wallet_keys:
            if wallet_id not in wallet_keys.keys():
                raise MissingWalletError(
                    f"Must provide entry for {wallet_id} in wallet_keys dictionary to migrate wallet"
                )

    async def check_missing_wallet_flag(self, wallet_keys, allow_missing_wallet):
        if allow_missing_wallet:
            try:
                await self.check_wallet_alignment(wallet_keys)
            except MissingWalletError:
                print("Running upgrade without migrating all wallets")
        else:
            await self.check_wallet_alignment(wallet_keys)

    def get_wallet(self, wallet_id: str) -> "PgMWSTWallet":
        return PgMWSTWallet(self._conn, wallet_id)


class PgMWSTWallet(PgWallet):
    def __init__(
        self, conn: Connection, wallet_id: str, profile_id: Optional[str] = None
    ):
        self._conn = conn
        self._wallet_id = wallet_id
        self._profile_id = profile_id

    @property
    def profile_id(self):
        if not self._profile_id:
            raise UpgradeError("Profile has not been initialized")
        return self._profile_id

    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""
        async with self._conn.transaction():
            id_row = await self._conn.fetch(
                """
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                    ON CONFLICT DO NOTHING RETURNING id
                """,
                name,
                key,
            )
            self._profile_id = id_row[0][0]
            return self._profile_id

    async def get_metadata(self):
        stmt = await self._conn.fetch(
            "SELECT value FROM metadata WHERE wallet_id = $1", (self._wallet_id)
        )
        found = None
        if stmt != "":
            for row in stmt:
                decoded = base64.b64decode(bytes.decode(row[0]))
                if found is None:
                    found = decoded
                else:
                    raise Exception("Found duplicate row")
            return found

        else:
            raise Exception("Row not found")

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items by wallet_id."""
        while True:
            stmt = await self._conn.fetch(
                """
                SELECT i.id, i.type, i.name, i.value, i.key,
                (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                    FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
                (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                    FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
                FROM items_old i WHERE i.wallet_id = $2 LIMIT $1;
                """,  # noqa
                limit,
                self._wallet_id,
            )
            if not stmt:
                break
            yield stmt

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