"""VaultDrop — офлайн верифікований бекап для Windows."""

__version__ = "0.2.0"


class VaultDropError(Exception):
    """Прогін неможливий: невірні шляхи, пошкоджений ledger або диск зник під час verify."""
