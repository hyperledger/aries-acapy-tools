"""Module for converting multi-tenant wallets between single wallet and multi wallet."""

import json
import time
from datetime import datetime

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
        self.sub_wallet_store = None

    def log(self, message: str):
        """Print a timestamped, unbuffered progress message."""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

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

    def tenant_uri(self, wallet_name: str) -> str:
        """Build the database URI for a tenant wallet."""
        return self.conn.uri.replace(self.admin_wallet_name, wallet_name)

    def tenant_key_method(self, settings: dict) -> str:
        """Get the askar key derivation method for a tenant wallet."""
        return KEY_METHODS.get(
            settings.get("wallet.key_derivation_method", "ARGON2I_MOD")
        )

    async def count_records_by_category(
        self, store: Store, profile: str = None
    ) -> dict:
        """Count the records per category in a store profile.

        Iterates the scan instead of fetching all entries so memory stays flat
        for large wallets.
        """
        counts = {}
        async for entry in store.scan(profile=profile):
            counts[entry.category] = counts.get(entry.category, 0) + 1
        return counts

    async def count_keys(self, store: Store, profile: str = None) -> int:
        """Count the key records in a store profile."""
        async with store.session(profile=profile) as session:
            return len(await session.fetch_all_keys())

    async def verify_tenant_wallet(self, wallet_record) -> tuple:
        """Verify a tenant database against the tenant's profile in the sub wallet.

        Checks that the target store opens with the tenant's own wallet key, that
        it contains exactly the tenant's profile, and that the record counts per
        category and the key counts match the tenant's profile in the source sub
        wallet.

        Returns:
            A ``(verified, reason)`` tuple: ``(True, "")`` when the target
            verifies, ``(False, reason)`` otherwise.
        """
        settings = wallet_record["settings"]
        wallet_id = settings["wallet.id"]
        try:
            tenant_store = await Store.open(
                self.tenant_uri(settings["wallet.name"]),
                key_method=self.tenant_key_method(settings),
                pass_key=settings["wallet.key"],
            )
        except Exception as e:
            return False, f"cannot open target store: {e}"

        try:
            profiles = list(await tenant_store.list_profiles())
            if profiles != [wallet_id]:
                return False, (
                    f"expected exactly one profile ['{wallet_id}'], found {profiles}"
                )

            source_counts = await self.count_records_by_category(
                self.sub_wallet_store, profile=wallet_id
            )
            target_counts = await self.count_records_by_category(tenant_store)
            if source_counts != target_counts:
                categories = sorted(set(source_counts) | set(target_counts))
                diff = {
                    category: (
                        source_counts.get(category, 0),
                        target_counts.get(category, 0),
                    )
                    for category in categories
                    if source_counts.get(category, 0) != target_counts.get(category, 0)
                }
                return False, (
                    f"record counts differ (category: source vs target): {diff}"
                )

            source_keys = await self.count_keys(
                self.sub_wallet_store, profile=wallet_id
            )
            target_keys = await self.count_keys(tenant_store)
            if source_keys != target_keys:
                return False, (
                    f"key counts differ: source {source_keys} vs target {target_keys}"
                )
        except Exception as e:
            return False, f"verification error: {e}"
        finally:
            await tenant_store.close()

        return True, ""

    async def convert_tenant_wallet(self, wallet_record):
        """Create the tenant database and copy the tenant's wallet into it."""
        settings = wallet_record["settings"]
        wallet_id = settings["wallet.id"]
        wallet_name = settings["wallet.name"]
        key_method = self.tenant_key_method(settings)

        # Create the new db for the individual wallet
        await self.conn.create_database(self.admin_wallet_name, wallet_name)

        # Get the tenant profile store and set it as the default profile
        sub_wallet_tenant_store = await Store.open(
            self.conn.uri.replace(self.admin_wallet_name, self.sub_wallet_name),
            key_method=key_method,
            pass_key=self.admin_wallet_key,
            profile=wallet_id,
        )
        try:
            await sub_wallet_tenant_store.set_default_profile(wallet_id)

            # Copy it to the individual wallet db
            await sub_wallet_tenant_store.copy_to(
                self.tenant_uri(wallet_name),
                key_method=key_method,
                pass_key=settings["wallet.key"],
                recreate=False,
            )
        finally:
            await sub_wallet_tenant_store.close()

        # Open the wallet from the new location and delete the extra profiles
        new_tenant_store = await Store.open(
            self.tenant_uri(wallet_name),
            key_method=key_method,
            pass_key=settings["wallet.key"],
        )
        try:
            for profile in await new_tenant_store.list_profiles():
                if profile != wallet_id:
                    await new_tenant_store.remove_profile(profile)
        finally:
            await new_tenant_store.close()

    async def convert_single_wallet_to_multi_wallet(self):
        """Convert a single wallet to a multi-wallet.

        Idempotent and resumable: for each tenant, a target database that already
        exists and verifies is skipped; one that exists but fails verification is
        dropped and re-converted; one that is absent is converted. The sub wallet
        is only deleted when every tenant wallet has been verified, and a
        ``ConversionError`` is raised (non-zero exit) otherwise, so a re-run
        after a failure resumes where the previous run left off.
        """
        run_started = time.monotonic()
        self.log("Converting multitenant single-wallet agent to multi-wallet...")
        self.log(f"Opening admin store [{self.admin_wallet_name}]...")
        self.log(f"Opening sub wallet store [{self.sub_wallet_name}]...")

        if f"{self.admin_wallet_name}" not in self.conn.uri:
            raise ConversionError("The wallet name must be included in the URI.")

        admin_store = await Store.open(self.conn.uri, pass_key=self.admin_wallet_key)

        try:
            self.sub_wallet_store = await Store.open(
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
        wallet_records = self.get_wallet_records(admin_store_entries)
        total = len(wallet_records)
        results = []
        sub_wallet_dropped = False

        try:
            for index, wallet_record in enumerate(wallet_records, start=1):
                settings = wallet_record["settings"]
                wallet_id = settings["wallet.id"]
                wallet_name = settings["wallet.name"]
                prefix = f"({index}/{total}) {wallet_id} : {wallet_name}"
                tenant_started = time.monotonic()
                outcome = None
                detail = ""
                target_fresh = False

                try:
                    if await self.conn.database_exists(
                        self.admin_wallet_name, wallet_name
                    ):
                        self.log(f"{prefix}: target database exists, verifying...")
                        verified, reason = await self.verify_tenant_wallet(
                            wallet_record
                        )
                        if verified:
                            outcome = "skipped"
                            self.log(f"{prefix}: SKIP (already converted and verified)")
                        else:
                            self.log(
                                f"{prefix}: failed verification ({reason}); "
                                "dropping and re-converting..."
                            )
                            await self.conn.remove_database(
                                self.admin_wallet_name, wallet_name
                            )
                            outcome = "redone"
                    else:
                        outcome = "converted"

                    if outcome != "skipped":
                        target_fresh = True
                        self.log(f"{prefix}: copying wallet...")
                        await self.convert_tenant_wallet(wallet_record)
                        verified, reason = await self.verify_tenant_wallet(
                            wallet_record
                        )
                        if not verified:
                            outcome = "failed"
                            detail = f"copied but failed verification: {reason}"
                            self.log(
                                f"{prefix}: FAILED ({detail}). Leaving the target "
                                "database in place; a re-run will drop and redo it."
                            )
                except Exception as e:
                    outcome = "failed"
                    detail = str(e)
                    self.log(
                        f"{prefix}: FAILED ({e}). The sub wallet "
                        f"{self.sub_wallet_name} will not be deleted. "
                        "Run again to resume."
                    )
                    if target_fresh:
                        # Only remove a database this run was actively copying into;
                        # pre-existing databases are never dropped on error.
                        try:
                            await self.conn.remove_database(
                                self.admin_wallet_name, wallet_name
                            )
                        except Exception as cleanup_error:
                            self.log(
                                f"{prefix}: could not clean up partial target "
                                f"database: {cleanup_error}"
                            )

                elapsed = round(time.monotonic() - tenant_started, 1)
                if outcome in ("converted", "redone") and not detail:
                    self.log(f"{prefix}: verified OK in {elapsed}s")
                results.append(
                    {
                        "wallet_id": wallet_id,
                        "wallet_name": wallet_name,
                        "outcome": outcome,
                        "detail": detail,
                        "seconds": elapsed,
                    }
                )

            failed = [result for result in results if result["outcome"] == "failed"]
            if total > 0 and not failed:
                self.log(f"Deleting sub wallet {self.sub_wallet_name}...")
                await self.sub_wallet_store.close()
                await self.conn.remove_database(
                    self.admin_wallet_name, self.sub_wallet_name
                )
                sub_wallet_dropped = True

            summary = {
                "total": total,
                "converted": sum(1 for r in results if r["outcome"] == "converted"),
                "skipped": sum(1 for r in results if r["outcome"] == "skipped"),
                "redone": sum(1 for r in results if r["outcome"] == "redone"),
                "failed": len(failed),
                "sub_wallet_dropped": sub_wallet_dropped,
                "elapsed_seconds": round(time.monotonic() - run_started, 1),
                "tenants": results,
            }
            print("=== mt-convert-to-mw summary ===", flush=True)
            print(json.dumps(summary, indent=2), flush=True)
        finally:
            if self.sub_wallet_store:
                await self.sub_wallet_store.close()
            await admin_store.close()
            await self.conn.close()

        if total == 0:
            raise ConversionError(
                f"No wallet records found in the admin store "
                f"[{self.admin_wallet_name}]; nothing converted and the sub wallet "
                f"was not deleted. Check the wallet name and URI."
            )
        if failed:
            raise ConversionError(
                f"{len(failed)} of {total} tenant wallets failed conversion; the "
                f"sub wallet {self.sub_wallet_name} was not deleted. Run again to "
                f"resume — completed tenants will be verified and skipped."
            )

    async def run(self):
        """Run the multi-wallet conversion."""
        await self.convert_single_wallet_to_multi_wallet()
