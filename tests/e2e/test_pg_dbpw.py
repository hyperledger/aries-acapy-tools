from controller import Controller
import pytest

from .cases import MigrationTestCases
from .containers import Containers

from acapy_wallet_upgrade.__main__ import main

from . import WalletTypeToBeTested


class TestPgDBPW(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_migrate(self, containers: Containers):
        # Pre condition
        postgres = containers.postgres(5432)
        alice_container = containers.acapy_postgres(
            "alice", "insecure", 3001, "indy", postgres
        )
        bob_container = containers.acapy_postgres(
            "bob", "insecure", 3002, "indy", postgres
        )
        containers.wait_until_healthy(alice_container)
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
            strategy="dbpw",
            uri=f"postgres://postgres:mysecretpassword@localhost:5432/alice",
            wallet_name="alice",
            wallet_key="insecure",
        )

        await main(
            strategy="dbpw",
            uri=f"postgres://postgres:mysecretpassword@localhost:5432/bob",
            wallet_name="bob",
            wallet_key="insecure",
        )

        # Post condition
        alice_container = containers.acapy_postgres(
            "alice", "insecure", 3001, "askar", postgres
        )
        bob_container = containers.acapy_postgres(
            "bob", "insecure", 3002, "askar", postgres
        )
        containers.wait_until_healthy(alice_container)
        containers.wait_until_healthy(bob_container)

        async with Controller("http://localhost:3001") as alice, Controller(
            "http://localhost:3002"
        ) as bob:
            await test_cases.post(alice, bob)
