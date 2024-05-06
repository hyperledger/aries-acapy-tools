from abc import ABC, abstractmethod
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import sys
from typing import Dict, Optional, Union, cast
from urllib.parse import urlparse

from aries_askar import Key, Store, Session
import asyncpg
import base58
import cbor2
import msgpack
import nacl.pwhash
from nacl.exceptions import CryptoError

from .db_connection import DbConnection, Wallet
from .error import DecryptionFailedError, UpgradeError, MissingWalletError
from .pg_connection import PgConnection, PgWallet
from .pg_mwst_connection import PgMWSTConnection
from .sqlite_connection import SqliteConnection

LOGGER = logging.getLogger(__name__)

# Constants
CHACHAPOLY_KEY_LEN = 32
CHACHAPOLY_NONCE_LEN = 12
CHACHAPOLY_TAG_LEN = 16
ENCRYPTED_KEY_LEN = CHACHAPOLY_NONCE_LEN + CHACHAPOLY_KEY_LEN + CHACHAPOLY_TAG_LEN


class Progress:
    """Simple progress indicator."""

    def __init__(
        self,
        message: str,
        report_in_progress: bool = True,
        interval: int = 10,
    ):
        self.count = 0
        self.message = message
        self.report_in_progress = report_in_progress
        self.interval = interval
        self.last_reported = None

        # Initial progress indicator -- let them know something is happening
        print(message, end="")

    def update(self, amount: int = 1):
        """Update count, report if thresholds met."""
        if self.report_in_progress:
            passed_intervals = ((self.count % self.interval) + amount) / self.interval
            if passed_intervals >= 1:
                if self.count == 0:
                    print()
                print(f"{self.message} {self.count + amount}")
                self.last_reported = self.count + amount

        self.count += amount

    def report(self):
        """Final report."""
        if not self.report_in_progress or self.last_reported is None:
            print(f" {self.count}")
            return

        if self.last_reported < self.count:
            print(f"{self.message} {self.count}")


