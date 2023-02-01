import os
from pathlib import Path
import time
from typing import Optional, cast

import docker
from docker.errors import NotFound
from docker.models.containers import Container
from docker.models.networks import Network


class Containers:
    """Manager for containers needed for testing."""

    NETWORK_NAME = "migration-testing"
    TAILS_NAME = "tails"
    TAILS_IMAGE = "ghcr.io/bcgov/tails-server:latest"
    FIX_PERMISSIONS_IMAGE = "alpine:3.17.1"
    POSTGRES_IMAGE = "postgres:11"
    POSTGRES_USER = "postgres"
    POSTGRES_PASSWORD = "mysecretpassword"
    ACAPY_IMAGE = "docker.io/bcgovimages/aries-cloudagent:py36-1.16-1_1.0.0-rc1"
    GENESIS_URL = "https://raw.githubusercontent.com/Indicio-tech/indicio-network/main/genesis_files/pool_transactions_testnet_genesis"

    def __init__(self, client: docker.DockerClient):
        self.client = client
        self._network: Optional[Network] = None
        self.containers = []

    @property
    def network(self):
        """Get network if set."""
        if self._network is None:
            nets = self.client.networks.list(names=[self.NETWORK_NAME])
            if not nets or len(nets) > 1:
                raise ValueError("Network not initialized or could not be identified")
            self._network = cast(Network, nets[0])
        return self._network

    def setup(self):
        """Setup prereqs for containers (network)."""
        self._network = cast(
            Network, self.client.networks.create(self.NETWORK_NAME, driver="bridge")
        )
        return self

    def teardown(self):
        """Stop and remove containers."""
        errors = []
        for container in self.containers:
            try:
                container.stop()
            except NotFound:
                pass
            except Exception as e:
                errors.append(e)
        self.network.remove()

        if errors:
            raise Exception("Errors during teardown: {}".format(errors))

    def fix_permissions(
        self, path: Path, user: Optional[int] = None, group: Optional[int] = None
    ):
        """Fix permissions of files created by a container."""
        # Special case for podman user namespace mapping
        if os.stat(path).st_uid > 100000:
            user = 0
            group = 0

        user = user if user is not None else os.getuid()
        group = group if group is not None else os.getgid()
        container = self.client.containers.run(
            self.FIX_PERMISSIONS_IMAGE,
            command=f"chown -R {user}:{group} /target",
            volumes={path: {"bind": "/target", "mode": "rw,z"}},
            auto_remove=True,
            detach=True,
        )
        container.wait()

    def healthy(self, container: Container) -> bool:
        """Check if container is healthy."""
        inspect_results = self.client.api.inspect_container(container.name)
        return inspect_results["State"]["Health"]["Status"] == "healthy"

    def wait_until_healthy(self, container: Container, attempts: int = 350):
        """Wait until container is healthy."""
        for _ in range(attempts):
            if self.healthy(container):
                return
            else:
                time.sleep(1)
        raise TimeoutError("Timed out waiting for container")

    def stop(self, container: Container):
        """Stop a container and remove it from the container manager state."""
        self.containers.remove(container)
        container.stop()

    def postgres(self, port: int, volume: Optional[str] = None) -> Container:
        """Create a postgres container."""
        container = self.client.containers.run(
            self.POSTGRES_IMAGE,
            name="postgres",
            volumes={volume: {"bind": "/var/lib/postgresql/data", "mode": "rw,z"}}
            if volume
            else None,
            ports={"5432/tcp": port},
            environment=["POSTGRES_PASSWORD=mysecretpassword"],
            auto_remove=True,
            detach=True,
            network=self.network.name,
            healthcheck={
                "test": ["CMD-SHELL", "pg_isready -U postgres"],
                "interval": int(10e9),
                "timeout": int(60e9),
                "retries": 5,
                "start_period": int(10e9),
            },
        )
        self.containers.append(container)
        return cast(Container, container)

    def tails(self) -> Container:
        """Create a tails server container."""
        container = self.client.containers.run(
            self.TAILS_IMAGE,
            name=self.TAILS_NAME,
            ports={"6543/tcp": 6543},
            environment=[
                f"GENESIS_URL={self.GENESIS_URL}",
            ],
            entrypoint="""tails-server
                --host 0.0.0.0
                --port 6543
                --storage-path /tmp/tails-files
                --log-level INFO""",
            network=self.network.name,
            auto_remove=True,
            detach=True,
        )
        self.containers.append(container)
        return cast(Container, container)

    def acapy(
        self, name: str, admin_port: int, command: str, volumes: Optional[dict] = None
    ) -> Container:
        """Create an acapy container."""
        container = self.client.containers.run(
            self.ACAPY_IMAGE,
            volumes=volumes,
            name=name,
            ports={"3001/tcp": admin_port},
            environment=["RUST_LOG=TRACE"],
            command=command,
            auto_remove=True,
            detach=True,
            network=self.network.name,
            healthcheck={
                "test": "curl -s -o /dev/null -w '%{http_code}' 'http://localhost:3001/status/live' | grep '200' > /dev/null",
                "interval": int(7e9),
                "timeout": int(5e9),
                "retries": 5,
            },
        )
        self.containers.append(container)
        return cast(Container, container)

    def acapy_sqlite(
        self,
        name: str,
        wallet_key: str,
        admin_port: int,
        wallet_type: str,
        volume_src: str,
        volume_dst: str,
    ) -> Container:
        """Create an acapy container for use with a sqlite DB."""
        return self.acapy(
            name,
            admin_port,
            command=f"""
                start -it http 0.0.0.0 3000
                    --label {name}
                    -ot http
                    -e http://{name}:3000
                    --admin 0.0.0.0 3001 --admin-insecure-mode
                    --log-level debug
                    --genesis-url {self.GENESIS_URL}
                    --tails-server-base-url http://{self.TAILS_NAME}:6543
                    --wallet-type {wallet_type}
                    --wallet-name {name}
                    --wallet-key {wallet_key}
                    --preserve-exchange-records
                    --auto-provision
            """,
            volumes={
                volume_src: {
                    "bind": volume_dst,
                    "mode": "rw,z",
                }
            },
        )

    def acapy_postgres(
        self,
        name: str,
        wallet_key: str,
        admin_port: int,
        wallet_type: str,
        postgres: Container,
        mwst: bool = False,
        mt: bool = False,
        askar_profile: bool = False,
    ) -> Container:
        """Create an acapy container for use with a postgres DB."""
        self.wait_until_healthy(postgres)
        command = f"""
            start -it http 0.0.0.0 3000
                --label {name}
                -ot http
                -e http://{name}:3000
                --admin 0.0.0.0 3001 --admin-insecure-mode
                --log-level debug
                --genesis-url {self.GENESIS_URL}
                --tails-server-base-url http://{self.TAILS_NAME}:6543
                --wallet-type {wallet_type}
                --wallet-name {name}
                --wallet-key {wallet_key}
                --wallet-storage-type postgres_storage
                --preserve-exchange-records
                --auto-provision
                --wallet-storage-creds '{{"account":"{self.POSTGRES_USER}","password":"{self.POSTGRES_PASSWORD}","admin_account":"{self.POSTGRES_USER}","admin_password":"{self.POSTGRES_PASSWORD}"}}'
        """

        if mwst:
            command += f"""
                --wallet-storage-config '{{"url":"{postgres.name}:5432","wallet_scheme":"MultiWalletSingleTable"}}'
            """
        else:
            command += f"""
                --wallet-storage-config '{{"url":"{postgres.name}:5432","max_connections":5}}'
            """

        if mt:
            command += """
                --multitenant
                --multitenant-admin
                --jwt-secret insecure
            """

        if askar_profile:
            command += f"""
                --multitenancy-config wallet_type=askar-profile
            """

        return self.acapy(
            name,
            admin_port,
            command=command,
        )


if __name__ == "__main__":
    containers = Containers(docker.from_env()).setup()
    try:
        postgres = containers.postgres(5432)
        tails = containers.tails()
        alice = containers.acapy_postgres(
            name="alice",
            wallet_key="insecure",
            admin_port=3001,
            wallet_type="indy",
            postgres=postgres,
        )
        containers.wait_until_healthy(alice)
        breakpoint()
    finally:
        containers.teardown()
