"""Review-only workspaces for user-requested HoneyOS product changes.

The companion never edits the checkout that is currently running HoneyOS.
This module prepares an isolated Git clone plus a machine-readable policy
manifest.  A later review step decides whether a candidate is safe to hand to
a human developer; this first version deliberately has no install operation.
"""

from __future__ import annotations

import json
import fnmatch
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_PROTECTED_PATHS = (
    ".env",
    ".env.*",
    "honeyos/agent/file_safety.py",
    "honeyos/companion/builder_workspace.py",
    "honeyos/companion/companion_skills/honeyos-builder/**",
    "honeyos/companion/companion_skills/honeyos-self-extension/**",
    "honeyos/companion/projects.py",
    "honeyos/runtime/auth.py",
    "honeyos/runtime/builder_cmd.py",
    "honeyos/tools/approval.py",
    "honeyos/tools/permission_policy.py",
    "honeyos/tools/threat_patterns.py",
)


@dataclass(frozen=True)
class PreparedBuilderChange:
    change_id: str
    change_root: Path
    workspace: Path
    manifest_path: Path


@dataclass(frozen=True)
class BuilderReviewReport:
    status: str
    allowed_changes: tuple[str, ...]
    protected_changes: tuple[str, ...]
    out_of_scope_changes: tuple[str, ...]
    installable: bool
    report_path: Path


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
    if change_root.exists() or workspace_change_root.exists():
        raise FileExistsError(f"builder change already exists: {normalized_id}")
    change_root.mkdir(parents=True)
    change_root.chmod(0o700)
    if workspace_change_root != change_root:
        workspace_change_root.mkdir(parents=True)

    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(source), str(workspace)],
            check=True,
            capture_output=True,
            text=True,
        )
        branch = f"honeyos-builder/{normalized_id}"
        _git(workspace, "switch", "-c", branch)
        source_commit = _git(source, "rev-parse", "HEAD")
        manifest = {
            "schema_version": 1,
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
    )


def _changed_paths(workspace: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "-C", str(workspace), "status", "--porcelain=v1", "-z"],
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[str] = []
    records = completed.stdout.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        path = record[3:]
        if "R" in status or "C" in status:
            # Porcelain -z emits the destination first and the source next.
            index += 1
        if path and path not in paths:
            paths.append(path)
    return tuple(sorted(paths))


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def inspect_builder_change(change_root: Path | str) -> BuilderReviewReport:
    """Classify a candidate diff without installing or touching live code."""

    root = Path(change_root).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("builder change manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    change_id = str(manifest.get("change_id", ""))
    workspace_root = Path(str(manifest.get("workspace_root", ""))).expanduser().resolve()
    expected_workspace = workspace_root / "changes" / change_id / "source"
    workspace = Path(str(manifest.get("workspace", ""))).expanduser().resolve()
    if workspace != expected_workspace or not (workspace / ".git").exists():
        raise ValueError("builder workspace does not match its protected manifest")

    allowed_patterns = tuple(manifest.get("allowed_paths") or ())
    protected_patterns = tuple(manifest.get("protected_paths") or ())
    allowed: list[str] = []
    protected: list[str] = []
    out_of_scope: list[str] = []
    for path in _changed_paths(workspace):
        if _matches_any(path, protected_patterns):
            protected.append(path)
        elif _matches_any(path, allowed_patterns):
            allowed.append(path)
        else:
            out_of_scope.append(path)

    if protected or out_of_scope:
        status = "blocked"
    elif allowed:
        status = "review_ready"
    else:
        status = "no_changes"
    report_path = root / "review.json"
    report_payload = {
        "schema_version": 1,
        "change_id": manifest.get("change_id"),
        "status": status,
        "inspected_at": datetime.now(timezone.utc).isoformat(),
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
    )
