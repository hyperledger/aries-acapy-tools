From root of project
```
docker build --tag wallet_upgrade --file docker/Dockerfile .
```
then interactive command line
```
docker run -it wallet_upgrade:latest
```

For sqlite share a volume with container.
For postgresql database bridge network to container.