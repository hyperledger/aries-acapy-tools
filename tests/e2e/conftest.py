from pathlib import Path
from typing import Callable, Tuple
from asyncpg import Path
from controller import Controller
from controller.models import ConnRecord
from controller.protocols import didexchange
import docker
import pytest
import pytest_asyncio


async def connections(alice, bob):
    alice_conn, bob_conn = await didexchange(alice, bob)

    async def _post():
        await alice.post(f"/connections/{alice_conn.connection_id}/trustping")

    yield _post


@pytest.fixture(scope="module", autouse=True)
async def migration(connections):
    pass


async def test_connections(connections):
    await connections()


class WalletTypeToBeTested:
    @pytest.fixture(scope="class")
    def alice(self):
        pass

    @pytest.fixture(scope="class")
    def bob(self):
        pass

    @pytest.fixture(scope="class")
    def postgres_with_volume(
        self, tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
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

    @pytest.fixture(scope="class")
    async def connections(self, alice: Controller, bob: Controller):
        async with alice, bob:
            alice_conn, bob_conn = await didexchange(alice, bob)

        yield alice_conn, bob_conn

    @pytest.fixture(scope="class", autouse=True)
    async def migrate(self, connections):
        # TODO do migration step
        pass

    @pytest.mark.asyncio
    async def test_connections(
        self,
        alice: Controller,
        bob: Controller,
        connections: Tuple[ConnRecord, ConnRecord],
    ):
        async with alice, bob:
            pass


class TestSqliteDBPW(WalletTypeToBeTested):
    @pytest.fixture(scope="class")
    def alice(self):
        pass

    @pytest.fixture(scope="class")
    def bob(self):
        pass

    @pytest.fixture(scope="class", autouse=True)
    async def migrate(self, connections):
        # TODO do migration step
        pass
