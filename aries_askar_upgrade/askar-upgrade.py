"""Indy wallet upgrade."""


import asyncio
import base64
import contextlib
import json
import hashlib
import hmac
import logging
import os
import re

import pprint
import sys
import uuid

import base58
import cbor2
import msgpack
import nacl.pwhash
from urllib.parse import urlparse

from aries_askar_upgrade.db_connection import DbConnection
from aries_askar_upgrade.sqlite_connection import SqliteConnection
from aries_askar_upgrade.pg_connection import PgConnection
from aries_askar_upgrade.error import UpgradeError


CHACHAPOLY_KEY_LEN = 32
CHACHAPOLY_NONCE_LEN = 12
CHACHAPOLY_TAG_LEN = 16
ENCRYPTED_KEY_LEN = CHACHAPOLY_NONCE_LEN + CHACHAPOLY_KEY_LEN + CHACHAPOLY_TAG_LEN


async def fetch_indy_key(conn: DbConnection, key_pass: str) -> dict:
    print(" ")
    print(f"fx fetch_indy_key(conn: DbConnection, key_pass: {key_pass})")
    print(" ")

    metadata_row = await conn.fetch_one("SELECT value FROM metadata")
    metadata_value = metadata_row[0]
    if conn.DB_TYPE == "pgsql":
        metadata_json = base64.b64decode(metadata_value)
    else:
        metadata_json = metadata_value
    metadata = json.loads(metadata_json)
    keys_enc = bytes(metadata["keys"])
    salt = bytes(metadata["master_key_salt"])

    print("Deriving wallet key...")
    key_pass = key_pass.encode("ascii")
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
    return keys


async def init_profile(conn: DbConnection, indy_key: dict) -> dict:
    print(" ")
    print("fx init_profile(conn: DbConnection, indy_key: dict)")
    print("indy_key: ")
    pprint.pprint(indy_key, indent=2)

    profile_row = await conn.fetch_one(
        "SELECT id, profile_key FROM profiles", optional=True
    )
    print("profile_row: ")
    pprint.pprint(profile_row, indent=2)

    if profile_row:
        print("before profile_key: ")
        pprint.pprint(profile_row[1], indent=2)

        profile_key = cbor2.loads(profile_row[1])
        print("after profile_key: ")
        pprint.pprint(profile_key, indent=2)
        print(" ")

    else:
        profile_key = {
            "ver": "1",
            "ick": indy_key["type"],
            "ink": indy_key["name"],
            "ihk": indy_key["item_hmac"],
            "tnk": indy_key["tag_name"],
            "tvk": indy_key["tag_value"],
            "thk": indy_key["tag_hmac"],
        }

        print("profile_key: ")
        pprint.pprint(profile_key, indent=2)

        pass_key = "kdf:argon2i:13:mod?salt=" + indy_key["salt"].hex()
        print("pass_key: ")
        pprint.pprint(pass_key, indent=2)

        enc_pk = encrypt_merged(cbor2.dumps(profile_key), indy_key["master"])
        print("enc_pk: ")
        pprint.pprint(enc_pk, indent=2)
        print(" ")

        await conn.insert_profile(pass_key, str(uuid.uuid4()), enc_pk)

    return profile_key


def encrypt_merged(message: bytes, my_key: bytes, hmac_key: bytes = None) -> bytes:
    print(" ")
    print("fx encrypt_merged(message: bytes, my_key: bytes, hmac_key: bytes = None)")
    print("message: ")
    pprint.pprint(message, indent=2)
    print("my_key: ")
    pprint.pprint(my_key, indent=2)
    print("hmac_key: ")
    pprint.pprint(hmac_key, indent=2)
    print(" ")

    if hmac_key:
        nonce = hmac.HMAC(hmac_key, message, digestmod=hashlib.sha256).digest()[:CHACHAPOLY_NONCE_LEN]
    else:
        nonce = os.urandom(CHACHAPOLY_NONCE_LEN)

    ciphertext = nacl.bindings.crypto_aead_chacha20poly1305_ietf_encrypt(message, None, nonce, my_key)

    return nonce + ciphertext


def encrypt_value(category: bytes, name: bytes, value: bytes, hmac_key: bytes) -> bytes:
    print(" ")
    print("fx encrypt_value(category: bytes, name: bytes, value: bytes, hmac_key: bytes)")
    print("category: ")
    pprint.pprint(category, indent=2)
    print("name: ")
    pprint.pprint(name, indent=2)
    print("value: ")
    pprint.pprint(value, indent=2)
    print("hmac_key: ")
    pprint.pprint(hmac_key, indent=2)
    print(" ")

    hasher = hmac.HMAC(hmac_key, digestmod=hashlib.sha256)
    hasher.update(len(category).to_bytes(4, "big"))
    hasher.update(category)
    hasher.update(len(name).to_bytes(4, "big"))
    hasher.update(name)
    value_key = hasher.digest()
    return encrypt_merged(value, value_key)


