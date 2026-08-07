"""Executable acceptance checks for the HONEYOS distribution contract."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from honeyos.cli.bootstrap import activate_home
from honeyos.companion.config import COMPANION_TOOLSETS
from honeyos.companion.doctor import DoctorCheck, run_doctor


_REQUIRED_COMPANION_TOOL_NAMES = {
    "companion_memory",
    "memory",
    "session_search",
    "browser_navigate",
    "skills_list",
    "skill_manage",
    "todo",
    "cronjob",
}
_FORBIDDEN_WORK_TOOL_NAMES = {
    "delegate_task",
    "kanban_create",
}


def resolved_companion_tool_definitions(home: Path) -> list[dict]:
    """Resolve the real model schema exposed by the companion toolsets."""

    activate_home(home)
    from honeyos.model_tools import _clear_tool_defs_cache, get_tool_definitions

    _clear_tool_defs_cache()
    previous_gateway_session = os.environ.get("HONEYOS_GATEWAY_SESSION")
    os.environ["HONEYOS_GATEWAY_SESSION"] = "1"
    try:
        definitions = get_tool_definitions(
            enabled_toolsets=list(COMPANION_TOOLSETS),
            quiet_mode=True,
            skip_tool_search_assembly=True,
        )
    finally:
        if previous_gateway_session is None:
            os.environ.pop("HONEYOS_GATEWAY_SESSION", None)
        else:
            os.environ["HONEYOS_GATEWAY_SESSION"] = previous_gateway_session
    return sorted(
        definitions,
        key=lambda item: item.get("function", {}).get("name", ""),
    )


def _read_config(home: Path) -> dict:
    try:
        value = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_distribution(home: Path) -> tuple[DoctorCheck, ...]:
    """Validate generated config and the resolved model-facing surface."""

    resolved = activate_home(home)
    config = _read_config(resolved)
    memory = config.get("memory", {}) if isinstance(config.get("memory"), dict) else {}
    skills = config.get("skills", {}) if isinstance(config.get("skills"), dict) else {}
    definitions = resolved_companion_tool_definitions(resolved)
    names = {item.get("function", {}).get("name") for item in definitions}
    doctor_checks = run_doctor(resolved).checks
    return doctor_checks + (
        DoctorCheck(
            "resolved-model-tools",
            _REQUIRED_COMPANION_TOOL_NAMES.issubset(names)
            and not _FORBIDDEN_WORK_TOOL_NAMES.intersection(names),
            repr(sorted(names)),
        ),
        DoctorCheck(
            "background-review-disabled",
            memory.get("nudge_interval") == 0
            and skills.get("creation_nudge_interval") == 0,
            f"memory={memory.get('nudge_interval')!r}, skills={skills.get('creation_nudge_interval')!r}",
        ),
        DoctorCheck(
            "mcp-disabled",
            config.get("mcp_servers", {}) == {},
            "no MCP servers configured",
        ),
    )
