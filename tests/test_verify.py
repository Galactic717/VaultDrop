"""Тести приймання verify: (b) 1 змінений байт -> changed, (c) видалений файл -> missing, пошкоджений ledger."""

import os

import pytest

from conftest import make_tree
from vaultdrop import VaultDropError
from vaultdrop.cli import main
from vaultdrop.copier import run_copy
from vaultdrop.verifier import run_verify
from vaultdrop.winio import lp


@pytest.fixture
def backup(dirs):
    src, d1, _ = dirs
    make_tree(src, {"a.txt": b"hello" * 1000, "b/c.bin": os.urandom(70000), "d.txt": b"bye"})
    assert run_copy(src, [d1])["verdict"] == "SAFE TO FORMAT"
    return d1


def snapshot(root):
    """Імена, розміри й mtime усього в папці — verify не має змінити нічого."""
    return sorted((os.path.join(p, n), os.stat(os.path.join(p, n)).st_size, os.stat(os.path.join(p, n)).st_mtime_ns)
                  for p, _, names in os.walk(lp(root)) for n in names)


def test_changed_byte(backup):
    assert run_verify(backup)["result"] == "INTACT"
    before = snapshot(backup)
    with open(lp(os.path.join(backup, "b", "c.bin")), "r+b") as f:
        f.seek(12345)
        byte = f.read(1)[0]
        f.seek(12345)
        f.write(bytes([byte ^ 1]))
    changed_state = snapshot(backup)

    result = run_verify(backup)

    assert (result["result"], result["intact"], result["changed"]) == ("DAMAGED", 2, 1)
    assert result["problems"] == [{"rel_path": "b/c.bin", "state": "changed"}]
    assert main(["verify", "--target", backup, "--lang", "en"]) == 1
    assert snapshot(backup) == changed_state != before


def test_missing(backup):
    os.remove(lp(os.path.join(backup, "d.txt")))
    result = run_verify(backup)
    assert (result["result"], result["missing"], result["intact"]) == ("DAMAGED", 1, 2)
    assert result["problems"] == [{"rel_path": "d.txt", "state": "missing"}]


def test_damaged_ledger(backup):
    path = lp(os.path.join(backup, ".vaultdrop.json"))
    with open(path, "rb") as f:
        data = bytearray(f.read())
    data[len(data) // 2] ^= 1
    with open(path, "wb") as f:
        f.write(data)
    with pytest.raises(VaultDropError):
        run_verify(backup)
    assert main(["verify", "--target", backup, "--lang", "en"]) == 2
