from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest


def _migration_module():
    try:
        spec = importlib.util.find_spec("honeyos.migration.legacy")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "the legacy home migrator must exist"
    return importlib.import_module("honeyos.migration.legacy")


def test_migrates_legacy_home_and_keeps_backup(tmp_path: Path) -> None:
    migration = _migration_module()
    old = tmp_path / ".h2os"
    new = tmp_path / ".honeyos"
    old.mkdir()
    (old / "config.yaml").write_text("agent:\n  mode: companion\n", encoding="utf-8")
    memories = old / "memories"
    memories.mkdir()
    (memories / "IDENTITY.md").write_text("温柔但有主见", encoding="utf-8")

    result = migration.migrate_legacy_home(new, old)

    assert result.migrated is True
    assert (new / "memories" / "IDENTITY.md").read_text(encoding="utf-8") == "温柔但有主见"
    assert result.backup_home is not None
    assert result.backup_home.exists()
    assert result.backup_home.name.startswith(".h2os.backup-")
    assert not old.exists()


def test_existing_new_home_wins_without_touching_legacy(tmp_path: Path) -> None:
    migration = _migration_module()
    old = tmp_path / ".h2os"
    new = tmp_path / ".honeyos"
    old.mkdir()
    new.mkdir()
    (old / "marker").write_text("legacy", encoding="utf-8")
    (new / "marker").write_text("current", encoding="utf-8")

    result = migration.migrate_legacy_home(new, old)

    assert result.migrated is False
    assert result.backup_home is None
    assert (old / "marker").read_text(encoding="utf-8") == "legacy"
    assert (new / "marker").read_text(encoding="utf-8") == "current"


def test_invalid_legacy_config_rolls_back_and_leaves_hermes_untouched(
    tmp_path: Path,
) -> None:
    migration = _migration_module()
    old = tmp_path / ".h2os"
    new = tmp_path / ".honeyos"
    hermes = tmp_path / ".hermes"
    old.mkdir()
    hermes.mkdir()
    (old / "config.yaml").write_text("[", encoding="utf-8")
    marker = hermes / "marker"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(migration.MigrationError):
        migration.migrate_legacy_home(new, old)

    assert old.exists()
    assert not new.exists()
    assert not list(tmp_path.glob(".honeyos.migrating-*"))
    assert marker.read_text(encoding="utf-8") == "keep"


def test_rewrites_only_runtime_paths_and_removes_stale_runtime_identity(
    tmp_path: Path,
) -> None:
    migration = _migration_module()
    old = tmp_path / ".h2os"
    new = tmp_path / ".honeyos"
    old.mkdir()
    (old / "config.yaml").write_text(
        f"workspace: {old / 'workspace'}\nagent:\n  mode: companion\n",
        encoding="utf-8",
    )
    (old / "runtime.json").write_text('{"repository_root": "/old/source"}', encoding="utf-8")

    migration.migrate_legacy_home(new, old)

    assert str(old) not in (new / "config.yaml").read_text(encoding="utf-8")
    assert str(new) in (new / "config.yaml").read_text(encoding="utf-8")
    assert not (new / "runtime.json").exists()
