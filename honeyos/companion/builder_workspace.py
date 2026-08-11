"""Review-only workspaces for user-requested HoneyOS product changes.

The companion never edits the checkout that is currently running HoneyOS.
This module prepares an isolated Git clone plus a machine-readable policy
manifest.  A later review step decides whether a candidate is safe to hand to
a human developer; this first version deliberately has no install operation.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_PROTECTED_PATHS = (
    ".env",
    ".env.*",
    # The host execution, service, gateway, agent-loop, and tool-dispatch
    # trees are not a self-modification surface.  Listing the whole trees is
    # intentional: new files in them must be protected by default too.
    "honeyos/agent/**",
    "honeyos/cli/**",
    "honeyos/core/**",
    "honeyos/gateway/**",
    "honeyos/runtime/**",
    "honeyos/tools/**",
    "honeyos/migration/**",
    "honeyos/plugins/**",
    "honeyos/providers/**",
    "honeyos/model_tools.py",
    "honeyos/toolsets.py",
    "honeyos/run_agent.py",
    "honeyos/__main__.py",
    "honeyos/__init__.py",
    "honeyos/utils.py",
    "honeyos/agent/file_safety.py",
    "honeyos/companion/builder_workspace.py",
    "honeyos/companion/builder_activation*.py",
    "honeyos/companion/companion_skills/honeyos-builder/**",
    "honeyos/companion/companion_skills/honeyos-self-extension/**",
    "honeyos/companion/projects.py",
    "honeyos/runtime/auth.py",
    "honeyos/runtime/backup.py",
    "honeyos/runtime/builder_cmd.py",
    "honeyos/runtime/builder_activation_worker.py",
    "honeyos/runtime/gateway.py",
    "honeyos/runtime/gateway_windows.py",
    "honeyos/runtime/main.py",
    "honeyos/runtime/service_manager.py",
    "honeyos/cli/service.py",
    # Gateway ingress and the tools that enforce approvals before host-side
    # execution are part of the trusted control plane.  Builder can still
    # improve ordinary HoneyOS application/runtime modules.
    "honeyos/gateway/authz_mixin.py",
    "honeyos/gateway/pairing.py",
    "honeyos/gateway/platforms/api_server.py",
    "honeyos/gateway/run.py",
    "honeyos/tools/approval.py",
    "honeyos/tools/write_approval.py",
    "honeyos/tools/companion_builder_tool.py",
    "honeyos/tools/terminal_tool.py",
    "honeyos/tools/code_execution_tool.py",
    "honeyos/tools/computer_use_tool.py",
    "honeyos/tools/computer_use/permissions.py",
    "honeyos/tools/permission_policy.py",
    "honeyos/tools/threat_patterns.py",
    "honeyos/tools/slash_confirm.py",
    "honeyos/runtime/approval_mode.py",
    "honeyos/runtime/approvals_suggest.py",
    "honeyos/runtime/subcommands/approvals.py",
    "honeyos/runtime/write_approval_commands.py",
    "honeyos/runtime/subcommands/pairing.py",
    "honeyos/gateway/slash_commands.py",
    "honeyos/agent/tool_executor.py",
    "honeyos/cli/main.py",
    "honeyos/tools/computer_use/**",
    "honeyos/tools/file_tools.py",
    "honeyos/tools/memory_tool.py",
    "honeyos/tools/companion_memory_tool.py",
    "honeyos/tools/skill_manager_tool.py",
    "pyproject.toml",
    "uv.lock",
    "requirements*.txt",
    "requirements/**/*.txt",
    "install.sh",
    "Install-HoneyOS.command",
    "install*",
    "update*",
    "release*",
    "scripts/*install*",
    "scripts/*update*",
    "scripts/*release*",
    "scripts/**/install*",
    "scripts/**/update*",
    "scripts/**/release*",
)


# This is the release-1 security boundary for controlled self-modification.
# It is owned by the currently running HoneyOS code, not a Builder task or its
# JSON files.  The user can ask Builder to work on a narrower area, but neither
# a broad task scope nor same-user edits to metadata can expand this list.
#
# Keep this deliberately explicit.  Companion product behavior, personality,
# memories, ordinary companion skills, and the browser presentation are safe
# to review/activate.  Configuration, installation, status/health, the
# project/filesystem boundary, permission UI, and Builder wiring stay trusted.
DEFAULT_ACTIVATABLE_PATHS = (
    "docs/**",
    "tests/**",
    "README.md",
    "honeyos/companion/activity.py",
    "honeyos/companion/channels.py",
    "honeyos/companion/continuity.py",
    "honeyos/companion/distillation.py",
    "honeyos/companion/memory_policy.py",
    "honeyos/companion/model_intent.py",
    "honeyos/companion/persistent_memory.py",
    "honeyos/companion/profile.py",
    "honeyos/companion/status_copy.py",
    "honeyos/companion/topic_delivery.py",
    "honeyos/companion/topic_pool.py",
    "honeyos/companion/topic_scout.py",
    "honeyos/companion/templates/**",
    "honeyos/companion/web_assets/**",
    "honeyos/companion/companion_skills/**",
)


# This version is intentionally owned by the running trusted control plane,
# rather than by a candidate manifest.  Older manifests must be recreated so a
# candidate cannot dilute a newly added safety boundary by editing JSON.
BUILDER_POLICY_VERSION = 3
TRUSTED_POLICY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PreparedBuilderChange:
    change_id: str
    change_root: Path
    workspace: Path
    manifest_path: Path
    trusted_policy_path: Path


@dataclass(frozen=True)
class BuilderReviewReport:
    status: str
    allowed_changes: tuple[str, ...]
    protected_changes: tuple[str, ...]
    out_of_scope_changes: tuple[str, ...]
    installable: bool
    report_path: Path
    candidate_digest: str = ""


@dataclass(frozen=True)
class _ChangedPath:
    relative: str
    status: str


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _validate_change_id(change_id: str) -> str:
    value = change_id.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", value):
        raise ValueError(
            "change_id must use 3-64 lowercase letters, numbers, or hyphens"
        )
    return value


def _validate_allowed_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_path in paths:
        value = str(raw_path).strip().replace("\\", "/")
        parts = tuple(part for part in value.split("/") if part not in ("", "."))
        if (
            not value
            or value.startswith("/")
            or re.match(r"^[A-Za-z]:", value)
            or ".." in parts
        ):
            raise ValueError(f"unsafe allowed path: {raw_path}")
        canonical = "/".join(parts)
        if any(
            fnmatch.fnmatchcase(canonical, protected)
            for protected in DEFAULT_PROTECTED_PATHS
        ):
            raise ValueError(f"allowed path overlaps a protected path: {raw_path}")
        if canonical not in normalized:
            normalized.append(canonical)
    if not normalized:
        raise ValueError("at least one allowed path is required")
    return tuple(normalized)


def _canonical_json_bytes(payload: object) -> bytes:
    """Serialize trusted metadata deterministically before binding a review."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _trusted_policy_digest(policy: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json_bytes(policy)).hexdigest()


