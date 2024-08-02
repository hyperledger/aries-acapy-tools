import pytest
from acapy_controller import Controller
from acapy_wallet_upgrade.__main__ import main

from . import WalletTypeToBeTested
from .cases import MigrationTestCases
from .containers import Containers


class TestPgMWSTStores(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_migrate(self, containers: Containers):
        # Pre condition
        postgres = containers.postgres(5432)
        alice_container = containers.acapy_postgres(
            "alice", "alice_insecure1", 3001, "indy", postgres, mwst=True
        )
        # We must wait until Alice starts before starting Bob or else there are
        # race conditions on who can create the DB first
        containers.wait_until_healthy(alice_container)

        bob_container = containers.acapy_postgres(
            "bob", "bob_insecure1", 3002, "indy", postgres, mwst=True
        )
        containers.wait_until_healthy(bob_container)

        test_cases = MigrationTestCases()
        async with Controller("http://localhost:3001") as alice, Controller(
            "http://localhost:3002"
        ) as bob:
            await test_cases.pre(alice, bob)

        # Prepare for migration
        containers.stop(alice_container)
        containers.stop(bob_container)

        # Migrate
        await main(
            strategy="mwst-as-stores",
            uri="postgres://postgres:mysecretpassword@localhost:5432/wallets",
            wallet_keys={
                "alice": "alice_insecure1",
                "bob": "bob_insecure1",
            },
        )

        # Post condition
        alice_container = containers.acapy_postgres(
            "alice", "alice_insecure1", 3001, "askar", postgres, mwst=True
        )
        bob_container = containers.acapy_postgres(
            "bob", "bob_insecure1", 3002, "askar", postgres, mwst=True
        )
        containers.wait_until_healthy(alice_container)
        containers.wait_until_healthy(bob_container)

        async with Controller("http://localhost:3001") as alice, Controller(
            "http://localhost:3002"
        ) as bob:
            await test_cases.post(alice, bob)
