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
    --base-wallet-name <base wallet name> \
    --base-wallet-key <base wallet key>
    ```

### Multitenant Wallet - Switch from single wallet to multi wallet:

##### Prerequisites:
    Backup sub-wallet. This operation will delete the sub-wallet when finished. If the wallet is broken for some reason you will not be able to recover it without a backup.

 * Converts the profiles in the sub-wallet to individual wallets and databases.
 * After completion, the sub-wallet will be deleted and the deployment should no longer use the `--multitenancy-config '{"wallet_type": "single-wallet-askar"}'` configuration.

- `export` (Output the contents of a wallet to a json file):

    ```
    poetry run askar-tools \ 
    --strategy mt-convert-to-mw  \ 
    --uri postgres://<username>:<password>@<hostname>:<port>/<dbname> \ 
    --wallet-name <base wallet name> \
    --wallet-key <base wallet key> \ 
    --multitenant-sub-wallet-name <optional: custom sub wallet name>
    ```