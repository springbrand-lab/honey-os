from __future__ import annotations

import re
import subprocess
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
        ROOT / "honeyos" / "migration" / "legacy.py",
    }
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    offenders: list[str] = []
    for relative_name in tracked:
        path = ROOT / relative_name
        if not path.is_file() or path in allowed:
            continue
        if any(part in {"tests", "docs", ".venv"} for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        if re.search(r"hermes|h2os|springbrand", str(relative), re.IGNORECASE):
            offenders.append(str(relative))
    assert offenders == []


def test_forbidden_runtime_names_are_absent_from_product_source() -> None:
    forbidden = re.compile(r"hermes|h2os|springbrand", re.IGNORECASE)
    offenders: list[str] = []
    for path in (ROOT / "honeyos").rglob("*"):
        if not path.is_file() or path == ROOT / "honeyos" / "migration" / "legacy.py":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if forbidden.search(content):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
