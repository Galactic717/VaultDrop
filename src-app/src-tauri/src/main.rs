// A single window over the CLI: vaultdrop.exe (--json) copies and verifies, its events are streamed to the window.
// Drives, folder size and backup discovery are computed in Rust: instant, no CLI launch needed.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::ptr::{null, null_mut};

use serde::Serialize;
use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use windows_sys::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, GetDiskFreeSpaceExW, GetDriveTypeW, GetLogicalDrives, GetVolumeInformationW,
    FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING,
};
use windows_sys::Win32::System::Ioctl::{
    PropertyStandardQuery, StorageDeviceProperty, IOCTL_STORAGE_GET_DEVICE_NUMBER,
    IOCTL_STORAGE_QUERY_PROPERTY, STORAGE_DEVICE_DESCRIPTOR, STORAGE_DEVICE_NUMBER,
    STORAGE_PROPERTY_QUERY,
};
use windows_sys::Win32::System::IO::DeviceIoControl;

const DRIVE_REMOVABLE: u32 = 2;
const DRIVE_FIXED: u32 = 3;
const BUS_TYPE_USB: i32 = 7; // STORAGE_BUS_TYPE::BusTypeUsb

/// Translations are embedded in the exe from the same files the Python core reads. New language = one new line here.
const LOCALES: &[(&str, &str)] = &[
    (
        "de",
        include_str!("../../../src-core/vaultdrop/locales/de.json"),
    ),
    (
        "en",
        include_str!("../../../src-core/vaultdrop/locales/en.json"),
    ),
    (
        "es",
        include_str!("../../../src-core/vaultdrop/locales/es.json"),
    ),
    (
        "fr",
        include_str!("../../../src-core/vaultdrop/locales/fr.json"),
    ),
    (
        "pl",
        include_str!("../../../src-core/vaultdrop/locales/pl.json"),
    ),
    (
        "uk",
        include_str!("../../../src-core/vaultdrop/locales/uk.json"),
    ),
];

mod runtime;
use runtime::{cancel_run, run_cli, stop_running, Running};

#[derive(Serialize)]
struct Drive {
    root: String,
    label: String,
    fs: String,
    total: u64,
    free: u64,
    usb: bool,
    removable: bool,
    system: bool,
    /// Physical disk number: two partitions of one SSD share it, so a copy between them protects nothing.
    disk: Option<u32>,
}

#[derive(Serialize)]
struct Backup {
    path: String,
    source: Option<String>,
    finished: Option<String>,
    files: Option<u64>,
    bytes: Option<u64>,
    verdict: Option<String>,
}

#[derive(Serialize)]
struct FolderInfo {
    exists: bool,
    empty: bool,
    backup: bool,
    source: Option<String>,
}

#[derive(Serialize)]
struct Stats {
    files: u64,
    bytes: u64,
    errors: u64,
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn from_wide(buf: &[u16]) -> String {
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..end])
}

#[tauri::command]
fn locales() -> Vec<(&'static str, &'static str)> {
    LOCALES.to_vec()
}

/// Bit mask of drive letters: cheap to poll, so a newly plugged-in drive is noticed.
#[tauri::command]
fn drive_mask() -> u32 {
    unsafe { GetLogicalDrives() }
}

#[tauri::command]
async fn list_drives() -> Result<Vec<Drive>, String> {
    tauri::async_runtime::spawn_blocking(enumerate_drives)
        .await
        .map_err(|e| e.to_string())
}

