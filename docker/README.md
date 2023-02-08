# Running Migration Script From Docker Container
From root of project
```
docker build --tag wallet_upgrade --file docker/Dockerfile .
```
Then start container with interactive command line
```
docker run -it wallet_upgrade:latest
```

For sqlite database, share a volume with the container.
For postgresql database bridge network to container.