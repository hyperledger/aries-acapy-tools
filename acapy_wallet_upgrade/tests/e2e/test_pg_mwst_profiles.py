import pytest
from acapy_controller import Controller
from acapy_controller.models import CreateWalletResponse
from acapy_wallet_upgrade.__main__ import main

from . import WalletTypeToBeTested
from .cases import MigrationTestCases
from .containers import Containers


class TestPgMWSTProfiles(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_migrate(self, containers: Containers):
        # Pre condition
        postgres = containers.postgres(5432)
        agency_container = containers.acapy_postgres(
            "agency",
            "agency_insecure0",
            3001,
            "indy",
            postgres,
            mwst=True,
            mt=True,
        )
        containers.wait_until_healthy(agency_container)

        test_cases = MigrationTestCases()
        async with Controller("http://localhost:3001") as agency:
            alice_wallet = await agency.post(
                "/multitenancy/wallet",
                json={
                    "label": "Alice",
                    "wallet_name": "alice",
                    "wallet_key": "alice_insecure1",
                    "wallet_type": "indy",
                },
                response=CreateWalletResponse,
            )
            bob_wallet = await agency.post(
                "/multitenancy/wallet",
                json={
                    "label": "Bob",
                    "wallet_name": "bob",
                    "wallet_key": "bob_insecure1",
                    "wallet_type": "indy",
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

        # Prepare for migration
        containers.stop(agency_container)

        # Migrate
        await main(
            strategy="mwst-as-profiles",
            uri="postgres://postgres:mysecretpassword@localhost:5432/wallets",
            base_wallet_name="agency",
            base_wallet_key="agency_insecure0",
        )

        # Post condition
        agency_container = containers.acapy_postgres(
            "agency",
            "agency_insecure0",
            3001,
            "askar",
            postgres,
            mwst=True,
            mt=True,
            askar_profile=True,
        )
        containers.wait_until_healthy(agency_container)

        async with Controller(
            "http://localhost:3001",
            wallet_id=alice_wallet.wallet_id,
            subwallet_token=alice_wallet.token,
        ) as alice, Controller(
            "http://localhost:3001",
            wallet_id=bob_wallet.wallet_id,
            subwallet_token=bob_wallet.token,
        ) as bob:
            await test_cases.post(alice, bob)