class Strategy(ABC):
    """Base class for upgrade strategies."""

    def __init__(self, batch_size: int):
        self.batch_size = batch_size

    def encrypt_merged(
        self, message: bytes, my_key: bytes, hmac_key: bytes = None
    ) -> bytes:
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

    def encrypt_value(
        self, category: bytes, name: bytes, value: bytes, hmac_key: bytes
    ) -> bytes:
        hasher = hmac.HMAC(hmac_key, digestmod=hashlib.sha256)
        hasher.update(len(category).to_bytes(4, "big"))
        hasher.update(category)
        hasher.update(len(name).to_bytes(4, "big"))
        hasher.update(name)
        value_key = hasher.digest()
        return self.encrypt_merged(value, value_key)

    def decrypt_merged(self, enc_value: bytes, key: bytes, b64: bool = False) -> bytes:
        if b64:
            enc_value = base64.b64decode(enc_value)

        nonce, ciphertext = (
            enc_value[:CHACHAPOLY_NONCE_LEN],
            enc_value[CHACHAPOLY_NONCE_LEN:],
        )
        return nacl.bindings.crypto_aead_chacha20poly1305_ietf_decrypt(
            ciphertext, None, nonce, key
        )

    def decrypt_tags(
        self, tags: str, name_key: bytes, value_key: Optional[bytes] = None
    ):
        for tag in tags.split(","):
            tag_name, tag_value = map(bytes.fromhex, tag.split(":"))
            name = self.decrypt_merged(tag_name, name_key)
            value = (
                self.decrypt_merged(tag_value, value_key) if value_key else tag_value
            )
            yield name, value

    def decrypt_item(self, row: tuple, keys: dict, b64: bool = False):
        row_id, row_type, row_name, row_value, row_key, tags_enc, tags_plain = row
        value_key = self.decrypt_merged(row_key, keys["value"])
        value = self.decrypt_merged(row_value, value_key) if row_value else None
        tags = [
            (0, k, v)
            for k, v in (
                (
                    self.decrypt_tags(tags_enc, keys["tag_name"], keys["tag_value"])
                    if tags_enc
                    else ()
                )
            )
        ]
        for k, v in (
            self.decrypt_tags(tags_plain, keys["tag_name"]) if tags_plain else ()
        ):
            tags.append((1, k, v))
        return {
            "id": row_id,
            "type": self.decrypt_merged(row_type, keys["type"], b64),
            "name": self.decrypt_merged(row_name, keys["name"], b64),
            "value": value,
            "tags": tags,
        }

    def update_item(self, item: dict, key: dict) -> dict:
        tags = []
        for plain, k, v in item["tags"]:
            if not plain:
                v = self.encrypt_merged(v, key["tvk"], key["thk"])
            k = self.encrypt_merged(k, key["tnk"], key["thk"])
            tags.append((plain, k, v))

        ret_val = {
            "id": item["id"],
            "category": self.encrypt_merged(item["type"], key["ick"], key["ihk"]),
            "name": self.encrypt_merged(item["name"], key["ink"], key["ihk"]),
            "value": self.encrypt_value(
                item["type"], item["name"], item["value"], key["ihk"]
            ),
            "tags": tags,
        }

        return ret_val

    async def update_items(
        self,
        wallet: Wallet,
        indy_key: dict,
        profile_key: dict,
    ):
        progress = Progress("Migrating items...", interval=self.batch_size)
        decrypted_at_least_one = False
        try:
            async for rows in wallet.fetch_pending_items(self.batch_size):
                upd = []
                for row in rows:
                    result = self.decrypt_item(
                        row, indy_key, b64=isinstance(wallet, PgWallet)
                    )
                    decrypted_at_least_one = True
                    upd.append(self.update_item(result, profile_key))
                await wallet.update_items(upd)
                progress.update(len(upd))
            progress.report()
        except CryptoError as err:
            if decrypted_at_least_one:
                raise UpgradeError(
                    "Failed to decrypt an item after successfully decrypting others"
                ) from err
            else:
                raise DecryptionFailedError("Could not decrypt any items from wallet")

    async def fetch_indy_key(self, wallet: Wallet, wallet_key: str) -> dict:
        metadata_json = await wallet.get_metadata()
        metadata = json.loads(metadata_json)
        keys_enc = bytes(metadata["keys"])
        salt = bytes(metadata["master_key_salt"])

        salt = salt[:16]
        master_key = nacl.pwhash.argon2i.kdf(
            CHACHAPOLY_KEY_LEN,
            wallet_key.encode("ascii"),
            salt,
            nacl.pwhash.argon2i.OPSLIMIT_MODERATE,
            nacl.pwhash.argon2i.MEMLIMIT_MODERATE,
        )

        keys_mpk = self.decrypt_merged(keys_enc, master_key)
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

    async def batched_fetch_all(self, txn: Session, category: str):
        while True:
            items = await txn.fetch_all(category, limit=self.batch_size)
            if not items:
                break
            for row in items:
                yield row

    async def update_keys(self, store: Store):
        progress = Progress("Updating keys...", interval=self.batch_size)
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(txn, "Indy::Key"):
                await txn.remove("Indy::Key", row.name)
                meta = await txn.fetch("Indy::KeyMetadata", row.name)
                if meta:
                    await txn.remove("Indy::KeyMetadata", meta.name)
                    meta = json.loads(meta.value)["value"]
                key_sk = base58.b58decode(json.loads(row.value)["signkey"])
                key = Key.from_secret_bytes("ed25519", key_sk[:32])
                await txn.insert_key(row.name, key, metadata=meta)
                progress.update()
            await txn.commit()
        progress.report()

    async def update_master_keys(self, store: Store):
        progress = Progress("Updating master secret(s)...", interval=self.batch_size)
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(txn, "Indy::MasterSecret"):
                if progress.count > 0:
                    raise Exception("Encountered multiple master secrets")
                await txn.remove("Indy::MasterSecret", row.name)
                await txn.insert("master_secret", "default", value=row.value)
                progress.update()
            await txn.commit()
        progress.report()

    async def update_dids(self, store: Store):
        progress = Progress("Updating DIDs...", interval=self.batch_size)
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(txn, "Indy::Did"):
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
                progress.update()
            await txn.commit()
        progress.report()

    async def update_schemas(self, store: Store):
        progress = Progress("Updating stored schemas...", interval=self.batch_size)
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(txn, "Indy::Schema"):
                await txn.remove("Indy::Schema", row.name)
                await txn.insert(
                    "schema",
                    row.name,
                    value=row.value,
                )
                progress.update()
            await txn.commit()
        progress.report()

    async def update_cred_defs(self, store: Store):
        progress = Progress(
            "Updating stored credential definitions...", interval=self.batch_size
        )
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(txn, "Indy::CredentialDefinition"):
                await txn.remove("Indy::CredentialDefinition", row.name)
                sid = await txn.fetch("Indy::SchemaId", row.name)
                if not sid:
                    raise Exception(
                        f"Schema ID not found for credential definition: {row.name}"
                    )
                sid = sid.value.decode("utf-8")
                await txn.insert(
                    "credential_def",
                    row.name,
                    value=row.value,
                    tags={"schema_id": sid},
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
                    value = json.loads(proof.value)["value"]
                    await txn.insert(
                        "credential_def_key_proof",
                        proof.name,
                        value_json=value,
                    )
                progress.update()

            await txn.commit()
        progress.report()

    async def update_rev_reg_defs(self, store: Store):
        progress = Progress(
            "Updating stored revocation registry definitions...",
            interval=self.batch_size,
        )
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(
                txn,
                "Indy::RevocationRegistryDefinition",
            ):
                await txn.remove("Indy::RevocationRegistryDefinition", row.name)
                await txn.insert("revocation_reg_def", row.name, value=row.value)
                progress.update()
            await txn.commit()
        progress.report()

    async def update_rev_reg_keys(self, store: Store):
        progress = Progress(
            "Updating stored revocation registry keys...", interval=self.batch_size
        )
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(
                txn, "Indy::RevocationRegistryDefinitionPrivate"
            ):
                await txn.remove("Indy::RevocationRegistryDefinitionPrivate", row.name)
                await txn.insert(
                    "revocation_reg_def_private", row.name, value=row.value
                )
                progress.update()
            await txn.commit()
        progress.report()

    async def update_rev_reg_states(self, store: Store):
        progress = Progress(
            "Updating stored revocation registry states...", interval=self.batch_size
        )
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(
                txn,
                "Indy::RevocationRegistry",
            ):
                await txn.remove("Indy::RevocationRegistry", row.name)
                await txn.insert("revocation_reg", row.name, value=row.value)
                progress.update()
            await txn.commit()
        progress.report()

    async def update_rev_reg_info(self, store: Store):
        progress = Progress(
            "Updating stored revocation registry info...", interval=self.batch_size
        )
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(
                txn,
                "Indy::RevocationRegistryInfo",
            ):
                await txn.remove("Indy::RevocationRegistryInfo", row.name)
                await txn.insert("revocation_reg_info", row.name, value=row.value)
                progress.update()
            await txn.commit()
        progress.report()

    async def update_creds(self, store: Store):
        progress = Progress("Updating stored credentials...", interval=self.batch_size)
        async with store.transaction() as txn:
            async for row in self.batched_fetch_all(txn, "Indy::Credential"):
                await txn.remove("Indy::Credential", row.name)
                cred_data = row.value_json
                tags = self._credential_tags(cred_data)
                await txn.insert("credential", row.name, value=row.value, tags=tags)
                progress.update()
            await txn.commit()
        progress.report()

    async def convert_items_to_askar(
        self,
        uri: str,
        wallet_key: str,
        profile: str = None,
    ):
        print("Opening wallet with Askar...")
        store = await Store.open(uri, pass_key=wallet_key, profile=profile)

        await self.update_keys(store)
        await self.update_master_keys(store)
        await self.update_dids(store)
        await self.update_schemas(store)
        await self.update_cred_defs(store)
        await self.update_rev_reg_defs(store)
        await self.update_rev_reg_keys(store)
        await self.update_rev_reg_states(store)
        await self.update_rev_reg_info(store)
        await self.update_creds(store)

        print("Closing wallet")
        await store.close()

    def _credential_tags(self, cred_data: dict) -> dict:
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
            "rev_reg_id": cred_data.get("rev_reg_id") or "None",
        }
        for k, attr_value in cred_data["values"].items():
            attr_name = k.replace(" ", "")
            tags[f"attr::{attr_name}::value"] = attr_value["raw"]

        return tags

    async def create_config(self, conn: DbConnection, name: str, indy_key: dict):
        pass_key = "kdf:argon2i:13:mod?salt=" + indy_key["salt"].hex()
        await conn.create_config(default_profile=name, key=pass_key)

    async def init_profile(self, wallet: Wallet, name: str, indy_key: dict) -> dict:
        profile_key = {
            "ver": "1",
            "ick": indy_key["type"],
            "ink": indy_key["name"],
            "ihk": indy_key["item_hmac"],
            "tnk": indy_key["tag_name"],
            "tvk": indy_key["tag_value"],
            "thk": indy_key["tag_hmac"],
        }

        enc_pk = self.encrypt_merged(cbor2.dumps(profile_key), indy_key["master"])
        await wallet.insert_profile(name, enc_pk)
        return profile_key

    async def retrieve_wallet_ids(self, conn):
        wallet_id_records = await conn.fetch("""SELECT wallet_id FROM metadata""")
        return [wallet_id[0] for wallet_id in wallet_id_records]

    async def delete_wallets_database(self):
        parts = urlparse(self.uri)
        sys_conn = await asyncpg.connect(
            host=parts.hostname,
            port=parts.port or 5432,
            user=parts.username,
            password=parts.password,
            database="template1",
        )
        await sys_conn.execute(f"DROP DATABASE {parts.path[1:]}")
        await sys_conn.close()
        print("Indy wallets database deleted.")

    async def determine_wallet_deletion(self):
        if self.delete_indy_wallets:
            if self.skip_confirmation:
                await self.delete_wallets_database()
            elif sys.stdout.isatty():
                response = input(
                    "Would you like to delete the original Indy wallet database? Y/N "
                )
                if response in ["Y", "y", "yes", "Yes"]:
                    await self.delete_wallets_database()
                else:
                    print("Indy wallets database not deleted.")
            else:
                print("Indy wallets database not deleted.")
        else:
            print("Indy wallets database not deleted.")

    @abstractmethod
    async def run(self):
        """Perform the upgrade."""


