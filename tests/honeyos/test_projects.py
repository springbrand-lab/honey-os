from __future__ import annotations

from pathlib import Path

import yaml

import honeyos.companion.projects as projects_module
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


def test_recovery_copies_visible_legacy_projects_without_deleting_sources(
    tmp_path, monkeypatch
):
    home = tmp_path / ".honeyos"
    projects = tmp_path / "HoneyOS Projects"
    legacy = home / "sandboxes" / "docker" / "default"
    game = legacy / "workspace" / "game" / "index.html"
    note = legacy / "home" / "notes.txt"
    hidden_cache = legacy / "home" / ".cache" / "large.bin"
    game.parent.mkdir(parents=True)
    note.parent.mkdir(parents=True)
    hidden_cache.parent.mkdir(parents=True)
    game.write_text("<h1>game</h1>", encoding="utf-8")
    note.write_text("remember this project", encoding="utf-8")
    hidden_cache.write_bytes(b"cache")
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))
    recover = getattr(projects_module, "recover_legacy_projects", None)

    assert recover is not None
    result = recover(home)

    recovered = projects / "从旧版本恢复" / "default"
    assert (recovered / "workspace" / "game" / "index.html").read_text(
        encoding="utf-8"
    ) == "<h1>game</h1>"
    assert (recovered / "home" / "notes.txt").read_text(
        encoding="utf-8"
    ) == "remember this project"
    assert not (recovered / "home" / ".cache").exists()
    assert game.exists()
    assert note.exists()
    assert result.copied
    assert result.errors == ()


def test_recovery_is_idempotent_and_never_overwrites_a_collision(tmp_path, monkeypatch):
    home = tmp_path / ".honeyos"
    projects = tmp_path / "HoneyOS Projects"
    source = home / "sandboxes" / "docker" / "default" / "workspace" / "game.txt"
    destination = projects / "从旧版本恢复" / "default" / "workspace" / "game.txt"
    source.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    source.write_text("old container version", encoding="utf-8")
    destination.write_text("user kept version", encoding="utf-8")
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))
    recover = getattr(projects_module, "recover_legacy_projects", None)

    assert recover is not None
    first = recover(home)
    second = recover(home)

    assert destination.read_text(encoding="utf-8") == "user kept version"
    assert str(destination) in first.skipped
    assert second.copied == ()
    assert second.skipped == ()
    assert source.exists()


def test_recovery_never_scans_companion_memory(tmp_path, monkeypatch):
    home = tmp_path / ".honeyos"
    projects = tmp_path / "HoneyOS Projects"
    secret_memory = home / "memories" / "RELATIONSHIP.md"
    secret_memory.parent.mkdir(parents=True)
    secret_memory.write_text("private relationship", encoding="utf-8")
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))
    recover = getattr(projects_module, "recover_legacy_projects", None)

    assert recover is not None
    recover(home)

    assert secret_memory.read_text(encoding="utf-8") == "private relationship"
    assert not projects.exists() or not any(
        "private relationship" in path.read_text(encoding="utf-8", errors="ignore")
        for path in projects.rglob("*")
        if path.is_file()
    )
