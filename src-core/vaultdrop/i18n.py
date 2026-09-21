"""Translations and locale formats. Strings live in locales/<lang>.json, shared by the core and the UI.

New language = a new JSON file with the same keys as en.json (+ one line in src-app/src-tauri/src/main.rs).
"""

import json
import os
from datetime import datetime, timezone

LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
FALLBACK = "en"
_strings: dict = {}
current = FALLBACK


def available() -> list[str]:
    return sorted(name[:-5] for name in os.listdir(LOCALES_DIR) if name.endswith(".json"))


def load(lang: str | None = None) -> str:
    """Switches the language (None means English); keys missing from a translation fall back to English."""
    global _strings, current
    code = (lang or FALLBACK).split("-")[0].lower()
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
    """ISO UTC time from a report -> local time in the language's format."""
    if not iso_utc:
        return "?"
    moment = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
    return moment.strftime(t("fmt.datetime"))


def _read(code: str) -> dict:
    with open(os.path.join(LOCALES_DIR, code + ".json"), encoding="utf-8") as f:
        return json.load(f)
