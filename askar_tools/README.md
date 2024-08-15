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