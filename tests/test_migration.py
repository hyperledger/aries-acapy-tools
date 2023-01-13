import contextlib
import shutil
from pathlib import Path
import time

import pytest
import docker

from acapy_wallet_upgrade.__main__ import upgrade
from acapy_wallet_upgrade.pg_connection import PgConnection
from acapy_wallet_upgrade.pg_connection_mwst import PgConnectionMWST
from acapy_wallet_upgrade.sqlite_connection import SqliteConnection


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


async def migrate_pg_db(db_name, key, mode = None):
    """Run migration script on postgresql database."""
    db_host = "localhost"
    db_port = 5432
    user_name = "postgres"
    db_user_password = "mysecretpassword"
    if mode == "pgsql_mwst":
        conn = PgConnectionMWST(
            db_host=db_host,
            db_name=db_name,
            db_user=user_name,
            db_pass=db_user_password,
            path=f"postgres://{user_name}:{db_user_password}@{db_host}:{db_port}/{db_name}",
        )
    else:
        conn = PgConnection(
            db_host=db_host,
            db_name=db_name,
            db_user=user_name,
            db_pass=db_user_password,
            path=f"postgres://{user_name}:{db_user_password}@{db_host}:{db_port}/{db_name}",
        )
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
    await migrate_pg_db("wallets", "insecure", "pgsql_mwst")
