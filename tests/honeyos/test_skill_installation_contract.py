from __future__ import annotations

import json
from types import SimpleNamespace

from honeyos.companion.config import initialize_home


def test_skills_list_reports_local_tree_as_installed_with_provenance(
    monkeypatch, tmp_path
):
    initialize_home(tmp_path)
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))

    from honeyos.tools import skills_tool

    skills_tool._SKILLS_CACHE.clear()
    payload = json.loads(skills_tool.skills_list())
    relationship = next(
        skill
        for skill in payload["skills"]
        if skill["name"] == "relationship-continuity"
    )

    assert payload["catalog"] == "installed"
    assert relationship["installed"] is True
    assert relationship["enabled"] is True
    assert relationship["source"] == "bundled"


def test_empty_skills_list_still_identifies_the_installed_catalog(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))

    from honeyos.tools import skills_tool

    skills_tool._SKILLS_CACHE.clear()
    payload = json.loads(skills_tool.skills_list())

    assert payload["success"] is True
    assert payload["catalog"] == "installed"
    assert payload["skills"] == []


def test_companion_skill_index_is_explicitly_an_installed_index(
    monkeypatch, tmp_path
):
    initialize_home(tmp_path)
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))

    from honeyos.agent import prompt_builder

    prompt_builder._SKILLS_PROMPT_CACHE.clear()
    prompt = prompt_builder.build_skills_system_prompt(companion_mode=True)

    assert "下面列出的 Skill 都已安装" in prompt
    assert "<installed_skills>" in prompt
    assert "<available_skills>" not in prompt


def test_skills_tool_schema_calls_the_index_installed_not_available():
    from honeyos.tools.skills_tool import SKILLS_LIST_SCHEMA

    assert "installed" in SKILLS_LIST_SCHEMA["description"].lower()
    assert "available skills" not in SKILLS_LIST_SCHEMA["description"].lower()


def test_skill_marketplace_search_runs_in_host_runtime(monkeypatch):
    from honeyos.tools.skill_marketplace_tool import skill_marketplace

    observed = []

    def fake_run(argv, **kwargs):
        observed.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "name": "relationship-check-in",
                        "identifier": "official/relationship-check-in",
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    payload = json.loads(skill_marketplace("search", query="relationship", limit=5))

    assert payload["success"] is True
    assert payload["catalog"] == "marketplace"
    assert payload["skills"][0]["installed"] is False
    argv, kwargs = observed[0]
    assert argv[-6:] == [
        "skills",
        "search",
        "relationship",
        "--limit",
        "5",
        "--json",
    ]
    assert kwargs["shell"] is False


def test_skill_marketplace_install_uses_scanned_noninteractive_runtime(monkeypatch):
    from honeyos.tools.skill_marketplace_tool import skill_marketplace

    observed = []

    def fake_run(argv, **kwargs):
        observed.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout="Installed: relationship-check-in\n",
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    payload = json.loads(
        skill_marketplace(
            "install",
            identifier="official/relationship-check-in",
        )
    )

    assert payload["success"] is True
    assert observed[0][-3:] == [
        "install",
        "official/relationship-check-in",
        "--yes",
    ]


def test_normal_skill_install_does_not_create_builder_activation(monkeypatch, tmp_path):
    from honeyos.tools.skill_marketplace_tool import skill_marketplace

    home = tmp_path / ".honeyos"
    monkeypatch.setenv("HONEYOS_HOME", str(home))
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="Installed: relationship-check-in\n", stderr=""
        ),
    )

    payload = json.loads(
        skill_marketplace("install", identifier="official/relationship-check-in")
    )

    assert payload["success"] is True
    assert not (home / "builder" / "changes").exists()
    assert not (home / "runtime" / "current-slot.json").exists()


def test_skills_toolset_exposes_marketplace_bridge():
    from honeyos.toolsets import resolve_toolset

    assert "skill_marketplace" in resolve_toolset("skills")
