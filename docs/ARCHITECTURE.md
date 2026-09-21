# Reverse engineering and changes — VaultDrop 0.2.0

## Original system

The project was an operational Windows-only MVP, not an empty scaffold. The baseline had 24 passing Python tests, a Tauri 2 shell, vanilla HTML/CSS/JavaScript, and a Python 3.12 CLI packaged with PyInstaller. It had no Git repository. A source snapshot was saved in `.tmp/before-redesign-20260921-152801.zip` before editing.

The two supported product workflows are **copy a folder to one or two local destinations** and **verify an existing backup**. Cloud storage, encryption, synchronization and scheduling are outside this product's current scope.

## Data and execution flow

```text
UI (app.js + model.js)
  ↕ bridge.js: typed-by-convention Tauri commands and events
Tauri Windows shell
  ├─ main.rs: volumes, folder selection, scans, backup discovery, locales
  └─ runtime.rs: one worker process, stdout/stderr, cancellation, exit status
       ↕ JSON Lines (--json)
Python CLI (cli.py)
  ├─ copier.py: preflight → stream → read-back → atomic replacement → reports
  ├─ verifier.py: validated index → read-back → integrity and completeness verdict
  ├─ ledger.py: verified index and checksum writes
  ├─ paths.py: canonical relative paths and destination boundaries
  ├─ locking.py: exclusive Windows byte-range destination locks
  └─ winio.py: long paths, uncached reads, drive error classification, sleep prevention
```

The source is streamed once to temporary destination files while xxHash64 is computed. Each destination is flushed, read using `FILE_FLAG_NO_BUFFERING`, compared and atomically renamed. The index (`.vaultdrop.json`) and its checksum are also written through read-back verification. This established mechanism was retained; replacing it with a browser filesystem or a second implementation in Rust would add risk without improving the product.

## Defects found and addressed

| Finding | Change |
|---|---|
| Verification returned INTACT for an intact subset of a failed/interrupted backup. | INCOMPLETE is now a distinct result, yields CLI exit 1 and an amber UI result. |
| Index validation merely checked the presence of three fields. | Validate relative paths, nonnegative integer sizes, hash format and case-insensitive duplicate paths. |
| Destination links could redirect writes outside the backup. | Resolve path boundaries and reject symlink/junction destination entries before writes and checks. |
| Two processes could copy into the same destination and clean each other's temporary files. | OS-managed byte-range locks across all destinations, released automatically on process death. |
| Report-writing failures occurred after the successful verdict had already been calculated. | A report failure changes the final result to FAIL; unfinished metadata keeps the running marker. |
| GUI could launch overlapping worker processes. | Rust owns one locked worker slot; JS guards both preflight and execution. |
| Worker could exit without a done event, leaving an unexplained error. | Exit status and missing results are surfaced; stderr is collected before exit notification. |
| Large folder scans performed synchronous I/O on the async executor. | Folder/volume/backup scans use blocking workers; reparse points are skipped; partial scan counts are shown. |
| Matching folder names from different sources silently shared the same backup location. | Existing backup source is inspected; replacing another source requires a specific in-app confirmation. |
| No stop action inside the main workflow. | Stop action terminates the owned process tree; restart uses the existing interrupted-copy recovery. |
| Copy results advised unconditionally formatting the source. | UI states what was verified and recommends retaining an independent copy. Legacy machine verdict retained for compatibility. |

## Interface

A desktop workspace with a dark navigation panel, off-white content, restrained green accents and visible source/destination steps replaces the original stacked form. A backup summary stays beside the setup at the default width. The UI includes drive capacity, selected states, same-disk/system-disk warnings, empty states, progress, cancellation, errors and results. It adapts to a 760 px window. Keyboard tab navigation, focus indicators and reduced-motion preferences are supported. All six existing locales are preserved and expanded; no remote fonts or CDN assets are used.

`bridge.js` is the desktop boundary. `model.js` contains pure result and progress decisions. Browser integration tests inject their own host double; no sample drives or fake copy operations are shipped in the UI.

## Validation

- 49 Python tests: original copy/verify cases plus metadata validation, incomplete backups, exclusive locks, report-write failure, junction escape and resolved overlap.
- 5 JavaScript model tests.
- Browser integration: successful copy, verification, incomplete copy, cancellation, abnormal worker exit, missing source, six languages, compact layout; screenshots inspected.
- Rust compilation and release build through `build.ps1`.
- See `VALIDATION.md` for packaged application checks and remaining hardware limitations.

## Compatibility and boundaries

0.1 indexes with valid paths and hashes remain readable. Copy success still emits the legacy string `SAFE TO FORMAT` so existing consumers keep working. Verification adds `INCOMPLETE`; consumers should treat anything other than `INTACT` as non-success. `.vaultdrop.lock` is a small persistent coordination file, not evidence that a job is running. `.vaultdrop.running` records interrupted work or unfinished metadata.

This remains a file backup utility, not a full disk-image or snapshot system. It does not copy ACLs, ADS, links or filesystem metadata beyond file modification times. xxHash is for accidental corruption, not adversarial tampering. Path checks protect existing static links; they are not a sandbox against another process racing to alter directory links between checks and writes. Hardware failure testing, signed distribution and testing on Windows 10 still require external work.
