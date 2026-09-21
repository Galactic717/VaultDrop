"""Переклади й локальні формати. Рядки лежать у locales/<мова>.json, спільних для ядра й інтерфейсу.

Нова мова = новий JSON з тими самими ключами, що й en.json (+ рядок у src-app/src-tauri/src/main.rs).
"""

import ctypes
import json
import os
from datetime import datetime, timezone

LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
FALLBACK = "en"
_strings: dict = {}
current = FALLBACK


def available() -> list[str]:
    return sorted(name[:-5] for name in os.listdir(LOCALES_DIR) if name.endswith(".json"))


def detect() -> str:
    """Мова Windows. Якщо інтерфейс англійський, а регіональний формат — інша підтримувана мова,
    беремо регіон: англійський інтерфейс часто стоїть за замовчуванням, а регіон людина обирає сама."""
    k32 = ctypes.WinDLL("kernel32")
    buf = ctypes.create_unicode_buffer(85)
    ui = buf.value if k32.LCIDToLocaleName(k32.GetUserDefaultUILanguage(), buf, 85, 0) else ""
    region = buf.value if k32.GetUserDefaultLocaleName(buf, 85) else ""
    langs = available()
    for name in ([region, ui] if ui.lower().startswith("en") else [ui, region]):
        code = name.split("-")[0].lower()
        if code in langs:
            return code
    return FALLBACK


def load(lang: str | None = None) -> str:
    """Вмикає мову (None — мова Windows); ключі, яких нема в перекладі, беруться з англійської."""
    global _strings, current
    code = (lang or detect()).split("-")[0].lower()
    if code not in available():
        code = FALLBACK
    strings = _read(FALLBACK)
    if code != FALLBACK:
        strings.update(_read(code))
    _strings, current = strings, code
    return code


def t(key: str, **values) -> str:
    if not _strings:
        load()
    return _strings.get(key, key).format(**values)


def fmt_size(n: int) -> str:
    for unit, shift in (("TB", 40), ("GB", 30), ("MB", 20), ("KB", 10)):
        if n >= 1 << shift:
            return f"{n / (1 << shift):.2f}".replace(".", t("num.decimal")) + " " + t("unit." + unit)
    return f"{n} {t('unit.B')}"


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if seconds < 60:
        return t("dur.s", s=f"{seconds:.1f}".replace(".", t("num.decimal")))
    if s < 3600:
        return t("dur.ms", m=s // 60, s=s % 60)
    return t("dur.hm", h=s // 3600, m=s % 3600 // 60)


def fmt_time(iso_utc: str | None) -> str:
    """ISO-час UTC зі звіту -> місцевий час у форматі мови."""
    if not iso_utc:
        return "?"
    moment = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
    return moment.strftime(t("fmt.datetime"))


def _read(code: str) -> dict:
    with open(os.path.join(LOCALES_DIR, code + ".json"), encoding="utf-8") as f:
        return json.load(f)