fn enumerate_drives() -> Vec<Drive> {
    let mask = unsafe { GetLogicalDrives() };
    let system = std::env::var("SystemDrive")
        .unwrap_or_default()
        .to_uppercase();
    (0..26u8)
        .filter(|i| mask & (1 << i) != 0)
        .filter_map(|i| {
            let letter = (b'A' + i) as char;
            let root = format!("{letter}:\\");
            let w = wide(&root);
            let kind = unsafe { GetDriveTypeW(w.as_ptr()) };
            if kind != DRIVE_REMOVABLE && kind != DRIVE_FIXED {
                return None;
            }
            let mut label = [0u16; 261];
            let mut fs = [0u16; 261];
            let ok = unsafe {
                GetVolumeInformationW(
                    w.as_ptr(),
                    label.as_mut_ptr(),
                    261,
                    null_mut(),
                    null_mut(),
                    null_mut(),
                    fs.as_mut_ptr(),
                    261,
                )
            };
            if ok == 0 {
                return None; // empty card reader or a volume without a file system
            }
            let (mut free, mut total) = (0u64, 0u64);
            unsafe { GetDiskFreeSpaceExW(w.as_ptr(), &mut free, &mut total, null_mut()) };
            let (usb, disk) = device_info(letter);
            Some(Drive {
                root,
                label: from_wide(&label),
                fs: from_wide(&fs),
                total,
                free,
                usb,
                removable: kind == DRIVE_REMOVABLE,
                system: system == format!("{letter}:"),
                disk,
            })
        })
        .collect()
}

/// Bus type (USB or not) and physical disk number. Access mask 0, so no admin rights are needed.
fn device_info(letter: char) -> (bool, Option<u32>) {
    let path = wide(&format!("\\\\.\\{letter}:"));
    let handle = unsafe {
        CreateFileW(
            path.as_ptr(),
            0,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            null(),
            OPEN_EXISTING,
            0,
            null_mut(),
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return (false, None);
    }
    let mut returned = 0u32;
    let query = STORAGE_PROPERTY_QUERY {
        PropertyId: StorageDeviceProperty,
        QueryType: PropertyStandardQuery,
        AdditionalParameters: [0],
    };
    let mut descriptor = [0u8; 1024];
    let usb = unsafe {
        DeviceIoControl(
            handle,
            IOCTL_STORAGE_QUERY_PROPERTY,
            &query as *const _ as *const _,
            std::mem::size_of::<STORAGE_PROPERTY_QUERY>() as u32,
            descriptor.as_mut_ptr() as *mut _,
            descriptor.len() as u32,
            &mut returned,
            null_mut(),
        ) != 0
            && std::ptr::read_unaligned(descriptor.as_ptr() as *const STORAGE_DEVICE_DESCRIPTOR)
                .BusType
                == BUS_TYPE_USB
    };
    let mut number: STORAGE_DEVICE_NUMBER = unsafe { std::mem::zeroed() };
    let disk = unsafe {
        DeviceIoControl(
            handle,
            IOCTL_STORAGE_GET_DEVICE_NUMBER,
            null(),
            0,
            &mut number as *mut _ as *mut _,
            std::mem::size_of::<STORAGE_DEVICE_NUMBER>() as u32,
            &mut returned,
            null_mut(),
        ) != 0
    }
    .then_some(number.DeviceNumber);
    unsafe { CloseHandle(handle) };
    (usb, disk)
}

/// File count and total size of a folder, so the user can see whether it fits on the drive.
#[tauri::command]
async fn folder_stats(path: String) -> Result<Stats, String> {
    tauri::async_runtime::spawn_blocking(move || scan_folder(path))
        .await
        .map_err(|e| e.to_string())?
}

fn scan_folder(path: String) -> Result<Stats, String> {
    if !Path::new(&path).is_dir() {
        return Err(format!("Folder not found: {path}"));
    }
    let mut stats = Stats {
        files: 0,
        bytes: 0,
        errors: 0,
    };
    let mut stack = vec![PathBuf::from(path)];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            stats.errors += 1;
            continue;
        };
        for entry in entries {
            let Ok(entry) = entry else {
                stats.errors += 1;
                continue;
            };
            let Ok(meta) = entry.metadata() else {
                stats.errors += 1;
                continue;
            };
            use std::os::windows::fs::MetadataExt;
            if meta.file_attributes() & 0x400 != 0 {
                continue;
            } // all reparse points, including junctions
            let Ok(kind) = entry.file_type() else {
                stats.errors += 1;
                continue;
            };
            if kind.is_symlink() {
                continue;
            }
            if kind.is_dir() {
                stack.push(entry.path());
            } else if let Ok(meta) = entry.metadata() {
                stats.files += 1;
                stats.bytes += meta.len();
            }
        }
    }
    Ok(stats)
}

