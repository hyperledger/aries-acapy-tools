"""This module contains the Exporter class."""

import json
from json import JSONDecodeError

from aries_askar import Store

from .key_methods import KEY_METHODS
from .pg_connection import PgConnection
from .sqlite_connection import SqliteConnection


class Exporter:
    """The Exporter class."""

    def __init__(
        self,
        conn: SqliteConnection | PgConnection,
        wallet_name: str,
        wallet_key: str,
        wallet_key_derivation_method: str = "ARGON2I_MOD",
        export_filename: str = "wallet_export.json",
    ):
        """Initialize the Exporter object.

        Args:
            conn: The connection object.
            wallet_name: The name of the wallet.
            wallet_key: The key for the wallet.
            wallet_key_derivation_method: The key derivation method for the wallet.
            export_filename: The name of the export file.
        """
        self.conn = conn
        self.wallet_name = wallet_name
        self.wallet_key = wallet_key
        self.wallet_key_derivation_method = wallet_key_derivation_method
        self.export_filename = export_filename

    async def _get_decoded_items_and_tags(self, store):
        scan = store.scan()
        entries = await scan.fetch_all()
        items = {}
        for entry in entries:
            if entry.category not in items:
                items[entry.category] = []
            try:
                value = entry.value_json
            except JSONDecodeError:
                value = entry.value.decode("utf-8")
            items[entry.category].append(
                {
                    "name": entry.name,
                    "value": value,
                    "tags": entry.tags,
                }
            )
        return items

    async def export(self):
        """Export the wallet data."""
        print(f"Exporting wallet to {self.export_filename}...")

        tables = {"config": {}, "items": {}, "profiles": {}}
        store = await Store.open(
            self.conn.uri,
            pass_key=self.wallet_key,
            key_method=KEY_METHODS[self.wallet_key_derivation_method],
        )

        tables["items"] = await self._get_decoded_items_and_tags(store)

        tables["config"] = await self.conn.get_root_config()

        tables["profiles"] = await self.conn.get_profiles()

        with open(self.export_filename, "w") as json_file:
            json.dump(tables, json_file, indent=4)

        await store.close()
        await self.conn.close()

    async def run(self):
        """Run the exporter."""
        await self.export()
