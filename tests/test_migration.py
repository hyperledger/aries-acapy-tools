from pathlib import Path
import shutil
import time
from typing import Callable, cast

import docker
from docker.models.containers import Container
import pytest

from acapy_wallet_upgrade.__main__ import migration


async def migrate_pg_db(
    db_port: int,
    db_name: str,
    mode: str,
    profile_store_name: str = None,
    wallet_keys: dict = {},
    base_wallet_name: str = None,
):
    """Run migration script on postgresql database."""
    db_host = "localhost"
    user_name = "postgres"
    db_user_password = "mysecretpassword"
    # postgres[ql]://[username[:password]@][host[:port],]/database[?parameter_list]
    # \_____________/\____________________/\____________/\_______/\_______________/
    #     |                   |                  |          |            |
    #     |- schema           |- userspec        |          |            |- parameter list
    #                                            |          |
    #                                            |          |- database name
    #                                            |
    #                                            |- hostspec
    await migration(
        mode,
        f"postgres://{user_name}:{db_user_password}@{db_host}:{db_port}/{db_name}",
        profile_store_name,
        wallet_keys,
        base_wallet_name,
    )


@pytest.fixture
def sqlite_temp(tmp_path: Path):
    def _sqlite_temp(actor: str):
        src = Path(__file__).parent / "input" / f"{actor}.db"
        dst = tmp_path / f"{actor}.db"
        shutil.copyfile(src, dst)
        return dst

    yield _sqlite_temp


@pytest.fixture
def sqlite_alice(sqlite_temp):
    yield sqlite_temp("alice")


@pytest.fixture
def sqlite_bob(sqlite_temp):
    yield sqlite_temp("bob")


@pytest.mark.asyncio
async def test_migration_sqlite(sqlite_alice, sqlite_bob):
    """
    Run the migration script with SQLite db files.
    """
    # Alice
    await migration(
        mode="sqlite",
        db_path=str(sqlite_alice),
        wallet_keys={"alice": "insecure"},
        base_wallet_name="alice",
    )

    # Bob
    await migration(
        "sqlite",
        db_path=sqlite_bob,
        wallet_keys={"bob": "insecure"},
        base_wallet_name="bob",
    )


def poll_until_pg_is_ready(container: Container, attempts: int = 5):
    for _ in range(attempts):
        exit_code, _ = container.exec_run("pg_isready")
        if exit_code == 0:
            break
        else:
            time.sleep(1)


@pytest.fixture
def postgres_with_volume(tmp_path: Path, unused_tcp_port_factory: Callable[[], int]):
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
async def test_migration_dbpw(postgres_with_volume):
    """
    Run the migration script with the db in the docker container.
    """
    port = postgres_with_volume("dbpw")
    await migrate_pg_db(
        port, "alice", "dbpw", "", {"alice": "alice_insecure0"}, "alice"
    )
    await migrate_pg_db(port, "bob", "dbpw", "", {"bob": "bob_insecure0"}, "bob")


@pytest.mark.asyncio
async def test_migration_mwst_as_profiles(postgres_with_volume):
    """
    Run the migration script with the db in the docker container.
    """
    port = postgres_with_volume("mt-mwst")
    await migrate_pg_db(
        db_port=port,
        db_name="wallets",
        mode="mwst_as_profiles",
        profile_store_name="multitenant_sub_wallet",
        wallet_keys={
            "agency": "agency_insecure0",
            "alice": "alice_insecure1",
            "bob": "bob_insecure1",
        },
        base_wallet_name="agency",
    )


# @pytest.mark.asyncio
# async def test_migration_mwst_as_separate_stores(tmp_path):
#     """
#     Run the migration script with the db in the docker container.
#     """
#     postgres_start_with_volume(tmp_path, "mwst")  # TODO: update mwst
#     await migrate_pg_db(
#         db_name="wallets",
#         mode="mwst_as_separate_stores",
#         wallet_keys={
#             "alice": "alice_insecure1",
#             "bob": "bob_insecure1",
#         },
#     )
