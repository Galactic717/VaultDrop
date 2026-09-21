"use strict";

import { invoke, listen, currentWindow } from "./bridge.js";
import { resultVariant, progressFraction, pathKey } from "./model.js";
const $ = (id) => document.getElementById(id);

// Окреме ім'я, щоб копії не змішувались із чужою папкою «VaultDrop» у корені диска.
const BACKUP_DIR = "VaultDrop Backups";
const MAX_LISTED = 8; // файлів на кожну причину в підсумку; повний список — у звіті
const state = {
  lang: "en",
  locales: {},
  strings: {},
  source: "",
  sourceStats: null,
  statsToken: 0,
  drives: [],
  driveMask: -1,
  dests: [], // { root: "E:\\" } — папка BACKUP_DIR\<назва> на диску, або { custom: "шлях" }
  busy: false,
  starting: false,
  tab: "copy",
  run: null, // поточний або останній запуск CLI
};

// ---------- переклади й формати

function t(key, vars = {}) {
  const text = state.strings[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => (name in vars ? vars[name] : `{${name}}`));
}

async function initLanguage() {
  for (const [code, json] of await invoke("locales")) state.locales[code] = JSON.parse(json);
  const select = $("lang");
  for (const code of Object.keys(state.locales).sort()) select.add(new Option(state.locales[code]._name, code));
  let code = load("lang");
  if (!state.locales[code]) {
    // Англійський інтерфейс Windows часто стоїть за замовчуванням, а регіон людина обирає сама.
    const [ui, region] = await invoke("system_langs");
    const order = ui.toLowerCase().startsWith("en") ? [region, ui] : [ui, region];
    code = order.map((name) => name.split("-")[0].toLowerCase()).find((c) => state.locales[c]) || "en";
  }
  select.value = code;
  select.addEventListener("change", () => setLanguage(select.value));
  setLanguage(code);
}

function setLanguage(code) {
  state.lang = code;
  state.strings = { ...state.locales.en, ...state.locales[code] };
  document.documentElement.lang = code;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  save("lang", code);
  renderSource();
  renderDrives();
  renderDests();
  renderPlan();
  $("breadcrumb").textContent = t("ui.tab." + state.tab);
  $("app-status").textContent = t(state.busy ? "ui.working" : "ui.ready");
  if (!$("pane-verify").hidden) action(renderBackups)();
  if (state.run?.finished) renderResult();
}

