"""Error classes for askar_tools."""


class ConversionError(Exception):
    """Conversion error."""

    def __init__(self, message):
        """Initialize the ConversionError object."""
        self.message = message
        print(message)


class InvalidArgumentsError(Exception):
    """Invalid arguments error."""

    def __init__(self, message):
        """Initialize the InvalidArgumentsError object."""
        self.message = message
        print(message)