class DbpwStrategy(Strategy):
    """Database per wallet upgrade strategy."""

    def __init__(
        self,
        conn: Union[SqliteConnection, PgConnection],
        wallet_name: str,
        wallet_key: str,
        batch_size: int,
    ):
        super().__init__(batch_size)
        self.conn = conn
        self.wallet_name = wallet_name
        self.wallet_key = wallet_key

    async def run(self):
        """Perform the upgrade."""
        await self.conn.connect()
        wallet = self.conn.get_wallet()

        try:
            await self.conn.pre_upgrade()
            indy_key = await self.fetch_indy_key(wallet, self.wallet_key)
            await self.create_config(self.conn, self.wallet_name, indy_key)
            profile_key = await self.init_profile(wallet, self.wallet_name, indy_key)
            await self.update_items(wallet, indy_key, profile_key)
            await self.conn.finish_upgrade()
        finally:
            await self.conn.close()

        await self.convert_items_to_askar(self.conn.uri, self.wallet_key)


class MwstAsProfilesStrategy(Strategy):
    """MultiWalletSingleTable as Askar Profiles upgrade strategy."""

    def __init__(
        self,
        uri: str,
        base_wallet_name: str,
        base_wallet_key: str,
        batch_size: int,
        delete_indy_wallets: Optional[bool] = False,
        skip_confirmation: Optional[bool] = False,
    ):
        super().__init__(batch_size)
        self.uri = uri
        self.base_wallet_name = base_wallet_name
        self.base_wallet_key = base_wallet_key
        self.delete_indy_wallets = delete_indy_wallets
        self.skip_confirmation = skip_confirmation

    async def init_profile(
        self, wallet: Wallet, name: str, base_indy_key: dict, indy_key: dict
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

        enc_pk = self.encrypt_merged(cbor2.dumps(profile_key), base_indy_key["master"])
        await wallet.insert_profile(name, enc_pk)
        return profile_key

    async def migrate_one_profile(
        self,
        wallet: PgWallet,
        base_indy_key: dict,
        wallet_id: str,
        wallet_key: str,
    ):
        """Migrate one wallet."""
        indy_key = await self.fetch_indy_key(wallet, wallet_key)
        profile_key = await self.init_profile(
            wallet, wallet_id, base_indy_key, indy_key
        )
        await self.update_items(wallet, indy_key, profile_key)

    async def get_wallet_info(self, uri: str):
        store = await Store.open(
            uri, profile=self.base_wallet_name, pass_key=self.base_wallet_key
        )
        async for record in store.scan("wallet_record"):
            settings = record.value_json["settings"]
            yield (
                settings["wallet.name"],
                cast(str, record.name),
                settings["wallet.key"],
            )

    async def create_sub_config(self, conn: DbConnection, indy_key: dict):
        pass_key = "kdf:argon2i:13:mod?salt=" + indy_key["salt"].hex()
        await conn.create_config(key=pass_key)

    async def check_for_leftover_wallets(self, old_conn, migrated_wallets):
        retrieved_wallets = await self.retrieve_wallet_ids(old_conn)
        leftover_wallets = [
            wallet for wallet in retrieved_wallets if wallet not in migrated_wallets
        ]
        if len(leftover_wallets) > 0:
            print(f"The following wallets were not migrated: {leftover_wallets}")
            if self.delete_indy_wallets:
                print(
                    "Indy wallets will not be deleted because there are wallets "
                    "that were not migrated"
                )
                self.delete_indy_wallets = False

    async def run(self):
        """Perform the upgrade.

        - Source Indy Wallet is read from, values deleted as we go to reduce
          storage overhead
        - Base Wallet Store where the base wallet and it's records are migrated
        - Sub wallet Store where the sub wallets and their records are migrated

        After Base wallet is migrated, it can be finalized.

        Wallet info of subwallets read from base wallet post migration.
        """
        source = await asyncpg.connect(self.uri)
        parsed = urlparse(self.uri)

        base_conn = PgMWSTConnection(
            f"{parsed.scheme}://{parsed.netloc}/{self.base_wallet_name}"
        )
        await base_conn.connect()
        sub_conn = PgMWSTConnection(
            f"{parsed.scheme}://{parsed.netloc}/multitenant_sub_wallet"
        )
        await sub_conn.connect()

        try:
            await base_conn.pre_upgrade()
            await sub_conn.pre_upgrade()
            base_wallet = base_conn.get_wallet(source, self.base_wallet_name)

            base_indy_key: dict = await self.fetch_indy_key(
                base_wallet, self.base_wallet_key
            )
            await self.create_config(base_conn, self.base_wallet_name, base_indy_key)

            # ACA-Py expects a default profile
            default_wallet = sub_conn.get_wallet(source, "default")
            await self.create_config(sub_conn, "default", base_indy_key)
            await super().init_profile(default_wallet, "default", base_indy_key)

            await self.migrate_one_profile(
                base_wallet,
                base_indy_key,
                self.base_wallet_name,
                self.base_wallet_key,
            )
            await base_conn.finish_upgrade()
            await base_conn.close()
            await self.convert_items_to_askar(
                base_conn.uri,
                self.base_wallet_key,
            )
            # Track migrated wallets
            migrated_wallets = [self.base_wallet_name]

            wallet_ids = []
            async for wallet_name, wallet_id, wallet_key in self.get_wallet_info(
                base_conn.uri
            ):
                wallet_ids.append(wallet_id)
                wallet = sub_conn.get_wallet(source, wallet_name)
                await self.migrate_one_profile(
                    wallet, base_indy_key, wallet_id, wallet_key
                )
                migrated_wallets.append(wallet_name)
            await self.check_for_leftover_wallets(source, migrated_wallets)

            await sub_conn.finish_upgrade()
        finally:
            await source.close()
            await base_conn.close()
            await sub_conn.close()

        for wallet_id in wallet_ids:
            await self.convert_items_to_askar(
                sub_conn.uri, self.base_wallet_key, wallet_id
            )
        await self.determine_wallet_deletion()


class MwstAsStoresStrategy(Strategy):
    """MultiWalletSingleTable as separate Askar stores upgrade strategy."""

    def __init__(
        self,
        uri: str,
        wallet_keys: Dict[str, str],
        batch_size: int,
        allow_missing_wallet: Optional[bool] = False,
        delete_indy_wallets: Optional[bool] = False,
        skip_confirmation: Optional[bool] = False,
    ):
        super().__init__(batch_size)
        self.uri = uri
        self.wallet_keys = wallet_keys
        self.allow_missing_wallet = allow_missing_wallet
        self.delete_indy_wallets = delete_indy_wallets
        self.skip_confirmation = skip_confirmation

    def create_new_db_connection(self, wallet_name: str):
        parsed = urlparse(self.uri)
        new_conn_uri = f"{parsed.scheme}://{parsed.netloc}/{wallet_name}"
        return PgMWSTConnection(new_conn_uri)

    async def check_wallet_alignment(self, conn, wallet_keys):
        """Verify that the wallet names passed in align with
        the wallet names found in the database.
        """
        retrieved_wallet_keys = await self.retrieve_wallet_ids(conn)
        for wallet_id in wallet_keys.keys():
            if wallet_id not in retrieved_wallet_keys:
                raise UpgradeError(f"Wallet {wallet_id} not found in database")
        for wallet_id in retrieved_wallet_keys:
            if wallet_id not in wallet_keys.keys():
                raise MissingWalletError(
                    f"Must provide entry for {wallet_id} in wallet_keys dictionary "
                    "to migrate wallet"
                )

    async def check_missing_wallet_flag(self, conn, wallet_keys, allow_missing_wallet):
        if allow_missing_wallet:
            try:
                await self.check_wallet_alignment(conn, wallet_keys)
            except MissingWalletError:
                print("Running upgrade without migrating all wallets")
                # Remaining wallets will not be deleted
                self.delete_indy_wallets = False
        else:
            await self.check_wallet_alignment(conn, wallet_keys)

    async def run(self):
        """Perform the upgrade."""

        # Connect to original database
        source = await asyncpg.connect(self.uri)
        await self.check_missing_wallet_flag(
            source, self.wallet_keys, self.allow_missing_wallet
        )

        for wallet_name, wallet_key in self.wallet_keys.items():

            # Connect to new database
            new_db_conn: PgMWSTConnection = self.create_new_db_connection(wallet_name)
            await new_db_conn.connect()

            wallet = new_db_conn.get_wallet(source, wallet_name)
            try:
                await new_db_conn.pre_upgrade()
                indy_key = await self.fetch_indy_key(wallet, wallet_key)
                await self.create_config(new_db_conn, wallet_name, indy_key)
                profile_key = await self.init_profile(wallet, wallet_name, indy_key)
                await self.update_items(wallet, indy_key, profile_key)
                await new_db_conn.finish_upgrade()
            except UpgradeError as err:
                raise UpgradeError(
                    f"Failed to upgrade wallet {wallet_name}; bad wallet key given?"
                ) from err
            finally:
                await new_db_conn.close()

            await self.convert_items_to_askar(new_db_conn.uri, wallet_key)

        await source.close()
        await self.determine_wallet_deletion()
