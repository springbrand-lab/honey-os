"""Resolve HONEYOS_HOME for standalone skill scripts.

Skill scripts may run outside the HoneyOS process (system Python, nix env,
CI) where ``honeyos.core.constants`` is not importable.  This module provides the
same ``get_honeyos_home()`` contract without requiring it on ``sys.path``.

When ``honeyos.core.constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from honeyos.core.constants import get_honeyos_home as get_honeyos_home
except (ModuleNotFoundError, ImportError):

    def get_honeyos_home() -> Path:
        """Return the HoneyOS home directory (default: ``~/.honeyos``)."""
        val = os.environ.get("HONEYOS_HOME", "").strip()
        return Path(val) if val else Path.home() / ".honeyos"
