
# End-to-End Testing
End-to-end (E2E) testing is performed to validate the entire system, from start to finish. The goal of E2E testing is to ensure that the system behaves as expected in a real-world scenario.
## Running the Tests
The following command will run all E2E tests:
```
poetry run pytest -m e2e
```
You can also specify a test case to run by using the -k flag:

```
poetry run pytest -m e2e -k pg
```

## Architecture
The Containers class in containers.py is used to create and manage [aries-cloudagent-python](https://github.com/hyperledger/aries-cloudagent-python) docker containers. The class provides methods to create docker agents and encapsulates the logic for doing so.

The E2E module uses the Containers class to implement the WalletTypeToBeTested class, which contains fixtures that start and stop/takedown the agent containers. The WalletTypeToBeTested class is extended by each test scenario, which consumes the fixtures.

Migration can be performed on sqlite and postgresql wallets. Each scenario is tested by creating a separate class for each wallet type. The classes for each wallet type scenario can be found in separate files starting with "test_" followed by the scenario name. For example, test_sqlite.py contains the test class TestSqliteDBPW, which prepares agents to run the MigrationTestCases test cases.

The MigrationTestCases class contains a list of asynchronous generator test cases. Each scenario calls the pre and post methods, passing in an issuer and holder agent controller, with a yield. Each test case has two code blocks defined by the yield, the first part executed before the scenario executes wallet migration, and the second after migration. Each case contains asserts to check the expected wallet state.


## Adding Scenarios
To add a new scenario for a wallet type migration, follow these steps:

1. Create a new file following the current practice, `test_<scenario>.py`.
2. Define a new class that extends `WalletTypeToBeTested`.
3. Using fixtures, prepare two agents to be tested.
4. Run the first part of the test cases with `MigrationTestCases().pre(<controller>,<controller>)`.
5. Shut down the agents.
6. Migrate the wallet using the main method from the migration script module.
7. Prepare two agents using the newly migrated wallets.
8. Run the second part of the test cases with `MigrationTestCases().pre(<controller>,<controller>)`.

## Adding test cases
The list of test cases that are executed lives in the `init` method for the `MigrationTestCases` class in `cases.py`. To add a new test case, follow these steps:

1. Create a new method for the test case in the `MigrationTestCases` class.
2. Call the yield to get controllers to two agents, for example `issuer, holder = yield`.
3. Set up the pre-migration state.
4. Call the yield again to get controllers to migrated agents.
5. Set up the post-migration state.
6. Assert the wallet state.