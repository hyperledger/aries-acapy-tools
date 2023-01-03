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
> python ./bin/askar-upgrade.py <path-to-sqlite-db> '<database-master-password>'


`pgsql:`
> python ./bin/askar-upgrade.py postgres://<username>:<password>@<hostname>:<port>/<dbname> '<database-master-password>'
