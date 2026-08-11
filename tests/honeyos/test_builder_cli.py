from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "live-honeyos"
    (source / "honeyos" / "companion").mkdir(parents=True)
    (source / "honeyos" / "companion" / "feature.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
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
    assert payload["installation"] == "review_only"

    (workspace / "honeyos" / "companion" / "feature.py").write_text(
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
    assert "review-only" in completed.stdout
