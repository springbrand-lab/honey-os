from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_only_honeyos_console_script_is_exported() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["name"] == "honeyos"
    assert config["project"]["scripts"] == {"honeyos": "honeyos.cli.main:main"}


def test_forbidden_runtime_paths_are_absent() -> None:
    allowed = {
        ROOT / "LICENSE",
        ROOT / "NOTICE",
        ROOT / "honeyos" / "migration" / "legacy_h2os.py",
    }
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path in allowed:
            continue
        if any(part in {"tests", "docs", ".venv"} for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        if re.search(r"hermes|h2os|springbrand", str(relative), re.IGNORECASE):
            offenders.append(str(relative))
    assert offenders == []
