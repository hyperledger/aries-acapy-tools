# Demo Instruction Guide
## Introduction
This demo directory contains docker-compose configuration and instructions to create an ACA-Py Indy wallet, migrate that Indy wallet to an Askar wallet, and restart ACA-Py using the migrated Askar wallet.

## Preparation
This demo assumes that you are familiar with ACA-Py and have docker and poetry installed.

## Step-by-Step Instructions
### Populate DB:
The `docker-compose.yml` contains two services that will start an issuer agent (Alice) and a holder agent (Bob). Alice and Bob are configured to use an Indy PostgreSQL wallet. We will run a script that will propagate Alice and Bob's wallets with their connections and credentials.

#### Start Alice and Bob
```
cd demo
docker-compose up -d alice bob
```
#### Run propagation service
The `docker-compose.yml` also contains a service called juggernaut for running propagation scripts.
```
docker-compose run juggernaut
``` 
You can examine the Admin APIs of [Alice](http://localhost:3001) and [Bob](http://localhost:3002) to demonstrate contents of the Indy wallet before migration.

#### Stop agents
The ACA-Py agents using the database must be stopped before the migration is performed.
```
docker-compose stop alice bob
```
#### Migrate the wallets
```
askar-upgrade --strategy dbpw --uri postgres://postgres:mysecretpassword@localhost:5432/alice --wallet-name alice --wallet-key alice_insecure0

askar-upgrade --strategy dbpw --uri postgres://postgres:mysecretpassword@localhost:5432/bob --wallet-name bob --wallet-key bob_insecure0
```
#### Run agents using Askar wallet configuration
Now that Alice and Bob's wallets have been migrated, we need to update the `wallet-type` in the ACA-Py config. Out of convenience, the demo directory contains an updated docker-compose file called `docker-compose-askar.yml`.
```
docker-compose -f docker-compose-askar.yml up -d alice bob
```
Post migration, you can examine the Admin APIs of [Alice](http://localhost:3001) and [Bob](http://localhost:3002) to demonstrate contents of the Askar wallet.
### Clean up
```
docker-compose down
```


