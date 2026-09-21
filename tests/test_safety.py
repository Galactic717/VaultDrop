"""Regression coverage for trustworthy verdicts and backup path boundaries."""
import json
import os
import subprocess

import pytest
import xxhash

from conftest import make_tree, read
from vaultdrop import VaultDropError, copier, ledger
from vaultdrop.cli import main
from vaultdrop.copier import run_copy
from vaultdrop.locking import lock_destinations
from vaultdrop.verifier import run_verify
from vaultdrop.paths import contained_path


def replace_ledger(root, mutate):
    doc = json.loads(read(root, ledger.LEDGER))
    mutate(doc)
    data = json.dumps(doc).encode()
    make_tree(root, {ledger.LEDGER: data, ledger.SIDECAR: xxhash.xxh64(data).hexdigest().encode()})


@pytest.fixture
def backup(dirs):
    src, dest, _ = dirs
    make_tree(src, {"a.txt": b"original"})
    run_copy(src, [dest])
    return src, dest


@pytest.mark.parametrize("path", ["../secret", "/absolute", "C:/secret", "a/../../b", "a\\b", "a:stream", "CON", "foo.", "a//b", "a/./b"])
def test_ledger_rejects_unsafe_paths(backup, path):
    _, dest = backup
    replace_ledger(dest, lambda doc: doc["files"][0].update(rel_path=path))
    with pytest.raises(VaultDropError):
        run_verify(dest)


@pytest.mark.parametrize("changes", [{"size": -1}, {"size": "8"}, {"size": True}, {"xxhash64_hex": "bad"}])
def test_ledger_rejects_invalid_fields(backup, changes):
    _, dest = backup
    replace_ledger(dest, lambda doc: doc["files"][0].update(changes))
    with pytest.raises(VaultDropError):
        run_verify(dest)


def test_ledger_rejects_duplicate_paths(backup):
    _, dest = backup
    replace_ledger(dest, lambda doc: doc["files"].append(dict(doc["files"][0], rel_path="A.TXT")))
    with pytest.raises(VaultDropError):
        run_verify(dest)


@pytest.mark.parametrize("unfinished", [True, False])
def test_incomplete_backup_cannot_pass(backup, unfinished):
    _, dest = backup
    if unfinished:
        make_tree(dest, {ledger.RUNNING: b"interrupted"})
    else:
        replace_ledger(dest, lambda doc: doc.update(run_verdict="FAIL"))
    result = run_verify(dest)
    assert result["intact"] == 1
    assert result["result"] == "INCOMPLETE"
    assert main(["verify", "--target", dest, "--json"]) == 1


def test_empty_index_is_not_a_complete_backup(backup):
    _, dest = backup
    replace_ledger(dest, lambda doc: doc.update(files=[]))
    assert run_verify(dest)["result"] == "INCOMPLETE"


def test_report_failure_is_not_success(backup, monkeypatch):
    src, dest = backup
    original = ledger.write_verified
    def fail_report(path, data):
        if path.endswith(copier.REPORT_TXT):
            raise OSError("simulated report failure")
        original(path, data)
    monkeypatch.setattr(ledger, "write_verified", fail_report)
    result = run_copy(src, [dest])
    assert result["verdict"] == "FAIL"
    assert os.path.exists(os.path.join(dest, ledger.RUNNING))
    assert run_verify(dest)["result"] == "INCOMPLETE"


def test_destination_is_exclusive_and_reusable(dirs):
    src, dest, _ = dirs
    make_tree(src, {"a.txt": b"new"})
    with lock_destinations([dest]):
        with pytest.raises(VaultDropError, match="already writing"):
            run_copy(src, [dest])
        assert not os.path.exists(os.path.join(dest, ledger.RUNNING))
    assert run_copy(src, [dest])["verdict"] == "SAFE TO FORMAT"


def junction(link, target):
    # Fixed test-owned paths, no destructive operations in another shell.
    result = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
    assert result.returncode == 0, result.stderr


def test_destination_junction_does_not_overwrite_outside(dirs, tmp_path):
    src, dest, _ = dirs
    outside = str(tmp_path / "outside")
    make_tree(src, {"sub/a.txt": b"new", "good.txt": b"ok"})
    make_tree(outside, {"a.txt": b"must survive"})
    os.makedirs(dest)
    link = os.path.join(dest, "sub")
    junction(link, outside)
    try:
        assert run_copy(src, [dest])["verdict"] == "FAIL"
        assert read(outside, "a.txt") == b"must survive"
        assert read(dest, "good.txt") == b"ok"
    finally:
        os.rmdir(link)


def test_resolved_source_destination_overlap_is_refused(dirs):
    src, dest, _ = dirs
    make_tree(src, {"a.txt": b"original"})
    junction(dest, src)
    try:
        with pytest.raises(VaultDropError):
            run_copy(src, [dest])
        assert read(src, "a.txt") == b"original"
    finally:
        os.rmdir(dest)


def test_system_named_user_files_are_copied(dirs):
    src, dest, _ = dirs
    make_tree(src, {"pagefile.sys": b"user file, not a drive-root system file"})
    assert run_copy(src, [dest])["verdict"] == "SAFE TO FORMAT"
    assert read(src, "pagefile.sys") == read(dest, "pagefile.sys")


def test_cross_volume_resolution_is_an_io_error(monkeypatch):
    monkeypatch.setattr(os.path, "realpath", lambda p: "C:\\backup" if p == "root" else "E:\\outside\\file")
    with pytest.raises(OSError, match="leaves the backup"):
        contained_path("root", "file")


def test_case_collisions_refused_before_writing(dirs, monkeypatch):
    src, dest, _ = dirs
    make_tree(src, {"a.txt": b"data"})
    monkeypatch.setattr(copier._Copy, "walk", lambda self: ([("a.txt", 4), ("A.txt", 4)], [], [], []))
    with pytest.raises(VaultDropError):
        run_copy(src, [dest])
    assert not os.path.exists(dest)
