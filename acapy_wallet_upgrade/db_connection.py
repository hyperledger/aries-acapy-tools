from abc import ABC, abstractmethod
from typing import AsyncIterator, Sequence, Tuple, Union


class DbConnection(ABC):
    """Abstract database connection."""

    DB_TYPE: str

    @abstractmethod
    async def connect(self):
        """Initialize the connection handler."""

    @abstractmethod
    async def find_table(self, name: str) -> bool:
        """Check for existence of a table."""

    @abstractmethod
    async def pre_upgrade(self):
        """Add new tables and columns."""

    @abstractmethod
    async def create_config(self, default_profile: str, key: str):
        """Insert the initial profile."""

    @abstractmethod
    async def finish_upgrade(self):
        """Complete the upgrade."""

    @abstractmethod
    async def close(self):
        """Release the connection."""


class Wallet(ABC):
    """Abstract wallet.

    Represents a single wallet in an Indy SDK DB.
    """

    @abstractmethod
    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""

    @abstractmethod
    async def get_metadata(self) -> Union[str, bytes]:
        """Fetch metadata value from the database."""

    @abstractmethod
    def fetch_pending_items(self, limit: int) -> AsyncIterator[Sequence[Tuple]]:
        """Fetch un-updated items."""

    @abstractmethod
    async def update_items(self, items):
        """Update items in the database."""
