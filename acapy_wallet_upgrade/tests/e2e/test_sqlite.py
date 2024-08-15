import pytest
from acapy_controller import Controller
from acapy_wallet_upgrade.__main__ import main

from . import WalletTypeToBeTested
from .cases import MigrationTestCases
from .containers import Containers


class TestSqliteDBPW(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.mark.e2e
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
