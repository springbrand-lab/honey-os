"""Select and prepare the HoneyOS data home before runtime imports."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from honeyos import PRODUCT_NAME, RUNTIME_ID, default_home
from honeyos.migration.legacy import (
    default_legacy_home,
    migrate_legacy_home,
    stop_legacy_service,
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
    if (
        not destination.exists()
        and resolved_legacy is not None
        and resolved_legacy.is_dir()
    ):
        stop_legacy()
        migrate_legacy_home(destination, resolved_legacy)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.chmod(0o700)
    except OSError:
        pass
    for legacy_variable in (
        "HONEYOS_HOME",
        "HONEYOS_HOME",
        "HONEYOS_RUNTIME_ID",
        "HONEYOS_PRODUCT_NAME",
    ):
        os.environ.pop(legacy_variable, None)
    os.environ["HONEYOS_HOME"] = str(destination)
    os.environ["HONEYOS_RUNTIME_ID"] = RUNTIME_ID
    os.environ["HONEYOS_PRODUCT_NAME"] = PRODUCT_NAME
    return destination