function num(n, digits = 0) {
  return new Intl.NumberFormat(state.lang, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

function size(bytes) {
  for (const [unit, shift] of [["TB", 40], ["GB", 30], ["MB", 20], ["KB", 10]]) {
    const scale = 2 ** shift;
    if (bytes >= scale) return `${num(bytes / scale, bytes >= scale * 100 ? 0 : 1)} ${t("unit." + unit)}`;
  }
  return `${num(bytes)} ${t("unit.B")}`;
}

function duration(seconds) {
  const s = Math.max(1, Math.round(seconds));
  if (s < 60) return t("dur.s", { s });
  if (s < 3600) return t("dur.ms", { m: Math.floor(s / 60), s: s % 60 });
  return t("dur.hm", { h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60) });
}

function date(iso) {
  if (!iso || !Number.isFinite(Date.parse(iso))) return "—";
  return new Intl.DateTimeFormat(state.lang, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function load(key, fallback = null) {
  try {
    const value = localStorage.getItem("vaultdrop." + key);
    return value == null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

function save(key, value) {
  try { localStorage.setItem("vaultdrop." + key, JSON.stringify(value)); } catch { /* сховище недоступне */ }
}

function hint(text) {
  $("copy-hint").textContent = text;
}

function showError(error) {
  const box = $("global-error");
  box.textContent = String(error?.message || error);
  box.hidden = false;
}

function action(fn) {
  return (...args) => Promise.resolve().then(() => fn(...args)).catch(showError);
}

function renderPlan() {
  const stats = state.sourceStats;
  const ready = Boolean(state.source && stats?.files && state.dests.length && !state.busy && !state.starting);
  $("start").disabled = !ready;
  $("plan-files").textContent = stats ? num(stats.files) : "—";
  $("plan-size").textContent = stats ? size(stats.bytes) : "—";
  $("plan-copies").textContent = `${state.dests.length} / 2`;
  $("plan-title").textContent = state.source ? sourceName() : t("ui.plan_empty");
  document.querySelector(".plan-card").classList.toggle("ready", ready);
}

// ---------- що копіювати

function sourceName() {
  const parts = state.source.replace(/[\\/]+$/, "").split(/[\\/]/);
  const last = parts[parts.length - 1] || "backup";
  return last.endsWith(":") ? `Drive ${last[0]}` : last;
}

async function setSource(path) {
  $("global-error").hidden = true;
  state.source = path;
  state.sourceStats = null;
  save("source", path);
  hint("");
  renderSource();
  renderDrives();
  renderDests();
  const token = ++state.statsToken;
  const stats = await invoke("folder_stats", { path });
  if (token === state.statsToken) {
    state.sourceStats = stats;
    renderSource();
  }
}

function renderSource() {
  const box = $("source-path");
  box.textContent = state.source || t("ui.no_source");
  box.classList.toggle("empty", !state.source);
  $("source-name").textContent = state.source ? sourceName() : t("ui.pick_folder");
  $("source-change").hidden = !state.source;
  const stats = state.sourceStats;
  $("source-stats").textContent = !state.source ? t("ui.source_hint")
    : stats ? t("ui.source_stats", { files: num(stats.files), size: size(stats.bytes) }) : t("ui.counting");
  if (stats?.errors) $("source-stats").textContent += " · " + t("ui.scan_partial");
  renderPlan();
}

// ---------- куди копіювати

function driveOf(path) {
  const root = path.slice(0, 3).toUpperCase();
  return state.drives.find((d) => d.root.toUpperCase() === root);
}

function sameDisk(drive) {
  const src = state.source && driveOf(state.source);
  if (!src) return false;
  return src.root === drive.root || (src.disk != null && src.disk === drive.disk);
}

function destPath(dest) {
  return dest.custom || `${dest.root}${BACKUP_DIR}\\${sourceName()}`;
}

async function refreshDrives(force = false) {
  const mask = await invoke("drive_mask");
  if (!force && mask === state.driveMask) return;
  state.drives = await invoke("list_drives");
  state.driveMask = mask;
  state.dests = state.dests.filter((d) => d.custom || state.drives.some((x) => x.root === d.root));
  renderDrives();
  renderDests();
}

function rank(drive) {
  if (drive.system) return 3;
  if (sameDisk(drive)) return 2;
  return drive.usb || drive.removable ? 0 : 1;
}

function renderDrives() {
  const box = $("drives");
  box.textContent = "";
  if (!state.drives.length) {
    box.append(el("p", "muted", t("ui.drives_none")));
    return;
  }
  const sorted = [...state.drives].sort((a, b) => rank(a) - rank(b) || a.root.localeCompare(b.root));
  for (const drive of sorted) {
    const selected = state.dests.some((d) => d.root === drive.root);
    const card = el("button", "drive" + (selected ? " selected" : ""));
    card.type = "button";
    card.setAttribute("aria-pressed", String(selected));
    const badges = el("div", "badges");
    badges.append(drive.usb || drive.removable ? el("span", "badge usb", t("ui.badge.usb"))
      : el("span", "badge", t("ui.badge.internal")));
    if (drive.system) badges.append(el("span", "badge warn", t("ui.badge.system")));
    if (sameDisk(drive)) badges.append(el("span", "badge warn", t("ui.badge.same")));
    const meter = el("div", "meter");
    const fill = el("div", "fill");
    fill.style.width = `${drive.total ? Math.round(100 * (1 - drive.free / drive.total)) : 0}%`;
    meter.append(fill);
    const top = el("div", "drive-top");
    const heading = el("div", "drive-heading");
    heading.append(el("div", "drive-title", drive.label || drive.root.slice(0, 2)), el("div", "drive-fs", `${drive.root.slice(0, 2)} · ${drive.fs || "—"}`));
    top.append(el("span", "disk-icon"), heading, el("span", "drive-check"));
    card.append(top, badges, meter,
      el("div", "muted small", t("ui.drive_free", { free: size(drive.free), total: size(drive.total) })));
    card.addEventListener("click", () => toggleDest({ root: drive.root }));
    box.append(card);
  }
}

function toggleDest(dest) {
  const same = (d) => pathKey(destPath(d)) === pathKey(destPath(dest));
  const index = state.dests.findIndex(same);
  if (index >= 0) state.dests.splice(index, 1);
  else if (state.dests.length >= 2) return hint(t("ui.max_two"));
  else state.dests.push(dest);
  save("dests", state.dests);
  hint("");
  renderDrives();
  renderDests();
}

function renderDests() {
  const list = $("dest-list");
  list.textContent = "";
  $("dest-box").hidden = !state.dests.length;
  for (const dest of state.dests) {
    const item = el("li");
    const remove = el("button", "link", t("ui.remove"));
    remove.type = "button";
    remove.addEventListener("click", () => toggleDest(dest));
    item.append(el("span", "mono", destPath(dest)), remove);
    list.append(item);
  }
  renderPlan();
}

async function ask(key, path) {
  return invoke("ask", { title: t("ui.warn.title"), message: t(key, { path }), ok: t("ui.continue"), cancel: t("ui.cancel") });
}

async function startCopy() {
  if (state.busy || state.starting) return;
  state.starting = true;
  renderPlan();
  try {
  if (!state.source) return hint(t("ui.need_source"));
  if (!state.dests.length) return hint(t("ui.need_dest"));
  const paths = state.dests.map(destPath);
  const need = state.sourceStats?.bytes;
  for (const path of paths) {
    const drive = driveOf(path);
    const folder = await invoke("inspect_folder", { path });
    if (folder.backup && folder.source && pathKey(folder.source) !== pathKey(state.source)) {
      if (!(await ask("ui.warn.other_source", path))) return;
    }
    if (drive && need != null && !folder.exists && drive.free < need) {
      return hint(t("ui.warn.space", { path: drive.root, need: size(need), free: size(drive.free) }));
    }
    if (drive && sameDisk(drive)) {
      if (!(await ask("ui.warn.same_disk", path))) return;
    } else if (drive?.system && !(await ask("ui.warn.system", path))) {
      return;
    }
    if (folder.exists && !folder.empty && !folder.backup && !(await ask("ui.warn.not_empty", path))) return;
  }
  save("history", [...new Set([...paths, ...load("history", [])])].slice(0, 20));
  const args = ["copy", "--source", state.source];
  for (const path of paths) args.push("--to", path); // --to не ділить шлях за комою
  await execute("copy", args, { dests: paths });
  } finally {
    state.starting = false;
    renderPlan();
  }
}

// ---------- перевірка

async function renderBackups() {
  const box = $("backups");
  const list = await invoke("find_backups", { extra: load("history", []) });
  box.textContent = "";
  if (!list.length) {
    const empty = el("div", "empty-state");
    empty.append(el("span", null, "◎"), el("p", null, t("ui.found_none")));
    box.append(empty);
    return;
  }
  for (const backup of list) {
    const info = el("div", "backup-info");
    info.append(el("div", "path", backup.path));
    if (backup.source) info.append(el("div", "muted small", t("ui.backup_from", { source: backup.source })));
    const meta = el("div", "muted small", t("ui.backup_meta", {
      date: date(backup.finished),
      files: backup.files != null ? num(backup.files) : "?",
      size: backup.bytes != null ? size(backup.bytes) : "?",
    }));
    if (backup.verdict && backup.verdict !== "SAFE TO FORMAT") {
      meta.append(" ", el("span", "badge warn", t("ui.backup_incomplete")));
    }
    info.append(meta);
    const check = el("button", "primary", t("ui.check"));
    check.type = "button";
    check.addEventListener("click", action(() => verify(backup.path)));
    const card = el("div", "backup");
    card.append(info, check);
    box.append(card);
  }
}

function verify(path) {
  return execute("verify", ["verify", "--target", path], { target: path });
}

// ---------- запуск CLI і показ результату

const listenersReady = Promise.all([listen("cli-line", (e) => {
  let event;
  try { event = JSON.parse(e.payload); } catch { log(e.payload); return; }
  onEvent(event);
}), listen("cli-stderr", (e) => log(e.payload)), listen("cli-exit", (e) => {
  if (state.run && !state.run.finished) {
    state.run.finished = true;
    state.run.exitCode = e.payload;
    if (!state.run.report && !state.run.verifyResult && !state.run.cancelled && !state.run.error) {
      state.run.error = t("ui.process_failed", { code: e.payload });
    }
    state.run.resolve();
  }
})]);
listenersReady.catch(showError);

async function execute(kind, args, context) {
  if (state.busy) return;
  await listenersReady;
  if (state.busy) return;
  state.busy = true;
  $("global-error").hidden = true;
  $("lang").disabled = true;
  $("tab-copy").disabled = true;
  $("tab-verify").disabled = true;
  $("stop-run").disabled = false;
  $("app-status").textContent = t("ui.working");
  $("run-heading").textContent = t(kind === "copy" ? "ui.copy_title" : "ui.verify_title");
  const run = { kind, context, incidents: [], problems: [], totalBytes: 0, totalFiles: 0, finished: false };
  state.run = run;
  $("home").hidden = true;
  $("run").hidden = false;
  $("progress").hidden = false;
  $("result").hidden = true;
  $("log").textContent = "";
  $("run-title").textContent = kind === "copy" ? t("ui.copying") : t("ui.checking", { path: context.target });
  $("bar").value = 0;
  $("progress-percent").textContent = "0%";
  $("progress-main").textContent = t("ui.preparing");
  $("progress-sub").textContent = "";
  $("progress-file").textContent = "";
  await new Promise((resolve) => {
    run.resolve = resolve;
    invoke("run_cli", { args: [...args, "--lang", state.lang] }).catch((err) => {
      run.error = String(err);
      run.finished = true;
      resolve();
    });
  });
  state.busy = false;
  $("lang").disabled = false;
  $("tab-copy").disabled = false;
  $("tab-verify").disabled = false;
  $("app-status").textContent = t("ui.ready");
  renderResult();
}

function onEvent(event) {
  const run = state.run;
  if (!run || run.finished) return;
  switch (event.event) {
    case "start":
      run.totalBytes = event.bytes;
      run.totalFiles = event.files;
      run.started = performance.now();
      break;
    case "progress": {
      const frac = progressFraction(event, run);
      $("bar").value = frac;
      $("progress-percent").textContent = `${Math.floor(frac * 100)}%`;
      $("progress-main").textContent = t("ui.progress", {
        pct: Math.floor(frac * 100), done: num(event.files_done), total: num(run.totalFiles),
      });
      const elapsed = (performance.now() - run.started) / 1000;
      if (elapsed > 2 && event.bytes_done > 0 && frac < 1) {
        const speed = event.bytes_done / elapsed;
        $("progress-sub").textContent = t("ui.speed_eta", {
          speed: size(speed), eta: duration((run.totalBytes - event.bytes_done) / speed),
        });
      }
      if (event.current) $("progress-file").textContent = t("ui.now", { file: event.current });
      break;
    }
    case "incident":
      run.incidents.push(event);
      break;
    case "problem":
      run.problems.push(event);
      break;
    case "done":
      run.report = event.report;
      run.verifyResult = event.result;
      log(event.text);
      break;
    case "error":
      run.error = event.message;
      log(event.message);
      break;
  }
}

function renderResult() {
  const run = state.run;
  $("progress").hidden = true;
  $("result").hidden = false;
  const variant = resultVariant(run);
  const good = variant === "safe" || variant === "intact";
  $("result-card").className = "card " + (good ? "ok" : ["incomplete", "cancelled"].includes(variant) ? "warn" : "bad");
  $("result-title").textContent = t(`ui.result.${variant}.title`);
  $("result-text").textContent = variant === "error" ? run.error || "" : t(`ui.result.${variant}.text`);

  const summary = $("summary");
  summary.textContent = "";
  const row = (label, value) => summary.append(el("dt", null, label), el("dd", null, value));
  if (run.report) {
    const r = run.report;
    row(t("ui.summary.files"), `${num(r.ok)} / ${num(r.total)}`);
    row(t("ui.summary.size"), size(r.bytes_read));
    row(t("ui.summary.time"), duration(r.seconds));
    row(t("ui.summary.copies"), r.dests.join("\n"));
  } else if (run.verifyResult) {
    const r = run.verifyResult;
    row(t("ui.summary.checked"), t("ver.counts", {
      total: num(r.intact + r.changed + r.missing + r.unreadable), intact: num(r.intact), changed: num(r.changed),
      missing: num(r.missing), unreadable: num(r.unreadable),
    }));
  }
  summary.hidden = !summary.childElementCount;

  const groups = new Map();
  const add = (key, line) => groups.set(key, [...(groups.get(key) || []), line]);
  for (const i of run.incidents) add(t("reason." + i.reason), i.dest ? `${i.rel_path}  [${i.dest}]` : i.rel_path);
  for (const p of run.problems) add(t("state." + p.state), p.rel_path);
  const box = $("problems");
  box.textContent = "";
  if (groups.size) box.append(el("h3", null, t("ui.problems")));
  for (const [label, lines] of groups) {
    const block = el("div", "problem");
    block.append(el("div", "problem-title", `${label[0].toUpperCase()}${label.slice(1)} — ${num(lines.length)}`));
    const list = el("ul");
    for (const line of lines.slice(0, MAX_LISTED)) list.append(el("li", "mono", line));
    if (lines.length > MAX_LISTED) list.append(el("li", "muted", t("ui.more", { n: num(lines.length - MAX_LISTED) })));
    block.append(list);
    box.append(block);
  }

  const folder = run.kind === "copy" ? run.context.dests[0] : run.context.target;
  $("open-folder").hidden = ["error", "cancelled"].includes(variant);
  $("open-folder").onclick = action(() => invoke("open_path", { path: folder }));
  $("open-report").hidden = run.kind !== "copy" || ["error", "cancelled"].includes(variant);
  $("open-report").onclick = action(() => invoke("open_path", { path: `${folder}\\vaultdrop-report.txt` }));
}

function log(text) {
  const box = $("log");
  box.textContent += text.endsWith("\n") ? text : text + "\n";
  if (box.textContent.length > 100000) box.textContent = box.textContent.slice(-100000);
}

function selectTab(name) {
  if (state.busy) return;
  state.tab = name;
  $("breadcrumb").textContent = t("ui.tab." + name);
  for (const tab of ["copy", "verify"]) {
    $(`tab-${tab}`).setAttribute("aria-selected", String(tab === name));
    $(`tab-${tab}`).tabIndex = tab === name ? 0 : -1;
    $(`pane-${tab}`).hidden = tab !== name;
  }
  if (name === "verify") action(renderBackups)();
  else if (state.source) action(() => setSource(state.source))();
}

// ---------- старт

$("tab-copy").addEventListener("click", () => selectTab("copy"));
$("tab-verify").addEventListener("click", () => selectTab("verify"));
$("pick-source").addEventListener("click", action(async () => {
  const path = await invoke("pick_folder");
  if (path) await setSource(path);
}));
$("pick-dest").addEventListener("click", action(async () => {
  const path = await invoke("pick_folder");
  if (path) toggleDest({ custom: path });
}));
$("pick-backup").addEventListener("click", action(async () => {
  const path = await invoke("pick_folder");
  if (path) await verify(path);
}));
$("refresh-drives").addEventListener("click", action(() => refreshDrives(true)));
$("refresh-backups").addEventListener("click", action(renderBackups));
$("start").addEventListener("click", action(startCopy));
$("done").addEventListener("click", () => {
  $("run").hidden = true;
  $("home").hidden = false;
  action(() => refreshDrives(true))();
  selectTab($("pane-verify").hidden ? "copy" : "verify");
});

currentWindow()?.onCloseRequested(async (event) => {
  if (!state.busy) return;
  event.preventDefault();
  try {
    const stop = await invoke("ask", { title: t("ui.stop_title"), message: t("ui.stop_text"), ok: t("ui.stop"), cancel: t("ui.cancel") });
    if (stop) await currentWindow().destroy();
  } catch (error) { showError(error); }
});

(async () => {
  await initLanguage();
  const saved = load("dests", []);
  state.dests = Array.isArray(saved) ? saved.filter(d => d && (typeof d.root === "string" || typeof d.custom === "string")).slice(0, 2) : [];
  await refreshDrives(true);
  const source = load("source", "");
  if (typeof source === "string" && source) await setSource(source);
  let refreshing = false;
  setInterval(async () => {
    if (state.busy || refreshing) return;
    refreshing = true;
    try { await refreshDrives(); } catch (error) { showError(error); }
    finally { refreshing = false; }
  }, 4000);
})().catch(showError);

$("stop-run").addEventListener("click", action(async () => {
  const run = state.run;
  if (!state.busy || !run) return;
  const stop = await invoke("ask", { title: t("ui.stop_run"), message: t("ui.stop_run_text"), ok: t("ui.stop_run"), cancel: t("ui.cancel") });
  if (!stop || run.finished) return;
  $("stop-run").disabled = true;
  run.cancelled = true;
  try { await invoke("cancel_run"); }
  catch (error) { run.cancelled = false; $("stop-run").disabled = false; throw error; }
}));
for (const name of ["copy", "verify"]) {
  $("tab-" + name).addEventListener("keydown", event => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? "copy" : event.key === "End" ? "verify" : name === "copy" ? "verify" : "copy";
    selectTab(next);
    $("tab-" + next).focus();
  });
}
document.querySelector(".brand").addEventListener("click", event => { event.preventDefault(); selectTab("copy"); });
