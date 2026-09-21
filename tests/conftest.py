import os

import pytest

from vaultdrop import i18n
from vaultdrop.winio import lp


def pytest_configure(config):
    os.makedirs(".tmp", exist_ok=True)  # parent folder for --basetemp=.tmp/pytest


def make_tree(root, spec: dict) -> None:
    """Creates files {rel_path: bytes}; paths go through \\\\?\\, so long ones work too."""
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
    """Report texts in tests are English regardless of the Windows language."""
    i18n.load("en")


@pytest.fixture
def dirs(tmp_path):
    """source, dest1, dest2 as strings."""
    return str(tmp_path / "src"), str(tmp_path / "d1"), str(tmp_path / "d2")
