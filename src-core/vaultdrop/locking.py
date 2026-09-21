"""Process-level destination lock; Windows releases it after a crash."""

import msvcrt
import os
from contextlib import contextmanager

from . import VaultDropError
from .i18n import t
from .paths import contained_path
from .winio import lp


@contextmanager
def lock_destinations(destinations):
    handles = []
    try:
        for dest in sorted(destinations, key=str.casefold):
            os.makedirs(lp(dest), exist_ok=True)
            handle = open(contained_path(lp(dest), ".vaultdrop.lock"), "a+b")
            try:
                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                raise VaultDropError(t("err.backup_busy", path=dest)) from None
            handles.append(handle)
        yield
    finally:
        for handle in reversed(handles):
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass  # A removed destination may no longer accept an unlock.
            finally:
                try:
                    handle.close()
                except OSError:
                    pass
