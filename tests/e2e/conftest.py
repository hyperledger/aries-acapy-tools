import asyncio
import shutil
import time
from pathlib import Path
from typing import Callable, Tuple, cast

import docker
import pytest
import pytest_asyncio
from asyncpg import Path
from controller import Controller
from controller.models import ConnRecord
from controller.protocols import didexchange
from docker.models.containers import Container

"""async def connections(alice, bob):
    alice_conn, bob_conn = await didexchange(alice, bob)

    async def _post():
        await alice.post(f"/connections/{alice_conn.connection_id}/trustping")

    yield _post"""


class WalletTypeToBeTested:
    @pytest.fixture(scope="class")
    def tails(self):
        client = docker.from_env()
        client.containers.run(
            "ghcr.io/bcgov/tails-server:latest",
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

    @pytest.fixture(scope="class")
    def alice(self, tails):
        pass

    @pytest.fixture(scope="class")
    def bob(self, tails):
        pass

    @pytest.fixture
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

        def _postgres_with_volume(volume_name: str):
            src = Path(__file__).parent / "input" / volume_name
            d = tmp_path / "sub"
            d.mkdir()
            dst = d / volume_name
            shutil.copytree(src, dst)

            port = unused_tcp_port_factory()
            container = client.containers.run(
                "postgres:11",
                volumes={dst: {"bind": "/var/lib/postgresql/data", "mode": "rw,z"}},
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

    @pytest.mark.asyncio
    @pytest.fixture(scope="class")
    async def connections(self, alice: Controller, bob: Controller):
        print(alice,"\n",bob)
        async with alice, bob:
            alice_conn, bob_conn = await didexchange(alice, bob)

        yield alice_conn, bob_conn

    @pytest.mark.asyncio
    @pytest.fixture(scope="class", autouse=True)
    async def migrate(self, connections):
        # TODO do migration step
        assert connections

    @pytest.mark.asyncio
    async def test_connections(
        self,
        alice: Controller,
        bob: Controller,
        connections: Tuple[ConnRecord, ConnRecord],
    ):
        async with alice, bob:
            print(connections)
            assert True


class TestSqliteDBPW(WalletTypeToBeTested):
    @pytest.fixture(scope="class")
    def alice(self):
        client = docker.from_env()
        client.containers.run(
            "docker.io/bcgovimages/aries-cloudagent:py36-1.16-1_0.7.5",
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
                "test": "curl -s -o /dev/null -w 'http://localhost:3001/status/live' | grep '200' > /dev/null",
                "interval": 7000000000,
                "timeout": 5000000000,
                "retries": 5,
            },
        )
        return Controller("http://alice-sqlite:3001")

    @pytest.fixture(scope="class")
    def bob(self):
        client = docker.from_env()
        client.containers.run(
            "docker.io/bcgovimages/aries-cloudagent:py36-1.16-1_0.7.5",
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
                "test": "curl -s -o /dev/null -w 'http://localhost:3001/status/live' | grep '200' > /dev/null",
                "interval": 7000000000,
                "timeout": 5000000000,
                "retries": 5,
            },
        )
        return Controller("http://bob-sqlite:3001")
        

    @pytest.fixture(scope="class", autouse=True)
    @pytest.mark.asyncio
    async def migrate(self, connections):
        # TODO do migration step
        assert connections
