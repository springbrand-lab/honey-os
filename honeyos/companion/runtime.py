"""Runtime identity and absolute-path dispatch for HoneyOS."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from honeyos.companion import PRODUCT_NAME, RUNTIME_ID, __version__


SOURCE_REVISION = "6e9cae6ac4b41b5325d3ef8bdce5ed8e6fd9b28a"
_GATEWAY_COMMANDS = frozenset({"install", "start", "stop", "restart", "status"})
_LEGACY_HOME_VARIABLES = ("HONEYOS_HOME", "HONEYOS_HOME", "HONEYOS_RUNTIME_ID", "HONEYOS_PRODUCT_NAME")


@dataclass(frozen=True)
class RuntimeIdentity:
    honeyos_version: str
    source_revision: str
    python_executable: str
    package_root: str
    repository_root: str
    data_directory: str
    initialized_at: str


def resolve_repository_root(start: Path | str) -> Path | None:
    """Return the Git top-level containing *start*, if one is available."""

    candidate = Path(start).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    if not candidate.is_dir():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    rendered = completed.stdout.strip()
    if not rendered:
        return None
    root = Path(rendered).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return root if root.is_dir() and (root / ".git").exists() else None


def gateway_argv(command: str, arguments: tuple[str, ...] = ()) -> list[str]:
    """Build a gateway lifecycle command using this installation."""

    normalized = command.strip().lower()
    if normalized not in _GATEWAY_COMMANDS:
        raise ValueError(f"unsupported gateway command: {command}")
    return [
        sys.executable,
        "-m",
        "honeyos.runtime.main",
        "gateway",
        normalized,
        *arguments,
    ]


def runtime_module_argv(*arguments: str) -> list[str]:
    """Build an internal runtime invocation using this interpreter."""

    return [sys.executable, "-m", "honeyos.runtime.main", *arguments]


def write_runtime_identity(home: Path) -> RuntimeIdentity:
    """Persist non-secret build metadata under the HoneyOS data directory."""

    resolved = home.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    package_root = Path(__file__).resolve().parent.parent
    repository_root = resolve_repository_root(package_root)
    identity = RuntimeIdentity(
        honeyos_version=__version__,
        source_revision=SOURCE_REVISION,
        python_executable=sys.executable,
        package_root=str(package_root),
        repository_root=str(repository_root) if repository_root is not None else "",
        data_directory=str(resolved),
        initialized_at=datetime.now(timezone.utc).isoformat(),
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".runtime.", suffix=".json", dir=resolved
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(identity), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, resolved / "runtime.json")
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return identity


def upgrade_companion_home_for_gateway(home: Path | None = None) -> bool:
    """Apply idempotent companion migrations before a long-lived gateway starts."""

    if home is None:
        from honeyos.core.constants import get_honeyos_home

        home = get_honeyos_home()
    resolved = Path(home).expanduser().resolve()
    config_path = resolved / "config.yaml"
    if not config_path.is_file():
        return False
    try:
        import yaml

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    agent = config.get("agent", {}) if isinstance(config, dict) else {}
    if not isinstance(agent, dict) or str(agent.get("mode", "")).lower() != "companion":
        return False

    from honeyos.companion.config import upgrade_companion_capabilities

    changed = upgrade_companion_capabilities(resolved)
    write_runtime_identity(resolved)
    return changed


def run_gateway_command(
    command: str, *, home: Path, arguments: tuple[str, ...] = ()
) -> int:
    """Run a gateway lifecycle command with an explicit HoneyOS home."""

    resolved = home.expanduser().resolve()
    environment = os.environ.copy()
    for variable in _LEGACY_HOME_VARIABLES:
        environment.pop(variable, None)
    environment["HONEYOS_HOME"] = str(resolved)
    environment["HONEYOS_RUNTIME_ID"] = RUNTIME_ID
    environment["HONEYOS_PRODUCT_NAME"] = PRODUCT_NAME
    completed = subprocess.run(
        gateway_argv(command, arguments), env=environment, check=False
    )
    return completed.returncode


def run_runtime_module(arguments: list[str], *, home: Path) -> int:
    """Run an internal CLI operation under the HoneyOS home."""

    resolved = home.expanduser().resolve()
    environment = os.environ.copy()
    for variable in _LEGACY_HOME_VARIABLES:
        environment.pop(variable, None)
    environment["HONEYOS_HOME"] = str(resolved)
    environment["HONEYOS_RUNTIME_ID"] = RUNTIME_ID
    environment["HONEYOS_PRODUCT_NAME"] = PRODUCT_NAME
    completed = subprocess.run(
        runtime_module_argv(*arguments), env=environment, check=False
    )
    return completed.returncode
