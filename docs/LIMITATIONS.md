# VaultDrop 0.2.0 — limitations

## Product scope

- Windows x64. Tested on Windows 11; Windows 10 has not been tested yet. WebView2 is required.
- Copies a folder to one or two local drives and verifies the resulting backup. Network UNC paths are not supported.
- Every run copies the files again. There is no incremental mode, resume, deduplication, compression, encryption, cloud or scheduler.
- This is a file copy, not a disk image, system backup or VSS snapshot. Files that are in use or changing may not be copied; the result reports this.
- ACLs, alternate data streams, creation time and the hidden/read-only attributes are not preserved. Modification time is preserved.
- Symlinks and junctions in the source are skipped and counted in the report. They do not by themselves make an otherwise normal backup fail. In the destination, such entries are never used to write or verify files.
- Empty folders are created, but verify checks only the files listed in the index. Extra files in the destination are neither deleted nor checked.
- Case-sensitive Windows/WSL folders that contain both `A.txt` and `a.txt` are not supported.
- VaultDrop service names are not allowed in the source root. The root of an existing backup cannot be used as a new source.

## Verification scope

- xxHash64 detects accidental corruption. It is not cryptographic authentication of the files or the index.
- `fsync` and `FILE_FLAG_NO_BUFFERING` bypass the Windows cache, but they do not prove that the drive controller has flushed its own cache to flash memory.
- Data can still be damaged after a successful check. Keep an independent copy of important files and use Safely Remove Hardware.
- The source is not frozen. A write that keeps the file size and mtime, and changes to the set of files after the initial scan, may go unnoticed. Close programs that modify these files before copying.
- Path checks reject existing dangerous links and escapes outside the backup. They do not protect against a hostile process that swaps the directory tree between the check and the I/O operation.
- The index and its checksum are written with separate atomic replacements. If the run is interrupted between them, the index may fail verification; run the copy again.
- The `.vaultdrop.lock` service file stays in the backup. The file itself does not mean an operation is active; the OS lock is released when the process finishes or crashes.
- Two processes cannot write to the same destination at the same time. Do not verify a backup while it is being updated.

## Not yet tested on real hardware

- Physically unplugging a USB drive during a write: tests simulate an OS failure, but not a specific driver hanging.
- FAT32 behaviour on a real drive. The core rejects files larger than 4 GiB − 1 byte when the file system type is known.
- Speed on specific USB drives, degraded disks, RAID and Storage Spaces.
- Installing and uninstalling via NSIS on a clean Windows 10/11. The installer is built; the packaged GUI and the sidecar are tested separately.
- The pl/de/es/fr translations have not been reviewed by native speakers. Automated tests check keys and placeholders; the browser test checks language switching and that no untranslated keys remain.

## Practical notes

- By default the backup goes to `<drive>:\VaultDrop Backups\<source name>`. The app warns before replacing a backup of a different source; with the CLI, make sure `--to` points to the right folder.
- The local history of found backups keeps up to 20 paths. Reports in the backup are overwritten; there is no long-term version history.
- The scan in the UI is a preview. The authoritative file list is built by the core right before copying.
- On `subst` drives the physical disk or the USB bus cannot always be detected.
- `disk_full` stops further writes to that destination.
- The CLI `--dest` option splits paths on commas. For a path that contains a comma, use `--to`.
- PyInstaller `--onefile` unpacks the core to `%TEMP%` while it runs.
- The binaries and the installer are not code-signed, which may trigger a SmartScreen warning.
- Tauri reports that some of its own NSIS messages are missing in Polish. The app's own Polish translation is complete.
