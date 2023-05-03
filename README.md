# Migration Script

The purpose of this script is to migrate ACA-Py Indy SDK format storage data into the Aries Askar format. This transition from Indy-SDK to Askar for storage is part of the larger project to eliminate the Indy-SDK in favor of shared components.


## Prerequisites

* Upgrade PostgreSQL wallet database to >= PostgreSQL 11
* Backup data (there are destructive actions in the migration script)
* Upgrade Python version to >= v3.10

## Install

```
poetry install
poetry shell
```

## Step-by-step ACA-Py Wallet Migration Guide

### 0. Stop any agents using the wallet:
Before starting the migration process, make sure to stop any agents or applications that are currently using the wallet to avoid database access conflicts.

### 1. Backup your current wallet:

It is important to create a backup of your current wallet before starting the migration process, in case anything goes wrong. Exact instructions for a full backup and how to restore it are outside of the scope of this guide.

If using sqlite, copy the indy wallet from `/home/<user>/.indy_client/wallet/<wallet name>` to a temporary location you can run the migration script from. After running migration script you will need to copy the resulting db into an Askar-specific location.

Migrating a postgresql database will require backup but will not require any file relocation, as is the case for sqlite wallets.

Both sqlite and postgresql migration will require updating ACA-Py startup config, which this guide will explain.

### 2. Prepare configuration:

**DATA LOSS CAN OCCUR IF YOU ARE NOT CAREFUL. THIS PROCESS IS DELIBERATELY DESTRUCTIVE. BACKUP YOUR DATABASE BEFORE PROCEEDING.**

