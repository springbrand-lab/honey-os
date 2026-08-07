from __future__ import annotations

import os
from pathlib import Path

from h2os_cli.bootstrap import activate_h2os_home, resolve_h2os_home


def test_resolve_h2os_home_defaults_outside_hermes(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("H2OS_HOME", raising=False)

    assert resolve_h2os_home() == (tmp_path / ".h2os").resolve()


def test_resolve_h2os_home_accepts_explicit_path(monkeypatch, tmp_path):
    monkeypatch.setenv("H2OS_HOME", str(tmp_path / "from-env"))

    assert resolve_h2os_home(str(tmp_path / "explicit")) == (
        tmp_path / "explicit"
    ).resolve()


def test_activate_h2os_home_sets_absolute_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("H2OS_HOME", raising=False)
    monkeypatch.delenv("H2OS_RUNTIME_ID", raising=False)
    monkeypatch.delenv("H2OS_PRODUCT_NAME", raising=False)

    result = activate_h2os_home(tmp_path / "data")

    assert os.environ["HERMES_HOME"] == str(result)
    assert os.environ["H2OS_HOME"] == str(result)
    assert os.environ["H2OS_RUNTIME_ID"] == "h2os-companion-v0.2"
    assert os.environ["H2OS_PRODUCT_NAME"] == "HoneyOS"
    assert result.is_absolute()