def _trusted_policy_path(change_root: Path) -> Path:
    return change_root / "trusted-policy.json"


def _load_json_object(path: Path, *, description: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} is missing or invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description} is missing or invalid")
    return payload


def _load_trusted_policy(change_root: Path) -> tuple[dict[str, object], str]:
    """Load Builder task metadata kept outside its candidate checkout.

    This record binds the candidate to its requested goal and makes a useful
    audit trail.  It is *not* a security boundary: a same-user process may be
    able to alter local files.  Activation eligibility is instead decided by
    :data:`DEFAULT_ACTIVATABLE_PATHS` and :data:`DEFAULT_PROTECTED_PATHS` in
    the currently running trusted code.
    """

    path = _trusted_policy_path(change_root)
    policy = _load_json_object(path, description="trusted policy")
    if (
        policy.get("schema_version") != TRUSTED_POLICY_SCHEMA_VERSION
        or policy.get("policy_version") != BUILDER_POLICY_VERSION
    ):
        raise ValueError("trusted policy is missing or invalid")

    change_id = policy.get("change_id")
    goal = policy.get("goal")
    source_repo = policy.get("source_repo")
    source_commit = policy.get("source_commit")
    workspace_raw = policy.get("workspace")
    workspace_root_raw = policy.get("workspace_root")
    change_root_raw = policy.get("change_root")
    allowed_raw = policy.get("allowed_paths")
    if not all(
        isinstance(value, str) and value
        for value in (
            change_id,
            goal,
            source_repo,
            source_commit,
            workspace_raw,
            workspace_root_raw,
            change_root_raw,
        )
    ) or not isinstance(allowed_raw, list):
        raise ValueError("trusted policy is missing or invalid")
    try:
        normalized_id = _validate_change_id(change_id)
        allowed = _validate_allowed_paths(allowed_raw)
        workspace_root = Path(workspace_root_raw).expanduser().resolve()
        workspace = Path(workspace_raw).expanduser().resolve()
        recorded_change_root = Path(change_root_raw).expanduser().resolve()
    except (TypeError, ValueError) as exc:
        raise ValueError("trusted policy is missing or invalid") from exc

    expected_workspace = workspace_root / "changes" / normalized_id / "source"
    if (
        recorded_change_root != change_root
        or workspace != expected_workspace
        or list(allowed) != allowed_raw
    ):
        raise ValueError("trusted policy is missing or invalid")
    return policy, _trusted_policy_digest(policy)


