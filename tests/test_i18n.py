"""Переклади: повнота кожної мови, збіг плейсхолдерів, мова звіту в копії."""

import json
import os
import re
import string

import pytest

from conftest import make_tree, read
from vaultdrop import i18n
from vaultdrop.cli import main

LOCALES = i18n.available()
MAIN_RS = os.path.join(os.path.dirname(__file__), "..", "src-app", "src-tauri", "src", "main.rs")


def strings(code):
    with open(os.path.join(i18n.LOCALES_DIR, code + ".json"), encoding="utf-8") as f:
        return json.load(f)


def placeholders(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def test_at_least_six_languages():
    assert {"en", "uk", "pl", "de", "es", "fr"} <= set(LOCALES)


@pytest.mark.parametrize("code", LOCALES)
def test_locale_is_complete(code):
    """Кожна мова має всі ключі англійської, ті самі плейсхолдери й жодного зайвого ключа."""
    base, other = strings("en"), strings(code)
    assert set(other) == set(base)
    for key, text in base.items():
        assert placeholders(other[key]) == placeholders(text), key
        assert other[key].strip(), key


def test_app_embeds_every_locale():
    """Інтерфейс вшиває переклади в exe: кожен JSON має бути підключений у main.rs."""
    with open(MAIN_RS, encoding="utf-8") as f:
        embedded = set(re.findall(r'locales/(\w+)\.json', f.read()))
    assert embedded == set(LOCALES)


def test_detect_returns_supported_language():
    assert i18n.detect() in LOCALES


@pytest.mark.parametrize("code, verdict", [("uk", "МОЖНА ФОРМАТУВАТИ"), ("de", "SICHER ZU FORMATIEREN"),
                                           ("fr", "PRÊT À FORMATER")])
def test_report_language(dirs, code, verdict):
    src, d1, _ = dirs
    make_tree(src, {"a.txt": b"a"})
    assert main(["copy", "--source", src, "--dest", d1, "--lang", code]) == 0
    report = read(d1, "vaultdrop-report.txt").decode("utf-8")
    assert verdict in report
    assert json.loads(read(d1, "vaultdrop-report.json"))["verdict"] == "SAFE TO FORMAT"  # JSON не перекладається


def test_unknown_language_falls_back_to_english():
    assert i18n.load("xx") == "en"
    assert i18n.t("verdict.safe") == "SAFE TO FORMAT"
    assert i18n.fmt_size(1536 * 1024 * 1024) == "1.50 GB"
    i18n.load("fr")
    assert i18n.fmt_size(1536 * 1024 * 1024) == "1,50 Go"
