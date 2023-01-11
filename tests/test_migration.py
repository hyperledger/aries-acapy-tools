import shutil
from pathlib import Path

import pytest

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
