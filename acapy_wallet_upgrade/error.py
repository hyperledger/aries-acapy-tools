"""Errors that can occur on upgrade."""


class UpgradeError(Exception):
    """Raised on error during upgrade."""


class MissingWalletError(UpgradeError):
    """Raised when a wallet is missing from the wallet keys input."""


class DecryptionFailedError(UpgradeError):
    """Raised when unable to decrypt an item from the source wallet."""
