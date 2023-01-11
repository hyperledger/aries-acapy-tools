import shutil
from pathlib import Path

import pytest
import docker

from acapy_wallet_upgrade.__main__ import upgrade
from acapy_wallet_upgrade.sqlite_connection import SqliteConnection


@pytest.mark.asyncio
async def test_migration_sqlite(tmp_path):
    """
    Run the migration script with SQLite db files.
    """
    d = tmp_path / "sub"
    d.mkdir()
    key = "insecure"

    # Alice
    src_alice = Path("input/alice.db")
    dst_alice = d / "alice.db"
    shutil.copyfile(src_alice, dst_alice)
    conn_alice = SqliteConnection(dst_alice)
    await upgrade(conn_alice, key)

    # Bob
    src_bob = Path("input/bob.db")
    dst_bob = d / "bob.db"
    shutil.copyfile(src_bob, dst_bob)
    conn_bob = SqliteConnection(dst_bob)
    await upgrade(conn_bob, key)


def test_migration_dbpw(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    d = tmp_path / "sub"
    d.mkdir()
    key = "insecure"

    src = Path("input/dbpw")
    dst = d / "dbpw"
    shutil.copytree(src, dst)

    # docker stuff
    client = docker.from_env()
    container = client.containers.prune("indy-demo-postgres")
    if container:
        container.stop()
        container.kill()
    container = client.containers.run(
        "postgres:11",
        name="indy-demo-postgres",
        volumes={dst: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        ports={"5432/tcp": 5432},
        environment=["POSTGRES_PASSWORD=mysecretpassword"],
        detach=True,
    )
    container.kill()
    print(container.id)
