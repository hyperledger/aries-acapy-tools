import pytest
from acapy_controller import Controller
from acapy_controller.models import CreateWalletResponse
from askar_tools.__main__ import main

from . import WalletTypeToBeTested
from .cases import MtConvertToMwTestCases
from .containers import Containers


class TestPgMtConvertToMw(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_conversion_pg(self, containers: Containers):
        # Prepare
        postgres = containers.postgres(5432)
        # Create an admin container with a single wallet
        admin_container = containers.acapy_postgres(
            "admin",
            "insecure",
            3001,
            "askar",
            postgres,
            mwst=True,
            mt=True,
            askar_profile=True,
        )
        containers.wait_until_healthy(admin_container)

        async with Controller("http://localhost:3001") as admin:
            test_cases = MtConvertToMwTestCases()
            # Create sub wallets and run test cases which create db objects
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
            bob_wallet = await admin.post(
                "/multitenancy/wallet",
                json={
                    "label": "Bob",
                    "wallet_name": "bob",
                    "wallet_key": "bob_insecure1",
                    "wallet_type": "askar",
                },
                response=CreateWalletResponse,
            )

            async with Controller(
                "http://localhost:3001",
                wallet_id=alice_wallet.wallet_id,
                subwallet_token=alice_wallet.token,
            ) as alice, Controller(
                "http://localhost:3001",
                wallet_id=bob_wallet.wallet_id,
                subwallet_token=bob_wallet.token,
            ) as bob:
                await test_cases.pre(alice, bob)

        # Stop the admin container
        containers.stop(admin_container)

        # Action the conversion
        await main(
            strategy="mt-convert-to-mw",
            uri="postgres://postgres:mysecretpassword@localhost:5432/admin",
            wallet_name="admin",
            wallet_key="insecure",
        )

        # Start a new admin container that expects multiple wallet for each sub wallet
        admin_container = containers.acapy_postgres(
            "admin",
            "insecure",
            3001,
            "askar",
            postgres,
            mt=True,
            askar_profile=False,
        )

        containers.wait_until_healthy(admin_container)

        # Run the test cases again for the sub wallets
        async with Controller("http://localhost:3001") as admin:
            test_cases = MtConvertToMwTestCases()
            async with Controller(
                "http://localhost:3001",
                wallet_id=alice_wallet.wallet_id,
                subwallet_token=alice_wallet.token,
            ) as alice, Controller(
                "http://localhost:3001",
                wallet_id=bob_wallet.wallet_id,
                subwallet_token=bob_wallet.token,
            ) as bob:
                await test_cases.pre(alice, bob)

        containers.stop(admin_container)
        containers.stop(postgres)

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_conversion_sqlite(self, containers: Containers, tmp_path_factory):
        # Prepare
        admin_volume_path = tmp_path_factory.mktemp("admin")
        sub_wallet_volume_path = tmp_path_factory.mktemp("multitenant_sub_wallet")
        containers.fix_permissions(admin_volume_path, user=1001, group=1001)
        containers.fix_permissions(sub_wallet_volume_path, user=1001, group=1001)
        admin_container = containers.acapy_sqlite(
            "admin",
            "insecure",
            3001,
            "askar",
            admin_volume_path,
            "/home/aries/.aries_cloudagent/wallet/admin",
            sub_wallet_volume_path,
            "/home/aries/.aries_cloudagent/wallet/multitenant_sub_wallet",
            mt=True,
            askar_profile=True,
        )
        containers.wait_until_healthy(admin_container)

        async with Controller("http://localhost:3001") as admin:
            test_cases = MtConvertToMwTestCases()
            # Create sub wallets and run test cases which create db objects
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
            bob_wallet = await admin.post(
                "/multitenancy/wallet",
                json={
                    "label": "Bob",
                    "wallet_name": "bob",
                    "wallet_key": "bob_insecure1",
                    "wallet_type": "askar",
                },
                response=CreateWalletResponse,
            )

            async with Controller(
                "http://localhost:3001",
                wallet_id=alice_wallet.wallet_id,
                subwallet_token=alice_wallet.token,
            ) as alice, Controller(
                "http://localhost:3001",
                wallet_id=bob_wallet.wallet_id,
                subwallet_token=bob_wallet.token,
            ) as bob:
                await test_cases.pre(alice, bob)

        containers.fix_permissions(admin_volume_path)
        containers.fix_permissions(sub_wallet_volume_path)

        # Action the conversion
        await main(
            strategy="mt-convert-to-mw",
            uri=f"sqlite://{admin_volume_path}/sqlite.db",
            wallet_name="admin",
            wallet_key="insecure",
        )
