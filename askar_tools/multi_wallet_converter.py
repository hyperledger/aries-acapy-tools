"""Module for converting multi-tenant wallets between single wallet and multi wallet."""

from aries_askar import Store

from .error import ConversionError
from .key_methods import KEY_METHODS
from .pg_connection import PgConnection
from .sqlite_connection import SqliteConnection


class MultiWalletConverter:
    """Util class for converting multi-tenant wallets between single wallet and multi wallet."""  # noqa: E501

    def __init__(
        self,
        conn: SqliteConnection | PgConnection,
        wallet_name: str,
        wallet_key: str,
        wallet_key_derivation_method: str,
        sub_wallet_name: str,
    ):
        """Initialize the MultiWalletConverter instance.

        Args:
            conn (SqliteConnection): The SQLite connection object.
            wallet_name (str): The name of the wallet.
            wallet_key (str): The key for the wallet.
            wallet_key_derivation_method (str): The key derivation method for the wallet.
            sub_wallet_name (str): The name of the sub wallet.
        """
        self.conn = conn
        self.admin_wallet_name = wallet_name
        self.admin_wallet_key = wallet_key
        self.wallet_key_derivation_method = wallet_key_derivation_method
        self.sub_wallet_name = sub_wallet_name

    def get_wallet_records(self, entries):
        """Get the wallet records from the given entries.

        Args:
            entries: The entries to process.

        Returns:
            A list of wallet records.
        """
        wallet_records = []
        for entry in entries:
            if entry.category == "wallet_record":
                wallet_records.append(entry.value_json)

        return wallet_records

    async def convert_single_wallet_to_multi_wallet(self):
        """Converts a single wallet to a multi-wallet."""

        print("Converting multitenant single-wallet agent to multi-wallet...")
        print(f"Opening admin store [{self.admin_wallet_name}]...")
        print(f"Opening sub wallet store [{self.sub_wallet_name}]...")

        if f"{self.admin_wallet_name}" not in self.conn.uri:
            raise ConversionError("The wallet name must be included in the URI.")

        admin_store = await Store.open(self.conn.uri, pass_key=self.admin_wallet_key)

        try:
            sub_wallet_store = await Store.open(
                self.conn.uri.replace(self.admin_wallet_name, self.sub_wallet_name),
                pass_key=self.admin_wallet_key,
            )
        except Exception as e:
            print(e)
            raise ConversionError(
                f"""Error opening sub wallet store {self.sub_wallet_name}. Are you sure 
                this is a multitenant wallet and you have the name correct?"""
            )

        admin_store_scan = admin_store.scan()
        admin_store_entries = await admin_store_scan.fetch_all()
        success = True
        for wallet_record in self.get_wallet_records(admin_store_entries):
            try:
                # Create the new db for the individual wallet
                await self.conn.create_database(
                    self.admin_wallet_name, wallet_record["settings"]["wallet.name"]
                )
                key_method = KEY_METHODS.get(
                    wallet_record["settings"].get(
                        "wallet.key_derivation_method", "ARGON2I_MOD"
                    )
                )
                print(
                    f"""Copying wallet {wallet_record['settings']['wallet.id']} : 
                    {wallet_record['settings']['wallet.name']}..."""
                )

                # Get the tenant profile store and set it as the default profile
                sub_wallet_tenant_store = await sub_wallet_store.open(
                    self.conn.uri.replace(self.admin_wallet_name, self.sub_wallet_name),
                    key_method=key_method,
                    pass_key=self.admin_wallet_key,
                    profile=wallet_record["settings"]["wallet.id"],
                )
                await sub_wallet_tenant_store.set_default_profile(
                    wallet_record["settings"]["wallet.id"]
                )

                # Copy it to the individual wallet db
                await sub_wallet_tenant_store.copy_to(
                    self.conn.uri.replace(
                        self.admin_wallet_name,
                        wallet_record["settings"]["wallet.name"],
                    ),
                    key_method=key_method,
                    pass_key=wallet_record["settings"]["wallet.key"],
                    recreate=False,
                )

                # Open the wallet from the new location an delete the extra profiles
                new_tenant_store = await Store.open(
                    self.conn.uri.replace(
                        self.admin_wallet_name, wallet_record["settings"]["wallet.name"]
                    ),
                    key_method=key_method,
                    pass_key=wallet_record["settings"]["wallet.key"],
                )
                for profile in await new_tenant_store.list_profiles():
                    if profile != wallet_record["settings"]["wallet.id"]:
                        await new_tenant_store.remove_profile(profile)
            except Exception as e:
                print(e)
                print(
                    f"""There was an error copying the wallet 
                    {wallet_record["settings"]["wallet.name"]}. The sub wallet 
                    {self.sub_wallet_name} will not be deleted. Try running again."""
                )
                await self.conn.remove_wallet(
                    self.admin_wallet_name, wallet_record["settings"]["wallet.name"]
                )
                success = False

        if success:
            print(f"Deleting sub wallet {self.sub_wallet_name}...")
            await sub_wallet_store.close()
            await self.conn.remove_wallet(self.admin_wallet_name, self.sub_wallet_name)

        await admin_store.close()
        await self.conn.close()

    async def run(self):
        """Run the multi-wallet conversion."""
        await self.convert_single_wallet_to_multi_wallet()