def decrypt_merged(enc_value: bytes, key: bytes, b64: bool = False) -> bytes:
    print(" ")
    print(f"fx decrypt_merged(enc_value: bytes, key: bytes, b64: {b64})")
    print("enc_value: ")
    pprint.pprint(enc_value, indent=2)
    print("key: ")
    pprint.pprint(key, indent=2)
    print(" ")

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
    print(" ")
    print(f"fx decrypt_tags(tags: str, name_key: bytes, value_key: bytes = {bytes})")
    print("tags: ")
    pprint.pprint(tags, indent=2)
    print("name_key: ")
    pprint.pprint(name_key, indent=2)
    print("value_key: ")
    pprint.pprint(value_key, indent=2)
    print(" ")

    for tag in tags.split(","):
        tag_name, tag_value = map(bytes.fromhex, tag.split(":"))
        name = decrypt_merged(tag_name, name_key)
        value = decrypt_merged(tag_value, value_key) if value_key else tag[1]
        yield name, value


def decrypt_item(row: tuple, keys: dict, b64: bool = False):
    print(" ")
    print(f"fx decrypt_item(row: tuple, keys: dict, b64: bool = {b64})")
    print("row: ")
    pprint.pprint(row, indent=2)
    pprint.pprint(f"keys: {keys}", indent=2)
    print(" ")

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
    print(" ")
    print("fx update_item(item: dict, key: dict)")
    print("item: ")
    pprint.pprint(item, indent=2)
    print("key: ")
    pprint.pprint(key, indent=2)
    print(" ")

    tags = []
    for plain, k, v in item["tags"]:
        if not plain:
            v = encrypt_merged(v, key["tvk"], key["thk"])
        k = encrypt_merged(k, key["tnk"], key["thk"])
        tags.append((plain, k, v))

    print(f"found type: {item['type']}")
    print(f"found key: {key}")
    # print(f"found ick: {key['ick']}")
    # print(f"found ihk: {key['ihk']}")

    ret_val = {
        "id": item["id"],
        "category": encrypt_merged(item["type"], key["ick"], key["ihk"]),
        "name": encrypt_merged(item["name"], key["ink"], key["ihk"]),
        "value": encrypt_value(item["type"], item["name"], item["value"], key["ihk"]),
        "tags": tags,
    }

    print("ret_val: ")
    pprint.pprint(ret_val, indent=2)

    return ret_val


async def update_items(conn: DbConnection, indy_key: dict, profile_key: dict):
    print(" ")
    print("fx update_items(conn: DbConnection, indy_key: dict, profile_key: dict)")
    print("indy_key: ")
    pprint.pprint(indy_key, indent=2)
    print("profile_key: ")
    pprint.pprint(profile_key, indent=2)
    print(" ")

    while True:
        rows = await conn.fetch_pending_items(1)
        if not rows:
            break

        upd = []
        for row in rows:
            result = decrypt_item(row, indy_key, b64=conn.DB_TYPE == "pgsql")
            pprint.pprint(result, indent=2)
            # print(f"found: {result}")
            # print(f"indy_key: {indy_key}")
            # print(" ")
            upd.append(update_item(result, profile_key))
        await conn.update_items(upd)


async def post_upgrade(uri: str, master_pw: str):
    from aries_askar import Key, Store

    print("Opening wallet with Askar...")
    store = await Store.open(uri, pass_key=master_pw)

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
                # name as "default" ?
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
    print(" ")
    print("fx _credential_tags(cred_data: dict)")
    print("cred_data: ")
    pprint.pprint(cred_data, indent=2)
    print(" ")

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


async def upgrade(db: DbConnection, master_pw: str):
    await db.connect()

    try:
        await db.pre_upgrade()
        indy_key = await fetch_indy_key(db, master_pw)
        print(" ")
        print(f"fx upgrade(db: DbConnection, master_pw: {master_pw})")
        print("indy_key")
        pprint.pprint(indy_key, indent=2)
        print(" ")
        profile_key = await init_profile(conn, indy_key)
        print(" ")
        print("fx upgrade(db, master_pw)")
        print("profile_key: ")
        print(" ")
        pprint.pprint(profile_key, indent=2)
        await update_items(conn, indy_key, profile_key)
        await conn.finish_upgrade()
        print("Finished schema upgrade")
    finally:
        await db.close()

    # TODO: Finish this...
    await post_upgrade(f"sqlite://{db._path}", master_pw)
    print("done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARN)

    if len(sys.argv) < 2:
        raise SystemExit("Missing database URL")
    if len(sys.argv) < 3:
        raise SystemExit("Missing database master password")

    if sys.argv[1][0:8] == "postgres":
        print("DB type: pgsql")
        r = urlparse(sys.argv[1])

        conn = PgConnection(f"{r.hostname}:{r.port}", r.path[1:], r.username, r.password)
    else:
        print("DB type: sqlite")

        conn = SqliteConnection(sys.argv[1])

    key = sys.argv[2]  # Faber.Agent372766
    asyncio.get_event_loop().run_until_complete(upgrade(conn, key))
