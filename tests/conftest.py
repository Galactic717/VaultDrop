import os

import pytest

from vaultdrop import i18n
from vaultdrop.winio import lp


def pytest_configure(config):
    os.makedirs(".tmp", exist_ok=True)  # батьківська папка для --basetemp=.tmp/pytest


def make_tree(root, spec: dict) -> None:
    """Створює файли {rel_path: bytes}; шляхи через \\\\?\\, тож довгі теж."""
    for rel, data in spec.items():
        path = os.path.join(str(root), *rel.split("/"))
        os.makedirs(lp(os.path.dirname(path)), exist_ok=True)
        with open(lp(path), "wb") as f:
            f.write(data)


def read(root, rel) -> bytes:
    with open(lp(os.path.join(str(root), *rel.split("/"))), "rb") as f:
        return f.read()


def exists(root, rel) -> bool:
    return os.path.exists(lp(os.path.join(str(root), *rel.split("/"))))


@pytest.fixture(autouse=True)
def english():
    """Тексти звітів у тестах — англійською, незалежно від мови Windows."""
    i18n.load("en")


@pytest.fixture
def dirs(tmp_path):
    """source, dest1, dest2 як рядки."""
    return str(tmp_path / "src"), str(tmp_path / "d1"), str(tmp_path / "d2")