#[tauri::command]
fn inspect_folder(path: String) -> FolderInfo {
    let p = Path::new(&path);
    FolderInfo {
        exists: p.exists(),
        empty: std::fs::read_dir(p)
            .map(|mut it| it.next().is_none())
            .unwrap_or(true),
        backup: p.join(".vaultdrop.json").is_file(),
        source: std::fs::read(p.join(".vaultdrop.json"))
            .ok()
            .and_then(|data| serde_json::from_slice::<serde_json::Value>(&data).ok())
            .and_then(|doc| doc["source_label"].as_str().map(String::from)),
    }
}

/// VaultDrop backups: X:\VaultDrop Backups\* on every drive plus folders this computer has already backed up to.
#[tauri::command]
async fn find_backups(extra: Vec<String>) -> Result<Vec<Backup>, String> {
    tauri::async_runtime::spawn_blocking(move || discover_backups(extra))
        .await
        .map_err(|e| e.to_string())
}

fn discover_backups(extra: Vec<String>) -> Vec<Backup> {
    let mut candidates: Vec<PathBuf> = extra.into_iter().map(PathBuf::from).collect();
    for drive in enumerate_drives() {
        if let Ok(entries) = std::fs::read_dir(Path::new(&drive.root).join("VaultDrop Backups")) {
            candidates.extend(entries.flatten().map(|e| e.path()));
        }
    }
    let mut seen = HashSet::new();
    candidates
        .into_iter()
        .filter(|p| p.join(".vaultdrop.json").is_file())
        .filter(|p| seen.insert(p.to_string_lossy().to_lowercase()))
        .map(|p| {
            let report: Option<serde_json::Value> = std::fs::read(p.join("vaultdrop-report.json"))
                .ok()
                .and_then(|bytes| serde_json::from_slice(&bytes).ok());
            let text = |key: &str| {
                report
                    .as_ref()
                    .and_then(|r| r[key].as_str())
                    .map(String::from)
            };
            let count = |key: &str| report.as_ref().and_then(|r| r[key].as_u64());
            Backup {
                path: p.display().to_string(),
                source: text("source"),
                finished: text("finished_at_utc"),
                files: count("total"),
                bytes: count("bytes_read"),
                verdict: text("verdict"),
            }
        })
        .collect()
}

/// Opens a folder in Explorer or a report file in its default app.
#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    if !Path::new(&path).exists() {
        return Err(format!("{path}: not found"));
    }
    Command::new("explorer")
        .arg(&path)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn pick_folder(app: AppHandle) -> Option<String> {
    app.dialog()
        .file()
        .blocking_pick_folder()
        .and_then(|p| p.into_path().ok())
        .map(|p| p.display().to_string())
}

/// Native warning dialog with translated buttons. Returns true if the user pressed OK.
#[tauri::command]
async fn ask(app: AppHandle, title: String, message: String, ok: String, cancel: String) -> bool {
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(ok, cancel))
        .blocking_show()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Running::default())
        .invoke_handler(tauri::generate_handler![
            locales,
            drive_mask,
            list_drives,
            folder_stats,
            inspect_folder,
            find_backups,
            open_path,
            pick_folder,
            ask,
            run_cli,
            cancel_run
        ])
        .build(tauri::generate_context!())
        .expect("VaultDrop failed to start")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                let _ = stop_running(app);
            }
        });
}
