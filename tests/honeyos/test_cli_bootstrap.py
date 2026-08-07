from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def _bootstrap_module():
    try:
        spec = importlib.util.find_spec("honeyos.cli.bootstrap")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "the HoneyOS bootstrap layer must exist"
    return importlib.import_module("honeyos.cli.bootstrap")


def test_bootstrap_migrates_legacy_before_returning_home(
    tmp_path: Path,
) -> None:
    bootstrap = _bootstrap_module()
    old = tmp_path / ".h2os"
    old.mkdir()
    (old / "config.yaml").write_text("agent:\n  mode: companion\n", encoding="utf-8")
    stopped: list[bool] = []

    home = bootstrap.activate_home(
        home=tmp_path / ".honeyos",
        legacy_home=old,
        stop_legacy=lambda: stopped.append(True),
    )

    assert home == (tmp_path / ".honeyos").resolve()
    assert stopped == [True]
    assert list(tmp_path.glob(".h2os.backup-*"))


def test_bootstrap_never_reads_or_changes_hermes_home(tmp_path: Path) -> None:
    bootstrap = _bootstrap_module()
    hermes = tmp_path / ".hermes"
    hermes.mkdir()
    marker = hermes / "marker"
    marker.write_text("untouched", encoding="utf-8")

    home = bootstrap.activate_home(
        home=tmp_path / ".honeyos",
        legacy_home=tmp_path / ".h2os",
        stop_legacy=lambda: (_ for _ in ()).throw(AssertionError("must not stop")),
    )

    assert home == (tmp_path / ".honeyos").resolve()
    assert marker.read_text(encoding="utf-8") == "untouched"
    assert not (tmp_path / ".h2os").exists()


def test_explicit_home_does_not_implicitly_migrate_default_legacy_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bootstrap = _bootstrap_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    old = tmp_path / ".h2os"
    old.mkdir()
    (old / "marker").write_text("keep", encoding="utf-8")
    explicit = tmp_path / "test-home"

    home = bootstrap.activate_home(home=explicit)

    assert home == explicit.resolve()
    assert (old / "marker").read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".h2os.backup-*"))
