from abc import ABC, abstractmethod


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
    async def close(self):
        """Release the connection."""

    @abstractmethod
    async def get_root_config(self):
        """Get the root config table of the wallet."""

    @abstractmethod
    async def get_profiles(self):
        """Get the root config table of the wallet."""

    @abstractmethod
    async def create_database(self, admin_wallet_name, sub_wallet_name):
        """Create a database."""

    @abstractmethod
    async def remove_database(self, admin_wallet_name, sub_wallet_name):
        """Remove the database."""
