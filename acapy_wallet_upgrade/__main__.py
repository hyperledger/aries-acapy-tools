"""Indy wallet upgrade."""

import argparse
import asyncio
import logging
import sys
from typing import Dict, Optional
from urllib.parse import urlparse

from .error import UpgradeError
from .pg_connection import PgConnection
from .sqlite_connection import SqliteConnection
from .strategies import DbpwStrategy, MwstAsProfilesStrategy, MwstAsStoresStrategy


def config():

    parser = argparse.ArgumentParser("askar-upgarde")
    parser.add_argument(
        "--strategy",
        required=True,
        choices=["dbpw", "mwst-as-profiles", "mwst-as-stores"],
        help=(
            "Specify migration strategy depending on database type, wallet "
            "management mode, and agent type."
        ),
    )
    parser.add_argument(
        "--uri",
        required=True,
        help=("Specify URI of database to be migrated."),
    )
    parser.add_argument(
        "--wallet-name",
        type=str,
        help=(
            "Specify name of wallet to be migrated for DatabasePerWallet "
            "(dbpw) migration strategy."
        ),
    )
    parser.add_argument(
        "--wallet-key",
        type=str,
        help=(
            "Specify key corresponding to the given name of the wallet to "
            "be migrated for database per wallet (dbpw) migration strategy."
        ),
    )
    parser.add_argument(
        "--base-wallet-name",
        type=str,
        help=(
            "Specify name of base wallet for the MultiWalletSingleTable as "
            "profiles (mwst-as-profiles) strategy. This base wallet and its "
            "subwallets will be migrated."
        ),
    )
    parser.add_argument(
        "--base-wallet-key",
        type=str,
        help=(
            "Specific key corresponding to the given name of the base wallet "
            "for the MultiWalletSingleTable as profiles (mwst-as-profiles) "
            "strategy."
        ),
    )
    parser.add_argument(
        "--wallet-keys",
        type=str,
        help=(
            "Specify mapping of wallet_name to wallet_key for all wallets "
            "to be migrated in the MultiWalletSingleTable as stores "
            "(mwst-as-stores) strategy."
        ),
    )
    parser.add_argument(
        "--allow-missing-wallet",
        action="store_true",
        help=(
            "Allow the migration of some, but not all, of the wallets in a "
            "MultiWalletSingleTable setup with standard agents to be migrated "
            "using the MultiWalletSingleTable as stores (mwst-as-stores) "
            "strategy. The remaining wallets will not be deleted."
        ),
    )
    parser.add_argument(
        "--delete-indy-wallets",
        action="store_true",
        help=(
            "Delete Indy wallets after migration. If there are wallets that "
            "were not migrated, whether or not the --allow-missing-wallet "
            "flag is True, the --delete-indy-wallets flag is overwritten and "
            "no wallets will be deleted."
        ),
    )
    parser.add_argument(
        "--skip-confirmation",
        action="store_true",
        help=(
            "Indicate if user does not want to be prompted for confirmation "
            "before deleting original Indy wallets database."
        ),
    )
    args, _ = parser.parse_known_args(sys.argv[1:])

    if args.strategy == "dbpw":
        if not args.wallet_name:
            raise ValueError("Wallet name required for dbpw strategy")
        if not args.wallet_key:
            raise ValueError("Wallet key required for dbpw strategy")

    if args.strategy == "mwst-as-profiles":
        if not args.base_wallet_name:
            raise ValueError("Base wallet name required for mwst-as-profiles strategy")
        if not args.base_wallet_key:
            raise ValueError("Base wallet key required for mwst-as-profiles strategy")

    if args.strategy == "mwst-as-stores":
        if not args.wallet_keys:
            raise ValueError("Wallet keys required for mwst-as-stores strategy")

    parsed = urlparse(args.uri)
    if parsed.scheme not in ("sqlite", "postgres"):
        raise ValueError("URI scheme must be one of: sqlite, postgres")

    return args


async def main(
    strategy: str,
    uri: str,
    wallet_name: Optional[str] = None,
    wallet_key: Optional[str] = None,
    base_wallet_name: Optional[str] = None,
    base_wallet_key: Optional[str] = None,
    wallet_keys: Optional[Dict[str, str]] = None,
    allow_missing_wallet: Optional[bool] = False,
    delete_indy_wallets: Optional[bool] = False,
    skip_confirmation: Optional[bool] = False,
):
    logging.basicConfig(level=logging.WARN)
    parsed = urlparse(uri)

    if strategy == "dbpw":
        if parsed.scheme == "sqlite":
            conn = SqliteConnection(uri)
        elif parsed.scheme == "postgres":
            conn = PgConnection(uri)
        else:
            raise ValueError("Unexpected DB URI scheme")
        if not wallet_name:
            raise ValueError("Wallet name required for dbpw strategy")
        if not wallet_key:
            raise ValueError("Wallet key required for dbpw strategy")

        strategy_inst = DbpwStrategy(conn, wallet_name, wallet_key)

    elif strategy == "mwst-as-profiles":
        if parsed.scheme != "postgres":
            raise ValueError("mwst-as-profiles strategy only valid for Postgres")

        if not base_wallet_name:
            raise ValueError("Base wallet name required for mwst-as-profiles strategy")
        if not base_wallet_key:
            raise ValueError("Base wallet key required for mwst-as-profiles strategy")

        strategy_inst = MwstAsProfilesStrategy(
            uri,
            base_wallet_name,
            base_wallet_key,
            delete_indy_wallets,
            skip_confirmation,
        )

    elif strategy == "mwst-as-stores":
        if parsed.scheme != "postgres":
            raise ValueError("mwst-as-stores strategy only valid for Postgres")

        if not wallet_keys:
            raise ValueError("Wallet keys required for mwst-as-stores strategy")

        strategy_inst = MwstAsStoresStrategy(
            uri, wallet_keys, allow_missing_wallet, delete_indy_wallets, skip_confirm
        )

    else:
        raise UpgradeError("Invalid strategy")

    await strategy_inst.run()


def entrypoint():
    args = config()
    asyncio.run(main(**vars(args)))


if __name__ == "__main__":
    entrypoint()
