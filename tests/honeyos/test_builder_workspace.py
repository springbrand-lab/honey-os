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
    (source / "honeyos" / "runtime").mkdir(parents=True)
    (source / "honeyos" / "companion" / "feature.py").write_text(
        "VALUE = 'live'\n", encoding="utf-8"
    )
    (source / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "MEMORY = 'live'\n", encoding="utf-8"
    )
    (source / "honeyos" / "tools" / "permission_policy.py").write_text(
        "PROTECTED = True\n", encoding="utf-8"
    )
    (source / "honeyos" / "runtime" / "model_routing.py").write_text(
        "MODEL = 'default'\n", encoding="utf-8"
    )
    (source / "README.md").write_text("# HoneyOS\n", encoding="utf-8")
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "builder-test@example.com")
    _git(source, "config", "user.name", "Builder Test")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "initial")
    return source


def _prepared_change(
    tmp_path: Path, *, allowed_paths: tuple[str, ...] = ("honeyos/companion/**",)
):
    from honeyos.companion.builder_workspace import prepare_builder_change

    return prepare_builder_change(
        source_repo=_source_repo(tmp_path),
        goal="改善记忆",
        allowed_paths=allowed_paths,
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="candidate-review-001",
    )


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


def test_prepare_writes_private_authoritative_policy_outside_candidate_workspace(tmp_path):
    prepared = _prepared_change(tmp_path)

    policy_path = prepared.change_root / "trusted-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))

    assert policy_path.is_file()
    assert not policy_path.is_relative_to(prepared.workspace)
    assert policy_path.stat().st_mode & 0o777 == 0o600
    assert policy["change_id"] == prepared.change_id
    assert policy["workspace"] == str(prepared.workspace)
    assert policy["allowed_paths"] == ["honeyos/companion/**"]


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
    (prepared.workspace / "honeyos" / "companion" / "persistent_memory.py").write_text(
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
    assert report.allowed_changes == ("honeyos/companion/persistent_memory.py",)
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


def test_inspect_binds_review_to_candidate_digest(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path)
    feature = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    feature.write_text("VALUE = 'candidate'\n", encoding="utf-8")

    first = inspect_builder_change(prepared.change_root)
    report_json = json.loads(first.report_path.read_text(encoding="utf-8"))
    feature.write_text("VALUE = 'changed-after-review'\n", encoding="utf-8")
    second = inspect_builder_change(prepared.change_root)

    assert first.candidate_digest
    assert second.candidate_digest != first.candidate_digest
    assert report_json["source_commit"]
    assert report_json["candidate_digest"] == first.candidate_digest
    assert report_json["reviewed_at"]


def test_candidate_digest_rejects_symlink(tmp_path):
    from honeyos.companion.builder_workspace import candidate_digest

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "outside.py"
    target.write_text("VALUE = 'outside'\n", encoding="utf-8")
    (workspace / "candidate.py").symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        candidate_digest(workspace, "source-commit", ("candidate.py",))


def test_inspect_rejects_workspace_commit_different_from_review_base(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path)
    feature = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    feature.write_text("VALUE = 'committed candidate'\n", encoding="utf-8")
    _git(prepared.workspace, "add", str(feature.relative_to(prepared.workspace)))
    _git(prepared.workspace, "commit", "-m", "candidate change")

    with pytest.raises(ValueError, match="revision"):
        inspect_builder_change(prepared.change_root)


def test_inspect_blocks_ignored_non_ephemeral_candidate_content(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path, allowed_paths=("**",))
    (prepared.workspace / ".gitignore").write_text("hidden_module.py\n", encoding="utf-8")
    (prepared.workspace / "hidden_module.py").write_text(
        "VALUE = 'must not hide'\n", encoding="utf-8"
    )

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "blocked"
    assert "hidden_module.py" in report.out_of_scope_changes


def test_inspect_ignores_narrow_ephemeral_cache_content(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path)
    (prepared.workspace / ".git" / "info" / "exclude").write_text(
        ".pytest_cache/\n", encoding="utf-8"
    )
    cache = prepared.workspace / ".pytest_cache" / "v" / "cache"
    cache.mkdir(parents=True)
    (cache / "nodeids").write_text("[]\n", encoding="utf-8")

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "no_changes"


def test_inspect_rejects_stale_policy_manifest(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path)
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    manifest["policy_version"] = 1
    manifest["protected_paths"] = []
    prepared.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="policy is stale"):
        inspect_builder_change(prepared.change_root)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("goal", "install something else"),
        ("allowed_paths", ["**"]),
        ("source_commit", "0" * 40),
        ("workspace", "/tmp/not-the-candidate"),
    ),
)
def test_inspect_rejects_mutable_manifest_identity_or_scope_tampering(
    tmp_path, field, replacement
):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path)
    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    manifest[field] = replacement
    prepared.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="trusted policy"):
        inspect_builder_change(prepared.change_root)


