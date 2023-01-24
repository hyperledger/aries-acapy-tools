# Migration Script

## Prerequisites

* Upgrade PostgreSQL wallet database to >= PostgreSQL 11
* Backup data (there are destructive actions in the migration script)
* python version >= v3.9

## Install

```
poetry install
poetry shell
```

## Run

`SQLite:`
```
askar-upgrade <path-to-sqlite-db> '<database-master-password>'
```

`PostgreSQL:`
```
askar-upgrade postgres://<username>:<password>@<hostname>:<port>/<dbname> '<database-master-password>'
```

## Developer automated testing
- generate sqlite and postgres db's
```
make sqlite
make dbpw
make mwst
```
- run tests
```
cd tests
pytest
```
## Migration Strategy
- Create Askar tables
- Move current tables to temporary tables
- Fill the Askar tables from the temporary tables
- Remove the temporary tables

## Roadmap


- [x] Support SQLite
- [x] Support PostgreSQL
- [ ] Support different wallet management modes
- [ ] Create automated testing

## trouble shooting
- mac m1 nacl issue.
    - https://github.com/pyca/pynacl/issues/654#issuecomment-901266575

## MultiWalletSingleTable and Multi-tenancy

Multi-tenancy in ACA-Py when using the Indy SDK impacts the database in
different ways dependning on the wallet scheme:

- DatabasePerWallet - A new database is created for every sub wallet. This is
  really inefficient and probably not commonly used and probably not
  intentional when it is used.
- MultiWalletSingleTable - A new row in the metadata table is created for every
  sub wallet and each row in the items table will have a wallet_id identifying
  which items are relevant to which wallet. Each row in the metadata table has
  a key encrypted using a "master key" or the key derived from the passphrase
  used to open the walet.

Multi-tenancy in ACA-Py when using Askar has different characteristics. Askar
does not have a wallet scheme that exactly matches MultiWalletSingleTable and
the simple multi-tenancy case for Askar more closely resembles the
DatabasePerWallet setup of the Indy SDK.

However, Askar supports the concept of profiles where each profile can
represent a different user. This mode of operation strictly follows a "managed"
wallet style -- the owner of the ACA-Py instance can decrypt and use every
Askar Profile contained in it's Askar Store.

The migration script should provide the following options:

- `--mwst-as-profiles` - This will translate the MultiWalletSingleTable setup
  into Askar Profiles. This is appropriate only when the wallets were sub wallets
  in a multi-tenanted agent.
  - Additional options should be required when this flag is used:
    - `--profile-store-name` - name of Askar store where profiles will be stored. Defaults to `multitenant_sub_wallet`.
    - `--wallet-keys` - a path to a json file containing a mapping from wallet name to wallet key for each sub wallet.
    - `--base-wallet-name` - the name of the base wallet.
    - `--base-wallet-key` - the master key of the base wallet; this will be the key of the `multitenant_sub_wallet` store.
- `--mwst-as-separate-stores` - This will translate the MultiWalletSingleTable
  setup into separate Askare stores. This will preserve the unique master keys
  for each wallet (something that is lost if `--mwst-as-profiles` is used).
  - Additional options should be required when this flag is used:
    - `--wallet-keys` - a path to a json file containing a mapping from wallet name to wallet key for each wallet in the database.
