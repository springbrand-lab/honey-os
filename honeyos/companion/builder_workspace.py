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
    "honeyos/agent/file_safety.py",
    "honeyos/companion/builder_workspace.py",
    "honeyos/companion/builder_activation*.py",
    "honeyos/companion/companion_skills/honeyos-builder/**",
    "honeyos/companion/companion_skills/honeyos-self-extension/**",
    "honeyos/companion/projects.py",
    "honeyos/runtime/auth.py",
    "honeyos/runtime/**",
    "honeyos/runtime/builder_cmd.py",
    "honeyos/cli/service.py",
    "honeyos/tools/approval.py",
    "honeyos/tools/write_approval.py",
    "honeyos/tools/companion_builder_tool.py",
    "honeyos/tools/permission_policy.py",
    "honeyos/tools/threat_patterns.py",
    "pyproject.toml",
    "uv.lock",
    "requirements*.txt",
    "requirements/**/*.txt",
    "install.sh",
    "Install-HoneyOS.command",
    "scripts/install*.sh",
    "scripts/update*.sh",
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


def _changed_paths(workspace: Path) -> tuple[_ChangedPath, ...]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
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
    workspace: Path, source_commit: str, paths: Iterable[_ChangedPath | str]
) -> str:
    """Return a deterministic digest of the exact candidate files reviewed."""

    digest = hashlib.sha256()
    _digest_update(digest, source_commit.encode("utf-8"))
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
    changed_paths = _changed_paths(workspace)
    for changed in changed_paths:
        if _matches_any(changed.relative, protected_patterns):
            protected.append(changed.relative)
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
    source_commit = str(manifest.get("source_commit", ""))
    digest = candidate_digest(workspace, source_commit, changed_paths)
    report_path = root / "review.json"
    report_payload = {
        "schema_version": 1,
        "change_id": manifest.get("change_id"),
        "status": status,
        "source_commit": source_commit,
        "candidate_digest": digest,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
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
