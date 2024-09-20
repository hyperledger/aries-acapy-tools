from argparse import Namespace

import pytest
from acapy_controller import Controller
from acapy_controller.models import CreateWalletResponse
from askar_tools.__main__ import main

from . import WalletTypeToBeTested
from .cases import TenantImportTestCases
from .containers import Containers


class TestTenantImport(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_tenant_import_pg(self, containers: Containers):
        # Prepare
        admin_postgres = containers.postgres(5432, name="admin_postgres")
        tenant_postgres = containers.postgres(5433, name="tenant_postgres")
        # Create an admin container with a single wallet
        admin_container = containers.acapy_postgres(
            "admin",
            "insecure",
            "kdf:argon2i:mod",
            "askar",
            3001,
            admin_postgres,
            mwst=True,
            mt=True,
            askar_profile=False,
        )
        tenant_container = containers.acapy_postgres(
            "tenant",
            "3cAZj1hPvUhKeBkzCKPTHhTxRRmYv5abDbjmaYwtk6Nf",
            "RAW",
            "askar",
            3002,
            tenant_postgres,
            mwst=False,
            mt=False,
        )
        containers.wait_until_healthy(admin_container)
        containers.wait_until_healthy(tenant_container)

        async with Controller("http://localhost:3001") as admin:
            test_cases = TenantImportTestCases()
            # Create sub wallet with admin
            alice_wallet = await admin.post(
                "/multitenancy/wallet",
                json={
                    "label": "Alice",
                    "wallet_name": "alice",
                    "wallet_key": "alice_insecure1",
                    "wallet_type": "askar",
                },
                response=CreateWalletResponse,
            )

            # Start the alice subwallet controller and create the separate db tenant controller
            async with Controller(
                "http://localhost:3001",
                wallet_id=alice_wallet.wallet_id,
                subwallet_token=alice_wallet.token,
            ) as alice, Controller(
                "http://localhost:3002",
            ) as tenant:
                await test_cases.pre(alice, tenant)

        # Action the import
        namespace = Namespace()
        namespace.__dict__.update(
            {
                "strategy": "tenant-import",
                "uri": "postgres://postgres:mysecretpassword@localhost:5432/admin",
                "wallet_name": "admin",
                "wallet_key": "insecure",
                "wallet_key_derivation_method": "ARGON2I_MOD",
                "tenant_uri": "postgres://postgres:mysecretpassword@localhost:5433/tenant",
                "tenant_wallet_name": "tenant",
                "tenant_wallet_key": "3cAZj1hPvUhKeBkzCKPTHhTxRRmYv5abDbjmaYwtk6Nf",
                "tenant_wallet_type": "askar",
                "tenant_label": "Tenant",
                "tenant_image_url": "https://example.com/image.png",
                "tenant_extra_settings": {"extra": "settings"},
                "tenant_webhook_urls": ["http://example.com/webhook"],
                "tenant_dispatch_type": "default",
                "tenant_wallet_key_derivation_method": "RAW",
            }
        )
        await main(namespace)

        async with Controller("http://localhost:3001") as admin:
            # Get the tenant wallet id and token
            wallets = await admin.get("/multitenancy/wallets")

            tenant_wallet_id = None
            for wallet in wallets["results"]:
                if wallet["settings"]["wallet.name"] == "tenant":
                    tenant_wallet_id = wallet["wallet_id"]
                    break
            assert tenant_wallet_id is not None

            tenant_wallet_token = (
                await admin.post(f"/multitenancy/wallet/{tenant_wallet_id}/token")
            )["token"]

            assert tenant_wallet_token is not None

            # Re-run the test cases with the new tenant wallet
            test_cases = TenantImportTestCases()
            async with Controller(
                "http://localhost:3001",
                wallet_id=alice_wallet.wallet_id,
                subwallet_token=alice_wallet.token,
            ) as alice, Controller(
                "http://localhost:3001",
                wallet_id=tenant_wallet_id,
                subwallet_token=tenant_wallet_token,
            ) as tenant:
                await test_cases.pre(alice, tenant)

        containers.stop(admin_container)
        containers.stop(admin_postgres)
        containers.stop(tenant_container)
        containers.stop(tenant_postgres)
