import asyncio
import shutil
import socket
import time
from contextlib import asynccontextmanager, closing, contextmanager
from pathlib import Path
from typing import Callable, cast

import docker
import pytest
import pytest_asyncio
from asyncpg import Path
from controller import Controller
from controller.models import ConnRecord
from controller.protocols import (didexchange,
                                  indy_anoncred_credential_artifacts,
                                  indy_anoncred_onboard,
                                  indy_issue_credential_v1)
from docker import APIClient
from docker.models.containers import Container

from acapy_wallet_upgrade.__main__ import main

"""async def connections(alice, bob):
    alice_conn, bob_conn = await didexchange(alice, bob)

    async def _post():
        await alice.post(f"/connections/{alice_conn.connection_id}/trustping")

    yield _post"""

# https://stackoverflow.com/a/64971593
def get_health(container: Container):
    api_client = APIClient()
    inspect_results = api_client.inspect_container(container.name)
    return inspect_results['State']['Health']['Status']

class WalletTypeToBeTested:
    @pytest.fixture(scope="class")
    def event_loop(self):
        policy = asyncio.get_event_loop_policy()
        loop = policy.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture(scope="class")
    def tails(self):
        client = docker.from_env()
        container = client.containers.run(
            "ghcr.io/bcgov/tails-server:latest",
            name="tails",
            ports={"6543/tcp": 6543},
            environment=[
                "GENESIS_URL=https://raw.githubusercontent.com/Indicio-tech/indicio-network/main/genesis_files/pool_transactions_testnet_genesis"
            ],
            entrypoint="""tails-server
                --host 0.0.0.0
                --port 6543
                --storage-path /tmp/tails-files
                --log-level INFO""",
            auto_remove=True,
            detach=True,
        )
        yield "http://tails:6543"
        container.stop()

    @pytest.fixture(scope="class")
    def alice(self, tails):
        pass

    @pytest.fixture(scope="class")
    def bob(self, tails):
        pass

    def poll_acapy_until_healthy(
        self, container: Container, port: int, attempts: int = 5
    ):
        for _ in range(attempts):
            if get_health(container) == 'healthy':
                break
            else:
                time.sleep(1)

    def poll_until_pg_is_ready(self, container: Container, attempts: int = 5):
        for _ in range(attempts):
            exit_code, _ = container.exec_run("pg_isready")
            if exit_code == 0:
                break
            else:
                time.sleep(1)

    @pytest.fixture(scope="class")
    def postgres_with_volume(
        self,
        tmp_path: Path,
        unused_tcp_port_factory: Callable[[], int],
        poll_until_pg_is_ready,
    ):
        client = docker.from_env()
        containers = []

        def _postgres_with_volume():

            port = unused_tcp_port_factory()
            container = client.containers.run(
                "postgres:11",
                # volumes={dst: {"bind": "/var/lib/postgresql/data", "mode": "rw,z"}},
                ports={"5432/tcp": port},
                environment=["POSTGRES_PASSWORD=mysecretpassword"],
                auto_remove=True,
                detach=True,
            )
            containers.append(container)

            # Give the DB a moment to start
            poll_until_pg_is_ready(cast(Container, container))
            return port

        yield _postgres_with_volume

        for container in containers:
            container.stop()

    @pytest_asyncio.fixture(scope="class")
    async def pre_migration(self, alice: Callable[[], Controller], bob: Controller):
        print(alice, "\n", bob)
        alice_state = {}
        bob_state = {}
        async with alice() as alice_controller, bob:
            alice_state["conn"], bob_state["conn"] = await didexchange(
                alice_controller, bob
            )

            alice_state["public_did"] = await indy_anoncred_onboard(alice_controller)
            (
                alice_state["schema"],
                alice_state["cred_def"],
            ) = await indy_anoncred_credential_artifacts(
                alice_controller,
                ["firstname", "lastname"],
                support_revocation=True,
            )

            # Issue the thing
            (
                alice_state["cred_ex"],
                bob_state["cred_ex"],
            ) = await indy_issue_credential_v1(
                alice_controller,
                bob,
                alice_state["conn"].connection_id,
                bob_state["conn"].connection_id,
                alice_state["cred_def"].credential_definition_id,
                {"firstname": "Bob", "lastname": "Builder"},
            )

        yield alice_state, bob_state

    @pytest_asyncio.fixture(scope="class", autouse=True)
    async def migrate(self, pre_migration):
        pass

    @pytest.mark.asyncio
    async def test_connections(self, alice: Controller, bob: Controller, pre_migration):
        async with alice(), bob:
            # TODO: trust ping over connection
            alice_state, bob_state = pre_migration
            print(alice_state, bob_state)
            assert False

    # TODO: test present credential
    # TODO: test public key
    # TODO: test issue credential
    # TODO: test


