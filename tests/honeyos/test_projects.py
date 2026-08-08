from __future__ import annotations

from pathlib import Path

import yaml

from honeyos.companion.config import initialize_home


def test_initialize_home_creates_visible_local_project_workspace(tmp_path, monkeypatch):
    projects = tmp_path / "HoneyOS Projects"
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))

    initialize_home(tmp_path / ".honeyos")

    config = yaml.safe_load(
        (tmp_path / ".honeyos" / "config.yaml").read_text(encoding="utf-8")
    )
    assert projects.is_dir()
    assert config["terminal"]["backend"] == "local"
    assert Path(config["terminal"]["cwd"]) == projects.resolve()
    assert config["terminal"]["env_passthrough"] == []
    assert config["approvals"]["mode"] == "manual"


def test_local_project_workspace_does_not_store_companion_memory(tmp_path, monkeypatch):
    projects = tmp_path / "HoneyOS Projects"
    home = tmp_path / ".honeyos"
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))

    initialize_home(home)

    assert (home / "memories").is_dir()
    assert not (projects / "memories").exists()
    assert not (projects / "SOUL.md").exists()