@pytest.mark.parametrize("mutation", ("missing", "invalid"))
def test_inspect_fails_closed_when_authoritative_policy_is_missing_or_tampered(
    tmp_path, mutation
):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path)
    policy_path = prepared.change_root / "trusted-policy.json"
    if mutation == "missing":
        policy_path.unlink()
    else:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["allowed_paths"] = ["**"]
        policy_path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(ValueError, match="trusted policy"):
        inspect_builder_change(prepared.change_root)


def test_review_binds_authoritative_policy_scope_and_digest(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path)
    feature = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    feature.write_text("VALUE = 'candidate'\n", encoding="utf-8")

    report = inspect_builder_change(prepared.change_root)
    report_json = json.loads(report.report_path.read_text(encoding="utf-8"))

    assert report_json["allowed_paths"] == ["honeyos/companion/**"]
    assert report_json["policy_digest"]
    assert report_json["candidate_digest"] == report.candidate_digest
    assert report_json["changed_paths"] == [
        {"path": "honeyos/companion/persistent_memory.py", "status": " M"}
    ]


def test_inspect_permits_explicit_companion_behavior_change(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path, allowed_paths=("honeyos/companion/**",))
    path = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    path.write_text("MEMORY = 'personalized'\n", encoding="utf-8")

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "review_ready"
    assert report.allowed_changes == ("honeyos/companion/persistent_memory.py",)


@pytest.mark.parametrize(
    "path",
    (
        "honeyos/companion/builder_activation.py",
        "honeyos/runtime/builder_activation_worker.py",
        "honeyos/tools/companion_builder_tool.py",
        "honeyos/runtime/gateway.py",
        "honeyos/runtime/backup.py",
        "honeyos/runtime/service_manager.py",
        "honeyos/gateway/platforms/api_server.py",
        "honeyos/gateway/run.py",
        "honeyos/tools/terminal_tool.py",
        "honeyos/tools/code_execution_tool.py",
        "honeyos/tools/computer_use_tool.py",
        "honeyos/tools/computer_use/tool.py",
        "honeyos/gateway/slash_commands.py",
        "honeyos/agent/tool_executor.py",
        "honeyos/runtime/approval_mode.py",
        "honeyos/runtime/approvals_suggest.py",
        "honeyos/runtime/subcommands/approvals.py",
        "honeyos/runtime/write_approval_commands.py",
        "pyproject.toml",
        "uv.lock",
        "install.sh",
        "scripts/build_release_zip.sh",
    ),
)
def test_builder_blocks_activation_and_dependency_surfaces(tmp_path, path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path, allowed_paths=("**",))
    target = prepared.workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n", encoding="utf-8")

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "blocked"
    assert path in report.protected_changes


def test_builder_allows_ordinary_honeyos_code_but_blocks_execution_enforcement(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path, allowed_paths=("honeyos/**",))
    allowed = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    protected = prepared.workspace / "honeyos" / "tools" / "terminal_tool.py"
    allowed.write_text("VALUE = 'candidate'\n", encoding="utf-8")
    protected.write_text("def terminal(): pass\n", encoding="utf-8")

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "blocked"
    assert report.allowed_changes == ("honeyos/companion/persistent_memory.py",)
    assert report.protected_changes == ("honeyos/tools/terminal_tool.py",)


@pytest.mark.parametrize(
    "path",
    (
        "honeyos/model_tools.py",
        "honeyos/toolsets.py",
        "honeyos/agent/agent_runtime_helpers.py",
        "honeyos/runtime/middleware.py",
        "honeyos/tools/registry.py",
    ),
)
def test_static_activation_surface_blocks_control_plane_even_when_all_metadata_is_broadened(
    tmp_path, path
):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path, allowed_paths=("**",))
    target = prepared.workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n", encoding="utf-8")

    # Same-user filesystem writes can alter both JSON records.  They must not
    # turn a non-static product/control-plane path into an activatable change.
    for record_path in (prepared.manifest_path, prepared.trusted_policy_path):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["allowed_paths"] = ["**"]
        record_path.write_text(json.dumps(record), encoding="utf-8")

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "blocked"
    assert path in report.protected_changes


def test_static_activation_surface_keeps_safe_companion_ui_reviewable(tmp_path):
    from honeyos.companion.builder_workspace import inspect_builder_change

    prepared = _prepared_change(tmp_path, allowed_paths=("**",))
    path = prepared.workspace / "honeyos" / "companion" / "web_assets" / "styles.css"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(".companion { color: honeydew; }\n", encoding="utf-8")

    report = inspect_builder_change(prepared.change_root)

    assert report.status == "review_ready"
    assert report.allowed_changes == ("honeyos/companion/web_assets/styles.css",)
