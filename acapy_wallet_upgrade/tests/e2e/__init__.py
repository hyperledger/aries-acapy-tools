import asyncio

import docker
import pytest

from .containers import Containers


class WalletTypeToBeTested:
    @pytest.fixture(scope="class")
    def event_loop(self):
        policy = asyncio.get_event_loop_policy()
        loop = policy.new_event_loop()
        yield loop
        loop.close()

    @pytest.fixture(scope="class")
    def containers(self):
        containers = Containers(docker.from_env()).setup()
        yield containers
        containers.teardown()

    @pytest.fixture(scope="class", autouse=True)
    def tails(self, containers: Containers):
        yield containers.tails()
