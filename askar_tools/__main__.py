"""Askar wallet tools."""

import argparse
import asyncio
import logging
import sys
from typing import Optional
from urllib.parse import urlparse

from .exporter import Exporter
from .multi_wallet_converter import MultiWalletConverter
from .pg_connection import PgConnection
from .sqlite_connection import SqliteConnection
from .tenant_importer import TenantImporter


def config():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser("askar-wallet-tools")
    parser.add_argument(
        "--strategy",
        required=True,
        choices=["export", "mt-convert-to-mw", "tenant-import"],
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
        required=True,
        type=str,
        help=(
            "Specify name of wallet to be migrated for DatabasePerWallet "
            "(export) migration strategy."
        ),
    )
    parser.add_argument(
        "--wallet-key",
        required=True,
        type=str,
        help=(
            "Specify key corresponding to the given name of the wallet to "
            "be migrated for database per wallet (export) migration strategy."
        ),
    )
    parser.add_argument(
        "--multitenant-sub-wallet-name",
        type=str,
        help=(
            "The existing wallet name for a multitenant single wallet conversion."
            "The default if not provided is 'multitenant_sub_wallet'"
        ),
        default="multitenant_sub_wallet",
    )

    # Add arguments for tenant import
    parser.add_argument(
        "--tenant-uri",
        help=("Specify URI of the tenant database to be imported."),
    )
    parser.add_argument(
        "--tenant-wallet-name",
        type=str,
        help=("Specify name of tenant wallet to be imported."),
    )
    parser.add_argument(
        "--tenant-wallet-key",
        type=str,
        help=("Specify key corresponding of the tenant wallet to be imported."),
    )
    parser.add_argument(
        "--export-filename",
        type=str,
        help=("Specify the filename to export the data to."),
    )

    args, _ = parser.parse_known_args(sys.argv[1:])

    if args.strategy == "tenant-import":
        if (
            not args.tenant_uri
            or not args.tenant_wallet_name
            or not args.tenant_wallet_key
        ):
            parser.error(
                """For tenant-import strategy, tenant-uri, tenant-wallet-name, and 
                tenant-wallet-key are required."""
            )

    return args


async def main(
    strategy: str,
    uri: str,
    wallet_name: Optional[str] = None,
    wallet_key: Optional[str] = None,
    multitenant_sub_wallet_name: Optional[str] = "multitenant_sub_wallet",
    tenant_uri: Optional[str] = None,
    tenant_wallet_name: Optional[str] = None,
    tenant_wallet_key: Optional[str] = None,
    tenant_export_filename: Optional[str] = "wallet_export.json",
):
    """Run the main function."""
    logging.basicConfig(level=logging.WARN)
    parsed = urlparse(uri)

    # Connection setup
    if parsed.scheme == "sqlite":
        conn = SqliteConnection(uri)
    elif parsed.scheme == "postgres":
        conn = PgConnection(uri)
    else:
        raise ValueError("Unexpected DB URI scheme")

    # Strategy setup
    if strategy == "export":
        await conn.connect()
        print("wallet_name", wallet_name)
        method = Exporter(
            conn=conn,
            wallet_name=wallet_name,
            wallet_key=wallet_key,
            export_filename=tenant_export_filename,
        )
    elif strategy == "mt-convert-to-mw":
        await conn.connect()
        method = MultiWalletConverter(
            conn=conn,
            wallet_name=wallet_name,
            wallet_key=wallet_key,
            sub_wallet_name=multitenant_sub_wallet_name,
        )
    elif strategy == "tenant-import":
        tenant_parsed = urlparse(tenant_uri)
        if tenant_parsed.scheme == "sqlite":
            tenant_conn = SqliteConnection(tenant_uri)
        elif tenant_parsed.scheme == "postgres":
            tenant_conn = PgConnection(tenant_uri)
        else:
            raise ValueError("Unexpected tenant DB URI scheme")

        await conn.connect()
        await tenant_conn.connect()
        method = TenantImporter(
            admin_conn=conn,
            admin_wallet_name=wallet_name,
            admin_wallet_key=wallet_key,
            tenant_conn=tenant_conn,
            tenant_wallet_name=tenant_wallet_name,
            tenant_wallet_key=tenant_wallet_key,
        )
    else:
        raise Exception("Invalid strategy")

    await method.run()


def entrypoint():
    """Entrypoint for the CLI."""
    args = config()
    asyncio.run(main(**vars(args)))


if __name__ == "__main__":
    asyncio.run(entrypoint())
