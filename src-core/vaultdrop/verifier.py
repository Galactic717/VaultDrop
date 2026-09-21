"""Verify: reads the backup back from disk bypassing the cache and compares every file with the ledger. Never writes to target."""

import os
import stat
import time

from . import VaultDropError, __version__, ledger
from .i18n import fmt_time, t
from .ledger import RUNNING, utc
from .paths import contained_path
from .winio import classify, hash_unbuffered, lp


def run_verify(target: str, emit=lambda event: None) -> dict:
    """Verifies a backup. VaultDropError if the ledger is missing or damaged, or the drive disappears mid-check."""
    target = os.path.abspath(target)
    doc = ledger.read(target)
    root = lp(target)
    files = doc["files"]
    emit({"event": "start", "command": "verify", "target": target, "files": len(files),
          "bytes": sum(e["size"] for e in files)})
    counts = dict.fromkeys(("intact", "changed", "missing", "unreadable"), 0)
    problems = []
    done_bytes, last = 0, 0.0
    for i, e in enumerate(files, 1):
        state = _check(root, target, e)
        counts[state] += 1
        if state != "intact":
            problems.append({"rel_path": e["rel_path"], "state": state})
            emit({"event": "problem", **problems[-1]})
        done_bytes += e["size"]
        now = time.monotonic()
        if now - last >= 0.2 or i == len(files):
            last = now
            emit({"event": "progress", "files_done": i, "bytes_done": done_bytes, "current": e["rel_path"]})
    unfinished = os.path.exists(os.path.join(root, RUNNING))
    complete = doc.get("run_verdict") == "SAFE TO FORMAT" and not unfinished and bool(files)
    result = {
        "vaultdrop_version": __version__,
        "command": "verify",
        "target": target,
        "checked_at_utc": utc(),
        "ledger_created_at_utc": doc.get("created_at_utc"),
        "source_label": doc.get("source_label"),
        "run_verdict": doc.get("run_verdict"),
        "unfinished_copy": unfinished,
        **counts,
        "result": ("INTACT" if complete else "INCOMPLETE") if counts["intact"] == len(files) else "DAMAGED",
        "problems": problems,
    }
    text = _text(result, len(files))
    emit({"event": "done", "result": result, "text": text})
    return result


def _check(root, target, e) -> str:
    try:
        path = contained_path(root, e["rel_path"])
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):
            return "missing"
        if st.st_size != e["size"]:
            return "changed"
        return "intact" if hash_unbuffered(path) == e["xxhash64_hex"] else "changed"
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError as exc:
        if classify(exc, target) == "yanked":
            raise VaultDropError(t("err.gone", path=target)) from None
        return "unreadable"


def _text(r, total) -> str:
    intact = r["result"] == "INTACT"
    lines = [
        t("ver.title", version=r["vaultdrop_version"], path=r["target"]),
        t("ver.result", result=t("verdict.intact" if intact else "verdict.fail" if r["result"] == "INCOMPLETE" else "verdict.damaged")),
        "",
        t("ver.created", date=fmt_time(r["ledger_created_at_utc"]), source=r["source_label"],
          verdict=t("verdict.safe" if r["run_verdict"] == "SAFE TO FORMAT" else "verdict.fail")),
        t("ver.counts", total=total, intact=r["intact"], changed=r["changed"], missing=r["missing"],
          unreadable=r["unreadable"]),
        t("ver.how", date=fmt_time(r["checked_at_utc"])),
    ]
    if r["unfinished_copy"]:
        lines.append(t("ver.unfinished"))
    if r["run_verdict"] != "SAFE TO FORMAT":
        lines.append(t("ver.incomplete"))
    for state in ("changed", "missing", "unreadable"):
        items = [p["rel_path"] for p in r["problems"] if p["state"] == state]
        if items:
            lines += ["", f"{t('state.' + state)} — {len(items)}:"] + [f"  {x}" for x in items[:200]]
            if len(items) > 200:
                lines.append("  " + t("ver.more", n=len(items) - 200))
    return "\n".join(lines) + "\n"
