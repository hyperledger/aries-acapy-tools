"""Indy wallet upgrade."""

import asyncio
import base64
import json
import hashlib
import hmac
import logging
import os
import re

import pprint
import sys
import uuid

from abc import ABC, abstractmethod
from urllib.parse import urlparse

import aiosqlite
import asyncpg
import base58
import cbor2
import msgpack
import nacl.pwhash


CHACHAPOLY_KEY_LEN = 32
CHACHAPOLY_NONCE_LEN = 12
CHACHAPOLY_TAG_LEN = 16
ENCRYPTED_KEY_LEN = CHACHAPOLY_NONCE_LEN + CHACHAPOLY_KEY_LEN + CHACHAPOLY_TAG_LEN


class UpgradeError(Exception):
    pass


class DbConnection(ABC):
    """Abstract database connection."""

    DB_TYPE: str

    @abstractmethod
    async def connect(self):
        """Initialize the connection handler."""

    @abstractmethod
    async def find_table(self, name: str) -> bool:
        """Check for existence of a table."""

    @abstractmethod
    async def pre_upgrade(self, name: str) -> bool:
        """Add new tables and columns."""

    @abstractmethod
    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""

    @abstractmethod
    async def finish_upgrade(self):
        """Complete the upgrade."""

    @abstractmethod
    async def fetch_one(self, sql: str, optional: bool = False):
        """Fetch a single row from the database."""

    @abstractmethod
    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items."""

    @abstractmethod
    async def update_items(self, items):
        """Update items in the database."""

    @abstractmethod
    async def close(self):
        """Release the connection."""


class PgConnection(DbConnection):
    """Postgres connection."""

    DB_TYPE = "pgsql"

    def __init__(
        self, db_host: str, db_name: str, db_user: str, db_pass: str
    ) -> "PgConnection":
        """Initialize a PgConnection instance."""
        self._config = {
            "host": db_host,
            "db": db_name,
            "user": db_user,
            "password": db_pass,
        }
        self._conn: asyncpg.Connection = None

    @property
    def parsed_url(self):
        """Accessor for the parsed database URL."""
        url = self._config["host"]
        if "://" not in url:
            url = f"http://{url}"
        return urlparse(url)

    async def connect(self):
        """Accessor for the connection pool instance."""
        if not self._conn:
            parts = self.parsed_url
            self._conn = await asyncpg.connect(
                host=parts.hostname,
                port=parts.port or 5432,
                user=self._config["user"],
                password=self._config["password"],
                database=self._config["db"],
            )

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None


class SqliteConnection(DbConnection):
    """Sqlite connection."""

    DB_TYPE = "sqlite"

    def __init__(self, path: str) -> "SqliteConnection":
        """Initialize a SqliteConnection instance."""
        self._path = path
        self._conn: aiosqlite.Connection = None

    async def connect(self):
        """Accessor for the connection pool instance."""
        if not self._conn:
            self._conn = await aiosqlite.connect(self._path)

    async def find_table(self, name: str) -> bool:
        """Check for existence of a table."""
        found = await self._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
            (name,),
        )
        return (await found.fetchone())[0]

    async def pre_upgrade(self) -> dict:
        """Add new tables and columns."""

        if not await self.find_table("metadata"):
            raise UpgradeError("No metadata table found: not an Indy wallet database")

        if await self.find_table("config"):
            stmt = await self._conn.execute("SELECT name, value FROM config")
            config = {}
            async for row in stmt:
                config[row[0]] = row[1]
            return config

        await self._conn.executescript(
            """
            BEGIN EXCLUSIVE TRANSACTION;

            CREATE TABLE config (
                name TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (name)
            );

            CREATE TABLE profiles (
                id INTEGER NOT NULL,
                name TEXT NOT NULL,
                reference TEXT NULL,
                profile_key BLOB NULL,
                PRIMARY KEY (id)
            );
            CREATE UNIQUE INDEX ix_profile_name ON profiles (name);

            ALTER TABLE items RENAME TO items_old;
            CREATE TABLE items (
                id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                kind INTEGER NOT NULL,
                category BLOB NOT NULL,
                name BLOB NOT NULL,
                value BLOB NOT NULL,
                expiry DATETIME NULL,
                PRIMARY KEY (id),
                FOREIGN KEY (profile_id) REFERENCES profiles (id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            );
            CREATE UNIQUE INDEX ix_items_uniq ON items
                (profile_id, kind, category, name);

            CREATE TABLE items_tags (
                id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                name BLOB NOT NULL,
                value BLOB NOT NULL,
                plaintext BOOLEAN NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY (item_id) REFERENCES items (id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            );
            CREATE INDEX ix_items_tags_item_id ON items_tags (item_id);
            CREATE INDEX ix_items_tags_name_enc ON items_tags
                (name, SUBSTR(value, 1, 12)) WHERE plaintext=0;
            CREATE INDEX ix_items_tags_name_plain ON items_tags
                (name, value) WHERE plaintext=1;

            COMMIT;
        """,
        )
        return {}

    async def insert_profile(self, pass_key: str, name: str, key: bytes):
        """Insert the initial profile."""
        await self._conn.executemany(
            "INSERT INTO config (name, value) VALUES (?1, ?2)",
            (
                ("default_profile", name),
                ("key", pass_key),
            ),
        )
        await self._conn.execute(
            "INSERT INTO profiles (name, profile_key) VALUES (?1, ?2)", (name, key)
        )
        await self._conn.commit()

    async def finish_upgrade(self):
        """Complete the upgrade."""
        await self._conn.executescript(
            """
            BEGIN EXCLUSIVE TRANSACTION;
            DROP TABLE items_old;
            DROP TABLE metadata;
            DROP TABLE tags_encrypted;
            DROP TABLE tags_plaintext;
            INSERT INTO config (name, value) VALUES ("version", "1");
            COMMIT;
        """
        )

    async def fetch_one(self, sql: str, optional: bool = False):
        """Fetch a single row from the database."""
        stmt = await self._conn.execute(sql)
        found = None
        async for row in stmt:
            if found is None:
                found = row
            else:
                raise Exception("Found duplicate row")
        if not optional and not found:
            raise Exception("Row not found")
        return found

    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items."""
        stmt = await self._conn.execute(
            """
            SELECT i.id, i.type, i.name, i.value, i.key,
            (SELECT GROUP_CONCAT(HEX(te.name) || ':' || HEX(te.value))
                FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
            (SELECT GROUP_CONCAT(HEX(tp.name) || ':' || HEX(tp.value))
                FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
            FROM items_old i LIMIT ?1
            """,
            (limit,),
        )
        return await stmt.fetchall()

    async def update_items(self, items):
        """Update items in the database."""
        del_ids = []
        for item in items:
            del_ids = item["id"]
            ins = await self._conn.execute(
                """
                INSERT INTO items (profile_id, kind, category, name, value)
                VALUES (1, 2, ?1, ?2, ?3)
                """,
                (item["category"], item["name"], item["value"]),
            )
            item_id = ins.lastrowid
            if item["tags"]:
                await self._conn.executemany(
                    """
                    INSERT INTO items_tags (item_id, plaintext, name, value)
                    VALUES (?1, ?2, ?3, ?4)
                    """,
                    ((item_id, *tag) for tag in item["tags"]),
                )
        await self._conn.execute("DELETE FROM items_old WHERE id IN (?1)", (del_ids,))
        await self._conn.commit()

    async def close(self):
        """Release the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None


async def fetch_indy_key(conn: DbConnection, key_pass: str) -> dict:
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
    profile_row = await conn.fetch_one(
        "SELECT id, profile_key FROM profiles", optional=True
    )
    if profile_row:
        profile_key = cbor2.loads(profile_row[1])
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
        pass_key = "kdf:argon2i:13:mod?salt=" + indy_key["salt"].hex()
        enc_pk = encrypt_merged(cbor2.dumps(profile_key), indy_key["master"])
        await conn.insert_profile(pass_key, str(uuid.uuid4()), enc_pk)
    return profile_key


def encrypt_merged(message: bytes, key: bytes, hmac_key: bytes = None) -> bytes:
    if hmac_key:
        nonce = hmac.HMAC(hmac_key, message, digestmod=hashlib.sha256).digest()[
            :CHACHAPOLY_NONCE_LEN
        ]
    else:
        nonce = os.urandom(CHACHAPOLY_NONCE_LEN)

    ciphertext = nacl.bindings.crypto_aead_chacha20poly1305_ietf_encrypt(
        message, None, nonce, key
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
    tags = []
    for k, v in (
        decrypt_tags(tags_enc, keys["tag_name"], keys["tag_value"]) if tags_enc else ()
    ):
        tags.append((0, k, v))
    for k, v in decrypt_tags(tags_plain, keys["tag_name"]) if tags_plain else ():
        tags.append((1, k, v))
    result = {
        "id": row_id,
        "type": decrypt_merged(row_type, keys["type"], b64),
        "name": decrypt_merged(row_name, keys["name"], b64),
        "value": value,
        "tags": tags,
    }
    return result


def update_item(item: dict, key: dict) -> dict:
    tags = []
    for plain, k, v in item["tags"]:
        if not plain:
            v = encrypt_merged(v, key["tvk"], key["thk"])
        k = encrypt_merged(k, key["tnk"], key["thk"])
        tags.append((plain, k, v))
    return {
        "id": item["id"],
        "category": encrypt_merged(item["type"], key["ick"], key["ihk"]),
        "name": encrypt_merged(item["name"], key["ink"], key["ihk"]),
        "value": encrypt_value(item["type"], item["name"], item["value"], key["ihk"]),
        "tags": tags,
    }


async def update_items(conn: DbConnection, indy_key: dict, profile_key: dict):
    while True:
        rows = await conn.fetch_pending_items(1)
        if not rows:
            break

        upd = []
        for row in rows:
            result = decrypt_item(row, indy_key, b64=conn.DB_TYPE == "pgsql")
            pprint.pprint(result, indent=2)
            print()
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
                    try:
                        meta = json.loads(meta)
                    except json.JSONDecodeError:
                        # leave as a string
                        pass
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


async def upgrade(db: DbConnection, master_pw: str):
    await db.connect()

    try:
        await db.pre_upgrade()
        indy_key = await fetch_indy_key(db, master_pw)
        profile_key = await init_profile(conn, indy_key)
        await update_items(conn, indy_key, profile_key)
        await conn.finish_upgrade()
        print("Finished schema upgrade")
    finally:
        await db.close()

    await post_upgrade(f"sqlite://{db._path}", master_pw)
    print("done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARN)

    if len(sys.argv) < 2:
        raise SystemExit("Missing database URL")
    if len(sys.argv) < 3:
        raise SystemExit("Missing database master password")

    conn = SqliteConnection(sys.argv[1])
    key = sys.argv[2]  # Faber.Agent372766
    asyncio.get_event_loop().run_until_complete(upgrade(conn, key))
