"""Indy wallet upgrade."""


import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
from typing import Dict
import uuid

import base58
import cbor2
import msgpack
import nacl.pwhash

from acapy_wallet_upgrade.pg_connection_mwst_profiles import PgConnectionMWSTProfiles
from acapy_wallet_upgrade.pg_connection_mwst_separate_stores import (
    PgConnectionMWSTSeparateStores,
)

from .db_connection import DbConnection, Wallet
from .error import UpgradeError
from .pg_connection import PgConnection
from .sqlite_connection import SqliteConnection


CHACHAPOLY_KEY_LEN = 32
CHACHAPOLY_NONCE_LEN = 12
CHACHAPOLY_TAG_LEN = 16
ENCRYPTED_KEY_LEN = CHACHAPOLY_NONCE_LEN + CHACHAPOLY_KEY_LEN + CHACHAPOLY_TAG_LEN


async def fetch_pgsql_mwst_keys(conn, wallet_id, key_pass):
    metadata_row: list = await conn.fetch_multiple(
        "SELECT value FROM metadata WHERE wallet_id = $1", (wallet_id)
    )
    results_dict = {}
    key_pass = key_pass.encode("ascii")
    for metadata_json in metadata_row:
        wallet_id = metadata_json[0]
        metadata = json.loads(metadata_json[1])
        keys_enc = bytes(metadata["keys"])
        salt = bytes(metadata["master_key_salt"])

        print("Deriving wallet key...")
        salt = salt[:16]
        master_key = nacl.pwhash.argon2i.kdf(
            CHACHAPOLY_KEY_LEN,
            key_pass,
            salt,
            nacl.pwhash.argon2i.OPSLIMIT_MODERATE,
            nacl.pwhash.argon2i.MEMLIMIT_MODERATE,
        )

        print("Opening wallet...")
        keys_mpk = decrypt_merged(keys_enc, master_key)
        keys_lst = msgpack.unpackb(keys_mpk)
        keys = dict(
            zip(
                (
                    "type",
                    "name",
                    "value",
                    "item_hmac",
                    "tag_name",
                    "tag_value",
                    "tag_hmac",
                ),
                keys_lst,
            )
        )
        keys["master"] = master_key
        keys["salt"] = salt
        results_dict[wallet_id] = keys

    return results_dict


async def fetch_indy_key(wallet: Wallet, key_pass: str) -> dict:
    metadata_json = await wallet.get_metadata()
    metadata = json.loads(metadata_json)
    keys_enc = bytes(metadata["keys"])
    salt = bytes(metadata["master_key_salt"])

    salt = salt[:16]
    master_key = nacl.pwhash.argon2i.kdf(
        CHACHAPOLY_KEY_LEN,
        key_pass.encode("ascii"),
        salt,
        nacl.pwhash.argon2i.OPSLIMIT_MODERATE,
        nacl.pwhash.argon2i.MEMLIMIT_MODERATE,
    )

    keys_mpk = decrypt_merged(keys_enc, master_key)
    keys_lst = msgpack.unpackb(keys_mpk)
    keys = dict(
        zip(
            (
                "type",
                "name",
                "value",
                "item_hmac",
                "tag_name",
                "tag_value",
                "tag_hmac",
            ),
            keys_lst,
        )
    )
    keys["master"] = master_key
    keys["salt"] = salt
    return keys


async def create_config(conn: DbConnection, indy_key, base_wallet_name):
    """Create the config table using the base wallet name and
    pass_key.
    """
    pass_key = "kdf:argon2i:13:mod?salt=" + indy_key["salt"].hex()
    await conn.create_config(pass_key, base_wallet_name)


