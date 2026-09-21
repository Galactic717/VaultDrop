"""Copy benchmarks on synthetic data: one 256 MiB file (1 and 2 copies) and 1000 files of 16 KiB.

Run from the project root:  .venv\\Scripts\\python bench\\bench_copy.py [backup_folder]
Without an argument, copies go to .tmp\\bench\\dest (same drive). Data is created in .tmp\\bench and deleted afterwards.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src-core"))

from vaultdrop.copier import run_copy  # noqa: E402
from vaultdrop.winio import hash_unbuffered, lp  # noqa: E402

MB = 1 << 20
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".tmp", "bench"))


def drop_cache(folder):
    """Reading with NO_BUFFERING drops the file from the cache (measured in P0), so copy reads the source from disk, not RAM."""
    for dirpath, _, names in os.walk(lp(folder)):
        for name in names:
            hash_unbuffered(os.path.join(dirpath, name))


def measure(label, source, dests):
    drop_cache(source)
    r = run_copy(source, dests)
    assert r["verdict"] == "SAFE TO FORMAT", r
    print(f"{label}: {r['total']} files, {r['bytes_read'] / MB:.0f} MiB in {r['seconds']} s -> "
          f"{r['mb_per_s']} MB/s, {r['total'] / max(r['seconds'], 0.001):.0f} files/s")
    for d in dests:
        shutil.rmtree(lp(d))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dest_root = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "dest")
    big, small = os.path.join(ROOT, "src-big"), os.path.join(ROOT, "src-small")
    os.makedirs(big, exist_ok=True)
    os.makedirs(small, exist_ok=True)
    block = os.urandom(64 * MB)
    with open(os.path.join(big, "big.bin"), "wb") as f:
        for _ in range(4):
            f.write(block)
    for i in range(1000):
        with open(os.path.join(small, f"s{i:04}.bin"), "wb") as f:
            f.write(block[i * 16384:(i + 1) * 16384])
    # Delete only our own uniquely named folders; never touch anything else, even on a name clash.
    a, b = (os.path.join(dest_root, f"vaultdrop-bench-{x}") for x in "ab")
    if os.path.exists(a) or os.path.exists(b):
        sys.exit(f"{a} or {b} already exists, remove it manually")
    try:
        measure("256 MiB -> 1 copy      ", big, [a])
        measure("256 MiB -> 2 copies    ", big, [a, b])
        measure("1000 x 16 KiB -> 1 copy ", small, [a])
    finally:
        shutil.rmtree(lp(ROOT), ignore_errors=True)


if __name__ == "__main__":
    main()
