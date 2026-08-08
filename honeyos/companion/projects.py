"""User-visible local project workspace for the HoneyOS companion."""

from __future__ import annotations

import os
from pathlib import Path


PROJECTS_ENV = "HONEYOS_PROJECTS_HOME"
DEFAULT_PROJECTS_DIR = "HoneyOS Projects"


def project_root(data_home: Path | None = None) -> Path:
    """Return the managed host directory used for companion-created projects."""

    configured = os.environ.get(PROJECTS_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if data_home is not None:
        resolved_home = data_home.expanduser().resolve()
        if resolved_home.name == ".honeyos":
            return resolved_home.parent / DEFAULT_PROJECTS_DIR
    return Path.home() / DEFAULT_PROJECTS_DIR


def ensure_project_root(data_home: Path | None = None) -> Path:
    """Create and return the managed project directory on the user's host."""

    root = project_root(data_home)
    root.mkdir(parents=True, exist_ok=True)
    return root
