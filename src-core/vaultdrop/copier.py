"""The copy algorithm.

The source is read once and the same bytes go to a tmp file in every dest. Each copy is read back from disk
bypassing the Windows cache, and only when xxh64 matches does tmp atomically become the final file. Any failure
of a single file or a single drive is recorded as an incident and the run continues.
"""

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field

import xxhash

from . import VaultDropError, __version__, ledger
from .i18n import fmt_duration, fmt_size, fmt_time, t
from .ledger import RUNNING, TMP_PREFIX, tmp_name, utc
from .locking import lock_destinations
from .paths import contained_path, relative_path
from .winio import CHUNK, classify, hash_unbuffered, lp, volume_fs

TMP_RE = re.compile(re.escape(TMP_PREFIX) + r"[0-9a-f]{16}")
RESERVED_PREFIXES = (".vaultdrop", "vaultdrop-")
# System objects in a drive root: they are not backed up and cannot be read.
SYSTEM_ROOT_NAMES = {"system volume information", "$recycle.bin", "pagefile.sys", "hiberfil.sys",
                     "swapfile.sys", "dumpstack.log.tmp"}
FAT32_MAX_FILE = (1 << 32) - 1
SAFE, FAIL = "SAFE TO FORMAT", "FAIL"
REPORT_JSON, REPORT_TXT = "vaultdrop-report.json", "vaultdrop-report.txt"
INCIDENT_JSON, INCIDENT_TXT = "vaultdrop-incident.json", "vaultdrop-incident.txt"


@dataclass(eq=False)
class Dest:
    root: str
    fs: str = ""
    alive: bool = True
    dead_reason: str = ""
    entries: list = field(default_factory=list)  # ledger entries for files that reached this dest
    ledger_written: bool = False
    reports_written: bool = False


def run_copy(source: str, dests: list[str], emit=lambda event: None) -> dict:
    """Copies source to 1-2 dests and returns the report. VaultDropError means the run did not start."""
    return _Copy(source, dests, emit).run()


def _open_tmp(path: str):
    return open(path, "xb")


def _sig(f) -> tuple:
    """Size and mtime of the open source file: if they changed while reading, the copy may mix versions."""
    st = os.fstat(f.fileno())
    return st.st_size, st.st_mtime_ns


