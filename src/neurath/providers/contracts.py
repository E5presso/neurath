"""Wire transport error shared with the native provider adapter."""


class UnsupportedOperation(ValueError):
    """The selected transport cannot perform the requested operation."""
