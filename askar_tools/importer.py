import json

from aries_askar import Store

from .sqlite_connection import SqliteConnection


class Importer:
    def __init__(
        self,
        conn: SqliteConnection,
        wallet_name: str,
        wallet_key: str,
        store_key_method: str = None,
    ):
        self.conn = conn
        self.wallet_name = wallet_name
        self.wallet_key = wallet_key
        self.store_key_method = store_key_method

    async def importer(self):
        print("Importing wallet...")
        store = await Store.provision(
            self.conn.uri, self.store_key_method, self.wallet_key
        )

        store_json = None
        with open("import", "r") as import_file:
            output = import_file.read()
            store_json = json.loads(output)

        print(store_json["config"])

        provisioned_profile = await store.get_default_profile()
        print(f"Provisioned profile: {provisioned_profile}")
        print(json.loads(store_json["config"]))
        existing_profile = None
        for config in json.loads(store_json["config"]):
            config = json.loads(config)
            print(config["default_profile"])
            if config["default_profile"]:
                existing_profile = config["default_profile"]
                break
        print(f"Default profile: {existing_profile}")
        profile = await store.create_profile(existing_profile)
        await store.set_default_profile(existing_profile)
        # await store.remove_profile(provisioned_profile)

        store = await store.open(
            uri=self.conn.uri,
            key_method=self.store_key_method,
            pass_key=self.wallet_key,
            profile=existing_profile,
        )

        async with store.transaction(profile=profile) as txn:
            for category in store_json["items"]:
                print(f"Importing category: {category}")
                for entry in store_json["items"][category]:
                    entry = json.loads(entry)
                    print(f"Importing entry: {entry}")
                    value = entry["value"]
                    if isinstance(value, str):
                        value = value.encode("utf-8")
                        await txn.insert(
                            category=category,
                            name=entry["name"],
                            value=value,
                            tags=entry["tags"],
                        )
                    else:
                        await txn.insert(
                            category=category,
                            name=entry["name"],
                            value_json=value,
                            tags=entry["tags"],
                        )

            await txn.commit()
