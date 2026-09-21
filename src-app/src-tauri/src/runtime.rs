//! Owns the single worker process and the JSON-lines event transport.
use std::io::{BufRead, BufReader, Read};
use std::os::windows::process::CommandExt;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[derive(Default)]
pub struct Running(pub Mutex<Option<u32>>);

#[tauri::command]
pub fn run_cli(app: AppHandle, args: Vec<String>) -> Result<(), String> {
    if !matches!(args.first().map(String::as_str), Some("copy" | "verify")) {
        return Err("Only copy and verify operations are supported".into());
    }
    let state = app.state::<Running>();
    let mut running = state.0.lock().map_err(|e| e.to_string())?;
    if running.is_some() {
        return Err("An operation is already running".into());
    }
    let cli = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .with_file_name("vaultdrop.exe");
    #[cfg(debug_assertions)]
    let cli = if cli.exists() {
        cli
    } else {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("binaries/vaultdrop-x86_64-pc-windows-msvc.exe")
    };
    let mut child = Command::new(&cli)
        .args(&args)
        .arg("--json")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|e| format!("{}: {e}", cli.display()))?;
    let pid = child.id();
    *running = Some(pid);
    drop(running);

    let mut stderr = child.stderr.take().expect("stderr piped");
    let err_app = app.clone();
    let error_reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 4096];
        while let Ok(n) = stderr.read(&mut chunk) {
            if n == 0 {
                break;
            }
            bytes.extend_from_slice(&chunk[..n]);
            if bytes.len() > 131072 {
                bytes.drain(..bytes.len() - 131072);
            }
        }
        let text = String::from_utf8_lossy(&bytes).into_owned();
        if !text.trim().is_empty() {
            let _ = err_app.emit("cli-stderr", text);
        }
    });
    let stdout = child.stdout.take().expect("stdout piped");
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let _ = app.emit("cli-line", line);
        }
        let code = child.wait().ok().and_then(|s| s.code()).unwrap_or(-1);
        let _ = error_reader.join();
        if let Ok(mut running) = app.state::<Running>().0.lock() {
            if *running == Some(pid) {
                *running = None;
            }
        }
        let _ = app.emit("cli-exit", code);
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.request_user_attention(Some(tauri::UserAttentionType::Informational));
        }
    });
    Ok(())
}

#[tauri::command]
pub async fn cancel_run(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || stop_running(&app))
        .await
        .map_err(|e| e.to_string())?
}

pub fn stop_running(app: &AppHandle) -> Result<(), String> {
    // Hold the lock through termination, so a newer worker cannot reuse this slot.
    let state = app.state::<Running>();
    let running = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(pid) = *running {
        let status = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|e| e.to_string())?;
        if !status.success() {
            return Err("The worker could not be stopped. It may already have finished.".into());
        }
    }
    Ok(())
}
