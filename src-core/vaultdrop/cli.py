"""Command line: vaultdrop copy / vaultdrop verify. Exit codes: 0 - all good, 1 - problems found, 2 - failed to run."""

import argparse
import json
import sys

from . import VaultDropError, __version__, i18n
from .copier import run_copy
from .i18n import t
from .verifier import run_verify
from .winio import keep_awake


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    # The language must be known before --help is built, so --lang is read in a separate first pass.
    early = argparse.ArgumentParser(add_help=False)
    early.add_argument("--lang")
    i18n.load(early.parse_known_args(argv)[0].lang)

    parser = argparse.ArgumentParser(prog="vaultdrop", description=t("cli.description"))
    parser.add_argument("--version", action="version", version=f"vaultdrop {__version__}")
    parser.add_argument("--lang", help=t("cli.lang", langs=", ".join(i18n.available())))
    sub = parser.add_subparsers(dest="command", required=True)
    copy = sub.add_parser("copy", help=t("cli.copy"))
    copy.add_argument("--source", required=True, help=t("cli.source"))
    copy.add_argument("--dest", help=t("cli.dest"))
    # --to is not split on commas: this is how the UI passes folders such as "Photos, 2024".
    copy.add_argument("--to", action="append", default=[], help=t("cli.to"))
    verify = sub.add_parser("verify", help=t("cli.verify"))
    verify.add_argument("--target", required=True, help=t("cli.target"))
    for cmd in (copy, verify):
        cmd.add_argument("--json", action="store_true", help=t("cli.json"))
        cmd.add_argument("--lang", help=t("cli.lang", langs=", ".join(i18n.available())))
    args = parser.parse_args(argv)
    if args.command == "copy" and not (args.dest or args.to):
        copy.error(t("err.dest_count"))

    emit = _emit_json if args.json else _Console()
    try:
        with keep_awake():
            if args.command == "copy":
                dests = [d.strip() for d in (args.dest or "").split(",") if d.strip()] + args.to
                return 0 if run_copy(args.source, dests, emit)["verdict"] == "SAFE TO FORMAT" else 1
            return 0 if run_verify(args.target, emit)["result"] == "INTACT" else 1
    except (VaultDropError, OSError) as e:
        if args.json:
            _emit_json({"event": "error", "message": str(e)})
        else:
            print("\n" + t("cli.error", message=e), file=sys.stderr)
        return 2


def _emit_json(event) -> None:
    print(json.dumps(event, ensure_ascii=True), flush=True)


class _Console:
    """Human-readable output: progress and incidents to stderr, the final report to stdout."""

    def __init__(self):
        self.files = 0
        self.bytes = 0

    def __call__(self, ev) -> None:
        kind = ev["event"]
        if kind == "start":
            self.files, self.bytes = ev["files"], ev["bytes"]
        elif kind == "progress":
            pct = 100 * ev["bytes_done"] / self.bytes if self.bytes else 100.0
            progress = t("cli.progress", done=ev["files_done"], total=self.files)
            sys.stderr.write(f"\r  {min(pct, 100.0):5.1f}%  {progress}   ")
            sys.stderr.flush()
        elif kind in ("incident", "problem"):
            where = f" [{ev['dest']}]" if ev.get("dest") else ""
            reason = t("reason." + ev["reason"]) if "reason" in ev else t("state." + ev["state"])
            sys.stderr.write(f"\r  ! {ev['rel_path']}: {reason}{where}\n")
        elif kind == "done":
            sys.stderr.write("\n")
            print(ev["text"], end="", flush=True)
