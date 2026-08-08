"""User-visible local project workspace for the HoneyOS companion."""

from __future__ import annotations

import os
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


PROJECTS_ENV = "HONEYOS_PROJECTS_HOME"
DEFAULT_PROJECTS_DIR = "HoneyOS Projects"
RECOVERY_DIR = "从旧版本恢复"
RECOVERY_MARKER = ".local-project-recovery-v1.json"

_ABSOLUTE_SHELL_PATH = r"(?:/|~/|\$HOME(?:/|$)|\$\{HOME\}(?:/|$))"
_REDIRECT_TARGET_RE = re.compile(
    r"(?<![<>])>{1,2}\s*(?:"
    rf'"(?P<double>{_ABSOLUTE_SHELL_PATH}[^"\n]*)"|'
    rf"'(?P<single>{_ABSOLUTE_SHELL_PATH}[^'\n]*)'|"
    rf"(?P<bare>{_ABSOLUTE_SHELL_PATH}[^\s;&|<>]*)"
    r")"
)
_TEE_TARGET_RE = re.compile(
    r"(?:^|[;&|]\s*|\s)tee(?:\s+-[A-Za-z]+)*\s+(?:"
    rf'"(?P<double>{_ABSOLUTE_SHELL_PATH}[^"\n]*)"|'
    rf"'(?P<single>{_ABSOLUTE_SHELL_PATH}[^'\n]*)'|"
    rf"(?P<bare>{_ABSOLUTE_SHELL_PATH}[^\s;&|<>]*)"
    r")"
)


@dataclass(frozen=True)
class RecoveryResult:
    copied: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


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


def active_managed_project_root() -> Path | None:
    """Return the configured companion workspace, or ``None`` outside it."""

    try:
        from honeyos.runtime.config import load_config_readonly

        config = load_config_readonly()
    except Exception:
        return None
    agent = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    terminal = (
        config.get("terminal") if isinstance(config.get("terminal"), dict) else {}
    )
    if str(agent.get("mode", "")).strip().lower() != "companion":
        return None
    if str(terminal.get("backend", "")).strip().lower() != "local":
        return None
    raw_root = str(terminal.get("cwd", "")).strip()
    if not raw_root:
        return None
    root = Path(raw_root).expanduser()
    return root.resolve() if root.is_absolute() else None


def path_is_in_managed_projects(path: Path, root: Path | None = None) -> bool:
    """Return whether a host path resolves within the active project root."""

    managed_root = (root or active_managed_project_root())
    if managed_root is None:
        return True
    try:
        path.expanduser().resolve().relative_to(managed_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def managed_project_boundary_error(path: Path) -> str | None:
    """Describe an out-of-workspace companion path without granting access."""

    root = active_managed_project_root()
    if root is None or path_is_in_managed_projects(path, root):
        return None
    return (
        f"Blocked: {path} is outside the managed HoneyOS Projects workspace "
        f"({root}). Put the project there; access to another user directory "
        "requires an explicit directory-authorization feature."
    )


def _expand_shell_home_path(raw_path: str) -> Path:
    """Resolve the small set of explicit home forms accepted by the scanner."""

    if raw_path == "$HOME" or raw_path == "${HOME}":
        return Path.home()
    if raw_path.startswith("$HOME/"):
        return Path.home() / raw_path[len("$HOME/") :]
    if raw_path.startswith("${HOME}/"):
        return Path.home() / raw_path[len("${HOME}/") :]
    return Path(raw_path).expanduser()


def managed_command_write_boundary_error(command: str) -> str | None:
    """Block obvious absolute shell write targets outside HoneyOS Projects.

    File tools already enforce this boundary themselves.  Shell redirection
    needs an equivalent preflight because checking only the command's working
    directory does not constrain ``> /tmp/file`` or ``tee ~/Desktop/file``.
    Relative targets remain project-local through the managed terminal cwd.
    """

    if active_managed_project_root() is None:
        return None
    for pattern in (_REDIRECT_TARGET_RE, _TEE_TARGET_RE):
        for match in pattern.finditer(command):
            raw_path = next(
                value
                for value in (
                    match.group("double"),
                    match.group("single"),
                    match.group("bare"),
                )
                if value is not None
            )
            boundary_error = managed_project_boundary_error(
                _expand_shell_home_path(raw_path)
            )
            if boundary_error:
                return boundary_error
    return None


def _load_completed_tasks(marker: Path) -> set[str]:
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    tasks = payload.get("completed_tasks", []) if isinstance(payload, dict) else []
    return {str(task) for task in tasks if str(task).strip()}


def _write_completed_tasks(marker: Path, tasks: set[str]) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{marker.name}.", dir=marker.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"completed_tasks": sorted(tasks)},
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
        os.replace(temporary_name, marker)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _copy_entry(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise OSError("symbolic links are not recovered automatically")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)


def recover_legacy_projects(
    data_home: Path, destination: Path | None = None
) -> RecoveryResult:
    """Copy legacy container projects into the visible host workspace once.

    The old sandbox tree is never renamed or removed. Companion memory is not
    below the scanned ``sandboxes/docker`` root and is therefore never read.
    """

    resolved_home = data_home.expanduser().resolve()
    legacy_root = resolved_home / "sandboxes" / "docker"
    if not legacy_root.is_dir():
        return RecoveryResult()

    root = (destination or ensure_project_root(resolved_home)).expanduser().resolve()
    marker = resolved_home / RECOVERY_MARKER
    completed = _load_completed_tasks(marker)
    copied: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    try:
        task_directories = sorted(path for path in legacy_root.iterdir() if path.is_dir())
    except OSError as exc:
        return RecoveryResult(errors=(f"{legacy_root}: {exc}",))

    for task_directory in task_directories:
        task_name = task_directory.name
        if task_name in completed:
            continue
        task_errors = 0
        for source_group, include_hidden in (("workspace", True), ("home", False)):
            source_root = task_directory / source_group
            if not source_root.is_dir():
                continue
            try:
                entries = sorted(source_root.iterdir())
            except OSError as exc:
                errors.append(f"{source_root}: {exc}")
                task_errors += 1
                continue
            for source in entries:
                if not include_hidden and source.name.startswith("."):
                    continue
                target = root / RECOVERY_DIR / task_name / source_group / source.name
                if target.exists() or target.is_symlink():
                    skipped.append(str(target))
                    continue
                try:
                    _copy_entry(source, target)
                except OSError as exc:
                    errors.append(f"{source}: {exc}")
                    task_errors += 1
                else:
                    copied.append(str(target))
        if task_errors == 0:
            completed.add(task_name)
            try:
                _write_completed_tasks(marker, completed)
            except OSError as exc:
                errors.append(f"{marker}: {exc}")

    return RecoveryResult(tuple(copied), tuple(skipped), tuple(errors))