class _Copy:
    def __init__(self, source, dest_roots, emit):
        self.source = os.path.abspath(source)
        self.dests = [Dest(os.path.abspath(d)) for d in dest_roots]
        self.emit = emit
        self.incidents = []
        self.hashes = {}  # rel -> (size, xxh64) of every source file read
        self.interrupted = []
        self.files_done = 0
        self.current = ""
        self.bytes_done = 0
        self.last_progress = 0.0

    def run(self) -> dict:
        started = time.time()
        files, dirs, links, system = self.preflight()
        with lock_destinations([d.root for d in self.dests]):
            self.prepare_destinations()
            return self.copy_files(files, dirs, links, system, started)

    def copy_files(self, files, dirs, links, system, started):
        self.emit({"event": "start", "command": "copy", "source": self.source,
                   "dests": [d.root for d in self.dests], "files": len(files),
                   "bytes": sum(size for _, size in files)})
        self.make_dirs(dirs)
        for rel, size in files:
            self.current = rel
            self.copy_one(rel, size)
            self.files_done += 1
            self.bytes_done += size
            self.progress(0, force=self.files_done == len(files))
        return self.finish([rel for rel, _ in files], links, system, started)

    # --- preflight: any failure here is a VaultDropError; nothing is in dest yet

    def preflight(self):
        if not 1 <= len(self.dests) <= 2:
            raise VaultDropError(t("err.dest_count"))
        paths = [self.source] + [d.root for d in self.dests]
        if any(p.startswith("\\\\") for p in paths):
            raise VaultDropError(t("err.network"))
        if not os.path.isdir(lp(self.source)):
            raise VaultDropError(t("err.source_missing", path=self.source))
        keys = [_key(p) for p in paths]
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if a == b or a.startswith(b + "\\") or b.startswith(a + "\\"):
                    raise VaultDropError(t("err.overlap"))
        with os.scandir(lp(self.source)) as it:
            clash = sorted(e.name for e in it if e.name.lower().startswith(RESERVED_PREFIXES))
        if clash:
            raise VaultDropError(t("err.reserved", names=", ".join(clash)))
        files, dirs, links, system = self.walk()
        if not files:
            raise VaultDropError(t("err.empty", path=self.source))
        seen = set()
        for rel in dirs + [rel for rel, _ in files]:
            try:
                key = relative_path(rel).casefold()
                if key in seen:
                    raise ValueError("case-insensitive path collision")
                seen.add(key)
            except ValueError:
                raise VaultDropError(t("err.unsupported_path", path=rel)) from None
        need = sum(size for _, size in files) + max(size for _, size in files)
        for d in self.dests:
            root = lp(d.root)
            try:
                os.makedirs(root, exist_ok=True)
                free = shutil.disk_usage(root).free
            except OSError as e:
                raise VaultDropError(t("err.dest_access", path=d.root, error=e)) from None
            if free < need:
                existing = sum(_size(self.dst(d, rel)) for rel, _ in files)
                if free < need - existing:
                    raise VaultDropError(t("err.space", path=d.root, need=fmt_size(need - existing),
                                           free=fmt_size(free)))
            d.fs = volume_fs(d.root)
        return files, dirs, links, system

    def prepare_destinations(self):
        for d in self.dests:
            marker = contained_path(lp(d.root), RUNNING)
            try:
                if os.path.exists(marker):  # the previous run was interrupted: power loss, crash, unplugged drive
                    self.interrupted.append(d.root)
                    _remove_stale_tmps(lp(d.root))
                with open(marker, "wb") as f:
                    f.write(utc().encode("ascii"))
            except OSError as e:
                raise VaultDropError(t("err.start_write", path=d.root, error=e)) from None

    def walk(self):
        files, dirs, links, system = [], [], [], []
        stack = [""]
        while stack:
            rel_dir = stack.pop()
            try:
                with os.scandir(self.src(rel_dir)) as it:
                    entries = list(it)
            except OSError as e:
                self.incident(rel_dir or ".", None, _source_reason(e), 1, e)
                continue
            for entry in entries:
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                try:
                    if (not rel_dir and os.path.splitdrive(self.source)[1] in ("\\", "/")
                            and entry.name.lower() in SYSTEM_ROOT_NAMES):
                        system.append(rel)
                    elif entry.is_symlink() or entry.is_junction():
                        links.append(rel)
                    elif entry.is_dir(follow_symlinks=False):
                        dirs.append(rel)
                        stack.append(rel)
                    elif not TMP_RE.fullmatch(entry.name):
                        files.append((rel, entry.stat(follow_symlinks=False).st_size))
                except OSError as e:
                    self.incident(rel, None, _source_reason(e), 1, e)
        files.sort()
        return files, sorted(dirs), sorted(links), system

    # --- copying

    def make_dirs(self, dirs):
        """Creates all folders, including empty ones."""
        for d in self.dests:
            for rel in dirs:
                if not d.alive:
                    break
                try:
                    os.makedirs(self.dst(d, rel), exist_ok=True)
                except OSError as e:
                    self.fail(d, rel, e, 1)

    def copy_one(self, rel, size):
        targets = []
        for d in self.dests:
            if not d.alive:
                self.incident(rel, d, d.dead_reason, 0, "drive unavailable after an earlier error")
            elif d.fs == "FAT32" and size > FAT32_MAX_FILE:
                self.incident(rel, d, "too_big_for_fs", 0, f"{size} bytes exceeds the FAT32 file size limit")
            else:
                try:
                    self.dst(d, rel)
                    targets.append(d)
                except OSError as e:
                    self.fail(d, rel, e, 1)
        if not targets:
            return
        src = self.src(rel)
        for attempt in (1, 2):
            result = self.stream(rel, src, targets, attempt)
            if result is None:
                return
            digest, st, tmps, stable = result
            if stable:
                break
            for path, out in tmps.values():
                _drop(path, out)
            targets = list(tmps)
            if attempt == 2:
                self.incident(rel, None, "unstable", 2, "size or modification time changed while reading")
                return
        self.hashes[rel] = (st.st_size, digest)
        for d, (path, out) in tmps.items():
            self.finish_one(d, rel, path, out, digest, st, src)

    def stream(self, rel, src, targets, attempt):
        """Reads the source once and writes the same bytes to tmp in every dest. None means the source could not be read."""
        try:
            f = open(src, "rb", buffering=0)
        except OSError as e:
            self.incident(rel, None, _source_reason(e), attempt, e)
            return None
        tmps = {}
        with f:
            st = os.fstat(f.fileno())
            before = _sig(f)
            for d in targets:
                path = os.path.join(os.path.dirname(self.dst(d, rel)), tmp_name())
                try:
                    tmps[d] = (path, _open_tmp(path))
                except OSError as e:
                    self.fail(d, rel, e, attempt)
            h = xxhash.xxh64()
            pos = 0
            try:
                while chunk := f.read(CHUNK):
                    h.update(chunk)
                    for d, (path, out) in list(tmps.items()):
                        try:
                            out.write(chunk)
                        except OSError as e:
                            del tmps[d]
                            _drop(path, out)
                            self.fail(d, rel, e, attempt)
                    pos += len(chunk)
                    self.progress(pos)
            except OSError as e:  # source read error in the middle of a file
                for path, out in tmps.values():
                    _drop(path, out)
                self.incident(rel, None, _source_reason(e), attempt, e)
                return None
            stable = _sig(f) == before
        return h.hexdigest(), st, tmps, stable

    def finish_one(self, d, rel, tmp, out, digest, st, src):
        """fsync, read back from disk, one retry on mismatch, atomic rename."""
        attempts = 1
        times = (st.st_atime_ns, st.st_mtime_ns)
        try:
            out.flush()
            os.fsync(out.fileno())
            out.close()
            os.utime(tmp, ns=times)
            got = hash_unbuffered(tmp)
            if got != digest:
                attempts = 2
                if _rewrite(src, tmp) != digest:
                    _drop(tmp)
                    self.incident(rel, d, "unstable", 2, "source changed between write and retry")
                    return
                os.utime(tmp, ns=times)
                got = hash_unbuffered(tmp)
                if got != digest:
                    _drop(tmp)
                    self.incident(rel, d, "mismatch", 2, f"source {digest} != copy {got}")
                    return
            os.replace(tmp, self.dst(d, rel))
        except OSError as e:
            _drop(tmp, out)
            self.fail(d, rel, e, attempts)
            return
        d.entries.append({"rel_path": rel, "size": st.st_size, "mtime_utc": utc(st.st_mtime),
                          "xxhash64_hex": digest, "copied_at_utc": utc()})

    # --- finish: ledger, reports, verdict

    def finish(self, rels, links, system, started) -> dict:
        ok_sets = [{e["rel_path"] for e in d.entries} for d in self.dests]
        ok = sum(all(rel in s for s in ok_sets) for rel in rels)
        locked = {i["rel_path"] for i in self.incidents if i["reason"] == "locked" and i["dest"] is None}
        skipped_locked = sum(rel in locked for rel in rels)
        files_verdict = SAFE if ok == len(rels) and not self.incidents else FAIL
        meta = {"vaultdrop_version": __version__, "created_at_utc": utc(started), "source_label": self.source,
                "source_root_hash": ledger.source_root_hash(self.hashes), "run_verdict": files_verdict}
        for d in self.dests:
            if d.alive:
                try:
                    ledger.write(d.root, meta, d.entries)
                    d.ledger_written = True
                except OSError as e:
                    self.fail(d, ledger.LEDGER, e, 1)
        verdict = SAFE if files_verdict == SAFE and all(d.ledger_written for d in self.dests) else FAIL
        finished = time.time()
        bytes_read = sum(size for size, _ in self.hashes.values())
        report = {
            "vaultdrop_version": __version__,
            "command": "copy",
            "started_at_utc": utc(started),
            "finished_at_utc": utc(finished),
            "source": self.source,
            "dests": [d.root for d in self.dests],
            "total": len(rels),
            "ok": ok,
            "failed": len(rels) - ok - skipped_locked,
            "skipped_locked": skipped_locked,
            "skipped_links": len(links),
            "skipped_system": len(system),
            "bytes_read": bytes_read,
            "seconds": round(finished - started, 1),
            "mb_per_s": round(bytes_read / (1 << 20) / max(finished - started, 1e-3), 1),
            "verdict": verdict,
            "previous_run_interrupted": self.interrupted,
            "per_dest": [{"dest": d.root, "fs": d.fs, "ok": len(d.entries), "failed": len(rels) - len(d.entries),
                          "ledger_written": d.ledger_written} for d in self.dests],
        }
        text = _report_text(report, self.incidents, links, system)
        for d in self.dests:
            if d.alive:
                self.write_reports(d, report, text)
        if self.incidents and report["verdict"] == SAFE:
            report["verdict"] = FAIL
            text = _report_text(report, self.incidents, links, system)
            for d in self.dests:
                if d.alive:
                    self.write_reports(d, report, text)
        marker_failed = False
        for d in self.dests:
            if d.alive and d.ledger_written and d.reports_written:
                try:
                    os.remove(contained_path(lp(d.root), RUNNING))
                except OSError as e:
                    self.fail(d, RUNNING, e, 1)
                    report["verdict"] = FAIL
                    marker_failed = True
        if marker_failed:
            text = _report_text(report, self.incidents, links, system)
            for d in self.dests:
                if d.alive:
                    self.write_reports(d, report, text)
        self.emit({"event": "done", "report": report, "text": text})
        return report

    def write_reports(self, d, report, text):
        root = lp(d.root)
        items = [(REPORT_JSON, json.dumps(report, indent=1, ensure_ascii=True).encode("ascii")),
                 (REPORT_TXT, text.encode("utf-8", "backslashreplace")),
                 (INCIDENT_JSON, json.dumps(self.incidents, indent=1, ensure_ascii=True).encode("ascii")),
                 (INCIDENT_TXT, _incident_text(self.incidents).encode("utf-8", "backslashreplace"))]
        try:
            for name, data in items:
                ledger.write_verified(contained_path(root, name), data)
            d.reports_written = True
        except OSError as e:
            d.reports_written = False
            self.fail(d, REPORT_TXT, e, 1)

    # --- helpers

    def src(self, rel):
        root = lp(self.source)
        return os.path.join(root, rel.replace("/", "\\")) if rel else root

    def dst(self, d, rel):
        return contained_path(lp(d.root), rel)

    def fail(self, d, rel, exc, attempts):
        reason = classify(exc, d.root)
        self.incident(rel, d, reason, attempts, exc)
        if reason in ("yanked", "disk_full"):  # stop writing to this drive: remaining files become incidents without attempts
            d.alive = False
            d.dead_reason = reason

    def incident(self, rel, dest, reason, attempts, detail):
        item = {"rel_path": rel, "dest": dest.root if dest else None, "reason": reason,
                "attempts": attempts, "detail": str(detail)}
        self.incidents.append(item)
        self.emit({"event": "incident", **item})

    def progress(self, pos, force=False):
        now = time.monotonic()
        if force or now - self.last_progress >= 0.2:
            self.last_progress = now
            self.emit({"event": "progress", "files_done": self.files_done, "bytes_done": self.bytes_done + pos,
                       "current": self.current})


