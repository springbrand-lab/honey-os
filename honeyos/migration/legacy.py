"""Safely migrate the previous Honey companion data directory once.

Old product identifiers are intentionally confined to this compatibility
module. The migration never inspects or controls an upstream agent home.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import platform
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml


_LEGACY_PRODUCT_NAME = "H2OS"
_LEGACY_SKILL_DIRECTORY = "h2os-self-extension"
_CURRENT_SKILL_DIRECTORY = "honeyos-self-extension"


class MigrationError(RuntimeError):
    """Raised when legacy data cannot be copied and validated safely."""


@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    new_home: Path
    backup_home: Path | None


def rewrite_legacy_product_text(text: str) -> str:
    """Translate previous companion branding in user-owned managed files."""

    return text.replace(_LEGACY_PRODUCT_NAME, "HoneyOS")


def migrate_legacy_skill_directory(home: Path) -> bool:
    """Rename the previous managed self-extension skill without losing edits."""

    old_skill = home / "skills" / _LEGACY_SKILL_DIRECTORY
    new_skill = home / "skills" / _CURRENT_SKILL_DIRECTORY
    if not old_skill.is_dir():
        return False
    if new_skill.exists():
        shutil.rmtree(new_skill)
    old_skill.rename(new_skill)
    return True


def default_legacy_home() -> Path:
    return Path.home() / ".h2os"


def stop_legacy_service() -> None:
    """Stop only the exact service used by the previous companion build."""

    if platform.system() == "Darwin":
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/ai.springbrand.h2os"],
            check=False,
            capture_output=True,
        )
    elif platform.system() == "Linux":
        subprocess.run(
            ["systemctl", "--user", "stop", "h2os-gateway"],
            check=False,
            capture_output=True,
        )


def _reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise MigrationError(f"legacy data contains an unsafe symlink: {path}")


def _rewrite_legacy_paths(staging: Path, legacy: Path, new_home: Path) -> None:
    config_path = staging / "config.yaml"
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        config_path.write_text(text.replace(str(legacy), str(new_home)), encoding="utf-8")

    # Runtime identity contains checkout/interpreter paths from the old install.
    # The new CLI writes a fresh identity after migration.
    (staging / "runtime.json").unlink(missing_ok=True)


def _validate_yaml(staging: Path) -> None:
    config_path = staging / "config.yaml"
    if not config_path.exists():
        return
    try:
        value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MigrationError("legacy config.yaml is not readable YAML") from exc
    if value is not None and not isinstance(value, dict):
        raise MigrationError("legacy config.yaml must contain a mapping")


def _validate_sqlite(staging: Path) -> None:
    database_suffixes = {".db", ".sqlite", ".sqlite3"}
    for path in staging.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in database_suffixes:
            continue
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise MigrationError(f"legacy database is not readable: {path.name}") from exc
        if not result or result[0] != "ok":
            raise MigrationError(f"legacy database failed validation: {path.name}")


def _validate_copied_directories(legacy: Path, staging: Path) -> None:
    for name in ("memories", "sessions", "skills", "cron", "todos"):
        if (legacy / name).is_dir() and not (staging / name).is_dir():
            raise MigrationError(f"legacy directory was not copied: {name}")


def _validate_migrated_home(legacy: Path, staging: Path) -> None:
    _validate_yaml(staging)
    _validate_sqlite(staging)
    _validate_copied_directories(legacy, staging)


def _backup_path(legacy: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return legacy.with_name(f".h2os.backup-{stamp}")


def migrate_legacy_home(
    new_home: Path,
    legacy_home: Path | None = None,
) -> MigrationResult:
    """Copy, validate, and archive an earlier companion data home.

    An existing new home always wins. Failures remove only the staging copy and
    restore the legacy directory if it had already been renamed.
    """

    destination = new_home.expanduser().resolve()
    legacy = (legacy_home or default_legacy_home()).expanduser().resolve()
    if destination.exists() or not legacy.exists():
        return MigrationResult(False, destination, None)
    if not legacy.is_dir():
        raise MigrationError("legacy data home is not a directory")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(
        f".{destination.name}.migrating-{uuid.uuid4().hex}"
    )
    backup: Path | None = None
    try:
        _reject_symlinks(legacy)
        shutil.copytree(
            legacy,
            staging,
            symlinks=False,
            ignore=shutil.ignore_patterns("*.pid", "*.lock", "*.sock"),
        )
        _rewrite_legacy_paths(staging, legacy, destination)
        _validate_migrated_home(legacy, staging)

        backup = _backup_path(legacy)
        legacy.replace(backup)
        try:
            staging.replace(destination)
        except Exception:
            backup.replace(legacy)
            backup = None
            raise
    except MigrationError:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and not legacy.exists():
            backup.replace(legacy)
        raise MigrationError("legacy companion data migration failed") from exc

    return MigrationResult(True, destination, backup)
