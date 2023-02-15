import asyncio

from populate_db import with_mt_agents
from controller.logging import logging_to_stdout


if __name__ == "__main__":
    logging_to_stdout()
    asyncio.run(with_mt_agents())
