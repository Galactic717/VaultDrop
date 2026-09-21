"""Тести приймання copy: (a) обрив dest, (d) 0 байт + кирилиця + довгий шлях, (e) locked, плюс гілки retry."""

import ctypes
import itertools
import json
import msvcrt
import os
from ctypes import wintypes

import pytest

from conftest import exists, make_tree, read
from vaultdrop import VaultDropError, copier
from vaultdrop.cli import main
from vaultdrop.copier import run_copy
from vaultdrop.ledger import RUNNING
from vaultdrop.winio import lp

MB = 1 << 20


def incidents(dest):
    return json.loads(read(dest, "vaultdrop-incident.json"))


def tmp_leftovers(dest):
    return [n for _, _, names in os.walk(lp(dest)) for n in names if n.startswith(".vaultdrop-tmp-")]


class Yanked:
    """Файл на флешці, яку висмикнули: після `limit` байтів запис падає з WinError 1167."""

    def __init__(self, f, limit):
        self.f, self.left = f, limit

    def write(self, data):
        if len(data) > self.left:
            raise OSError(None, "The device is not connected", None, 1167)
        self.left -= len(data)
        return self.f.write(data)

    def __getattr__(self, name):
        return getattr(self.f, name)


def test_yank(dirs, monkeypatch):
    src, d1, d2 = dirs
    make_tree(src, {"a.bin": os.urandom(4096), "b.bin": os.urandom(8 * MB), "c.bin": os.urandom(4096)})
    real_open = copier._open_tmp
    d2_prefix = lp(d2) + "\\"
    monkeypatch.setattr(copier, "_open_tmp",
                        lambda p: Yanked(real_open(p), 3 * MB) if p.startswith(d2_prefix) else real_open(p))

    assert main(["copy", "--source", src, "--dest", f"{d1},{d2}", "--lang", "en"]) == 1

    for name in ("a.bin", "b.bin", "c.bin"):
        assert read(d1, name) == read(src, name)
    assert read(d2, "a.bin") == read(src, "a.bin")
    assert not exists(d2, "b.bin") and not exists(d2, "c.bin")
    assert exists(d2, RUNNING)  # наступний запуск побачить обрив і прибере tmp
    assert not exists(d2, ".vaultdrop.json")
    yanked = [i for i in incidents(d1) if i["reason"] == "yanked"]
    assert [(i["rel_path"], i["dest"], i["attempts"]) for i in yanked] == [("b.bin", d2, 1), ("c.bin", d2, 0)]
    assert "Result: INCOMPLETE" in read(d1, "vaultdrop-report.txt").decode("utf-8")
    assert not exists(d1, RUNNING)


def test_edge_names(dirs):
    src, d1, _ = dirs
    deep = "/".join(["довга папка з пробілами " + "я" * 30] * 5)
    spec = {"empty.bin": b"", "Документи/звіт 2026 (фінал).txt": "привіт".encode(),
            f"{deep}/глибокий файл.txt": os.urandom(5000)}
    make_tree(src, spec)
    stamp = 1_700_000_000
    for rel in spec:
        os.utime(lp(os.path.join(src, *rel.split("/"))), (stamp, stamp))
    assert len(os.path.join(src, *deep.split("/"))) > 300

    report = run_copy(src, [d1])

    assert report["verdict"] == "SAFE TO FORMAT" and report["ok"] == 3
    doc = json.loads(read(d1, ".vaultdrop.json"))
    by_rel = {e["rel_path"]: e for e in doc["files"]}
    assert set(by_rel) == set(spec)
    assert by_rel["empty.bin"]["xxhash64_hex"] == "ef46db3751d8e999"
    for rel, data in spec.items():
        assert read(d1, rel) == data
        assert os.stat(lp(os.path.join(d1, *rel.split("/")))).st_mtime_ns == stamp * 10**9


def _open_exclusive(path):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.CreateFileW(lp(path), 0x80000000, 0, None, 3, 0, None)  # dwShareMode=0: нікого не пускає
    assert handle != ctypes.c_void_p(-1).value
    return lambda: k32.CloseHandle(handle)


