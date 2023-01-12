import shutil
from pathlib import Path
import time

import pytest
import docker

from acapy_wallet_upgrade.__main__ import upgrade
from acapy_wallet_upgrade.pg_connection import PgConnection
from acapy_wallet_upgrade.sqlite_connection import SqliteConnection


def docker_stop(client):
    try:
        container = client.containers.get("indy-demo-postgres")
    except docker.errors.NotFound:
        pass
    else:
        container.stop()


def postgres_start_with_volume(tmp_path, bd_src):
    src = Path(f"input/{bd_src}")
    d = tmp_path / "sub"
    d.mkdir()
    dst = d / bd_src
    shutil.copytree(src, dst)

    client = docker.from_env()
    docker_stop(client)
    try:
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
    except:
        pass  # TODO: handle error
    return


async def migrate_pg_db(db_name, key):
    db_host = "localhost"

    conn = PgConnection(
        db_host=db_host,
        db_name=db_name,
        db_user="postgres",
        db_pass="mysecretpassword",
        path=f"postgres://postgres:mysecretpassword@{db_host}:5432/{db_name}",
    )
    await upgrade(conn, key)


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


@pytest.mark.asyncio
async def test_migration_dbpw(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    postgres_start_with_volume(tmp_path, "dbpw")
    await migrate_pg_db("alice", "insecure")
    await migrate_pg_db("bob", "insecure")


@pytest.mark.asyncio
async def test_migration_mwst(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    postgres_start_with_volume(tmp_path, "mwst")
    await migrate_pg_db("wallets", "insecure")
