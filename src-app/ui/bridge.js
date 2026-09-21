// The only module that knows about the desktop host.
export async function invoke(command, args = {}) {
  if (!window.__TAURI__) throw new Error("Open VaultDrop from the Windows application.");
  return window.__TAURI__.core.invoke(command, args);
}

export async function listen(name, callback) {
  if (!window.__TAURI__) throw new Error("The VaultDrop desktop host is unavailable.");
  return window.__TAURI__.event.listen(name, callback);
}

export function currentWindow() {
  return window.__TAURI__?.window.getCurrentWindow();
}
