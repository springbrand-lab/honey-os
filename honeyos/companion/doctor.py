"""Secret-safe diagnostics for the HONEYOS companion runtime."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from honeyos.companion import PRODUCT_NAME
from honeyos.companion.config import COMPANION_TOOLSETS, DEFAULT_IM_PLATFORMS
from honeyos.companion.projects import project_root
from honeyos.companion.runtime import gateway_argv


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def by_name(self, name: str) -> DoctorCheck:
        for check in self.checks:
            if check.name == name:
                return check
        raise KeyError(name)

    def render(self) -> str:
        lines = [f"{PRODUCT_NAME} doctor"]
        for check in self.checks:
            mark = "✓" if check.ok else "✗"
            lines.append(f"{mark} {check.name}: {check.detail}")
        return "\n".join(lines)


def _read_yaml(path: Path) -> dict:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_runtime(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _gateway_detail() -> str:
    try:
        from honeyos.gateway.status import get_running_pid

        pid = get_running_pid()
    except Exception:
        pid = None
    return f"running (PID {pid})" if pid else "stopped"


def run_doctor(home: Path) -> DoctorReport:
    """Inspect only the selected HONEYOS home and return bounded diagnostics."""

    resolved = home.expanduser().resolve()
    config = _read_yaml(resolved / "config.yaml")
    runtime = _read_runtime(resolved / "runtime.json")
    agent = config.get("agent", {}) if isinstance(config.get("agent", {}), dict) else {}
    platform_toolsets = config.get("platform_toolsets", {})
    expected_tools = list(COMPANION_TOOLSETS)
    configured_tools = {
        platform: platform_toolsets.get(platform, [])
        for platform in DEFAULT_IM_PLATFORMS
    } if isinstance(platform_toolsets, dict) else {}
    tool_allowlist_ok = all(
        configured_tools.get(platform) == expected_tools
        for platform in DEFAULT_IM_PLATFORMS
    )
    terminal = config.get("terminal", {}) if isinstance(config.get("terminal"), dict) else {}
    expected_projects = project_root(resolved).resolve()
    configured_cwd = Path(str(terminal.get("cwd", ""))).expanduser()
    project_workspace_ok = (
        terminal.get("backend") == "local"
        and configured_cwd.is_absolute()
        and configured_cwd.resolve() == expected_projects
        and expected_projects.is_dir()
        and os.access(expected_projects, os.W_OK)
        and terminal.get("env_passthrough") == []
    )
    approvals = config.get("approvals", {}) if isinstance(config.get("approvals"), dict) else {}
    approval_mode = str(approvals.get("mode", "")).strip().lower()
    execution_approval_ok = approval_mode in {"manual", "smart"}

    runtime_ok = bool(runtime) and (
        runtime.get("data_directory") == str(resolved)
        and Path(str(runtime.get("python_executable", ""))).is_absolute()
        and Path(str(runtime.get("repository_root", ""))).is_absolute()
    )
    storage_dirs = [resolved, resolved / "memories", resolved / "sessions", resolved / "logs"]
    storage_ok = all(path.exists() and os.access(path, os.W_OK) for path in storage_dirs)
    dispatch = gateway_argv("status")
    dispatch_ok = Path(dispatch[0]).is_absolute() and "honeyos" not in dispatch

    checks = (
        DoctorCheck("data-home", resolved.name == ".honeyos" or resolved.exists(), str(resolved)),
        DoctorCheck(
            "runtime-isolated",
            runtime_ok,
            f"absolute {PRODUCT_NAME} runtime recorded"
            if runtime_ok
            else "runtime.json missing or invalid",
        ),
        DoctorCheck(
            "companion-mode",
            str(agent.get("mode", "")).strip().lower() == "companion",
            str(agent.get("mode", "missing")),
        ),
        DoctorCheck(
            "bundled-skills-disabled",
            (resolved / ".no-bundled-skills").is_file(),
            "marker present" if (resolved / ".no-bundled-skills").is_file() else "marker missing",
        ),
        DoctorCheck(
            "tool-allowlist",
            tool_allowlist_ok,
            repr(configured_tools),
        ),
        DoctorCheck(
            "project-workspace",
            project_workspace_ok,
            f"local writable workspace at {expected_projects}"
            if project_workspace_ok
            else repr(terminal),
        ),
        DoctorCheck(
            "execution-approval",
            execution_approval_ok,
            approval_mode or "missing",
        ),
        DoctorCheck(
            "storage-writable",
            storage_ok,
            "data, memory, session, and log directories writable"
            if storage_ok
            else "one or more storage directories are unavailable",
        ),
        DoctorCheck(
            "absolute-runtime-dispatch",
            dispatch_ok,
            "uses the current Python executable" if dispatch_ok else "unsafe PATH dispatch",
        ),
        DoctorCheck("gateway-state", True, _gateway_detail()),
    )
    return DoctorReport(checks)


def print_doctor(home: Path) -> int:
    report = run_doctor(home)
    print(report.render())
    return 0 if report.ok else 1
