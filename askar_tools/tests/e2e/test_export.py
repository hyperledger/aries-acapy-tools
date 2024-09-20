import os
from argparse import Namespace

import pytest
from acapy_controller import Controller
from askar_tools.__main__ import main

from . import WalletTypeToBeTested
from .cases import ExportTestCases
from .containers import Containers


class TestPgExport(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_export_pg(self, containers: Containers):
        # Prepare
        postgres = containers.postgres(5432)
        alice_container = containers.acapy_postgres(
            "alice",
            "3cAZj1hPvUhKeBkzCKPTHhTxRRmYv5abDbjmaYwtk6Nf",
            "RAW",
            "askar",
            3001,
            postgres,
        )
        bob_container = containers.acapy_postgres(
            "bob", "insecure", "kdf:argon2i:mod", "askar", 3002, postgres
        )
        containers.wait_until_healthy(alice_container)
        containers.wait_until_healthy(bob_container)

        test_cases = ExportTestCases()
        async with Controller("http://localhost:3001") as alice, Controller(
            "http://localhost:3002"
        ) as bob:
            await test_cases.pre(alice, bob)

        # Action
        namespace = Namespace()
        namespace.__dict__.update(
            {
                "strategy": "export",
                "uri": "postgres://postgres:mysecretpassword@localhost:5432/alice",
                "wallet_name": "alice",
                "wallet_key": "3cAZj1hPvUhKeBkzCKPTHhTxRRmYv5abDbjmaYwtk6Nf",
                "wallet_key_derivation_method": "RAW",
                "export_filename": "wallet_export_alice.json",
            }
        )
        await main(namespace)

        namespace = Namespace()
        namespace.__dict__.update(
            {
                "strategy": "export",
                "uri": "postgres://postgres:mysecretpassword@localhost:5432/bob",
                "wallet_name": "bob",
                "wallet_key": "insecure",
                "wallet_key_derivation_method": "ARGON2I_MOD",
                "export_filename": "wallet_export_bob.json",
            }
        )
        await main(namespace)

        found_alice_export_file = False
        found_bob_export_file = False
        for root, dirs, files in os.walk("../"):
            if "wallet_export_alice.json" in files:
                found_alice_export_file = True
            if "wallet_export_bob.json" in files:
                found_bob_export_file = True

        containers.stop(alice_container)
        containers.stop(bob_container)
        containers.stop(postgres)

        # Assert: TODO: check file contents
        assert found_alice_export_file
        assert found_bob_export_file

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_export_sqlite(self, containers: Containers, tmp_path_factory):
        alice_volume_path = tmp_path_factory.mktemp("alice")
        containers.fix_permissions(alice_volume_path, user=1001, group=1001)
        alice_container = containers.acapy_sqlite(
            "alice",
            "3cAZj1hPvUhKeBkzCKPTHhTxRRmYv5abDbjmaYwtk6Nf",
            "RAW",
            "askar",
            3001,
            alice_volume_path,
            "/home/aries/.aries_cloudagent/wallet/alice",
        )
        bob_volume_path = tmp_path_factory.mktemp("bob")
        containers.fix_permissions(bob_volume_path, user=1001, group=1001)
        bob_container = containers.acapy_sqlite(
            "bob",
            "insecure",
            "kdf:argon2i:mod",
            "askar",
            3002,
            bob_volume_path,
            "/home/aries/.aries_cloudagent/wallet/bob",
        )
        containers.wait_until_healthy(alice_container)
        containers.wait_until_healthy(bob_container)

        test_cases = ExportTestCases()
        async with Controller("http://localhost:3001") as alice, Controller(
            "http://localhost:3002"
        ) as bob:
            await test_cases.pre(alice, bob)

        # Set ownership of wallet directory to host user
        containers.fix_permissions(alice_volume_path)
        containers.fix_permissions(bob_volume_path)

        namespace = Namespace()
        namespace.__dict__.update(
            {
                "strategy": "export",
                "uri": f"sqlite://{alice_volume_path}/sqlite.db",
                "wallet_name": "alice",
                "wallet_key": "3cAZj1hPvUhKeBkzCKPTHhTxRRmYv5abDbjmaYwtk6Nf",
                "wallet_key_derivation_method": "RAW",
                "export_filename": "wallet_export_alice.json",
            }
        )
        # Action
        await main(namespace)

        namespace = Namespace()
        namespace.__dict__.update(
            {
                "strategy": "export",
                "uri": f"sqlite://{bob_volume_path}/sqlite.db",
                "wallet_name": "bob",
                "wallet_key": "insecure",
                "wallet_key_derivation_method": "ARGON2I_MOD",
                "export_filename": "wallet_export_bob.json",
            }
        )

        await main(namespace)

        found_alice_export_file = False
        found_bob_export_file = False
        for root, dirs, files in os.walk("../"):
            if "wallet_export_alice.json" in files:
                found_alice_export_file = True
            if "wallet_export_bob.json" in files:
                found_bob_export_file = True

        containers.stop(alice_container)
        containers.stop(bob_container)

        # Assert: TODO: check file contents
        assert found_alice_export_file
        assert found_bob_export_file
