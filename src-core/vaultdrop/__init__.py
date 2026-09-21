"""VaultDrop - offline verified backup for Windows."""

__version__ = "0.2.0"


class VaultDropError(Exception):
    """The run cannot proceed: invalid paths, a damaged ledger, or the drive disappeared during verify."""
