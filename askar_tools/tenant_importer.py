"""This module contains the Tenant Importer class."""

import time
import uuid

from aries_askar import Store

from .pg_connection import PgConnection
from .sqlite_connection import SqliteConnection


class TenantImporter:
    """The Tenant Importer class."""

    def __init__(
        self,
        admin_conn: SqliteConnection | PgConnection,
        admin_wallet_name: str,
        admin_wallet_key: str,
        tenant_conn: SqliteConnection | PgConnection,
        tenant_wallet_name: str,
        tenant_wallet_key: str,
    ):
        """Initialize the Tenant Importer object.

        Args:
            admin_conn: The admin connection object.
            admin_wallet_name: The name of the admin wallet.
            admin_wallet_key: The key for the admin wallet.
            tenant_conn: The tenant connection object.
            tenant_wallet_name: The name of the tenant wallet.
            tenant_wallet_key: The key for the tenant wallet.
        """
        self.admin_conn = admin_conn
        self.admin_wallet_name = admin_wallet_name
        self.admin_wallet_key = admin_wallet_key
        self.tenant_conn = tenant_conn
        self.tenant_wallet_name = tenant_wallet_name
        self.tenant_wallet_key = tenant_wallet_key

    async def _create_tenant(self, wallet_id: str, admin_txn, current_time: str):
        # Create wallet record in admin wallet
        await admin_txn.insert(
            category="wallet_record",
            name=wallet_id,
            value_json={
                "wallet_name": self.tenant_wallet_name,
                "created_at": current_time,
                "updated_at": current_time,
                "settings": {
                    "wallet.type": "askar",
                    "wallet.name": self.tenant_wallet_name,
                    "wallet.key": self.tenant_wallet_key,
                    "wallet.id": wallet_id,
                    "wallet.dispatch_type": "base",
                },
                "key_management_mode": "managed",
                "jwt_iat": current_time,
            },
            tags={
                "wallet_name": self.tenant_wallet_name,
            },
        )

    async def _create_forward_routes(
        self, tenant_wallet: Store, admin_txn, wallet_id: str, current_time: str
    ):
        # Import DIDs, connections, and DID keys in forward route table
        tenant_did_scan = tenant_wallet.scan(category="did")
        tenant_dids = await tenant_did_scan.fetch_all()
        for did in tenant_dids:
            print(f"Importing DID: {did.value_json}")
            await admin_txn.insert(
                category="forward_route",
                name=str(uuid.uuid4()),
                value_json={
                    "recipient_key": did.value_json["verkey"],
                    "wallet_id": wallet_id,
                    "created_at": current_time,
                    "updated_at": current_time,
                    "connection_id": None,
                },
                tags={
                    "recipient_key": did.value_json["verkey"],
                    "role": "server",
                    "wallet_id": wallet_id,
                },
            )
        tenant_connection_scan = tenant_wallet.scan(category="connection")
        tenant_connections = await tenant_connection_scan.fetch_all()
        for connection in tenant_connections:
            print(f"Importing connection: {connection.value_json}")
            await admin_txn.insert(
                category="forward_route",
                name=str(uuid.uuid4()),
                value_json={
                    "recipient_key": connection.value_json["invitation_key"],
                    "wallet_id": wallet_id,
                    "created_at": current_time,
                    "updated_at": current_time,
                    "connection_id": None,
                },
                tags={
                    "recipient_key": connection.value_json["invitation_key"],
                    "role": "server",
                    "wallet_id": wallet_id,
                },
            )
        tenant_did_key_scan = tenant_wallet.scan(category="did_key")
        tenant_did_keys = await tenant_did_key_scan.fetch_all()
        for did_key in tenant_did_keys:
            print(f"Importing did key: {did_key.value}")
            await admin_txn.insert(
                category="forward_route",
                name=str(uuid.uuid4()),
                value_json={
                    "recipient_key": did_key.tags["key"],
                    "wallet_id": wallet_id,
                    "created_at": current_time,
                    "updated_at": current_time,
                    "connection_id": None,
                },
                tags={
                    "recipient_key": did_key.tags["key"],
                    "role": "server",
                    "wallet_id": wallet_id,
                },
            )

    async def import_tenant(self):
        """Import the tenant wallet into the admin wallet."""
        print("Importing tenant wallet into admin wallet")

        # Make wallet/db in admin location for tenant
        await self.admin_conn.create_database(
            admin_wallet_name=self.admin_wallet_name,
            sub_wallet_name=self.tenant_wallet_name,
        )
        # Copy the tenant wallet to the admin wallet location
        tenant_wallet = await Store.open(
            uri=self.tenant_conn.uri,
            pass_key=self.tenant_wallet_key,
        )
        await tenant_wallet.copy_to(
            target_uri=self.admin_conn.uri.replace(
                self.admin_wallet_name, self.tenant_wallet_name
            ),
            pass_key=self.tenant_wallet_key,
        )

        # Import the tenant wallet into the admin wallet
        admin_store = await Store.open(
            uri=self.admin_conn.uri,
            pass_key=self.admin_wallet_key,
        )
        async with admin_store.transaction() as admin_txn:
            wallet_id = str(uuid.uuid4())
            current_time = time.time()
            await self._create_tenant(
                wallet_id=wallet_id,
                admin_txn=admin_txn,
                current_time=current_time,
            )
            await self._create_forward_routes(
                tenant_wallet=tenant_wallet,
                admin_txn=admin_txn,
                wallet_id=wallet_id,
                current_time=current_time,
            )
            await admin_txn.commit()

        await self.admin_conn.close()
        await self.tenant_conn.close()

    async def run(self):
        """Run the importer."""
        await self.import_tenant()
