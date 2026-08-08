"""Public identity for the standalone HoneyOS companion runtime."""

from __future__ import annotations

from pathlib import Path


PRODUCT_NAME = "HoneyOS"
RUNTIME_ID = "honeyos-companion-v0.3"
__version__ = "0.3.1"


def default_home() -> Path:
    """Return the only data home used by new HoneyOS installations."""

    return Path.home() / ".honeyos"
