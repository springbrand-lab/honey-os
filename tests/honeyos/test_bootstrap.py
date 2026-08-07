from __future__ import annotations

import os
from pathlib import Path

from honeyos import default_home
from honeyos.cli.bootstrap import activate_home


def test_default_home_is_honeyos(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert default_home() == tmp_path / ".honeyos"


def test_activate_home_uses_explicit_path(tmp_path):
    assert activate_home(tmp_path / "explicit") == (tmp_path / "explicit").resolve()


def test_activate_home_sets_only_honeyos_environment(monkeypatch, tmp_path):
    for name in (
        "HONEYOS_HOME",
        "HONEYOS_RUNTIME_ID",
        "HONEYOS_PRODUCT_NAME",
        "HERMES_HOME",
        "H2OS_HOME",
        "H2OS_RUNTIME_ID",
        "H2OS_PRODUCT_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    result = activate_home(tmp_path / "data")

    assert os.environ["HONEYOS_HOME"] == str(result)
    assert os.environ["HONEYOS_RUNTIME_ID"] == "honeyos-companion-v0.3"
    assert os.environ["HONEYOS_PRODUCT_NAME"] == "HoneyOS"
    assert "HERMES_HOME" not in os.environ
    assert "H2OS_HOME" not in os.environ
    assert result.is_absolute()
