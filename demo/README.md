# Demo Instruction Guide
## Introduction
This demo directory contains docker-compose configuration and instructions to create a ACA-Py indy wallet, migrate that indy wallet to aries wallet, and restart ACA-Py using the migrated wallet.

## Preparation
This demo assumes you are familiar with ACA-Py and have docker and poetry installed

## Step-by-Step Instructions
### Populate DB:
The docker-compose.yml contains two services that will start a Issuer agent alice and holder agent bob. alice and bob are configured to use an indy postgresql wallet. We will run a script that will propagate alice and bobs wallets with connections and credentials. Providing a indy wallet to demonstrate migration on.
#### Start alice and bob
```
cd demo
docker-compose up -d alice bob
```
The docker-compose.yml also contains a service called juggernaut for running propagation scripts.
#### Run propagation service
```
docker-compose run juggernaut
``` 
Before the migration script has finished you can examine the [admin api](http://localhost:3001) of alice and [admin api](http://localhost:3002) of bob to demonstrate contents of the indy wallet.

Before migration we need to stop any ACA-Py agents that are using the database
#### Stop agents
```
docker-compose stop alice bob
```
With the agents stopped we can execute the migration script.
#### Migrate
```
askar-upgrade --strategy dbpw --uri postgres://postgres:mysecretpassword@localhost:5432/alice --wallet-name alice --wallet-key alice_insecure0
askar-upgrade --strategy dbpw --uri postgres://postgres:mysecretpassword@localhost:5432/bob --wallet-name bob --wallet-key bob_insecure0
```
Now that alice and bob wallets have been migrated, we need to update the wallet type in aca-py config. Out of convenience the demo directory contains an updated docker-compose file called `docker-compose-askar.yml`. 
#### Run agents using Askar wallet configuration
```
docker-compose -f docker-compose-askar.yml up -d alice bob
```
Now that migration script has finished you can examine the [admin api](http://localhost:3001/api) of alice and [admin api](http://localhost:3002/api) of bob to demonstrate contents of the askar wallet.
### End the demo
```
docker-compose down
```


