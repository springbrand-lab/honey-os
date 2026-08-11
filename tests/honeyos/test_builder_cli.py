from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "live-honeyos"
    (source / "honeyos" / "companion").mkdir(parents=True)
    (source / "honeyos" / "companion" / "activity.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (source / "pyproject.toml").write_text(
        "[project]\nname = 'honeyos-test'\n", encoding="utf-8"
    )
    (source / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "init", "-b", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Test"], check=True
    )
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(source), "commit", "-m", "initial"], check=True
    )
    return source


def test_builder_prepare_cli_uses_managed_projects_and_returns_manifest(
    tmp_path, monkeypatch, capsys
):
    from honeyos.runtime.builder_cmd import build_parser, builder_command

    projects = tmp_path / "HoneyOS Projects"
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path / ".honeyos"))
    source = _source_repo(tmp_path)
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_parser(subparsers)
    args = parser.parse_args(
        [
            "builder",
            "prepare",
            "--source",
            str(source),
            "--goal",
            "改善记忆",
            "--allow",
            "honeyos/companion/**",
            "--change-id",
            "memory-cli-001",
        ]
    )

    assert builder_command(args) == 0

    payload = json.loads(capsys.readouterr().out)
    workspace = Path(payload["workspace"])
    manifest = Path(payload["manifest"])
    assert workspace.is_relative_to(projects / "HoneyOS Builder")
    assert manifest.is_relative_to(tmp_path / ".honeyos" / "builder")
    assert not manifest.is_relative_to(projects)
    assert manifest.is_file()
    assert payload["installation"] == "awaiting_user_confirmation"

    (workspace / "honeyos" / "companion" / "activity.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    inspect_args = parser.parse_args(["builder", "inspect", "memory-cli-001"])

    assert builder_command(inspect_args) == 0

    inspect_payload = json.loads(capsys.readouterr().out)
    assert inspect_payload["candidate_digest"]


def test_honeyos_main_exposes_builder_command():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from honeyos.runtime.main import main; "
            "sys.argv=['honeyos', 'builder', '--help']; main()",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "prepare" in completed.stdout
    assert "inspect" in completed.stdout
    assert "activate" in completed.stdout


def test_public_honeyos_command_exposes_builder():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from honeyos.cli.main import main; raise SystemExit(main(['builder', '--help']))",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "activate" in completed.stdout


def test_builder_activate_stages_static_checks_then_uses_plain_confirmation(
    tmp_path, monkeypatch, capsys
):
    from dataclasses import replace

    from honeyos.companion.builder_activation import ActivationStore
    from honeyos.runtime.builder_cmd import build_parser, builder_command

    projects = tmp_path / "HoneyOS Projects"
    home = tmp_path / ".honeyos"
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))
    monkeypatch.setenv("HONEYOS_HOME", str(home))
    source = _source_repo(tmp_path)
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_parser(subparsers)
    prepared = parser.parse_args(
        [
            "builder",
            "prepare",
            "--source",
            str(source),
            "--goal",
            "调整活动文案",
            "--allow",
            "honeyos/companion/activity.py",
            "--change-id",
            "activity-cli-001",
        ]
    )
    assert builder_command(prepared) == 0
    capsys.readouterr()
    workspace = projects / "HoneyOS Builder" / "changes" / "activity-cli-001" / "source"
    (workspace / "honeyos" / "companion" / "activity.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    inspect_args = parser.parse_args(["builder", "inspect", "activity-cli-001"])
    assert builder_command(inspect_args) == 0
    capsys.readouterr()

    seen: list[str] = []

    def confirmed(self, activation_id, **_kwargs):
        record = self.verify_staged(activation_id)
        assert record.state == "awaiting_confirmation"
        seen.append(activation_id)
        return replace(record, state="healthy")

    monkeypatch.setattr(ActivationStore, "activate_confirmed", confirmed)
    args = parser.parse_args(["builder", "activate", "activity-cli-001"])

    assert builder_command(args) == 0

    payload = json.loads(capsys.readouterr().out)
    assert seen == [payload["activation_id"]]
    assert payload["state"] == "healthy"
