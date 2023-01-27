import asyncio

from controller import Controller
import docker
import pytest
import pytest_asyncio

from .cases import MigrationTestCases
from .containers import Containers

from acapy_wallet_upgrade.__main__ import main


class WalletTypeToBeTested:
    @pytest.fixture(scope="class")
    def event_loop(self):
        policy = asyncio.get_event_loop_policy()
        loop = policy.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture(scope="class")
    def containers(self):
        containers = Containers(docker.from_env()).setup()
        yield containers
        containers.teardown()

    @pytest.fixture(scope="class", autouse=True)
    def tails(self, containers: Containers):
        yield containers.tails()


class TestSqliteDBPW(WalletTypeToBeTested):
    @pytest.mark.asyncio
    async def test_migrate(self, containers: Containers, tmp_path_factory):
        # Pre condition
        alice_volume_path = tmp_path_factory.mktemp("alice")
        alice_container = containers.acapy_sqlite(
            "alice", "insecure", 3001, "indy", alice_volume_path
        )
        containers.wait_until_healthy(alice_container)

        bob_volume_path = tmp_path_factory.mktemp("bob")
        bob_container = containers.acapy_sqlite(
            "bob", "insecure", 3002, "indy", bob_volume_path
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
        tmp_path = tmp_path_factory.getbasetemp()
        await main(
            strategy="dbpw",
            uri=f"sqlite://{tmp_path}/alice/alice/sqlite.db",
            wallet_name="alice",
            wallet_key="insecure",
        )

        await main(
            strategy="dbpw",
            uri=f"sqlite://{tmp_path}/bob/bob/sqlite.db",
            wallet_name="bob",
            wallet_key="insecure",
        )

        # Post condition
        alice_container = containers.acapy_sqlite(
            "alice", "insecure", 3001, "askar", alice_volume_path
        )
        containers.wait_until_healthy(alice_container)

        bob_container = containers.acapy_sqlite(
            "bob", "insecure", 3002, "askar", bob_volume_path
        )
        containers.wait_until_healthy(bob_container)

        async with Controller("http://localhost:3001") as alice, Controller(
            "http://localhost:3002"
        ) as bob:
            await test_cases.post(alice, bob)
