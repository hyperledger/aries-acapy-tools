# Tools: This repo contains a collection of tools for interacting with an Aries Cloud Agent Python (ACAPy) askar wallets.

## Prerequisites:

* Wallet(s) must be of type askar.

## Install

```
poetry install
```

### Export Wallet:

 * Exports a wallet into a file with a readable json format. This can be useful for debugging or for sharing wallet information with others.
 * Currently the private keys are not decrypted and are excluded from the exported file.

- `export` (Output the contents of a wallet to a json file):

    ```
    poetry run askar-tools \
    --strategy export \
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --wallet-name <base wallet name> \
    --wallet-key <base wallet key> \
    --wallet-key-derivation-method <optional> \
    --export-filename <optional>
    ```

### Multi-tenant Wallet - Switch from single wallet to multi wallet:

##### Prerequisites:
    Backup sub-wallet. This operation will delete the sub-wallet when finished. If the wallet is broken for some reason you will not be able to recover it without a backup.

 * Converts the profiles in the sub-wallet to individual wallets and databases.
 * Each converted wallet is verified against its sub-wallet profile (expected single profile, record counts per category, and key counts) before it is counted as done.
 * The sub-wallet is only deleted when every tenant wallet has been converted and verified. If any tenant fails, the sub-wallet is kept and the process exits non-zero. A per-tenant summary (converted / skipped / redone / failed, timings, and whether the sub-wallet was deleted) is printed at the end of every run.
 * The operation is safe to re-run after a failure: tenant databases that already exist and verify are skipped, and a tenant database that exists but fails verification (for example a partial copy from an interrupted run) is dropped and converted again. Completed tenants are never re-copied and never destroyed by a re-run.
 * After completion, the sub-wallet will be deleted and the deployment should no longer use the `--multitenancy-config '{"wallet_type": "single-wallet-askar"}'` configuration.

- `mt-convert-to-mw` (Convert from single wallet to multi-wallet multi-tenant agent):

    ```
    poetry run askar-tools \ 
    --strategy mt-convert-to-mw  \ 
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \ 
    --wallet-name <base wallet name> \
    --wallet-key <base wallet key> \ 
    --wallet-key-derivation-method <optional> \
    --multitenant-sub-wallet-name <optional: custom sub wallet name>
    ```

### Import Wallet:

- Imports a wallet from a database location into a multi-tenant multi-wallet admin and database location.
- **Important:** Existing connections to the imported agent won't work without a proxy server routing the requests to the correct agent. This is because any external agents will still only know the old endpoint.
- The database will not be deleted from the source location.
- `tenant-import` (Import a wallet into a multi-wallet multi-tenant agent):

    ```
    poetry run askar-tools \
    --strategy tenant-import \
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --wallet-name <base wallet name> \
    --wallet-key <base wallet key> \
    --wallet-key-derivation-method <optional> \
    --tenant-uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --tenant-wallet-name <tenant wallet name> \
    --tenant-wallet-key <tenant wallet key> \
    --tenant-wallet-key-derivation-method <optional> \
    --tenant-wallet-type <optional: default is askar> \
    --tenant-label <optional: default is None> \
    --tenant-image-url <optional: default is None> \
    --tenant-webhook-urls <optional: default is None> \
    --tenant-extra-settings <optional: default is None> \
    --tenant-dispatch-type <optional: default is None>
    ```
    
### Convert from acapy mediator to credo mediator:

 * Converts an acapy mediator records to a credo mediator records.
 * The acapy mediator wallet records will be deleted after the conversion.
 * The credo mediator wallet will be created in the same database as the acapy mediator wallet.
 * Only the default derivation method is supported.
- `mediator-convert` (Convert from acapy mediator to credo mediator):

     ```
    poetry run askar-tools \
    --strategy mediator-convert \
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --wallet-name <base wallet name> \
    --wallet-key <base wallet key> 
    ```

### Credo Mediator Clean Up:

 * This tool is designed to run as a cron job to clean up old records from the credo mediator wallet.
 * The tool will delete records that are older than the specified number of days.
 * The tool will run indefinitely until it is stopped.
 * The tool will wait until the specified start time before starting the first cleanup.
- `mediator-cleanup` (Clean up old records from the credo mediator wallet):
    ```
    poetry run askar-tools \
    --strategy mediator-cleanup \
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --pickup-repository-uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \
    --wallet-name <base wallet name> \
    --wallet-key <base wallet key> \
    --inactive-days-threshold <number of days after which a connection is considered inactive> \
    --cron-job-start-time <optional: start time for the cron job in ISO format, default is now> \
    --cron-job-interval-days <optional: number of days between each cleanup, default is 7>
    
    ```

### Anoncreds Repair:

 * Repairs wallet data by validating revocation registry definitions and credential definitions against their corresponding private records.
 * Removes orphaned records that lack matching private keys, which can occur due to incomplete transactions or corruption.
 * Processes all profiles in a multi-tenant single wallet configuration.
 * **Important:** Backup your wallet before running this operation. Records are permanently deleted and cannot be recovered without a backup.

- `anoncreds-repair` (Repair wallet revocation registry and credential definition records):

    ```
    poetry run askar-tools \
    --strategy anoncreds-repair \
    --uri sqlite:///<path-to-wallet-db> \
    --wallet-name <base wallet name> \
    --wallet-key <base wallet key> \
    --wallet-key-derivation-method <optional: default is ARGON2I_MOD>
    ```

    **What it does:**
    - Iterates through all profiles in the wallet
    - For each profile, verifies revocation registry definitions have corresponding private records
    - For each profile, verifies credential definitions have both private records and key proof records
    - Deletes revocation registry definition records and associated issuer records if private records are missing
    - Deletes credential definition records and associated records if private or key proof records are missing
    - Commits changes after processing all records in each profile

