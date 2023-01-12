import shutil
from pathlib import Path
import time

import pytest
import docker

from acapy_wallet_upgrade.__main__ import upgrade
from acapy_wallet_upgrade.pg_connection import PgConnection
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


@pytest.mark.asyncio
async def test_migration_dbpw(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    src = Path("input/dbpw")
    d = tmp_path / "sub"
    d.mkdir()
    dst = d / "dbpw"
    shutil.copytree(src, dst)

    client = docker.from_env()

    try:
        container = client.containers.get("indy-demo-postgres")
    except docker.errors.NotFound:
        pass
    else:
        container.stop()
    try:
        container = client.containers.run(
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
        pass  # shh, Conceal it. Don't feel it. Don't let it show.
    # else:
    #     container.stop()

    conn = PgConnection(
        db_host = "localhost",
        db_name = "alice",
        db_user = "postgres",
        db_pass = "mysecretpassword",
        path = "postgres://postgres:mysecretpassword@localhost:5432/alice"
    )
    key = "insecure"
    await upgrade(conn, key)


@pytest.mark.asyncio
async def test_migration_mwst(tmp_path):
    """
    Run the migration script with the db in the docker container.
    """
    src = Path("input/mwst")
    d = tmp_path / "sub"
    d.mkdir()
    dst = d / "mwst"
    shutil.copytree(src, dst)

    client = docker.from_env()

    try:
        container = client.containers.get("indy-demo-postgres")
    except docker.errors.NotFound:
        pass
    else:
        container.stop()
    try:
        container = client.containers.run(
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
        pass  # TODO: handle errors
    # else:
    #     container.stop()

    conn = PgConnection(
        db_host = "localhost",
        db_name = "wallets",
        db_user = "postgres",
        db_pass= "mysecretpassword",
        path = "postgres://postgres:mysecretpassword@localhosts:5432/wallets"
    )
    key = "insecure"
    await upgrade(conn, key)