The migration script supports migration from Indy SQLite to Askar SQLite or from Indy PostgreSQL to Askar PostgreSQL. Determine which database and [storage plugin](https://github.com/hyperledger/indy-sdk/tree/main/experimental/plugins/postgres_storage#wallet-management-modes) you are using and gather the necessary information for your scenario.

Wallet migration strategies include `dbpw`, `mwst-as-profiles`, `mwst-as-stores`. The postgres `dbpw` is the default `wallet_scheme` for Indy when using postgres storage plugin. Postgres `MWST` wallet scheme serves both `MultiWalletSingleTable` and `MultiWalletSingleTableSharedPool` indy postgres wallet schemes.

If you are using your `MultiWalletSingleTable` database for Multi-tenancy, it is recommended to use `mwst-as-profiles`. If you are using your `MultiWalletSingleTable` database for multiple ACA-Py instances but NOT Multi-tenancy, it is recommended to use `mwst-as-stores`. Here are examples of different strategies with minimum configuration. For `mwst-as-stores` strategy you will need to provide a json file that includes the wallet_name, keyed to wallet_key. For example: `{<wallet_name>:<wallet_key>,...}`.

- `dbpw`(Indy SQLite -> Askar SQLite):
    ```
    askar-upgrade \
    --strategy dbpw \
    --uri sqlite://<path to sqlite db> \
    --wallet-name <wallet name> \
    --wallet-key <wallet key>
    ```

- `dbpw`(Indy PostgreSQL single wallet per data store -> Askar PostgreSQL single wallet per data store):
    ```
    askar-upgrade \
    --strategy dbpw \
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --wallet-name <wallet name> \
    --wallet-key <wallet key>
    ```

- `mwst-as-profiles` (Indy PostgreSQL multiple wallets in a single table + multi-tenancy -> Askar PostgreSQL single store, one wallet per profile):
    ```
    askar-upgrade \
    --strategy mwst-as-profiles \
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --base-wallet-name <base wallet name> \
    --base-wallet-key <base wallet key>
    ```

- `mwst-as-stores`(Indy PostgreSQL multiple wallets in a single table -> Askar PostgreSQL multiple stores, one wallet per data store):
    ```
    askar-upgrade \
    --strategy mwst-as-stores \
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --wallet-keys <path to json file with wallet keys>
    ```

#### Multiple Wallet Edge Cases
To delete wallets that you did not migrate, include delete indy wallets flag.
```
--delete-indy-wallets
```
* Note: Items are deleted during the migration process, but the database itself is not deleted until after migration if this flag is specified.


If you are using the `mwst-as-stores` strategy and have wallets you do not want to migrate, you can do so by excluding them from the wallet keys file and including the allow missing wallet flag.

```
--allow-missing-wallet
```


* Note: If you are using the `mwst-as-stores` strategy, have included both the `--allow-missing-wallet` and `--delete-indy-wallets` flags, and there are wallets that you are not migrating, the `--delete-indy-wallets` flag will be overwritten so that no databases will be deleted.

There is a confirmation before database gets deleted. You can opt out of that confirmation by including skip conformation flag.

```
--skip-confirmation
```

### 3. Execute the migration with configuration:

Run the command you constructed in the previous step. Make sure you have followed the instructions carefully and double-check your inputs before starting the migration process, as it is a one-way process.

**DATA LOSS CAN OCCUR IF YOU ARE NOT CAREFUL. THIS PROCESS IS DELIBERATELY DESTRUCTIVE. BACKUP YOUR DATABASE BEFORE PROCEEDING.**

Example:

```
askar-upgrade --strategy dbpw --uri sqlite://<path to sqlite db> --wallet-name <wallet name> --wallet-key <wallet key>
```

### 4. Update ACA-Py Configuration:

ACA-Py startup configuration will need to be updated to reflect an Askar wallet type.

- `dbpw` (Indy SQLite -> Askar SQLite):
Copy the migrated db into `/home/<user>/.aries_cloudagent/wallet/<wallet name>`.
  ```
  --wallet-type askar
  ```

- `dbpw` (Indy PostgreSQL single wallet per data store -> Askar PostgreSQL single wallet per data store):
  ```
  --wallet-type askar
  ```

- `mwst-as-profiles` (Indy PostgreSQL multiple wallets in a single table + multi-tenancy -> Askar PostgreSQL single store, one wallet per profile):
  ```
  --wallet-type askar
  --multitenancy-config wallet_type=askar-profile
  ```
  You can remove the `wallet_scheme` portion of the `--wallet-storage-config` argument.

- `mwst-as-stores` (Indy PostgreSQL multiple wallets in a single table -> Askar PostgreSQL multiple stores, one wallet per data store):
  ```
  --wallet-type askar
  ```

## Migration Considerations

There are several considerations for determining the migration strategy for a given database: database type, wallet management mode, and agent type.

### Database Types
* SQLite
* PostreSQL

### Wallet Management Modes
For a PostgreSQL database, the Indy-SDK has multiple wallet management modes to take into account when determining migration strategy. The [Indy-SDK documentation](https://github.com/hyperledger/indy-sdk/tree/main/experimental/plugins/postgres_storage#wallet-management-modes) describes the follow modes:
* `DatabasePerWallet` - each wallet has its own database
* `MultiWalletSingleTable` - all wallets are stored in single table in single database

The third wallet management mode, `MultiWalletSingleTableSharedPool`, functions the same as the `MultiWalletSingleTable` mode for the purposes of this migration, so the two use the same strategy.

For a SQLite database, the only management mode available is `DatabasePerWallet`. Both SQLite databases and PostgreSQL databases that use the `DatabasePerWallet` mode are migrated via the `Dbpw` migration strategy described [below](#databaseperwallet).

### Agent Type

For a PostgreSQL database that uses the `MultiWalletSingleTable` management mode, there are two migration options depending on the type of agent used: standard or multi-tenanted.

#### Standard

A standard agent refers to an agent that is not multi-tenanted and is un-managed (i.e. there is no hierarchy in which a base wallet holds key to its subwallets). In this case, each wallet in the `MultiWalletSingleTable` setup is translated into a separate Askar store and the unique wallet keys are preserved for each wallet, as shown in the [diagram](#mwst-as-stores-key-diagram). This is optimal for separate users who must only be able ot access their own wallets but want to share resources. The database of a standard agent that uses the `MultiWalletSingleTable` mode is migrated using the `MwstAsStores` strategy described [below](#mwst-as-stores).

##### MWST as stores key diagram
![MWST as stores](mwst-as-stores.png)

#### Multi-tenanted Agent
For a multi-tenanted agent that uses the `MultiWalletSingleTable` management mode in Indy-SDK, each row in the metadata table corresponds to a subwallet. Each row in the items table has a `wallet_id` identifying which items correspond to which wallet. Each row in the metadata table has a key encrypted using a wallet key, the key derived from the passphrase used to open the wallet.

* Note: While the `DatabasePerWallet` mode is possible for a multi-tenanted agent, this setup is inefficient since a new database is created for every subwallet of the multi-tenanted agent and therefore not recommended. For this reason, this migration script does not support migrating a database that uses the `DatabasePerWallet` mode with multi-tenancy.

Multi-tenancy in ACA-Py when using Askar has different characteristics. Askar does not have a wallet scheme that exactly matches the `MultiWalletSingleTable` mode with multi-tenanted agents in Indy-SDK. The simple multi-tenancy case for Askar more closely resembles the `DatabasePerWallet` setup of the Indy SDK.

Askar supports the concept of profiles where each profile represents a different user. This mode of operation strictly follows a "managed" wallet style in which the owner of the ACA-Py instance can decrypt and use every Askar Profile contained in its Askar Store. The strategy to migrate such a database will translate the `MultiWalletSingleTable` setup into Askar Profiles, where each wallet corresponds to a row in the profiles table. Since this strategy is intended only for the wallets that were subwallets in a multi-tenanted agent, it does not preserve the unique keys for each wallet in the Indy-SDK setup, as shown in the [diagram](#mwst-as-profiles-key-diagram). Instead, the store key for all Askar profiles is derived from the wallet key of the base wallet in Indy-SDK. The database of a multi-tenanted agent that uses the `MultiWalletSingleTable` mode is migrated using the `MwstAsProfiles` strategy described [below](#mwst-as-profiles).

After migration using the `mwst-as-profiles` strategy, the base wallet will be in one database and the subwallets will be in another database. Both databases have the same store key. This reflects the setup that would have been created if the wallets had originated in an Askar database using the multi-tenancy with the Askar profile manager.

##### MWST as profiles key diagram
![MWST as profiles](mwst-as-profiles.png)


## Migration Strategies

### DatabasePerWallet

This strategy implements migration for both SQLite and PostgreSQL database that use the `DatabasePerWallet` management mode.

#### Parameters
* `strategy` - migration strategy (str)
    * Must be `"dbpw"`
* `uri` - URI for the database to be migrated (str)
    * SQLite example: `f"sqlite://{sqlite_alice}"`
    * PostgreSQL example: `f"postgres://{user_name}:{db_user_password}@{db_host}:{db_port}/{db_name}"`
* `wallet_name` - name of the wallet (str)
    * Example: `"alice"`
* `wallet_key` - key corresponding to the wallet (str)
    * Example: `"insecure"`
* [`batch_size`](#batch-size) - number of items to process in each batch (int)


### MWST as Stores
This strategy implements migration for a PostgreSQL database that uses the `MultiWalletSingleTable` management mode for a standard agent.

#### Parameters
* `strategy` - migration strategy (str)
    * Must be `"mwst-as-stores"`
* `uri` - URI for the database to be migrated (str)
    * Example: `f"postgres://{user_name}:{db_user_password}@{db_host}:{db_port}/{db_name}"`
* `wallet_keys` - mapping from wallet name to wallet key for each wallet in the database to be migrated (dict)
    * Example:
```
            {
                "alice": "alice_insecure1",
                "bob": "bob_insecure1",
            }
```
* [`batch_size`](#batch-size) - number of items to process in each batch (int)
* `allow_missing_wallet` - flag to allow wallets in database to not be migrated (bool)
    * There is a check to ensure that the wallet names passed into the migration script align with the wallet names retrieved from the database to be migrated. If a wallet name is passed in that does not correspond to an existing wallet in the database, an `UpgradeError` is raised. If a wallet name that corresponds to an existing wallet in the database is not passed into the script to be migrated, a `MissingWalletError` is raised. If the user wishes to migrate some, but not all, of the wallets in a `MultiWalletSingleTable` database, they can bypass the `MissingWalletError` by setting the `--allow-missing-wallet` argument as `True`.
* `delete_indy_wallets` - option to delete Indy wallets post-migration
* `skip_confirmation` - option to skip confirmation before deleting Indy wallets post-migration



### MWST as Profiles

This strategy implements migration for a PostgreSQL database that uses the `MultiWalletSingleTable` management mode with multi-tenanted agents. The name of the base wallet must be specified because the wallet key of the base wallet becomes the Askar store key for all profiles in the Askar database after migration.

#### Parameters

* `strategy` - migration strategy (str)
    * Must be `"mwst-as-profiles"`
* `uri` - URI for the database to be migrated (str)
    * Example: `f"postgres://{user_name}:{db_user_password}@{db_host}:{db_port}/{db_name}"`
* `base_wallet_name` - name of the base wallet (str)
    * Example: `"agency"`
* `base_wallet_key` - key corresponding to the base wallet (str)
* [`batch_size`](#batch-size) - number of items to process in each batch (int)
* `delete_indy_wallets` - option to delete Indy wallets post-migration
* `skip_confirmation` - option to skip confirmation before deleting Indy wallets post-migration

### Batch size
This parameter refers to the number of items that will be processed in each batch. For our lightly used database, in which the average record was approximately 3 kB and the largest record was approximately 60 kB, we set the default to 50 and process from 70 to 150 kB per batch. However, record sizes will be highly variable between databases. We recommend analyzing the size of the items in your particular database and tuning this value accordingly.

## Developer automated testing

### Intermediate testing

#### Generate database for each migration strategy:
```
cd tests/intermediate/input
make sqlite
make dbpw
make mt-mwst
make mwst
make mt-mwst-leftover-wallet
```

#### Run tests
```
cd ..
pytest
```

## Running Migration Script From Docker Container
From root of project
```
docker build --tag wallet_upgrade --file Dockerfile .
```
Then start container with interactive command line
```
docker run -it wallet_upgrade:latest
```

For sqlite database, share a volume with the container.
For postgresql database bridge network to container.
