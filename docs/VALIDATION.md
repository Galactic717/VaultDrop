# Validation — VaultDrop 0.2.0

Date: 2026-09-21. Host: Windows 11 x64 (10.0.26200), Python 3.12.13, Tauri 2 / MSVC.

## Automated checks

| Check | Result |
|---|---|
| Original Python baseline | 24 passed before changes |
| Final Python suite | 49 passed |
| JavaScript presentation model | 5 passed |
| Browser integration (Microsoft Edge) | Passed |
| Rust `cargo check` | Passed |
| Release build (PyInstaller, Tauri, NSIS) | Passed |
| Packaged native UI + real engine | Passed |
| Native cancellation + recovery | Passed |

Browser scenarios cover source and destination selection, successful copy, verification, incomplete backup, cancellation, abnormal worker exit, unreadable source, switching all six languages, and layout at 1180×860 and 760×600. Browser tests use an explicit Tauri host double; sample files and drives in those screenshots are fictional.

Native tests connect to the packaged application's WebView2 in a dedicated test profile. Only native confirmation dialogs are automatically accepted for the generated test destinations; filesystem scans, process launch, progress, file operations and verification use the real Rust shell and packaged Python engine.

## Actual packaged-application checks

Test directories, all under this project:

- `.tmp/native-smoke-1789995338561`: three files, two destinations. Includes a zero-byte file and a binary file of 4 MiB + 73 bytes in a path containing Ukrainian characters and a comma. Both destinations matched the source bytes. Rechecking returned an intact result. Flipping one byte in a copied file produced a damaged result identifying the correct file. Source contents remained unchanged.
- `.tmp/native-cancel-1789995343023`: a 64 MiB generated file. The actual process tree was stopped after the running marker appeared. The UI showed cancellation; the marker remained. Restart acquired the OS lock, recovered interrupted work, removed temporary files, verified the entire file, and removed the running marker.

The files in `D:\promin` were not used as test data and were not edited or deleted. The old README merely mentioned that path in a CLI example. Volume discovery reads Windows drive metadata; backup discovery looks in the conventional `VaultDrop Backups` directories and saved test history.

Visual inspection covered setup, compact layout, progress, success, empty verification, and native damaged results. Screenshots are under `docs/screenshots`; names beginning `native-` show the real packaged app.

## Release contents

- `dist/VaultDrop_0.2.0_x64-setup.exe` — NSIS installer.
- `dist/VaultDrop-0.2.0-portable.zip` — portable distribution.
- `dist/VaultDrop-0.2.0-portable/VaultDrop Desktop.exe` — GUI.
- `dist/VaultDrop-0.2.0-portable/vaultdrop.exe` — adjacent worker, required by the GUI.
- `dist/vaultdrop.exe` — standalone CLI.
- `dist/SHA256SUMS.txt` — hashes for the distribution files.

The portable package intentionally uses different GUI and worker names: Windows treats `VaultDrop.exe` and `vaultdrop.exe` as the same filename. The packaged launch test caught and corrected this collision before delivery. The previous 0.1 installer was preserved.

## Reproducing tests

```powershell
.venv\Scripts\python -m pytest -q
npm --prefix src-app ci
npm --prefix src-app test
npm --prefix src-app run test:ui
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

For native tests, start the packaged GUI with a dedicated `WEBVIEW2_USER_DATA_FOLDER` under `.tmp` and `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=19371`, then run `node tests/native-smoke.cjs` and `node tests/native-cancel.cjs` from `src-app`. These tests create their own timestamped fixture directories. Close that test instance afterward. The debugging flag is an environment override used only for testing, not a shipped default.

## What this does not prove

No clean-machine install/uninstall test, Windows 10 run, actual USB unplug, real FAT32-volume test or independent USB performance benchmark was performed. The binaries are unsigned. Tauri reported an upstream warning about some Polish NSIS-specific strings; application translations are present. See `LIMITATIONS.md` for the product's filesystem and snapshot boundaries.
