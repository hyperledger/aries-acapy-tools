# End-to-End Testing

- Docker python library for starting services
- Reuse populate_db script
- Different tests for different chunks of functionality
- Maybe we need to to tests for different wallet types

## Idea: Fixture setup

- Migrate Fixture - Session scoped, does the actual migration, autouse?
  - Depends on:
    - Connections
    - Issued revocable credential
    - Cred def with revocation support
    - Public DID
- Tests depend on one of those fixtures which encapsulate values that should
  continue to be usable after migration
