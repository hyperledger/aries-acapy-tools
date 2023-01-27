class UpgradeError(Exception):
    pass


class MissingWalletError(UpgradeError):
    pass
