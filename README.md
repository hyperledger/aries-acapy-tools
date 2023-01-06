# Migration Script

## Install
```
python -m venv env
source env/bin/activate
pip install -e .
askar-upgrade.py ...
```

## How to use

`sqlite:`
> askar-upgrade <path-to-sqlite-db> '<database-master-password>'


`pgsql:`
> cd acapy_wallet_upgrade
> askar-upgrade postgres://<username>:<password>@<hostname>:<port>/<dbname> '<database-master-password>'
