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