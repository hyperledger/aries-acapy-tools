# Migration Script

## Prerequisites

* Upgrade PostgreSQL wallet database to >= PostgreSQL 11
* Backup data (there are destructive actions in the migration script)

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