async def init_profile(
    conn: DbConnection, indy_key: dict, wallet_id: str = None
) -> dict:
    profile_key = {
        "ver": "1",
        "ick": indy_key["type"],
        "ink": indy_key["name"],
        "ihk": indy_key["item_hmac"],
        "tnk": indy_key["tag_name"],
        "tvk": indy_key["tag_value"],
        "thk": indy_key["tag_hmac"],
    }

    enc_pk = encrypt_merged(cbor2.dumps(profile_key), indy_key["master"])

    if conn.DB_TYPE.startswith("pgsql_mwst_"):
        id = await conn.insert_profile(wallet_id, enc_pk)
        return profile_key, id
    else:
        pass_key = "kdf:argon2i:13:mod?salt=" + indy_key["salt"].hex()
        await conn.insert_profile(pass_key, str(uuid.uuid4()), enc_pk)
        return profile_key


def encrypt_merged(message: bytes, my_key: bytes, hmac_key: bytes = None) -> bytes:
    if hmac_key:
        nonce = hmac.HMAC(hmac_key, message, digestmod=hashlib.sha256).digest()[
            :CHACHAPOLY_NONCE_LEN
        ]
    else:
        nonce = os.urandom(CHACHAPOLY_NONCE_LEN)

    ciphertext = nacl.bindings.crypto_aead_chacha20poly1305_ietf_encrypt(
        message, None, nonce, my_key
    )

    return nonce + ciphertext


def encrypt_value(category: bytes, name: bytes, value: bytes, hmac_key: bytes) -> bytes:
    hasher = hmac.HMAC(hmac_key, digestmod=hashlib.sha256)
    hasher.update(len(category).to_bytes(4, "big"))
    hasher.update(category)
    hasher.update(len(name).to_bytes(4, "big"))
    hasher.update(name)
    value_key = hasher.digest()
    return encrypt_merged(value, value_key)


def decrypt_merged(enc_value: bytes, key: bytes, b64: bool = False) -> bytes:
    if b64:
        enc_value = base64.b64decode(enc_value)

    nonce, ciphertext = (
        enc_value[:CHACHAPOLY_NONCE_LEN],
        enc_value[CHACHAPOLY_NONCE_LEN:],
    )
    return nacl.bindings.crypto_aead_chacha20poly1305_ietf_decrypt(
        ciphertext, None, nonce, key
    )


def decrypt_tags(tags: str, name_key: bytes, value_key: bytes = None):
    for tag in tags.split(","):
        tag_name, tag_value = map(bytes.fromhex, tag.split(":"))
        name = decrypt_merged(tag_name, name_key)
        value = decrypt_merged(tag_value, value_key) if value_key else tag[1]
        yield name, value


def decrypt_item(row: tuple, keys: dict, b64: bool = False):
    row_id, row_type, row_name, row_value, row_key, tags_enc, tags_plain = row
    value_key = decrypt_merged(row_key, keys["value"])
    value = decrypt_merged(row_value, value_key) if row_value else None
    tags = [
        (0, k, v)
        for k, v in (
            (
                decrypt_tags(tags_enc, keys["tag_name"], keys["tag_value"])
                if tags_enc
                else ()
            )
        )
    ]
    for k, v in decrypt_tags(tags_plain, keys["tag_name"]) if tags_plain else ():
        tags.append((1, k, v))
    return {
        "id": row_id,
        "type": decrypt_merged(row_type, keys["type"], b64),
        "name": decrypt_merged(row_name, keys["name"], b64),
        "value": value,
        "tags": tags,
    }


def update_item(item: dict, key: dict) -> dict:
    tags = []
    for plain, k, v in item["tags"]:
        if not plain:
            v = encrypt_merged(v, key["tvk"], key["thk"])
        k = encrypt_merged(k, key["tnk"], key["thk"])
        tags.append((plain, k, v))

    ret_val = {
        "id": item["id"],
        "category": encrypt_merged(item["type"], key["ick"], key["ihk"]),
        "name": encrypt_merged(item["name"], key["ink"], key["ihk"]),
        "value": encrypt_value(item["type"], item["name"], item["value"], key["ihk"]),
        "tags": tags,
    }

    return ret_val


