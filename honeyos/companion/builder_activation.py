"""Trusted, non-live staging for reviewed HoneyOS Builder candidates.

This module deliberately has no gateway/service lifecycle code.  It turns an
already reviewed candidate into a complete immutable source slot, and records
only the state needed by later trusted confirmation and switching code.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from honeyos.companion.builder_workspace import (
    BUILDER_POLICY_VERSION,
    DEFAULT_ACTIVATABLE_PATHS,
    DEFAULT_PROTECTED_PATHS,
    TRUSTED_POLICY_SCHEMA_VERSION,
    _ChangedPath,
    _changed_paths,
    _git,
    _is_static_activatable,
    _load_json_object,
    _load_trusted_policy,
    _manifest_matches_trusted_policy,
    _matches_any,
    _trusted_policy_digest,
    _validate_allowed_paths,
    candidate_digest,
)


class ActivationError(RuntimeError):
    """A candidate cannot safely be made into an activation slot."""


class ActivationConflict(ActivationError):
    """An activation state update lost its compare-and-swap race."""


_REVIEW_SCHEMA_VERSION = 1
_SLOT_SCHEMA_VERSION = 1
_ACTIVATION_SCHEMA_VERSION = 1
_TRANSITIONS = {
    "staged": {"awaiting_confirmation", "invalidated"},
    "awaiting_confirmation": {"switching", "denied", "expired", "invalidated"},
    "switching": {"healthy", "rolling_back", "recovery_required"},
    "rolling_back": {"rolled_back", "recovery_required"},
}


@dataclass(frozen=True)
class StagedActivation:
    activation_id: str
    change_id: str
    state: str
    candidate_digest: str
    slot_tree_digest: str
    slot_root: Path
    manifest_path: Path
    source_commit: str
    record_path: Path


ActivationRecord = StagedActivation


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    """Atomically persist private trusted-control-plane metadata."""

    _private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _read_private_object(path: Path, *, description: str) -> dict[str, object]:
    try:
        mode = stat.S_IMODE(os.lstat(path).st_mode)
    except OSError as exc:
        raise ActivationError(f"{description} is missing") from exc
    if not stat.S_ISREG(os.lstat(path).st_mode) or mode & 0o077:
        raise ActivationError(f"{description} is not private")
    try:
        return _load_json_object(path, description=description)
    except ValueError as exc:
        raise ActivationError(f"{description} is invalid") from exc


def _safe_relative(raw: str, *, description: str) -> Path:
    candidate = Path(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts:
        raise ActivationError(f"unsafe {description}: {raw!r}")
    return candidate


def _inside(path: Path, root: Path, *, description: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ActivationError(f"{description} escapes its trusted root") from exc
    return resolved


def _hash_piece(digest: hashlib._Hash, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _slot_tree_digest(source_root: Path) -> str:
    """Hash every regular file and directory in a slot source tree."""

    root = source_root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise ActivationError("slot source is missing or unsafe")
    digest = hashlib.sha256()
    entries: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories + files:
            entries.append(current_path / name)
    for path in sorted(entries, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ActivationError(f"slot path is unreadable: {relative}") from exc
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ActivationError(f"slot path is not a regular file or directory: {relative}")
        _hash_piece(digest, relative.encode("utf-8"))
        _hash_piece(digest, f"{stat.S_IMODE(info.st_mode):04o}".encode("ascii"))
        _hash_piece(digest, b"directory" if stat.S_ISDIR(info.st_mode) else b"file")
        if stat.S_ISREG(info.st_mode):
            try:
                _hash_piece(digest, path.read_bytes())
            except OSError as exc:
                raise ActivationError(f"slot path is unreadable: {relative}") from exc
    return digest.hexdigest()


def _extract_archive(source_repo: Path, source_commit: str, destination: Path) -> None:
    """Extract a complete pinned Git tree, rejecting links and path escapes."""

    archive = destination.parent / f".{destination.name}.tar"
    try:
        with archive.open("wb") as output:
            subprocess.run(
                ["git", "-C", str(source_repo), "archive", "--format=tar", source_commit],
                check=True,
                stdout=output,
                stderr=subprocess.PIPE,
            )
        _private_directory(destination)
        with tarfile.open(archive, "r:") as stream:
            for member in stream.getmembers():
                target = destination / _safe_relative(member.name, description="archive path")
                _inside(target, destination, description="archive path")
                if member.issym() or member.islnk() or member.isdev():
                    raise ActivationError(f"archive contains a link or device: {member.name}")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    os.chmod(target, stat.S_IMODE(member.mode))
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = stream.extractfile(member)
                    if extracted is None:
                        raise ActivationError(f"archive file is unreadable: {member.name}")
                    with target.open("wb") as output:
                        shutil.copyfileobj(extracted, output)
                    os.chmod(target, stat.S_IMODE(member.mode))
                else:
                    raise ActivationError(f"archive contains an unsupported member: {member.name}")
    except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        raise ActivationError("could not materialize the trusted source revision") from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            archive.unlink()


def _copy_reviewed_file(workspace: Path, source_root: Path, changed: _ChangedPath) -> None:
    relative = _safe_relative(changed.relative, description="reviewed path")
    candidate = workspace / relative
    target = source_root / relative
    _inside(candidate, workspace, description="candidate path")
    _inside(target, source_root, description="slot path")
    if candidate.exists():
        try:
            info = os.lstat(candidate)
        except OSError as exc:
            raise ActivationError(f"candidate path is unreadable: {changed.relative}") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ActivationError(f"candidate path is not a regular file: {changed.relative}")
        if stat.S_IMODE(info.st_mode) & 0o111:
            raise ActivationError(f"candidate file is executable: {changed.relative}")
        parent = target.parent
        while parent != source_root:
            if parent.exists() and os.path.islink(parent):
                raise ActivationError(f"slot path contains a symlink: {changed.relative}")
            parent = parent.parent
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not target.is_file():
            raise ActivationError(f"slot target is not a regular file: {changed.relative}")
        shutil.copy2(candidate, target, follow_symlinks=False)
        return
    if target.is_symlink():
        raise ActivationError(f"slot target is a symlink: {changed.relative}")
    if target.exists():
        if not target.is_file():
            raise ActivationError(f"slot target is not a regular file: {changed.relative}")
        target.unlink()


class ActivationStore:
    """Private immutable slots and durable compare-and-swap activation state."""

    def __init__(self, home: Path, bundled_root: Path):
        self.home = Path(home).expanduser().resolve()
        self.bundled_root = Path(bundled_root).expanduser().resolve()
        self.runtime_root = self.home / "runtime"
        self.slots = self.runtime_root / "slots"
        self.activations = self.runtime_root / "activations"
        for directory in (self.runtime_root, self.slots, self.activations):
            _private_directory(directory)
        self._lock_path = self.runtime_root / ".activation.lock"
        self._lock_path.touch(mode=0o600, exist_ok=True)
        self._lock_path.chmod(0o600)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _validated_review(
        self, change_root: Path
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object], tuple[_ChangedPath, ...], str]:
        root = Path(change_root).expanduser().resolve()
        manifest_path = root / "manifest.json"
        review_path = root / "review.json"
        try:
            manifest = _load_json_object(manifest_path, description="builder change manifest")
            policy, policy_digest = _load_trusted_policy(root)
        except ValueError as exc:
            raise ActivationError("candidate metadata is invalid") from exc
        if (
            manifest.get("schema_version") != 2
            or manifest.get("policy_version") != BUILDER_POLICY_VERSION
            or manifest.get("protected_paths") != list(DEFAULT_PROTECTED_PATHS)
            or manifest.get("activatable_paths") != list(DEFAULT_ACTIVATABLE_PATHS)
            or not _manifest_matches_trusted_policy(manifest, policy)
        ):
            raise ActivationError("candidate metadata is invalid")
        review = _read_private_object(review_path, description="candidate review")
        source_commit = policy.get("source_commit")
        source_repo_raw = policy.get("source_repo")
        workspace_raw = policy.get("workspace")
        if not all(isinstance(item, str) and item for item in (source_commit, source_repo_raw, workspace_raw)):
            raise ActivationError("candidate metadata is invalid")
        source_repo = Path(source_repo_raw).expanduser().resolve()
        workspace = Path(workspace_raw).expanduser().resolve()
        if not source_repo.is_dir() or not (source_repo / ".git").is_dir():
            raise ActivationError("source repository is unavailable")
        try:
            if _git(source_repo, "rev-parse", "HEAD") != source_commit:
                raise ActivationError("source revision changed after candidate preparation")
            if _git(workspace, "rev-parse", "HEAD") != source_commit:
                raise ActivationError("candidate workspace revision changed")
        except subprocess.CalledProcessError as exc:
            raise ActivationError("source repository is unavailable") from exc
        if (
            review.get("schema_version") != _REVIEW_SCHEMA_VERSION
            or review.get("status") != "review_ready"
            or review.get("source_commit") != source_commit
            or review.get("policy_digest") != policy_digest
            or review.get("allowed_paths") != policy.get("allowed_paths")
            or review.get("protected_changes") != []
            or review.get("out_of_scope_changes") != []
        ):
            raise ActivationError("candidate review is invalid")
        try:
            allowed_patterns = _validate_allowed_paths(policy["allowed_paths"])
        except (TypeError, ValueError) as exc:
            raise ActivationError("candidate metadata is invalid") from exc
        saved_paths_raw = review.get("changed_paths")
        if not isinstance(saved_paths_raw, list):
            raise ActivationError("candidate review is invalid")
        try:
            saved_paths = tuple(
                _ChangedPath(relative=str(item["path"]), status=str(item["status"]))
                for item in saved_paths_raw
                if isinstance(item, dict)
            )
        except (KeyError, TypeError) as exc:
            raise ActivationError("candidate review is invalid") from exc
        if len(saved_paths) != len(saved_paths_raw) or not saved_paths:
            raise ActivationError("candidate review is invalid")
        actual_paths = _changed_paths(workspace)
        if actual_paths != saved_paths:
            raise ActivationError("candidate changed after review")
        for changed in actual_paths:
            if (
                changed.status == "!!"
                or _matches_any(changed.relative, DEFAULT_PROTECTED_PATHS)
                or not _is_static_activatable(changed.relative)
                or not _matches_any(changed.relative, allowed_patterns)
            ):
                raise ActivationError("candidate review no longer has an eligible surface")
        recomputed = candidate_digest(
            workspace, source_commit, actual_paths, policy_digest=policy_digest
        )
        if not isinstance(review.get("candidate_digest"), str) or review["candidate_digest"] != recomputed:
            raise ActivationError("candidate changed after review")
        return policy, review, {"workspace": str(workspace)}, actual_paths, recomputed

    @staticmethod
    def _activation_id(change_id: str, candidate_digest_value: str) -> str:
        return f"{change_id}-{candidate_digest_value[:16]}"

    def _slot_root(self, activation_id: str) -> Path:
        return self.slots / activation_id

    def _record_path(self, activation_id: str) -> Path:
        if not activation_id or any(part in ("", ".", "..") for part in Path(activation_id).parts):
            raise ActivationError("unsafe activation identifier")
        return self.activations / f"{activation_id}.json"

    def _record_from_payload(self, payload: Mapping[str, object], path: Path) -> ActivationRecord:
        required = (
            "activation_id",
            "change_id",
            "state",
            "candidate_digest",
            "slot_tree_digest",
            "slot_root",
            "manifest_path",
            "source_commit",
        )
        if payload.get("schema_version") != _ACTIVATION_SCHEMA_VERSION or not all(
            isinstance(payload.get(key), str) and payload.get(key) for key in required
        ):
            raise ActivationError("activation record is invalid")
        slot_root = Path(str(payload["slot_root"])).expanduser().resolve()
        manifest_path = Path(str(payload["manifest_path"])).expanduser().resolve()
        _inside(slot_root, self.slots, description="activation slot")
        _inside(manifest_path, slot_root, description="activation manifest")
        return ActivationRecord(
            activation_id=str(payload["activation_id"]),
            change_id=str(payload["change_id"]),
            state=str(payload["state"]),
            candidate_digest=str(payload["candidate_digest"]),
            slot_tree_digest=str(payload["slot_tree_digest"]),
            slot_root=slot_root,
            manifest_path=manifest_path,
            source_commit=str(payload["source_commit"]),
            record_path=path,
        )

    def _load_record(self, activation_id: str) -> tuple[dict[str, object], ActivationRecord]:
        path = self._record_path(activation_id)
        payload = _read_private_object(path, description="activation record")
        record = self._record_from_payload(payload, path)
        if record.activation_id != activation_id:
            raise ActivationError("activation record is invalid")
        return payload, record

    def stage(self, change_root: Path) -> StagedActivation:
        """Materialize a complete pinned source slot without touching live data."""

        with self._locked():
            policy, review, workspace_info, changed_paths, reviewed_digest = self._validated_review(change_root)
            change_id = str(policy["change_id"])
            source_commit = str(policy["source_commit"])
            source_repo = Path(str(policy["source_repo"])).expanduser().resolve()
            workspace = Path(workspace_info["workspace"]).resolve()
            activation_id = self._activation_id(change_id, reviewed_digest)
            slot_root = self._slot_root(activation_id)
            record_path = self._record_path(activation_id)
            if slot_root.exists() or record_path.exists():
                raise ActivationConflict("this reviewed candidate has already been staged")
            temporary_root = Path(
                tempfile.mkdtemp(prefix=f".{activation_id}.", dir=self.slots)
            )
            temporary_slot = temporary_root / "slot"
            try:
                source_root = temporary_slot / "source"
                _private_directory(temporary_slot)
                _extract_archive(source_repo, source_commit, source_root)
                if (source_root / ".git").exists():
                    raise ActivationError("trusted archive unexpectedly contains .git")
                for changed in changed_paths:
                    _copy_reviewed_file(workspace, source_root, changed)
                tree_digest = _slot_tree_digest(source_root)
                manifest_path = temporary_slot / "runtime.json"
                manifest_payload: dict[str, object] = {
                    "schema_version": _SLOT_SCHEMA_VERSION,
                    "activation_id": activation_id,
                    "change_id": change_id,
                    "source_commit": source_commit,
                    "candidate_digest": reviewed_digest,
                    "slot_tree_digest": tree_digest,
                    "reviewed_diff_digest": reviewed_digest,
                    "review_path": str((Path(change_root).expanduser().resolve() / "review.json")),
                    "created_at": _utc_now(),
                }
                _write_private_json(manifest_path, manifest_payload)
                os.replace(temporary_slot, slot_root)
                slot_root.chmod(0o700)
                final_manifest = slot_root / "runtime.json"
                record_payload: dict[str, object] = {
                    "schema_version": _ACTIVATION_SCHEMA_VERSION,
                    "activation_id": activation_id,
                    "change_id": change_id,
                    "state": "staged",
                    "candidate_digest": reviewed_digest,
                    "slot_tree_digest": tree_digest,
                    "slot_root": str(slot_root),
                    "manifest_path": str(final_manifest),
                    "source_commit": source_commit,
                    "change_root": str(Path(change_root).expanduser().resolve()),
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                }
                _write_private_json(record_path, record_payload)
            except Exception:
                shutil.rmtree(temporary_root, ignore_errors=True)
                shutil.rmtree(slot_root, ignore_errors=True)
                with contextlib.suppress(FileNotFoundError):
                    record_path.unlink()
                raise
            finally:
                shutil.rmtree(temporary_root, ignore_errors=True)
            return self._record_from_payload(record_payload, record_path)

    def _verify_staged_unlocked(self, activation_id: str) -> ActivationRecord:
        payload, record = self._load_record(activation_id)
        change_root_raw = payload.get("change_root")
        if not isinstance(change_root_raw, str) or not change_root_raw:
            raise ActivationError("activation record is invalid")
        policy, _review, _workspace, _changes, reviewed_digest = self._validated_review(
            Path(change_root_raw)
        )
        if (
            reviewed_digest != record.candidate_digest
            or str(policy["source_commit"]) != record.source_commit
        ):
            raise ActivationError("candidate changed after review")
        manifest = _read_private_object(record.manifest_path, description="slot manifest")
        if (
            manifest.get("schema_version") != _SLOT_SCHEMA_VERSION
            or manifest.get("activation_id") != record.activation_id
            or manifest.get("source_commit") != record.source_commit
            or manifest.get("candidate_digest") != record.candidate_digest
            or manifest.get("slot_tree_digest") != record.slot_tree_digest
        ):
            raise ActivationError("slot manifest is invalid")
        actual_tree_digest = _slot_tree_digest(record.slot_root / "source")
        if actual_tree_digest != record.slot_tree_digest:
            raise ActivationError("slot tree digest changed")
        return record

    def verify_staged(self, activation_id: str) -> ActivationRecord:
        """Recheck both candidate and materialized-slot bytes before promotion."""

        with self._locked():
            return self._verify_staged_unlocked(activation_id)

    def transition(
        self, activation_id: str, expected: str, target: str, detail: str = ""
    ) -> ActivationRecord:
        """Apply one durable compare-and-swap state transition."""

        if target not in _TRANSITIONS.get(expected, set()):
            raise ActivationConflict(f"invalid activation transition: {expected} -> {target}")
        with self._locked():
            payload, record = self._load_record(activation_id)
            if record.state != expected:
                raise ActivationConflict(
                    f"activation state is {record.state}, not expected {expected}"
                )
            if target in {"awaiting_confirmation", "switching"}:
                self._verify_staged_unlocked(activation_id)
            payload["state"] = target
            payload["updated_at"] = _utc_now()
            payload["detail"] = detail
            _write_private_json(record.record_path, payload)
            return self._record_from_payload(payload, record.record_path)

    def resolve_candidate_module(self, activation_id: str, module: str) -> Path:
        """Resolve a module to a slot source file without importing candidate code."""

        if not module or any(not part.isidentifier() for part in module.split(".")):
            raise ActivationError("unsafe module name")
        record = self.verify_staged(activation_id)
        base = record.slot_root / "source"
        relative = Path(*module.split("."))
        file_candidate = base / f"{relative}.py"
        package_candidate = base / relative / "__init__.py"
        for candidate in (file_candidate, package_candidate):
            if candidate.is_file() and not candidate.is_symlink():
                return _inside(candidate, base, description="candidate module")
        raise ActivationError(f"candidate module is not present in the slot: {module}")
