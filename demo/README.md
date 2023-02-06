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
docker-compose up -d alice bob
```
The docker-compose.yml also contains a service called juggernaut for running propagation scripts.
#### Run propagation service
```
docker-compose run juggernaut
``` 
After the migration script has finished you can examine the admin api of alice to demonstrate contents of the indy wallet.
### Migrate

#### Stop agents

```
docker-compose down
```

### Modify docker-compose to use Askar

### Run agents

### Conclusion
Summarize the key takeaways from the demo and provide any additional resources or support that may be available.


