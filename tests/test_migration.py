import contextlib
import shutil
from pathlib import Path
import time

import pytest
import docker

from acapy_wallet_upgrade.__main__ import migration


def docker_stop(client):
    """Stop indy-demo-postgres container."""
    try:
        container = client.containers.get("indy-demo-postgres")
    except docker.errors.NotFound:
        pass
    else:
        container.stop()


def copy_db_into_temp(tmp_path, bd_src):
    """Copy database into temp directory."""
    src = Path(f"input/{bd_src}")
    d = tmp_path / "sub"
    d.mkdir()
    dst = d / bd_src
    shutil.copytree(src, dst)
    return dst


def postgres_start_with_volume(tmp_path, bd_src):
    """Run indy-demo-postgres container with a stored volume using a temp directory."""
    dst = copy_db_into_temp(tmp_path, bd_src)
    client = docker.from_env()
    docker_stop(client)
    with contextlib.suppress(Exception):
        client.containers.run(
            "postgres:11",
            name="indy-demo-postgres",
            volumes={dst: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
            ports={"5432/tcp": 5432},
            environment=["POSTGRES_PASSWORD=mysecretpassword"],
            auto_remove=True,
            detach=True,
        )
        time.sleep(4)
    return


async def migrate_pg_db(
    db_name: str,
    mode: str,
    profile_store_name: str = None,
    wallet_keys: dict = {},
    base_wallet_name: str = None,
):
    """Run migration script on postgresql database."""
    db_host = "localhost"
    db_port = 5432
    user_name = "postgres"
    db_user_password = "mysecretpassword"
    """
    postgres[ql]://[username[:password]@][host[:port],]/database[?parameter_list]
    \_____________/\____________________/\____________/\_______/\_______________/
        |                   |                  |          |            |
        |- schema           |- userspec        |          |            |- parameter list
                                               |          |
                                               |          |- database name
                                               |
                                               |- hostspec
    """
    await migration(
        mode,
        f"postgres://{user_name}:{db_user_password}@{db_host}:{db_port}/{db_name}",
        profile_store_name,
        wallet_keys,
        base_wallet_name,
    )


@pytest.mark.asyncio
async def test_migration_sqlite(tmp_path):
    """
    Run the migration script with SQLite db files.
    """
    d = tmp_path / "sub"
    d.mkdir()

    # Alice
    src_alice = Path("input/alice.db")
    dst_alice = d / "alice.db"
    shutil.copyfile(src_alice, dst_alice)
    await migration(
        mode="sqlite",
        db_path=dst_alice,
        wallet_keys={"alice": "insecure"},
        base_wallet_name="alice",
    )

    # Bob
    src_bob = Path("input/bob.db")
    dst_bob = d / "bob.db"
    shutil.copyfile(src_bob, dst_bob)
    await migration(
        "sqlite",
        db_path=dst_bob,
        wallet_keys={"bob": "insecure"},
        base_wallet_name="bob",
    )


@pytest.mark.asyncio
async def test_migration_dbpw(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    postgres_start_with_volume(tmp_path, "dbpw")
    await migrate_pg_db("alice", "dbpw", "", {"alice": "alice_insecure0"}, "alice")
    await migrate_pg_db("bob", "dbpw", "", {"bob": "bob_insecure0"}, "bob")


@pytest.mark.asyncio
async def test_migration_mwst_as_profiles(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    postgres_start_with_volume(tmp_path, "mt-mwst")
    await migrate_pg_db(
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


@pytest.mark.asyncio
async def test_migration_mwst_as_separate_stores(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    postgres_start_with_volume(tmp_path, "mwst")  # TODO: update mwst
    await migrate_pg_db(
        db_name="wallets",
        mode="mwst_as_separate_stores",
        wallet_keys={
            "alice": "alice_insecure1",
            "bob": "bob_insecure1",
        },
    )
