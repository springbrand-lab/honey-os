from __future__ import annotations

import tomllib
from pathlib import Path

from h2os_cli.bootstrap import activate_h2os_home
from h2os_cli.config import initialize_home
from h2os_cli.distribution import (
    resolved_companion_tool_definitions,
    validate_distribution,
)
from h2os_cli.runtime import write_runtime_identity


def _home(tmp_path):
    home = activate_h2os_home(tmp_path)
    initialize_home(home)
    write_runtime_identity(home)
    return home


def test_h2os_install_extra_includes_free_web_search_backend():
    pyproject = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "ddgs==9.14.4" in pyproject["project"]["optional-dependencies"]["h2os"]


def test_distribution_contract_exposes_companion_action_tools_without_orchestration(tmp_path):
    home = _home(tmp_path)

    definitions = resolved_companion_tool_definitions(home)
    names = {definition["function"]["name"] for definition in definitions}

    assert {
        "companion_memory",
        "memory",
        "session_search",
        "browser_navigate",
        "skills_list",
        "skill_manage",
        "todo",
        "cronjob",
    }.issubset(names)
    assert not {
        "delegate_task",
        "kanban_create",
    }.intersection(names)


def test_companion_memory_schema_requires_explicit_confirmation(tmp_path):
    home = _home(tmp_path)

    definitions = resolved_companion_tool_definitions(home)
    memory = next(item for item in definitions if item["function"]["name"] == "memory")
    description = memory["function"]["description"]

    assert "explicitly" in description.lower()
    assert "save proactively" not in description.lower()
    assert "inferred" in description.lower()


def test_distribution_validator_reports_all_contracts(tmp_path):
    home = _home(tmp_path)

    checks = validate_distribution(home)

    assert checks
    assert all(check.ok for check in checks), [check for check in checks if not check.ok]
