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
    shutil.copyfile(src, dst)

    client = docker.from_env()

    container_id = client.create_container(
        'postgres:11', "localhost", volumes=[f'{dst}:/var/lib/postgresql/data'],
        host_config=docker.utils.create_host_config(binds={
            '/home/user1/': {
                'bind': f'{dst}:/var/lib/postgresql/data',
                'ro': True
            }
        })
    )
