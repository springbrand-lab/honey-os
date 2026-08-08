"""Select and prepare the HoneyOS data home before runtime imports."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path

from honeyos import PRODUCT_NAME, RUNTIME_ID, default_home
from honeyos.migration.legacy import (
    clear_product_runtime_environment,
    default_legacy_home,
    migrate_legacy_home,
    stop_legacy_service,
)


def _is_incomplete_home(home: Path) -> bool:
    """Recognize a shell created before legacy companion data was migrated."""

    memories = home / "memories"
    has_memory_files = memories.is_dir() and any(
        path.is_file() for path in memories.iterdir()
    )
    return home.is_dir() and not any(
        ((home / "config.yaml").is_file(), (home / ".env").is_file(), has_memory_files)
    )


def activate_home(
    home: Path | None = None,
    *,
    legacy_home: Path | None = None,
    stop_legacy: Callable[[], None] = stop_legacy_service,
) -> Path:
    """Migrate when needed, then pin the sole HoneyOS data directory."""

    destination = (home or default_home()).expanduser().resolve()
    legacy = legacy_home
    if legacy is None and home is None:
        legacy = default_legacy_home()
    resolved_legacy = legacy.expanduser().resolve() if legacy is not None else None
    legacy_available = resolved_legacy is not None and resolved_legacy.is_dir()
    should_migrate = legacy_available and (
        not destination.exists() or _is_incomplete_home(destination)
    )
    incomplete_backup: Path | None = None
    if should_migrate:
        stop_legacy()
        if destination.exists():
            incomplete_backup = destination.with_name(
                f".{destination.name.lstrip('.')}.incomplete-{uuid.uuid4().hex}"
            )
            destination.replace(incomplete_backup)
        try:
            migrate_legacy_home(destination, resolved_legacy)
        except Exception:
            if (
                incomplete_backup is not None
                and incomplete_backup.exists()
                and not destination.exists()
            ):
                incomplete_backup.replace(destination)
            raise
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.chmod(0o700)
    except OSError:
        pass
    clear_product_runtime_environment(os.environ)
    os.environ["HONEYOS_HOME"] = str(destination)
    os.environ["HONEYOS_RUNTIME_ID"] = RUNTIME_ID
    os.environ["HONEYOS_PRODUCT_NAME"] = PRODUCT_NAME
    return destination