def _manifest_matches_trusted_policy(
    manifest: dict[str, object], policy: dict[str, object]
) -> bool:
    """Require the candidate-visible manifest to be an exact policy mirror."""

    mirrored_fields = (
        "change_id",
        "goal",
        "source_repo",
        "source_commit",
        "branch",
        "workspace",
        "workspace_root",
        "allowed_paths",
    )
    return all(manifest.get(field) == policy.get(field) for field in mirrored_fields)


def prepare_builder_change(
    *,
    source_repo: Path | str,
    goal: str,
    allowed_paths: Iterable[str],
    builder_root: Path | str,
    change_id: str,
    state_root: Path | str | None = None,
) -> PreparedBuilderChange:
    """Clone ``source_repo`` into an isolated, review-only change workspace."""

    source = Path(source_repo).expanduser().resolve()
    if not source.is_dir() or not (source / ".git").exists():
        raise ValueError("source_repo must be a local Git checkout")
    goal_text = goal.strip()
    if not goal_text:
        raise ValueError("goal must not be empty")
    normalized_id = _validate_change_id(change_id)
    allowed = _validate_allowed_paths(allowed_paths)

    workspace_root = Path(builder_root).expanduser().resolve()
    policy_root = (
        Path(state_root).expanduser().resolve() if state_root is not None else workspace_root
    )
    change_root = policy_root / "changes" / normalized_id
    workspace_change_root = workspace_root / "changes" / normalized_id
    workspace = workspace_change_root / "source"
    manifest_path = change_root / "manifest.json"
    trusted_policy_path = _trusted_policy_path(change_root)
    if change_root.exists() or workspace_change_root.exists():
        raise FileExistsError(f"builder change already exists: {normalized_id}")
    change_root.mkdir(parents=True)
    change_root.chmod(0o700)
    if workspace_change_root != change_root:
        workspace_change_root.mkdir(parents=True)

    try:
        source_commit = _git(source, "rev-parse", "HEAD")
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(source), str(workspace)],
            check=True,
            capture_output=True,
            text=True,
        )
        branch = f"honeyos-builder/{normalized_id}"
        _git(workspace, "switch", "-c", branch)
        if _git(workspace, "rev-parse", "HEAD") != source_commit:
            raise ValueError("source checkout changed while Builder was preparing a candidate")
        trusted_policy = {
            "schema_version": TRUSTED_POLICY_SCHEMA_VERSION,
            "policy_version": BUILDER_POLICY_VERSION,
            "change_id": normalized_id,
            "goal": goal_text,
            "source_repo": str(source),
            "source_commit": source_commit,
            "branch": branch,
            "workspace": str(workspace),
            "workspace_root": str(workspace_root),
            "change_root": str(change_root),
            "allowed_paths": list(allowed),
        }
        trusted_policy_path.write_text(
            json.dumps(trusted_policy, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        trusted_policy_path.chmod(0o600)
        manifest = {
            "schema_version": 2,
            "policy_version": BUILDER_POLICY_VERSION,
            "change_id": normalized_id,
            "goal": goal_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_repo": str(source),
            "source_commit": source_commit,
            "branch": branch,
            "workspace": str(workspace),
            "workspace_root": str(workspace_root),
            "allowed_paths": list(allowed),
            "protected_paths": list(DEFAULT_PROTECTED_PATHS),
            "activatable_paths": list(DEFAULT_ACTIVATABLE_PATHS),
            "data_access": {
                "real_user_memory": False,
                "credentials": False,
                "synthetic_test_data": True,
            },
            "installation": {
                "mode": "review_only",
                "automatic": False,
                "requires_human_review": True,
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
    except Exception:
        # Keep failures recoverable without ever touching the live checkout.
        import shutil

        shutil.rmtree(change_root, ignore_errors=True)
        if workspace_change_root != change_root:
            shutil.rmtree(workspace_change_root, ignore_errors=True)
        raise

    return PreparedBuilderChange(
        change_id=normalized_id,
        change_root=change_root,
        workspace=workspace,
        manifest_path=manifest_path,
        trusted_policy_path=trusted_policy_path,
    )


def _is_ephemeral_ignored(path: str) -> bool:
    """Return true only for local test/tool cache bytes never copied to a slot."""

    parts = Path(path).parts
    return (
        ".pytest_cache" in parts
        or "__pycache__" in parts
        or path.endswith(".pyc")
        or path == ".coverage"
        or path.startswith(".ruff_cache/")
        or path.startswith(".mypy_cache/")
    )


def _changed_paths(workspace: Path) -> tuple[_ChangedPath, ...]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "-z",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[_ChangedPath] = []
    records = completed.stdout.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        path = record[3:]
        if status == "!!":
            if path and not _is_ephemeral_ignored(path):
                paths.append(_ChangedPath(path, status))
            continue
        if "R" in status or "C" in status:
            # Porcelain -z emits the destination first and the source next.
            source = records[index] if index < len(records) else ""
            index += 1
            if "R" in status and source:
                paths.append(_ChangedPath(source, "D"))
        if path:
            paths.append(_ChangedPath(path, status))
    return tuple(
        sorted(
            {path.relative: path for path in paths}.values(),
            key=lambda path: path.relative,
        )
    )


def _digest_update(digest: hashlib._Hash, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def candidate_digest(
    workspace: Path,
    source_commit: str,
    paths: Iterable[_ChangedPath | str],
    *,
    policy_digest: str = "",
) -> str:
    """Return a deterministic digest of the exact candidate files reviewed."""

    digest = hashlib.sha256()
    _digest_update(digest, source_commit.encode("utf-8"))
    _digest_update(digest, policy_digest.encode("ascii"))
    candidates = sorted(
        (
            path
            if isinstance(path, _ChangedPath)
            else _ChangedPath(relative=str(path), status="")
            for path in paths
        ),
        key=lambda path: path.relative,
    )
    for changed in candidates:
        relative = changed.relative
        parts = Path(relative).parts
        if not relative or Path(relative).is_absolute() or ".." in parts:
            raise ValueError(f"unsafe candidate path: {relative}")
        path = workspace / relative
        if path.is_symlink():
            raise ValueError(f"candidate path is a symlink: {relative}")
        try:
            if path.exists():
                if not path.is_file():
                    raise ValueError(f"candidate path is not a file: {relative}")
                mode = f"{stat.S_IMODE(path.stat().st_mode):04o}".encode("ascii")
                content = path.read_bytes()
            else:
                mode = b"deleted"
                content = b"<deleted>"
        except OSError as exc:
            raise ValueError(f"candidate path is unreadable: {relative}") from exc
        _digest_update(digest, relative.encode("utf-8"))
        _digest_update(digest, changed.status.encode("ascii"))
        _digest_update(digest, mode)
        _digest_update(digest, content)
    return digest.hexdigest()


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_static_activatable(path: str) -> bool:
    """Return whether a path belongs to the fixed release-1 product surface."""

    return _matches_any(path, DEFAULT_ACTIVATABLE_PATHS)


def inspect_builder_change(change_root: Path | str) -> BuilderReviewReport:
    """Classify a candidate diff without installing or touching live code."""

    root = Path(change_root).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("builder change manifest is missing")
    manifest = _load_json_object(manifest_path, description="builder change manifest")
    policy, policy_digest = _load_trusted_policy(root)
    if (
        manifest.get("schema_version") != 2
        or manifest.get("policy_version") != BUILDER_POLICY_VERSION
        or manifest.get("protected_paths") != list(DEFAULT_PROTECTED_PATHS)
        or manifest.get("activatable_paths") != list(DEFAULT_ACTIVATABLE_PATHS)
    ):
        raise ValueError("builder change policy is stale or has been modified")
    if not _manifest_matches_trusted_policy(manifest, policy):
        raise ValueError("builder change manifest differs from trusted policy")
    change_id = str(policy["change_id"])
    workspace_root = Path(str(policy["workspace_root"])).expanduser().resolve()
    expected_workspace = workspace_root / "changes" / change_id / "source"
    workspace = Path(str(policy["workspace"])).expanduser().resolve()
    if workspace != expected_workspace or not (workspace / ".git").exists():
        raise ValueError("builder workspace does not match trusted policy")

    source_commit = str(policy["source_commit"])
    if not source_commit or _git(workspace, "rev-parse", "HEAD") != source_commit:
        raise ValueError("builder workspace revision differs from the trusted review base")

    allowed_patterns = _validate_allowed_paths(policy["allowed_paths"])
    # Dynamic task scope is a useful narrowing/relevance record.  It is never
    # the security boundary: static protected paths win first and only the
    # running release's fixed activatable surface can be review-ready.
    protected_patterns = DEFAULT_PROTECTED_PATHS
    allowed: list[str] = []
    protected: list[str] = []
    out_of_scope: list[str] = []
    changed_paths = _changed_paths(workspace)
    for changed in changed_paths:
        if changed.status == "!!":
            out_of_scope.append(changed.relative)
        elif _matches_any(changed.relative, protected_patterns):
            protected.append(changed.relative)
        elif not _is_static_activatable(changed.relative):
            out_of_scope.append(changed.relative)
        elif _matches_any(changed.relative, allowed_patterns):
            allowed.append(changed.relative)
        else:
            out_of_scope.append(changed.relative)

    if protected or out_of_scope:
        status = "blocked"
    elif allowed:
        status = "review_ready"
    else:
        status = "no_changes"
    digest = candidate_digest(
        workspace,
        source_commit,
        changed_paths,
        policy_digest=policy_digest,
    )
    report_path = root / "review.json"
    report_payload = {
        "schema_version": 1,
        "change_id": policy["change_id"],
        "status": status,
        "source_commit": source_commit,
        "allowed_paths": list(allowed_patterns),
        "policy_digest": policy_digest,
        "candidate_digest": digest,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "changed_paths": [
            {"path": changed.relative, "status": changed.status}
            for changed in changed_paths
        ],
        "allowed_changes": allowed,
        "protected_changes": protected,
        "out_of_scope_changes": out_of_scope,
        "installation": {
            "mode": "review_only",
            "automatic": False,
            "installable": False,
        },
    }
    report_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.chmod(0o600)
    return BuilderReviewReport(
        status=status,
        allowed_changes=tuple(allowed),
        protected_changes=tuple(protected),
        out_of_scope_changes=tuple(out_of_scope),
        installable=False,
        report_path=report_path,
        candidate_digest=digest,
    )