def _rewrite(src, tmp) -> str:
    """Rewrites tmp from the source for one dest; returns the xxh64 of the source read."""
    h = xxhash.xxh64()
    with open(src, "rb", buffering=0) as f, open(tmp, "wb") as out:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    return h.hexdigest()


def _drop(path, out=None):
    """Removes tmp. If the drive is already gone, tmp stays and the next run cleans it up."""
    if out is not None:
        try:
            out.close()
        except OSError:
            pass
    try:
        os.remove(path)
    except OSError:
        pass


def _remove_stale_tmps(root):
    """Deletes only our own tmp files in dest, matching exactly .vaultdrop-tmp-<16 hex>."""
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(dirpath, name))
                   and not os.path.isjunction(os.path.join(dirpath, name))]
        for name in names:
            if TMP_RE.fullmatch(name):
                try:
                    os.remove(os.path.join(dirpath, name))
                except OSError:
                    pass


def _source_reason(exc) -> str:
    return "locked" if isinstance(exc, PermissionError) else "io_error"


def _key(path) -> str:
    return os.path.normcase(os.path.realpath(path)).rstrip("\\")


def _size(path) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def _report_text(r, incidents, links, system) -> str:
    safe = r["verdict"] == SAFE
    lines = [
        t("rep.copy_title", version=r["vaultdrop_version"]),
        t("rep.result", verdict=t("verdict.safe" if safe else "verdict.fail")),
        "",
        t("rep.source", path=r["source"]),
        t("rep.copies", list=", ".join(f"{p['dest']} ({p['fs'] or '?'})" for p in r["per_dest"])),
        t("rep.files", total=r["total"], ok=r["ok"]),
        t("rep.volume", size=fmt_size(r["bytes_read"]), time=fmt_duration(r["seconds"]),
          speed=fmt_size(int(r["mb_per_s"] * (1 << 20)))),
        t("rep.period", start=fmt_time(r["started_at_utc"]), end=fmt_time(r["finished_at_utc"])),
        "",
    ]
    if safe:
        lines.append(t("rep.safe"))
        if len(r["dests"]) == 1:
            lines.append(t("rep.one_copy"))
    else:
        lines.append(t("rep.fail"))
        lines += [t("rep.no_ledger", dest=p["dest"]) for p in r["per_dest"] if not p["ledger_written"]]
        by_reason = {}
        for i in incidents:
            by_reason.setdefault(i["reason"], []).append(i)
        for reason, items in by_reason.items():
            lines += ["", f"{t('reason.' + reason)} — {len(items)}:"]
            lines += [f"  {i['rel_path']}" + (f"  [{i['dest']}]" if i["dest"] else "") for i in items[:20]]
            if len(items) > 20:
                lines.append("  " + t("rep.more", n=len(items) - 20, file=INCIDENT_TXT))
    if r["previous_run_interrupted"]:
        lines += ["", t("rep.interrupted", list=", ".join(r["previous_run_interrupted"]))]
    if links:
        lines += ["", t("rep.links", n=len(links))]
    if system:
        lines += ["", t("rep.system", list=", ".join(system))]
    lines += ["", t("rep.eject"), t("rep.verify_hint", path=r["dests"][0])]
    return "\n".join(lines) + "\n"


def _incident_text(incidents) -> str:
    if not incidents:
        return t("inc.none") + "\n"
    lines = [t("inc.count", n=len(incidents)), t("inc.header"), ""]
    for i in incidents:
        lines.append(f"{i['rel_path']} | {i['dest'] or t('inc.source')} | {i['reason']}: {t('reason.' + i['reason'])}"
                     f" | {i['attempts']} | {i['detail']}")
    return "\n".join(lines) + "\n"
