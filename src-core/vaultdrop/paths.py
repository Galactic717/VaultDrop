"""Windows path boundaries shared by copy and verification."""

import os
import re


def relative_path(value: str) -> str:
    """Accept only canonical, portable ledger paths, never drives or streams."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("invalid relative path")
    parts = value.split("/")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((" ", "."))
                or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)):
            raise ValueError("unsafe relative path")
    return value


def contained_path(root: str, rel: str) -> str:
    relative_path(rel)
    path = os.path.join(root, *rel.split("/"))
    base = os.path.normcase(os.path.realpath(root))
    resolved = os.path.normcase(os.path.realpath(path))
    try:
        inside = os.path.commonpath([base, resolved]) == base
    except ValueError:  # A junction can point at a different drive.
        inside = False
    if not inside:
        raise OSError("Path leaves the backup folder through a link: " + rel)
    # Even links that stay inside a backup are not regular backup data.
    current = root
    for part in rel.split("/"):
        current = os.path.join(current, part)
        if os.path.islink(current) or os.path.isjunction(current):
            raise OSError("Linked backup entries are not supported: " + rel)
    return path
