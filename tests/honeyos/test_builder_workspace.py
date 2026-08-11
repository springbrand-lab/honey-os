from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "live-honeyos"
    (source / "honeyos" / "companion").mkdir(parents=True)
    (source / "honeyos" / "tools").mkdir(parents=True)
    (source / "honeyos" / "companion" / "feature.py").write_text(
        "VALUE = 'live'\n", encoding="utf-8"
    )
    (source / "honeyos" / "tools" / "permission_policy.py").write_text(
        "PROTECTED = True\n", encoding="utf-8"
    )
    (source / "README.md").write_text("# HoneyOS\n", encoding="utf-8")
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "builder-test@example.com")
    _git(source, "config", "user.name", "Builder Test")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "initial")
    return source


def test_prepare_builder_change_clones_review_only_workspace(tmp_path):
    from honeyos.companion.builder_workspace import prepare_builder_change

    source = _source_repo(tmp_path)
    live_file = source / "honeyos" / "companion" / "feature.py"

    prepared = prepare_builder_change(
        source_repo=source,
        goal="改善跨会话记忆",
        allowed_paths=("honeyos/companion/**", "tests/honeyos/**"),
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="memory-upgrade-001",
    )

    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert prepared.workspace != source
    assert prepared.workspace.is_relative_to(tmp_path / "HoneyOS Builder")
    assert _git(prepared.workspace, "branch", "--show-current") == (
        "honeyos-builder/memory-upgrade-001"
    )
    assert manifest["goal"] == "改善跨会话记忆"
    assert manifest["source_commit"] == _git(source, "rev-parse", "HEAD")
    assert manifest["installation"]["mode"] == "review_only"
    assert manifest["installation"]["automatic"] is False
    assert "honeyos/tools/permission_policy.py" in manifest["protected_paths"]
    assert (
        "honeyos/companion/companion_skills/honeyos-builder/**"
        in manifest["protected_paths"]
    )
    assert live_file.read_text(encoding="utf-8") == "VALUE = 'live'\n"


@pytest.mark.parametrize(
    "unsafe_scope",
    (
        "/Users/example",
        "../outside/**",
        "honeyos/tools/permission_policy.py",
    ),
)
def test_prepare_builder_change_rejects_unsafe_allowed_scope(
    tmp_path, unsafe_scope
):
    from honeyos.companion.builder_workspace import prepare_builder_change

    source = _source_repo(tmp_path)

    with pytest.raises(ValueError, match="allowed path"):
        prepare_builder_change(
            source_repo=source,
            goal="change the runtime",
            allowed_paths=(unsafe_scope,),
            builder_root=tmp_path / "HoneyOS Builder",
            change_id="unsafe-change-001",
        )


def test_inspect_builder_change_blocks_protected_and_out_of_scope_edits(tmp_path):
    from honeyos.companion.builder_workspace import (
        inspect_builder_change,
        prepare_builder_change,
    )

    prepared = prepare_builder_change(
        source_repo=_source_repo(tmp_path),
        goal="改善记忆",
        allowed_paths=("honeyos/**",),
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="memory-review-001",
    )
    (prepared.workspace / "honeyos" / "companion" / "feature.py").write_text(
        "VALUE = 'candidate'\n", encoding="utf-8"
    )
    (prepared.workspace / "honeyos" / "tools" / "permission_policy.py").write_text(
        "PROTECTED = False\n", encoding="utf-8"
    )
    (prepared.workspace / "README.md").write_text(
        "# silently changed\n", encoding="utf-8"
    )

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "blocked"
    assert report.allowed_changes == ("honeyos/companion/feature.py",)
    assert report.protected_changes == ("honeyos/tools/permission_policy.py",)
    assert report.out_of_scope_changes == ("README.md",)
    assert report.installable is False
    report_json = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert report_json["installation"]["automatic"] is False
    assert report.report_path.stat().st_mode & 0o777 == 0o600


def test_inspect_builder_change_does_not_mark_empty_candidate_review_ready(tmp_path):
    from honeyos.companion.builder_workspace import (
        inspect_builder_change,
        prepare_builder_change,
    )

    prepared = prepare_builder_change(
        source_repo=_source_repo(tmp_path),
        goal="改善记忆",
        allowed_paths=("honeyos/companion/**",),
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="empty-review-001",
    )

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "no_changes"
    assert report.installable is False
