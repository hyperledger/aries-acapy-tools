"""Tests for the multi wallet converter resume/verify state machine."""

from types import SimpleNamespace
from unittest import mock

import pytest

from askar_tools.error import ConversionError
from askar_tools.multi_wallet_converter import MultiWalletConverter


def wallet_entry(name):
    """Build a fake admin-store wallet_record entry for a tenant."""
    return SimpleNamespace(
        category="wallet_record",
        value_json={
            "settings": {
                "wallet.id": f"{name}-id",
                "wallet.name": name,
                "wallet.key": f"{name}-key",
            }
        },
    )


def make_converter(entries):
    """Build a converter with a mocked connection and admin/sub wallet stores."""
    conn = mock.MagicMock()
    conn.uri = "postgres://user:pass@host:5432/admin"
    conn.database_exists = mock.AsyncMock(return_value=False)
    conn.create_database = mock.AsyncMock()
    conn.remove_database = mock.AsyncMock()
    conn.close = mock.AsyncMock()

    converter = MultiWalletConverter(
        conn=conn,
        wallet_name="admin",
        wallet_key="insecure",
        wallet_key_derivation_method="ARGON2I_MOD",
        sub_wallet_name="multitenant_sub_wallet",
    )

    admin_store = mock.MagicMock()
    admin_store.scan.return_value = mock.MagicMock(
        fetch_all=mock.AsyncMock(return_value=entries)
    )
    admin_store.close = mock.AsyncMock()

    sub_wallet_store = mock.MagicMock()
    sub_wallet_store.close = mock.AsyncMock()

    return converter, conn, admin_store, sub_wallet_store


def patch_store_open(admin_store, sub_wallet_store):
    """Patch Store.open to return the admin store then the sub wallet store."""
    return mock.patch(
        "askar_tools.multi_wallet_converter.Store.open",
        mock.AsyncMock(side_effect=[admin_store, sub_wallet_store]),
    )


@pytest.mark.asyncio
async def test_new_tenant_is_converted_verified_and_sub_wallet_dropped():
    converter, conn, admin_store, sub_wallet_store = make_converter(
        [wallet_entry("alice")]
    )
    converter.convert_tenant_wallet = mock.AsyncMock()
    converter.verify_tenant_wallet = mock.AsyncMock(return_value=(True, ""))

    with patch_store_open(admin_store, sub_wallet_store):
        await converter.convert_single_wallet_to_multi_wallet()

    converter.convert_tenant_wallet.assert_awaited_once()
    converter.verify_tenant_wallet.assert_awaited_once()
    conn.remove_database.assert_awaited_once_with("admin", "multitenant_sub_wallet")


@pytest.mark.asyncio
async def test_existing_verified_tenant_is_skipped():
    converter, conn, admin_store, sub_wallet_store = make_converter(
        [wallet_entry("alice")]
    )
    conn.database_exists = mock.AsyncMock(return_value=True)
    converter.convert_tenant_wallet = mock.AsyncMock()
    converter.verify_tenant_wallet = mock.AsyncMock(return_value=(True, ""))

    with patch_store_open(admin_store, sub_wallet_store):
        await converter.convert_single_wallet_to_multi_wallet()

    converter.convert_tenant_wallet.assert_not_awaited()
    conn.create_database.assert_not_awaited()
    # Only the final sub wallet drop, never the tenant database
    conn.remove_database.assert_awaited_once_with("admin", "multitenant_sub_wallet")


@pytest.mark.asyncio
async def test_existing_unverified_tenant_is_dropped_and_redone():
    converter, conn, admin_store, sub_wallet_store = make_converter(
        [wallet_entry("alice")]
    )
    conn.database_exists = mock.AsyncMock(return_value=True)
    converter.convert_tenant_wallet = mock.AsyncMock()
    converter.verify_tenant_wallet = mock.AsyncMock(
        side_effect=[(False, "record counts differ"), (True, "")]
    )

    with patch_store_open(admin_store, sub_wallet_store):
        await converter.convert_single_wallet_to_multi_wallet()

    converter.convert_tenant_wallet.assert_awaited_once()
    assert conn.remove_database.await_args_list == [
        mock.call("admin", "alice"),
        mock.call("admin", "multitenant_sub_wallet"),
    ]


@pytest.mark.asyncio
async def test_final_sub_wallet_drop_failure_exits_nonzero():
    converter, conn, admin_store, sub_wallet_store = make_converter(
        [wallet_entry("alice")]
    )
    conn.remove_database = mock.AsyncMock(side_effect=RuntimeError("still connected"))
    converter.convert_tenant_wallet = mock.AsyncMock()
    converter.verify_tenant_wallet = mock.AsyncMock(return_value=(True, ""))

    with patch_store_open(admin_store, sub_wallet_store):
        with pytest.raises(ConversionError, match="could not be deleted"):
            await converter.convert_single_wallet_to_multi_wallet()


@pytest.mark.asyncio
async def test_copy_failure_cleans_partial_target_and_keeps_sub_wallet():
    converter, conn, admin_store, sub_wallet_store = make_converter(
        [wallet_entry("alice")]
    )
    converter.convert_tenant_wallet = mock.AsyncMock(side_effect=RuntimeError("boom"))
    converter.verify_tenant_wallet = mock.AsyncMock(return_value=(True, ""))

    with patch_store_open(admin_store, sub_wallet_store):
        with pytest.raises(ConversionError):
            await converter.convert_single_wallet_to_multi_wallet()

    # The partially copied tenant database is removed; the sub wallet is not
    conn.remove_database.assert_awaited_once_with("admin", "alice")


@pytest.mark.asyncio
async def test_error_before_copy_never_drops_preexisting_target():
    converter, conn, admin_store, sub_wallet_store = make_converter(
        [wallet_entry("alice")]
    )
    conn.database_exists = mock.AsyncMock(return_value=True)
    conn.remove_database = mock.AsyncMock(side_effect=RuntimeError("drop refused"))
    converter.convert_tenant_wallet = mock.AsyncMock()
    converter.verify_tenant_wallet = mock.AsyncMock(
        return_value=(False, "cannot open target store")
    )

    with patch_store_open(admin_store, sub_wallet_store):
        with pytest.raises(ConversionError):
            await converter.convert_single_wallet_to_multi_wallet()

    # Only the failed redo drop was attempted; no cleanup drop afterwards and
    # no sub wallet drop
    conn.remove_database.assert_awaited_once_with("admin", "alice")
    converter.convert_tenant_wallet.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_on_one_tenant_continues_with_the_rest():
    converter, conn, admin_store, sub_wallet_store = make_converter(
        [wallet_entry("alice"), wallet_entry("bob")]
    )
    converter.convert_tenant_wallet = mock.AsyncMock(
        side_effect=[RuntimeError("boom"), None]
    )
    converter.verify_tenant_wallet = mock.AsyncMock(return_value=(True, ""))

    with patch_store_open(admin_store, sub_wallet_store):
        with pytest.raises(ConversionError):
            await converter.convert_single_wallet_to_multi_wallet()

    assert converter.convert_tenant_wallet.await_count == 2
    # Cleanup of alice's partial target only; the sub wallet survives
    conn.remove_database.assert_awaited_once_with("admin", "alice")


@pytest.mark.asyncio
async def test_no_wallet_records_raises_and_keeps_sub_wallet():
    converter, conn, admin_store, sub_wallet_store = make_converter([])

    with patch_store_open(admin_store, sub_wallet_store):
        with pytest.raises(ConversionError):
            await converter.convert_single_wallet_to_multi_wallet()

    conn.remove_database.assert_not_awaited()