async def update_items(
    conn: DbConnection,
    indy_key: dict,
    profile_key: dict,
    wallet_id: str = None,
    profile_id: int = None,
):
    while True:
        if conn.DB_TYPE.startswith("pgsql_mwst_"):
            rows = await conn.fetch_pending_items(1, wallet_id)
            if not rows:
                break

            upd = []
            for row in rows:
                result = decrypt_item(
                    row[1:], indy_key, b64=conn.DB_TYPE == "pgsql_mwst_profiles"
                )  # update for separate stores
                upd.append(update_item(result, profile_key))
            await conn.update_items(upd, profile_id)

        else:
            rows = await conn.fetch_pending_items(1)
            if not rows:
                break

            upd = []
            for row in rows:
                db_type = conn.DB_TYPE
                if db_type.startswith("pgsql_mwst_"):
                    result = decrypt_item(
                        row, indy_key, b64=conn.DB_TYPE == "pgsql_mwst_profiles"
                    )  # update
                else:
                    result = decrypt_item(row, indy_key, b64=conn.DB_TYPE == "pgsql")
                upd.append(update_item(result, profile_key))
            await conn.update_items(upd)


async def post_upgrade(uri: str, wallet_pw: str, profile: str = None):
    from aries_askar import Key, Store

    print("Opening wallet with Askar...")
    store = await Store.open(uri, pass_key=wallet_pw, profile=profile)

    print("Updating keys...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            keys = await txn.fetch_all("Indy::Key", limit=50)
            if not keys:
                break
            for row in keys:
                await txn.remove("Indy::Key", row.name)
                meta = await txn.fetch("Indy::KeyMetadata", row.name)
                if meta:
                    await txn.remove("Indy::KeyMetadata", meta.name)
                    meta = json.loads(meta.value)["value"]
                key_sk = base58.b58decode(json.loads(row.value)["signkey"])
                key = Key.from_secret_bytes("ed25519", key_sk[:32])
                await txn.insert_key(row.name, key, metadata=meta)
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating master secret(s)...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            ms = await txn.fetch_all("Indy::MasterSecret")
            if not ms:
                break
            elif len(ms) > 1:
                raise Exception("Encountered multiple master secrets")
            else:
                row = ms[0]
                await txn.remove("Indy::MasterSecret", row.name)
                value = json.loads(row.value)["value"]
                await txn.insert("master_secret", row.name, value_json=value)
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating DIDs...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            dids = await txn.fetch_all("Indy::Did", limit=50)
            if not dids:
                break
            for row in dids:
                await txn.remove("Indy::Did", row.name)
                info = json.loads(row.value)
                meta = await txn.fetch("Indy::DidMetadata", row.name)
                if meta:
                    await txn.remove("Indy::DidMetadata", meta.name)
                    meta = json.loads(meta.value)["value"]
                    with contextlib.suppress(json.JSONDecodeError):
                        meta = json.loads(meta)
                await txn.insert(
                    "did",
                    row.name,
                    value_json={
                        "did": info["did"],
                        "verkey": info["verkey"],
                        "metadata": meta,
                    },
                    tags={"verkey": info["verkey"]},
                )
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating stored schemas...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            schemas = await txn.fetch_all("Indy::Schema", limit=50)
            if not schemas:
                break
            for row in schemas:
                await txn.remove("Indy::Schema", row.name)
                await txn.insert(
                    "schema",
                    row.name,
                    value=row.value,
                )
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating stored credential definitions...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            cred_defs = await txn.fetch_all("Indy::CredentialDefinition", limit=50)
            if not cred_defs:
                break
            for row in cred_defs:
                await txn.remove("Indy::CredentialDefinition", row.name)
                sid = await txn.fetch("Indy::SchemaId", row.name)
                if not sid:
                    raise Exception(
                        f"Schema ID not found for credential definition: {row.name}"
                    )
                sid = sid.value.decode("utf-8")
                await txn.insert(
                    "credential_def", row.name, value=row.value, tags={"schema_id": sid}
                )

                priv = await txn.fetch("Indy::CredentialDefinitionPrivateKey", row.name)
                if priv:
                    await txn.remove("Indy::CredentialDefinitionPrivateKey", priv.name)
                    await txn.insert(
                        "credential_def_private",
                        priv.name,
                        value=priv.value,
                    )
                proof = await txn.fetch(
                    "Indy::CredentialDefinitionCorrectnessProof", row.name
                )
                if proof:
                    await txn.remove(
                        "Indy::CredentialDefinitionCorrectnessProof", proof.name
                    )
                    await txn.insert(
                        "credential_def_key_proof",
                        proof.name,
                        value=proof.value,
                    )
                upd_count += 1

            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating stored revocation registry definitions...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            reg_defs = await txn.fetch_all(
                "Indy::RevocationRegistryDefinition", limit=50
            )
            if not reg_defs:
                break
            for row in reg_defs:
                await txn.remove("Indy::RevocationRegistryDefinition", row.name)
                await txn.insert("revocation_reg_def", row.name, value=row.value)
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating stored revocation registry keys...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            reg_defs = await txn.fetch_all(
                "Indy::RevocationRegistryDefinitionPrivate", limit=50
            )
            if not reg_defs:
                break
            for row in reg_defs:
                await txn.remove("Indy::RevocationRegistryDefinitionPrivate", row.name)
                await txn.insert(
                    "revocation_reg_def_private", row.name, value=row.value
                )
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating stored revocation registry states...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            reg_defs = await txn.fetch_all("Indy::RevocationRegistry", limit=50)
            if not reg_defs:
                break
            for row in reg_defs:
                await txn.remove("Indy::RevocationRegistry", row.name)
                await txn.insert("revocation_reg", row.name, value=row.value)
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating stored revocation registry info...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            reg_defs = await txn.fetch_all("Indy::RevocationRegistryInfo", limit=50)
            if not reg_defs:
                break
            for row in reg_defs:
                await txn.remove("Indy::RevocationRegistryInfo", row.name)
                await txn.insert("revocation_reg_info", row.name, value=row.value)
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Updating stored credentials...", end="")
    upd_count = 0
    while True:
        async with store.transaction() as txn:
            creds = await txn.fetch_all("Indy::Credential", limit=50)
            if not creds:
                break
            for row in creds:
                await txn.remove("Indy::Credential", row.name)
                cred_data = row.value_json
                tags = _credential_tags(cred_data)
                await txn.insert("credential", row.name, value=row.value, tags=tags)
                upd_count += 1
            await txn.commit()
    print(f" {upd_count} updated")

    print("Closing wallet")
    await store.close()


def _credential_tags(cred_data: dict) -> dict:
    schema_id = cred_data["schema_id"]
    schema_id_parts = re.match(r"^(\w+):2:([^:]+):([^:]+)$", schema_id)
    if not schema_id_parts:
        raise UpgradeError(f"Error parsing credential schema ID: {schema_id}")
    cred_def_id = cred_data["cred_def_id"]
    cdef_id_parts = re.match(r"^(\w+):3:CL:([^:]+):([^:]+)$", cred_def_id)
    if not cdef_id_parts:
        raise UpgradeError(f"Error parsing credential definition ID: {cred_def_id}")

    tags = {
        "schema_id": schema_id,
        "schema_issuer_did": schema_id_parts[1],
        "schema_name": schema_id_parts[2],
        "schema_version": schema_id_parts[3],
        "issuer_did": cdef_id_parts[1],
        "cred_def_id": cred_def_id,
        "rev_reg_id": cred_data.get("rev_reg_id", "None"),
    }
    for k, attr_value in cred_data["values"].items():
        attr_name = k.replace(" ", "")
        tags[f"attr::{attr_name}::value"] = attr_value["raw"]

    return tags


async def upgrade_pgsql_mwst_profiles(conn, wallet_pw, base_wallet_name, wallet_keys):
    try:
        await conn.pre_upgrade()

        indy_key_dict: dict = await fetch_pgsql_mwst_keys(
            conn, base_wallet_name, wallet_pw
        )
        await create_config(conn, indy_key_dict[base_wallet_name], base_wallet_name)

        for wallet_name, wallet_pw in wallet_keys.items():
            indy_key_dict: dict = await fetch_pgsql_mwst_keys(
                conn, wallet_name, wallet_pw
            )
            profile_row = await conn.retrieve_entries(
                "SELECT * FROM profiles", optional=True
            )
            if len(profile_row) > 0:
                raise UpgradeError("Config table must be empty prior to migration.")
            for wallet_id, indy_key in indy_key_dict.items():
                profile_key, profile_id = await init_profile(conn, indy_key, wallet_id)
                await update_items(conn, indy_key, profile_key, wallet_id, profile_id)
                await conn.finish_upgrade()
                await post_upgrade(conn._path, wallet_pw)  # TODO: pass in profile name
    finally:
        await conn.close()


async def upgrade(
    conn: DbConnection,
    base_wallet_name: str,
    wallet_keys: Dict[str, str],
    profile_store_name: str = None,
):
    """Upgrade and Indy SDK wallet to Aries Askar.

    Strategy for simple case, one database == one wallet:

    1. Fetch Indy key
    2. Create config table
    3. Initialize profile
    4. Update items
    6. Transform Indy items to Askar items
    5. Remove old tables

    Strategy for multi-wallet single table as profiles:

    1. User provides a mapping of wallet names and passwords
    2. User provides base wallet name and password
    3. Create config table using base wallet info to fill in default profile
    4. For every mapping:
        1. Fetch Indy Key
        2. Create a profile
        3. Update items
        4. Transform Indy items to Askar items
    4. Remove old tables

    Strategy for multi-wallet single table as separate stores:

    1. User provides a mapping of wallet names and passwords
    2. For every mapping:
        1. Create a new Askar Store DB
        2. Connect to DB
        3. Fetch Indy key from original DB
        4. Create config table
        5. Initialize profile
        6. Retrieve items from old DB
        7. Update items, insert into new DB
        8. Transform Indy items to Askar items
    7. Remove old tables
    """
    wallet_pw = wallet_keys.get(base_wallet_name)
    if not wallet_pw:
        raise ValueError("Base wallet passphrase not found")

    await conn.connect()

    if conn.DB_TYPE == "pgsql_mwst_profiles":
        await upgrade_pgsql_mwst_profiles(
            conn, wallet_pw, base_wallet_name, wallet_keys
        )

    if isinstance(conn, SqliteConnection):
        wallet = conn
    elif isinstance(conn, PgConnection):
        wallet = conn
    else:
        raise ValueError("Unknown database type")

    try:
        await conn.pre_upgrade()
        indy_key = await fetch_indy_key(wallet, wallet_pw)
        profile_key = await init_profile(conn, indy_key)
        await update_items(conn, indy_key, profile_key)
        await conn.finish_upgrade()
    finally:
        await conn.close()
    if conn.DB_TYPE == "sqlite":
        await post_upgrade(f"sqlite://{conn._path}", wallet_pw)
    else:
        await post_upgrade(conn._path, wallet_pw)


async def migration(
    mode: str,
    db_path: str = None,
    profile_store_name: str = None,
    wallet_keys: dict = {},
    base_wallet_name: str = "agency",
):
    logging.basicConfig(level=logging.WARN)
    # TODO: make base_wallet_name optional
    # TODO: if base wallet name is empty default to wallet_keys key value
    if mode == "sqlite":
        conn = SqliteConnection(db_path)

    elif mode == "dbpw":
        conn = PgConnection(db_path)

    elif mode == "mwst_as_profiles":
        conn = PgConnectionMWSTProfiles(db_path)

    elif mode == "mwst_as_separate_stores":
        conn = PgConnectionMWSTSeparateStores(db_path)

    else:
        raise UpgradeError("Invalid mode")

    await upgrade(
        conn,
        profile_store_name,
        wallet_keys,
        base_wallet_name,
    )
