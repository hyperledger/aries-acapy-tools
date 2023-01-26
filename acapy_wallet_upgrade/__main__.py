"""Indy wallet upgrade."""

import argparse
import asyncio
import logging
import sys
from typing import Dict, Optional
from urllib.parse import urlparse

from .error import UpgradeError
from .pg_connection import PgConnection
from .pg_mwst_connection import PgMWSTConnection
from .pg_mwst_stores_connection import PgMWSTStoresConnection
from .sqlite_connection import SqliteConnection
from .strategies import DbpwStrategy, MwstAsProfilesStrategy, MwstAsStoresStrategy


def config():

    parser = argparse.ArgumentParser("askar-upgarde")
    parser.add_argument(
        "--strategy",
        type=str,
        action="store",
        required=True,
    )
    parser.add_argument("--uri", type=str, action="store", required=True)
    parser.add_argument("--wallet-name", type=str, action="store")
    parser.add_argument("--wallet-key", type=str, action="store")
    parser.add_argument("--base-wallet-name", type=str, action="store")
    parser.add_argument("--wallet-keys", type=str, action="store")
    parser.add_argument("--allow-missing-wallet", type=str, action="store")
    args, _ = parser.parse_known_args(sys.argv[1:])

    if args.strategy not in ("dpbw", "mwst-as-profiles", "mwst-as-stores"):
        raise ValueError(
            "Strategy must be one of: dbpw, mwst-as-profiles, mwst-as-stores"
        )

    if args.strategy == "dbpw":
        if not args.wallet_name:
            raise ValueError("Wallet name required for dbpw strategy")
        if not args.wallet_key:
            raise ValueError("Wallet key required for dbpw strategy")

    if args.strategy == "mwst-as-profiles":
        if not args.base_wallet_name:
            raise ValueError("Base wallet name required for mwst-as-profiles strategy")
        if not args.wallet_keys:
            raise ValueError("Wallet keys required for mwst-as-profiles strategy")

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
    wallet_keys: Optional[Dict[str, str]] = None,
    allow_missing_wallet: Optional[bool] = None,
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
        if not wallet_keys:
            raise ValueError("Wallet keys required for mwst-as-profiles strategy")

        conn = PgMWSTConnection(uri)
        strategy_inst = MwstAsProfilesStrategy(
            conn, base_wallet_name, wallet_keys, allow_missing_wallet
        )

    elif strategy == "mwst-as-stores":
        if parsed.scheme != "postgres":
            raise ValueError("mwst-as-stores strategy only valid for Postgres")

        if not wallet_keys:
            raise ValueError("Wallet keys required for mwst-as-stores strategy")

        conn = PgMWSTStoresConnection(uri)
        strategy_inst = MwstAsStoresStrategy(conn, wallet_keys, allow_missing_wallet)

    else:
        raise UpgradeError("Invalid strategy")

    await strategy_inst.run()


if __name__ == "__main__":
    args = config()
    asyncio.run(main(**vars(args)))
