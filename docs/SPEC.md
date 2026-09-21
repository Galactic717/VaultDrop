> Historical document for version 0.1. Current state of 0.2: [architecture](ARCHITECTURE.md), [validation](VALIDATION.md), [limitations](LIMITATIONS.md).

# VaultDrop MVP spec — frozen 2026-09-21
# Built from scratch. Earlier projects are context only.

## 1. Scenarios

S1 Ingest: source dir -> dest1 (+dest2 optional) -> Start -> report + verdict.
S2 Verify: target dir (a former dest) -> Verify -> intact/changed/missing per file.

## 2. Copy algorithm (core written from scratch)

```
for each file in walk(source):
  rel = relative_path(file)
  h1 = xxhash64_stream(read(file, chunks=1MB))
  if mtime changed during read: re-read once, else mark unstable+incident
  for dest in [dest1, dest2]:
    tmp = dest / rel + ".vaultdrop-tmp-<rand>"
    write_stream(file -> tmp)
    h2 = xxhash64_stream(read(tmp from disk))
    if h1 != h2: retry once; if again != : incident[rel]+=dest_fail; continue
    rename(tmp -> dest/rel)
  ledger_entry[rel] = {size, mtime_utc, xxhash64_hex=h1, copied_at_utc}
write .vaultdrop.json + report.json + report.txt in each dest
verdict = SAFE TO FORMAT if all files matched in all dests else FAIL
```

Temp files left after a crash are ignored on the next run (mask `.vaultdrop-tmp-*`).

## 3. Ledger schema `.vaultdrop.json`

```json
{
  "vaultdrop_version": "0.1.0",
  "created_at_utc": "2026-09-21T10:00:00Z",
  "source_label": "D:\\Projects",
  "files": [
    {
      "rel_path": "docs/SPEC.md",
      "size": 12345,
      "mtime_utc": "2026-09-21T09:00:00Z",
      "xxhash64_hex": "9d2a...",
      "copied_at_utc": "2026-09-21T10:01:00Z"
    }
  ]
}
```

`report.json`: {total, ok, failed, skipped_locked, verdict}
`incident.json`: [{rel_path, dest, reason: mismatch/locked/yanked/power, attempts}]

## 4. Failure handling

- USB drive unplugged: write/verify catches OSError -> incident yanked -> FAIL for those files, the run continues, no crash.
- Locked file: skip + incident locked, the run does not fail.
- Zero-byte files, non-ASCII names, spaces, paths over 260 characters via `\\?\`: supported.
- File changed while being read: one re-read, otherwise unstable.
- The source is never deleted. The code never formats a destination.

## 5. Stack and paths

- Python 3.12 core, packages: xxhash. CLI with argparse.
- The Tauri UI calls the same CLI.
- Project, caches and venv on one drive. ASCII paths.
- Offline: a run with Wi-Fi switched off must succeed.

## 6. Phases

P0 spec (this file + market notes), no code.
P1 core copy + hash + 5 tests.
P2 verify + ledger + re-verify after changing one byte.
P3 CLI + single-window Tauri UI.
P4 NSIS installer + README with a GIF + .exe release.

## 7. Non-goals for v1

Encryption, compression, cloud, scheduler, deduplication, macOS/Linux, AI. Out of scope.
