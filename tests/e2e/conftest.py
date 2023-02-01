import asyncio

from controller import Controller
from controller.models import CreateWalletResponse
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
        containers.fix_permissions(alice_volume_path, user=1001, group=1001)
        alice_container = containers.acapy_sqlite(
            "alice",
            "insecure",
            3001,
            "indy",
            alice_volume_path,
            "/home/indy/.indy_client/wallet/alice",
        )
        bob_volume_path = tmp_path_factory.mktemp("bob")
        containers.fix_permissions(bob_volume_path, user=1001, group=1001)
        bob_container = containers.acapy_sqlite(
            "bob",
            "insecure",
            3002,
            "indy",
            bob_volume_path,
            "/home/indy/.indy_client/wallet/bob",
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

        # Set ownership of wallet directory to host user
        containers.fix_permissions(alice_volume_path)
        containers.fix_permissions(bob_volume_path)

        # (alice_volume_path / "sqlite.db").chmod(0o777)
        # (bob_volume_path / "sqlite.db").chmod(0o777)
        # Migrate
        await main(
            strategy="dbpw",
            uri=f"sqlite://{alice_volume_path}/sqlite.db",
            wallet_name="alice",
            wallet_key="insecure",
        )

        await main(
            strategy="dbpw",
            uri=f"sqlite://{bob_volume_path}/sqlite.db",
            wallet_name="bob",
            wallet_key="insecure",
        )

        # Set ownership of wallet directory back to indy
        containers.fix_permissions(alice_volume_path, user=1001, group=1001)
        containers.fix_permissions(bob_volume_path, user=1001, group=1001)

        # Post condition
        alice_container = containers.acapy_sqlite(
            "alice",
            "insecure",
            3001,
            "askar",
            alice_volume_path,
            "/home/indy/.aries_cloudagent/wallet/alice",
        )
        bob_container = containers.acapy_sqlite(
            "bob",
            "insecure",
            3002,
            "askar",
            bob_volume_path,
            "/home/indy/.aries_cloudagent/wallet/bob",
        )
        containers.wait_until_healthy(alice_container)
        containers.wait_until_healthy(bob_container)

        async with Controller("http://localhost:3001") as alice, Controller(
            "http://localhost:3002"
        ) as bob:
            await test_cases.post(alice, bob)


class TestPgDBPW(WalletTypeToBeTested):
    @pytest.mark.asyncio
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


class TestPgMWSTProfiles(WalletTypeToBeTested):
    @pytest.mark.asyncio
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
            uri=f"postgres://postgres:mysecretpassword@localhost:5432/wallets",
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


class TestPgMWSTStores(WalletTypeToBeTested):
    @pytest.mark.asyncio
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
            uri=f"postgres://postgres:mysecretpassword@localhost:5432/wallets",
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