class TestSqliteDBPW(WalletTypeToBeTested):
    @pytest.mark.asyncio
    @pytest.fixture(scope="class")
    def alice(self, tails, tmp_path_factory):
        @asynccontextmanager
        async def _alice():
            client = docker.from_env()
            _dir = tmp_path_factory.mktemp("alice")
            container = client.containers.run(
                "docker.io/bcgovimages/aries-cloudagent:py36-1.16-1_0.7.5",
                volumes={
                    _dir: {
                        "bind": "/home/indy/.indy_client/wallet/alice",
                        "mode": "rw,z",
                    }
                },
                domainname="alice-sqlite",
                name="alice-sqlite",
                ports={"3001/tcp": 3001},
                environment=["RUST_LOG=TRACE"],
                command="""start -it http 0.0.0.0 3000
                    --label Alice
                    -ot http
                    -e http://alice-sqlite:3000
                    --admin 0.0.0.0 3001 --admin-insecure-mode
                    --log-level debug
                    --genesis-url https://raw.githubusercontent.com/Indicio-tech/indicio-network/main/genesis_files/pool_transactions_testnet_genesis
                    --tails-server-base-url http://tails:6543
                    --wallet-type indy
                    --wallet-name alice
                    --wallet-key insecure
                    --preserve-exchange-records
                    --auto-provision""",
                auto_remove=True,
                detach=True,
                healthcheck={
                    "test": "curl -s -o /dev/null -w '%{http_code}' 'http://localhost:3001/status/live' | grep '200' > /dev/null",
                    "interval": int(7e9),
                    "timeout": int(5e9),
                    "retries": 5,
                },
            )
            self.poll_acapy_until_healthy(container, 3001)
            async with Controller("http://alice-sqlite:3001") as controller:
                yield controller
            container.stop()

        yield _alice

    @pytest.fixture(scope="class")
    def bob(self, tails, tmp_path_factory):
        client = docker.from_env()
        _dir = tmp_path_factory.mktemp("bob")
        container = client.containers.run(
            "docker.io/bcgovimages/aries-cloudagent:py36-1.16-1_0.7.5",
            volumes={
                _dir: {"bind": "/home/indy/.indy_client/wallet/bob", "mode": "rw,z"}
            },
            name="bob-sqlite",
            ports={"3001/tcp": 3002},
            environment=["RUST_LOG=TRACE"],
            command="""start -it http 0.0.0.0 3000
                --label Bob
                -ot http
                -e http://bob-sqlite:3000
                --admin 0.0.0.0 3001 --admin-insecure-mode
                --log-level debug
                --genesis-url https://raw.githubusercontent.com/Indicio-tech/indicio-network/main/genesis_files/pool_transactions_testnet_genesis
                --tails-server-base-url http://tails:6543
                --wallet-type indy
                --wallet-name bob
                --wallet-key insecure
                --preserve-exchange-records
                --auto-provision
                --monitor-revocation-notification""",
            auto_remove=True,
            detach=True,
            healthcheck={
                "test": "curl -s -o /dev/null -w '%{http_code}' 'http://localhost:3001/status/live' | grep '200' > /dev/null",
                "interval": int(7e9),
                "timeout": int(5e9),
                "retries": 5,
            },
        )
        yield Controller("http://bob-sqlite:3001")
        container.stop()

    @pytest_asyncio.fixture(scope="class", autouse=True)
    async def migrate(self, pre_migration, tmp_path_factory):
        # bind db volume in agent at start
        # stop agent container
        # migrate db
        # start agent container
        # Alice
        tmp_path = tmp_path_factory.getbasetemp()
        await main(
            strategy="dbpw",
            uri=f"sqlite://{tmp_path}/alice/sqlite.db",
            wallet_name="alice",
            wallet_key="insecure",
        )

        # Bob
        await main(
            strategy="dbpw",
            uri=f"sqlite://{tmp_path}/bob/sqlite.db",
            wallet_name="bob",
            wallet_key="insecure",
        )