def test_locked(dirs):
    src, d1, d2 = dirs
    make_tree(src, {"a.txt": b"ok", "range.db": os.urandom(65536), "exclusive.db": os.urandom(100)})
    locker = open(lp(os.path.join(src, "range.db")), "r+b")
    msvcrt.locking(locker.fileno(), msvcrt.LK_NBLCK, 65536)  # так тримають файли SQLite / Lightroom
    close_exclusive = _open_exclusive(os.path.join(src, "exclusive.db"))
    try:
        report = run_copy(src, [d1, d2])
    finally:
        locker.seek(0)
        msvcrt.locking(locker.fileno(), msvcrt.LK_UNLCK, 65536)
        locker.close()
        close_exclusive()

    assert report["verdict"] == "FAIL"
    assert (report["ok"], report["skipped_locked"], report["failed"]) == (1, 2, 0)
    for d in (d1, d2):
        assert read(d, "a.txt") == b"ok"
        assert not exists(d, "range.db") and not exists(d, "exclusive.db")
        assert tmp_leftovers(d) == []
    locked = sorted((i["rel_path"], i["dest"]) for i in incidents(d1) if i["reason"] == "locked")
    assert locked == [("exclusive.db", None), ("range.db", None)]


def test_mismatch_retry(dirs, monkeypatch):
    src, d1, d2 = dirs
    make_tree(src, {"x.bin": b"x" * 100})
    real_hash = copier.hash_unbuffered
    calls = itertools.count()
    monkeypatch.setattr(copier, "hash_unbuffered", lambda p: "0" * 16 if next(calls) == 0 else real_hash(p))
    assert run_copy(src, [d1])["verdict"] == "SAFE TO FORMAT"  # перший збіг не вдався, повтор урятував

    monkeypatch.setattr(copier, "hash_unbuffered", lambda p: "0" * 16)
    assert run_copy(src, [d2])["verdict"] == "FAIL"
    assert [(i["reason"], i["attempts"]) for i in incidents(d2)] == [("mismatch", 2)]
    assert not exists(d2, "x.bin") and tmp_leftovers(d2) == []


def test_unstable_source(dirs, monkeypatch):
    src, d1, _ = dirs
    make_tree(src, {"log.txt": b"line\n" * 100, "ok.txt": b"fine"})
    real_sig = copier._sig
    ticks = itertools.count()
    monkeypatch.setattr(copier, "_sig", lambda f: next(ticks) if f.name.endswith("log.txt") else real_sig(f))

    report = run_copy(src, [d1])

    assert report["verdict"] == "FAIL" and report["ok"] == 1
    assert [(i["rel_path"], i["reason"], i["attempts"]) for i in incidents(d1)] == [("log.txt", "unstable", 2)]
    assert not exists(d1, "log.txt") and tmp_leftovers(d1) == []


def test_preflight_refuses(dirs):
    src, d1, _ = dirs
    with pytest.raises(VaultDropError):
        run_copy(src, [d1])  # source нема
    os.makedirs(src)
    with pytest.raises(VaultDropError):
        run_copy(src, [d1])  # source порожній
    make_tree(src, {"a.txt": b"a"})
    with pytest.raises(VaultDropError):
        run_copy(src, [os.path.join(src, "inner")])  # копія всередині джерела
    with pytest.raises(VaultDropError):
        run_copy(src, [d1, d1])
    make_tree(src, {"vaultdrop-report.txt": b"user file"})
    with pytest.raises(VaultDropError):
        run_copy(src, [d1])  # наш звіт перезаписав би файл користувача
    assert not os.path.exists(d1)
    assert main(["copy", "--source", src, "--dest", d1, "--lang", "en"]) == 2


def test_to_keeps_commas(dirs):
    """Інтерфейс передає копії через --to: кома в назві папки не ділить шлях на два."""
    src, d1, _ = dirs
    make_tree(src, {"a.txt": b"a"})
    target = os.path.join(d1, "Фото, 2024")
    assert main(["copy", "--source", src, "--to", target, "--lang", "en"]) == 0
    assert read(target, "a.txt") == b"a"


def test_interrupted_run_is_cleaned(dirs):
    src, d1, _ = dirs
    make_tree(src, {"a.txt": b"new"})
    make_tree(d1, {RUNNING: b"x", "a.txt": b"old", "sub/.vaultdrop-tmp-0123456789abcdef": b"stale",
                   "sub/user.vaultdrop-tmp-notours": b"keep"})

    report = run_copy(src, [d1])

    assert report["verdict"] == "SAFE TO FORMAT"
    assert report["previous_run_interrupted"] == [d1]
    assert not exists(d1, "sub/.vaultdrop-tmp-0123456789abcdef")
    assert read(d1, "sub/user.vaultdrop-tmp-notours") == b"keep"
    assert read(d1, "a.txt") == b"new"
    assert not exists(d1, RUNNING)
