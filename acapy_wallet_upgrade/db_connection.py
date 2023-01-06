from abc import ABC, abstractmethod


class DbConnection(ABC):
    """Abstract database connection."""

    DB_TYPE: str

    @abstractmethod
    async def connect(self):
        """Initialize the connection handler."""

    @abstractmethod
    async def pre_upgrade(self, name: str) -> bool:
        """Add new tables and columns."""

    @abstractmethod
    async def insert_profile(self, name: str, key: bytes):
        """Insert the initial profile."""

    @abstractmethod
    async def finish_upgrade(self):
        """Complete the upgrade."""

    @abstractmethod
    async def fetch_one(self, sql: str, optional: bool = False):
        """Fetch a single row from the database."""

    @abstractmethod
    async def fetch_pending_items(self, limit: int):
        """Fetch un-updated items."""

    @abstractmethod
    async def close(self):
        """Release the connection."""
