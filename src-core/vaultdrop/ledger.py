"""Ledger .vaultdrop.json: що лежить у dest і з яким хешем. Плюс контрольна сума самого ledger."""

import json
import os
import secrets
import re
import time
from datetime import datetime, timedelta, timezone

import xxhash

from . import VaultDropError
from .i18n import t
from .paths import contained_path, relative_path
from .winio import hash_unbuffered, lp, read_unbuffered

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
LEDGER = ".vaultdrop.json"
SIDECAR = LEDGER + ".xxh64"
RUNNING = ".vaultdrop.running"
TMP_PREFIX = ".vaultdrop-tmp-"


def utc(ts: float | None = None) -> str:
    """Час UTC у форматі ISO 8601 до секунди: 2026-09-21T10:00:00Z."""
    # Через timedelta, а не fromtimestamp: на Windows fromtimestamp падає на датах до 1970.
    moment = _EPOCH + timedelta(seconds=time.time() if ts is None else ts)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def tmp_name() -> str:
    return TMP_PREFIX + secrets.token_hex(8)


def source_root_hash(hashes: dict) -> str:
    """Відбиток знімка source: xxh64 від рядків `rel_path<TAB>size<TAB>xxh64` у порядку rel_path."""
    h = xxhash.xxh64()
    for rel in sorted(hashes):
        size, digest = hashes[rel]
        h.update(f"{rel}\t{size}\t{digest}\n".encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def write(dest_root: str, meta: dict, entries: list) -> None:
    """Пише ledger і його контрольну суму, кожен — через tmp, fsync і перечитування з диска."""
    doc = dict(meta, files=sorted(entries, key=lambda e: e["rel_path"]))
    data = json.dumps(doc, indent=1, ensure_ascii=True).encode("ascii")
    root = lp(dest_root)
    write_verified(contained_path(root, LEDGER), data)
    sidecar = f"{xxhash.xxh64(data).hexdigest()}  {LEDGER}\n".encode("ascii")
    write_verified(contained_path(root, SIDECAR), sidecar)


def write_verified(path: str, data: bytes) -> None:
    """tmp -> fsync -> перечитування в обхід кешу -> атомарний replace."""
    tmp = os.path.join(os.path.dirname(path), tmp_name())
    try:
        with open(tmp, "xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if hash_unbuffered(tmp) != xxhash.xxh64(data).hexdigest():
            raise OSError(None, "read-back from disk does not match", path)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read(target: str) -> dict:
    """Читає ledger і звіряє його контрольну суму. VaultDropError — ledger відсутній або пошкоджений."""
    root = lp(target)
    try:
        with open(contained_path(root, SIDECAR), "rb") as f:
            expected = f.read().split()[0].decode("ascii")
        data = bytearray()
        read_unbuffered(contained_path(root, LEDGER), data.extend)
    except FileNotFoundError:
        raise VaultDropError(t("err.no_ledger", path=target, file=LEDGER)) from None
    except (OSError, IndexError, UnicodeDecodeError) as e:
        raise VaultDropError(t("err.ledger_read", path=target, error=e)) from None
    if xxhash.xxh64(data).hexdigest() != expected:
        raise VaultDropError(t("err.ledger_damaged", path=target))
    try:
        doc = json.loads(data)
        files = doc["files"]
        if not isinstance(files, list):
            raise ValueError("files must be an array")
        seen = set()
        for e in files:
            key = relative_path(e["rel_path"]).casefold()
            if key in seen:
                raise ValueError("duplicate file path")
            seen.add(key)
            if type(e["size"]) is not int or e["size"] < 0:
                raise ValueError("invalid file size")
            if not isinstance(e["xxhash64_hex"], str) or not re.fullmatch(r"[0-9a-f]{16}", e["xxhash64_hex"]):
                raise ValueError("invalid xxHash64")
    except (ValueError, KeyError, TypeError) as e:
        raise VaultDropError(t("err.ledger_format", path=target, error=e)) from None
    return doc
