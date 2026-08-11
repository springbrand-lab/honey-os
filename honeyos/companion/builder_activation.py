"""Trusted, non-live staging for reviewed HoneyOS Builder candidates.

This module deliberately has no gateway/service lifecycle code.  It turns an
already reviewed candidate into a complete immutable source slot, and records
only the state needed by later trusted confirmation and switching code.
"""

from __future__ import annotations

import ast
import contextlib
import hmac
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
_JOURNAL_SCHEMA_VERSION = 1
_PREFLIGHT_SCHEMA_VERSION = 1
_PREFLIGHT_OUTPUT_LIMIT = 512
_STATIC_PREFLIGHT_CHECKS = (
    "slot_evidence",
    "release_artifacts",
    "source_tree",
    "candidate_python_syntax",
)
_CONFIRMATION_SCHEMA_VERSION = 1
_CANONICAL_OWNER_LANE = "agent:main:companion:dm:owner"
_CONFIRMATION_TTL = timedelta(minutes=10)
# Intentionally not exported.  The gateway owns the sole capability instance;
# model schemas never receive it and ActivationStore has no public resolver.
_GATEWAY_RESOLVER_CAPABILITY = object()
_TRANSITIONS = {
    "staged": {"awaiting_confirmation", "invalidated"},
    "awaiting_confirmation": {"authorized", "denied", "expired", "invalidated"},
    # Only the trusted post-confirmation worker may claim this transition.
    "authorized": {"switching", "invalidated"},
    "switching": {"healthy", "rolling_back", "recovery_required"},
    "rolling_back": {"rolled_back", "recovery_required"},
}

_MODEL_CONTROL_PLANE_MARKERS = (
    "builder_activation",
    "builder_confirmation",
    "builder_activation_worker",
    "activation_callback_key",
    "runtime/activations",
    "runtime\\activations",
    "runtime/confirmations",
    "runtime\\confirmations",
    ".activation.lock",
    "issue_confirmation",
    "resolve_gateway_confirmation",
    "activationstore(",
    "authorized",
    "switching",
    "rolling_back",
    "rolled_back",
    "rollback",
)


@dataclass(frozen=True)
class StagedActivation:
    activation_id: str
    change_id: str
    state: str
    candidate_digest: str
    slot_tree_digest: str
    metadata_digest: str
    slot_root: Path
    manifest_path: Path
    source_commit: str
    record_path: Path


ActivationRecord = StagedActivation


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    returncode: int | None
    duration_ms: int
    output: str
    timed_out: bool


@dataclass(frozen=True)
class PreflightReceipt:
    """Private evidence that a slot passed trusted static validation."""

    activation_id: str
    success: bool
    candidate_digest: str
    slot_tree_digest: str
    source_root: Path
    checks: tuple[PreflightCheck, ...]
    error: str
    record_path: Path


@dataclass(frozen=True)
class ActivationConfirmation:
    """Opaque, gateway-facing handle for one exact staged activation."""

    callback_id: str
    activation_id: str
    candidate_digest: str
    channel: str
    expires_at: str
    record_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_control_plane_access_error(value: str) -> str | None:
    """Return a hard denial for model attempts to reach activation internals.

    File mode is only accidental-write protection on a same-user machine.  The
    model-facing terminal and code tools must separately refuse confirmation,
    authorization, worker, switching, and rollback control-plane access.
    """

    lowered = str(value or "").lower().replace("-", "_")
    if any(marker in lowered for marker in _MODEL_CONTROL_PLANE_MARKERS):
        return "Blocked: Builder activation confirmation and switching are gateway-owned."
    return None


def _redact_preflight_text(value: str, *, limit: int = _PREFLIGHT_OUTPUT_LIMIT) -> str:
    """Keep diagnostics small and never persist obvious credential values."""

    import re

    compact = value.replace("\x00", " ")
    compact = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", compact)
    compact = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        compact,
    )
    compact = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", compact)
    return compact[-limit:]


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _fsync_directory(path: Path) -> None:
    """Best-effort directory durability on platforms that support it."""

    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


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
        _fsync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _read_private_object(path: Path, *, description: str) -> dict[str, object]:
    try:
        info = os.lstat(path)
        mode = stat.S_IMODE(info.st_mode)
    except OSError as exc:
        raise ActivationError(f"{description} is missing") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or mode & 0o077:
        raise ActivationError(f"{description} is not private")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if opened.st_ino != info.st_ino or opened.st_dev != info.st_dev:
                raise ActivationError(f"{description} changed while reading")
            payload = json.loads(handle.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActivationError(f"{description} is invalid") from exc
    if not isinstance(payload, dict):
        raise ActivationError(f"{description} is invalid")
    return payload


def _canonical_json_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _private_candidate_object(path: Path, *, description: str) -> dict[str, object]:
    """Read Builder metadata with no-follow checks.

    Builder workspaces are same-user directories, so Python cannot provide a
    fully portable `openat` transaction across every supported OS.  We narrow
    the race by lstat/opening with O_NOFOLLOW and checking inode identity; the
    metadata is then copied into the private slot and never consulted again.
    """

    return _read_private_object(path, description=description)


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
    try:
        info = os.lstat(candidate)
    except FileNotFoundError:
        info = None
    except OSError as exc:
        raise ActivationError(f"candidate path is unreadable: {changed.relative}") from exc
    if info is not None:
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
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(candidate, flags)
            with os.fdopen(descriptor, "rb") as incoming:
                opened = os.fstat(incoming.fileno())
                if opened.st_ino != info.st_ino or opened.st_dev != info.st_dev:
                    raise ActivationError(f"candidate path changed while copying: {changed.relative}")
                temporary = target.with_name(f".{target.name}.stage")
                with temporary.open("wb") as output:
                    shutil.copyfileobj(incoming, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, stat.S_IMODE(info.st_mode))
                os.replace(temporary, target)
        except OSError as exc:
            raise ActivationError(f"candidate path is unreadable: {changed.relative}") from exc
        return
    if target.is_symlink():
        raise ActivationError(f"slot target is a symlink: {changed.relative}")
    if target.exists():
        if not target.is_file():
            raise ActivationError(f"slot target is not a regular file: {changed.relative}")
        target.unlink()


def _make_source_read_only(source_root: Path) -> None:
    """Freeze staged source bytes while leaving the containing slot private."""

    for current, directories, files in os.walk(source_root, topdown=False, followlinks=False):
        for name in files:
            path = Path(current) / name
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise ActivationError("slot source contains an unsafe file")
            os.chmod(path, stat.S_IMODE(info.st_mode) & 0o555)
        for name in directories:
            path = Path(current) / name
            info = os.lstat(path)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise ActivationError("slot source contains an unsafe directory")
            os.chmod(path, 0o500)
    os.chmod(source_root, 0o500)


@contextmanager
def _platform_file_lock(path: Path) -> Iterator[None]:
    """Use the native process lock only when the host platform provides it."""

    with path.open("a+", encoding="utf-8") as handle:
        try:
            import fcntl  # type: ignore[import-not-found]
        except ImportError:
            fcntl = None  # type: ignore[assignment]
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return
        try:
            import msvcrt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ActivationError("this platform has no supported activation lock") from exc
        handle.seek(0)
        handle.write("0")
        handle.flush()
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class ActivationStore:
    """Private immutable slots and durable compare-and-swap activation state."""

    def __init__(
        self,
        home: Path,
        bundled_root: Path,
        *,
        crash_hook: Callable[[str], None] | None = None,
    ):
        self.home = Path(home).expanduser().resolve()
        self.bundled_root = Path(bundled_root).expanduser().resolve()
        self.runtime_root = self.home / "runtime"
        self.slots = self.runtime_root / "slots"
        self.activations = self.runtime_root / "activations"
        self.confirmations = self.runtime_root / "confirmations"
        self.journals = self.runtime_root / "journals"
        for directory in (
            self.runtime_root,
            self.slots,
            self.activations,
            self.confirmations,
            self.journals,
        ):
            _private_directory(directory)
        self._lock_path = self.runtime_root / ".activation.lock"
        self._lock_path.touch(mode=0o600, exist_ok=True)
        self._lock_path.chmod(0o600)
        self._crash_hook = crash_hook
        with self._locked():
            self._reconcile_unlocked()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with _platform_file_lock(self._lock_path):
            yield

    def _crash(self, point: str) -> None:
        if self._crash_hook is not None:
            self._crash_hook(point)

    def _journal_path(self, activation_id: str) -> Path:
        return self.journals / f"{activation_id}.json"

    def _reconcile_unlocked(self) -> None:
        """Complete or discard a prior staging attempt before accepting work."""

        for journal_path in sorted(self.journals.glob("*.json")):
            journal = _read_private_object(journal_path, description="activation staging journal")
            if journal.get("schema_version") != _JOURNAL_SCHEMA_VERSION or journal.get("state") != "staging":
                raise ActivationError("activation staging journal is invalid")
            activation_id = journal.get("activation_id")
            if not isinstance(activation_id, str) or not activation_id:
                raise ActivationError("activation staging journal is invalid")
            slot_root = self._slot_root(activation_id)
            record_path = self._record_path(activation_id)
            slot_exists = slot_root.exists()
            record_exists = record_path.exists()
            record_payload = journal.get("record_payload")
            if slot_exists and not record_exists:
                if not isinstance(record_payload, dict):
                    shutil.rmtree(slot_root, ignore_errors=True)
                    journal_path.unlink(missing_ok=True)
                    _fsync_directory(self.slots)
                    _fsync_directory(self.journals)
                    continue
                _write_private_json(record_path, record_payload)
            elif not slot_exists and record_exists:
                record_path.unlink(missing_ok=True)
                _fsync_directory(self.activations)
            journal_path.unlink(missing_ok=True)
            _fsync_directory(self.journals)
            for temporary in self.slots.glob(f".{activation_id}.*"):
                shutil.rmtree(temporary, ignore_errors=True)
            _fsync_directory(self.slots)

    def reconcile(self) -> None:
        with self._locked():
            self._reconcile_unlocked()

    def _validated_review(
        self, change_root: Path
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        tuple[_ChangedPath, ...],
        str,
        str,
    ]:
        root = Path(change_root).expanduser().resolve()
        manifest_path = root / "manifest.json"
        review_path = root / "review.json"
        try:
            manifest = _private_candidate_object(manifest_path, description="builder change manifest")
            policy = _private_candidate_object(root / "trusted-policy.json", description="trusted policy")
            policy_digest = _trusted_policy_digest(policy)
            checked_policy, checked_digest = _load_trusted_policy(root)
            if checked_policy != policy or checked_digest != policy_digest:
                raise ValueError("trusted policy changed while reading")
        except (ActivationError, ValueError) as exc:
            raise ActivationError("candidate metadata is invalid") from exc
        if (
            manifest.get("schema_version") != 2
            or manifest.get("policy_version") != BUILDER_POLICY_VERSION
            or manifest.get("protected_paths") != list(DEFAULT_PROTECTED_PATHS)
            or manifest.get("activatable_paths") != list(DEFAULT_ACTIVATABLE_PATHS)
            or not _manifest_matches_trusted_policy(manifest, policy)
        ):
            raise ActivationError("candidate metadata is invalid")
        review = _private_candidate_object(review_path, description="candidate review")
        source_commit = policy.get("source_commit")
        source_repo_raw = policy.get("source_repo")
        workspace_raw = policy.get("workspace")
        if not all(isinstance(item, str) and item for item in (source_commit, source_repo_raw, workspace_raw)):
            raise ActivationError("candidate metadata is invalid")
        source_repo = Path(source_repo_raw).expanduser().resolve()
        workspace = Path(workspace_raw).expanduser().resolve()
        if source_repo != self.bundled_root:
            raise ActivationError("candidate source is not the live bundled runtime")
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
        metadata_digest = _canonical_json_digest(
            {
                "manifest": manifest,
                "trusted_policy": policy,
                "review": review,
                "changed_paths": [
                    {"path": item.relative, "status": item.status} for item in actual_paths
                ],
            }
        )
        return policy, review, {"workspace": str(workspace), "manifest": manifest}, actual_paths, recomputed, metadata_digest

    @staticmethod
    def _activation_id(change_id: str, candidate_digest_value: str) -> str:
        return f"{change_id}-{candidate_digest_value[:16]}"

    def _slot_root(self, activation_id: str) -> Path:
        return self.slots / activation_id

    def _record_path(self, activation_id: str) -> Path:
        if not activation_id or any(part in ("", ".", "..") for part in Path(activation_id).parts):
            raise ActivationError("unsafe activation identifier")
        return self.activations / f"{activation_id}.json"

    def _confirmation_path(self, callback_id: str) -> Path:
        if not callback_id or not callback_id.isascii() or not callback_id.isalnum():
            raise ActivationError("unsafe activation confirmation identifier")
        return self.confirmations / f"{callback_id}.json"

    def _callback_key_path(self) -> Path:
        return self.runtime_root / ".activation-callback-key"

    def _callback_key_unlocked(self) -> bytes:
        """Return the server-only callback derivation key.

        Individual confirmation records retain only a hash of their derived
        secret.  The opaque callback id can therefore survive a gateway restart
        without becoming a bearer credential in a chat card or model context.
        """

        path = self._callback_key_path()
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(secrets.token_bytes(32))
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                raise
            _fsync_directory(path.parent)
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise ActivationError("activation callback key is unsafe")
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise ActivationError("activation callback key is not private")
            value = path.read_bytes()
        except OSError as exc:
            raise ActivationError("activation callback key is unavailable") from exc
        if len(value) != 32:
            raise ActivationError("activation callback key is invalid")
        return value

    def _confirmation_secret_unlocked(self, callback_id: str) -> bytes:
        return hmac.new(
            self._callback_key_unlocked(),
            f"honeyos-builder-confirmation:{callback_id}".encode("ascii"),
            hashlib.sha256,
        ).digest()

    def _record_from_payload(self, payload: Mapping[str, object], path: Path) -> ActivationRecord:
        required = (
            "activation_id",
            "change_id",
            "state",
            "candidate_digest",
            "slot_tree_digest",
            "metadata_digest",
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
            metadata_digest=str(payload["metadata_digest"]),
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
            self._reconcile_unlocked()
            policy, review, workspace_info, changed_paths, reviewed_digest, metadata_digest = self._validated_review(change_root)
            change_id = str(policy["change_id"])
            source_commit = str(policy["source_commit"])
            source_repo = Path(str(policy["source_repo"])).expanduser().resolve()
            workspace = Path(workspace_info["workspace"]).resolve()
            activation_id = self._activation_id(change_id, reviewed_digest)
            slot_root = self._slot_root(activation_id)
            record_path = self._record_path(activation_id)
            if slot_root.exists() or record_path.exists():
                raise ActivationConflict("this reviewed candidate has already been staged")
            journal_path = self._journal_path(activation_id)
            _write_private_json(
                journal_path,
                {
                    "schema_version": _JOURNAL_SCHEMA_VERSION,
                    "state": "staging",
                    "activation_id": activation_id,
                    "created_at": _utc_now(),
                },
            )
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
                materialized_digest = candidate_digest(
                    source_root,
                    source_commit,
                    changed_paths,
                    policy_digest=_trusted_policy_digest(policy),
                )
                if materialized_digest != reviewed_digest:
                    raise ActivationError(
                        "materialized candidate differs from the reviewed bytes"
                    )
                _make_source_read_only(source_root)
                tree_digest = _slot_tree_digest(source_root)
                trusted_root = temporary_slot / "trusted"
                _private_directory(trusted_root)
                _write_private_json(trusted_root / "manifest.json", workspace_info["manifest"])
                _write_private_json(trusted_root / "trusted-policy.json", policy)
                _write_private_json(trusted_root / "review.json", review)
                _write_private_json(
                    trusted_root / "changed-paths.json",
                    {"changed_paths": [
                        {"path": item.relative, "status": item.status} for item in changed_paths
                    ]},
                )
                manifest_path = temporary_slot / "runtime.json"
                manifest_payload: dict[str, object] = {
                    "schema_version": _SLOT_SCHEMA_VERSION,
                    "activation_id": activation_id,
                    "change_id": change_id,
                    "source_commit": source_commit,
                    "candidate_digest": reviewed_digest,
                    "slot_tree_digest": tree_digest,
                    "reviewed_diff_digest": reviewed_digest,
                    "metadata_digest": metadata_digest,
                    "created_at": _utc_now(),
                }
                _write_private_json(manifest_path, manifest_payload)
                final_manifest = slot_root / "runtime.json"
                record_payload: dict[str, object] = {
                    "schema_version": _ACTIVATION_SCHEMA_VERSION,
                    "activation_id": activation_id,
                    "change_id": change_id,
                    "state": "staged",
                    "candidate_digest": reviewed_digest,
                    "slot_tree_digest": tree_digest,
                    "metadata_digest": metadata_digest,
                    "slot_root": str(slot_root),
                    "manifest_path": str(final_manifest),
                    "source_commit": source_commit,
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                }
                _write_private_json(
                    journal_path,
                    {
                        "schema_version": _JOURNAL_SCHEMA_VERSION,
                        "state": "staging",
                        "activation_id": activation_id,
                        "record_payload": record_payload,
                        "created_at": _utc_now(),
                    },
                )
                self._crash("before_slot_publish")
                os.replace(temporary_slot, slot_root)
                slot_root.chmod(0o700)
                _fsync_directory(self.slots)
                self._crash("after_slot_publish")
                _write_private_json(record_path, record_payload)
                journal_path.unlink(missing_ok=True)
                _fsync_directory(self.journals)
            except Exception:
                shutil.rmtree(temporary_root, ignore_errors=True)
                shutil.rmtree(slot_root, ignore_errors=True)
                with contextlib.suppress(FileNotFoundError):
                    record_path.unlink()
                with contextlib.suppress(FileNotFoundError):
                    journal_path.unlink()
                raise
            finally:
                shutil.rmtree(temporary_root, ignore_errors=True)
            return self._record_from_payload(record_payload, record_path)

    def _verify_staged_unlocked(self, activation_id: str) -> ActivationRecord:
        payload, record = self._load_record(activation_id)
        manifest = _read_private_object(record.manifest_path, description="slot manifest")
        if (
            manifest.get("schema_version") != _SLOT_SCHEMA_VERSION
            or manifest.get("activation_id") != record.activation_id
            or manifest.get("source_commit") != record.source_commit
            or manifest.get("candidate_digest") != record.candidate_digest
            or manifest.get("slot_tree_digest") != record.slot_tree_digest
            or manifest.get("metadata_digest") != record.metadata_digest
        ):
            raise ActivationError("slot manifest is invalid")
        trusted = record.slot_root / "trusted"
        staged_manifest = _read_private_object(trusted / "manifest.json", description="staged candidate manifest")
        staged_policy = _read_private_object(trusted / "trusted-policy.json", description="staged trusted policy")
        staged_review = _read_private_object(trusted / "review.json", description="staged candidate review")
        staged_paths = _read_private_object(trusted / "changed-paths.json", description="staged changed paths")
        metadata_digest = _canonical_json_digest(
            {
                "manifest": staged_manifest,
                "trusted_policy": staged_policy,
                "review": staged_review,
                "changed_paths": staged_paths.get("changed_paths"),
            }
        )
        if (
            metadata_digest != record.metadata_digest
            or staged_review.get("candidate_digest") != record.candidate_digest
            or staged_policy.get("source_commit") != record.source_commit
            or staged_manifest.get("source_commit") != record.source_commit
        ):
            raise ActivationError("staged review evidence is invalid")
        actual_tree_digest = _slot_tree_digest(record.slot_root / "source")
        if actual_tree_digest != record.slot_tree_digest:
            raise ActivationError("slot tree digest changed")
        return record

    def verify_staged(self, activation_id: str) -> ActivationRecord:
        """Recheck both candidate and materialized-slot bytes before promotion."""

        with self._locked():
            return self._verify_staged_unlocked(activation_id)

    def _preflight_path(self, record: ActivationRecord) -> Path:
        return record.slot_root / "preflight.json"

    @staticmethod
    def _required_preflight_artifacts(source_root: Path) -> None:
        required = (source_root / "pyproject.toml", source_root / "uv.lock")
        for path in required:
            if not path.is_file() or path.is_symlink():
                raise ActivationError("approved preflight artifact is unavailable")

    @staticmethod
    def _static_source_tree_check(source_root: Path) -> None:
        maximum_file_bytes = 4 * 1024 * 1024
        for current, directories, files in os.walk(source_root, followlinks=False):
            for name in directories + files:
                path = Path(current) / name
                info = os.lstat(path)
                if stat.S_ISLNK(info.st_mode) or not (
                    stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
                ):
                    raise ActivationError("slot source contains an unsafe path")
                if stat.S_ISREG(info.st_mode) and info.st_size > maximum_file_bytes:
                    raise ActivationError("slot source contains an oversized file")
                if stat.S_IMODE(info.st_mode) & stat.S_IWUSR:
                    raise ActivationError("slot source is writable")

    @staticmethod
    def _changed_python_paths(record: ActivationRecord) -> tuple[Path, ...]:
        payload = _read_private_object(
            record.slot_root / "trusted" / "changed-paths.json",
            description="staged changed paths",
        )
        raw_paths = payload.get("changed_paths")
        if not isinstance(raw_paths, list):
            raise ActivationError("staged changed paths are invalid")
        paths: list[Path] = []
        for item in raw_paths:
            if not isinstance(item, dict):
                raise ActivationError("staged changed paths are invalid")
            raw_path, status = item.get("path"), item.get("status")
            if not isinstance(raw_path, str) or not isinstance(status, str):
                raise ActivationError("staged changed paths are invalid")
            relative = _safe_relative(raw_path, description="staged candidate path")
            if "D" not in status and relative.suffix == ".py":
                paths.append(record.slot_root / "source" / relative)
        return tuple(paths)

    def _static_python_syntax_check(self, record: ActivationRecord) -> None:
        source_root = record.slot_root / "source"
        for path in self._changed_python_paths(record):
            _inside(path, source_root, description="candidate Python path")
            if not path.is_file() or path.is_symlink():
                raise ActivationError("candidate Python path is unavailable")
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                raise ActivationError("candidate Python syntax is invalid") from exc

    def _run_static_preflight_unlocked(
        self, record: ActivationRecord
    ) -> tuple[PreflightCheck, ...]:
        operations = (
            ("slot_evidence", lambda: self._verify_staged_unlocked(record.activation_id)),
            ("release_artifacts", lambda: self._required_preflight_artifacts(record.slot_root / "source")),
            ("source_tree", lambda: self._static_source_tree_check(record.slot_root / "source")),
            ("candidate_python_syntax", lambda: self._static_python_syntax_check(record)),
        )
        checks: list[PreflightCheck] = []
        for name, operation in operations:
            try:
                operation()
            except ActivationError:
                checks.append(PreflightCheck(name, 1, 0, "failed", False))
            else:
                checks.append(PreflightCheck(name, 0, 0, "", False))
        return tuple(checks)

    def _write_preflight_receipt(
        self,
        record: ActivationRecord,
        *,
        success: bool,
        checks: tuple[PreflightCheck, ...],
        error: str,
    ) -> PreflightReceipt:
        safe_error = _redact_preflight_text(error).replace(str(self.home), "[private-home]")
        path = self._preflight_path(record)
        payload = {
            "schema_version": _PREFLIGHT_SCHEMA_VERSION,
            "activation_id": record.activation_id,
            "success": success,
            "candidate_digest": record.candidate_digest,
            "slot_tree_digest": record.slot_tree_digest,
            "source_root": str(record.slot_root / "source"),
            "checks": [
                {
                    "name": check.name,
                    "returncode": check.returncode,
                    "duration_ms": check.duration_ms,
                    "output": check.output,
                    "timed_out": check.timed_out,
                }
                for check in checks
            ],
            "error": safe_error,
            "finished_at": _utc_now(),
        }
        _write_private_json(path, payload)
        return self._preflight_receipt_from_payload(payload, path, record)

    def _preflight_receipt_from_payload(
        self,
        payload: Mapping[str, object],
        path: Path,
        record: ActivationRecord,
    ) -> PreflightReceipt:
        source_root = record.slot_root / "source"
        raw_checks = payload.get("checks")
        if (
            payload.get("schema_version") != _PREFLIGHT_SCHEMA_VERSION
            or payload.get("activation_id") != record.activation_id
            or not isinstance(payload.get("success"), bool)
            or payload.get("candidate_digest") != record.candidate_digest
            or payload.get("slot_tree_digest") != record.slot_tree_digest
            or payload.get("source_root") != str(source_root)
            or not isinstance(payload.get("error"), str)
            or not isinstance(raw_checks, list)
        ):
            raise ActivationError("preflight receipt is invalid")
        checks: list[PreflightCheck] = []
        for item in raw_checks:
            if not isinstance(item, dict):
                raise ActivationError("preflight receipt is invalid")
            name = item.get("name")
            returncode = item.get("returncode")
            duration_ms = item.get("duration_ms")
            output = item.get("output")
            timed_out = item.get("timed_out")
            if (
                not isinstance(name, str)
                or not (isinstance(returncode, int) or returncode is None)
                or not isinstance(duration_ms, int)
                or duration_ms < 0
                or not isinstance(output, str) or len(output) > _PREFLIGHT_OUTPUT_LIMIT
                or not isinstance(timed_out, bool)
            ):
                raise ActivationError("preflight receipt is invalid")
            checks.append(PreflightCheck(name, returncode, duration_ms, output, timed_out))
        return PreflightReceipt(
            activation_id=record.activation_id,
            success=bool(payload["success"]),
            candidate_digest=record.candidate_digest,
            slot_tree_digest=record.slot_tree_digest,
            source_root=source_root,
            checks=tuple(checks),
            error=str(payload["error"]),
            record_path=path,
        )

    def _successful_preflight_unlocked(self, record: ActivationRecord) -> PreflightReceipt:
        receipt = self._preflight_receipt_from_payload(
            _read_private_object(self._preflight_path(record), description="preflight receipt"),
            self._preflight_path(record),
            record,
        )
        expected_names = tuple(check.name for check in receipt.checks)
        if (
            not receipt.success
            or expected_names != _STATIC_PREFLIGHT_CHECKS
            or any(check.returncode != 0 or check.timed_out for check in receipt.checks)
        ):
            raise ActivationConflict("preflight must succeed before confirmation")
        fresh_checks = self._run_static_preflight_unlocked(record)
        if any(check.returncode != 0 or check.timed_out for check in fresh_checks):
            raise ActivationConflict("preflight must succeed before confirmation")
        return receipt

    def preflight(self, activation_id: str) -> PreflightReceipt:
        """Perform static validation without executing untrusted candidate code."""

        with self._locked():
            _payload, record = self._load_record(activation_id)
            if record.state != "staged":
                raise ActivationConflict("only staged candidates can be preflighted")
            checks = self._run_static_preflight_unlocked(record)
            failed = next((check for check in checks if check.returncode != 0), None)
            return self._write_preflight_receipt(
                record,
                success=failed is None,
                checks=checks,
                error="" if failed is None else f"{failed.name} failed",
            )

    def _transition_unlocked(
        self,
        payload: dict[str, object],
        record: ActivationRecord,
        *,
        expected: str,
        target: str,
        detail: str = "",
    ) -> ActivationRecord:
        """Apply a CAS transition while the control-plane lock is held."""

        if target not in _TRANSITIONS.get(expected, set()):
            raise ActivationConflict(
                f"invalid activation transition: {expected} -> {target}"
            )
        if record.state != expected:
            raise ActivationConflict(
                f"activation state is {record.state}, not expected {expected}"
            )
        if target == "awaiting_confirmation":
            self._verify_staged_unlocked(record.activation_id)
            self._successful_preflight_unlocked(record)
        payload["state"] = target
        payload["updated_at"] = _utc_now()
        payload["detail"] = detail
        _write_private_json(record.record_path, payload)
        return self._record_from_payload(payload, record.record_path)

    def transition(
        self, activation_id: str, expected: str, target: str, detail: str = ""
    ) -> ActivationRecord:
        """Apply a non-authorizing durable compare-and-swap transition.

        This deliberately cannot grant authorization or begin a switch.  Model
        tooling uses this public control-plane surface, whereas an authenticated
        callback is the only path to ``authorized`` and Task 5 owns the later
        ``authorized -> switching`` handoff.
        """

        if target in {"authorized", "switching"}:
            raise ActivationConflict("owner confirmation is required for activation")
        with self._locked():
            payload, record = self._load_record(activation_id)
            return self._transition_unlocked(
                payload, record, expected=expected, target=target, detail=detail
            )

    @staticmethod
    def _confirmation_datetime(value: object) -> datetime:
        if not isinstance(value, str):
            raise ActivationError("activation confirmation is invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ActivationError("activation confirmation is invalid") from exc
        if parsed.tzinfo is None:
            raise ActivationError("activation confirmation is invalid")
        return parsed.astimezone(timezone.utc)

    def _confirmation_from_payload(
        self, payload: Mapping[str, object], path: Path
    ) -> ActivationConfirmation:
        callback_id = payload.get("callback_id")
        if (
            payload.get("schema_version") != _CONFIRMATION_SCHEMA_VERSION
            or not isinstance(callback_id, str)
            or not callback_id.isascii()
            or not callback_id.isalnum()
            or not isinstance(payload.get("activation_id"), str)
            or not isinstance(payload.get("candidate_digest"), str)
            or payload.get("owner_lane") != _CANONICAL_OWNER_LANE
            or not isinstance(payload.get("channel"), str)
            or not payload["channel"]
            or not isinstance(payload.get("secret_hash"), str)
            or len(payload["secret_hash"]) != 64
            or payload.get("status") not in {"pending", "consumed", "denied", "expired", "superseded"}
        ):
            raise ActivationError("activation confirmation is invalid")
        expires_at = self._confirmation_datetime(payload.get("expires_at"))
        self._confirmation_datetime(payload.get("issued_at"))
        return ActivationConfirmation(
            callback_id=callback_id,
            activation_id=str(payload["activation_id"]),
            candidate_digest=str(payload["candidate_digest"]),
            channel=str(payload["channel"]),
            expires_at=expires_at.isoformat(),
            record_path=path,
        )

    def issue_confirmation(
        self,
        activation_id: str,
        lane_key: str,
        channel: str,
        *,
        now: datetime | None = None,
    ) -> ActivationConfirmation:
        """Create one opaque owner-only callback for an exact static receipt."""

        if lane_key != _CANONICAL_OWNER_LANE or not channel.strip():
            raise ActivationConflict("activation confirmation requires the owner DM")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._locked():
            payload, record = self._load_record(activation_id)
            if record.state != "awaiting_confirmation":
                raise ActivationConflict("activation is not ready for confirmation")
            self._verify_staged_unlocked(activation_id)
            self._successful_preflight_unlocked(record)
            previous = payload.get("confirmation_callback_id")
            if isinstance(previous, str):
                previous_path = self._confirmation_path(previous)
                if previous_path.exists():
                    old_payload = _read_private_object(
                        previous_path, description="activation confirmation"
                    )
                    if old_payload.get("status") == "pending":
                        old_payload["status"] = "superseded"
                        old_payload["resolved_at"] = current.isoformat()
                        _write_private_json(previous_path, old_payload)
            callback_id = secrets.token_hex(18)
            secret_hash = hashlib.sha256(
                self._confirmation_secret_unlocked(callback_id)
            ).hexdigest()
            path = self._confirmation_path(callback_id)
            confirmation_payload: dict[str, object] = {
                "schema_version": _CONFIRMATION_SCHEMA_VERSION,
                "callback_id": callback_id,
                "activation_id": record.activation_id,
                "candidate_digest": record.candidate_digest,
                "owner_lane": _CANONICAL_OWNER_LANE,
                "channel": channel.strip(),
                "secret_hash": secret_hash,
                "status": "pending",
                "issued_at": current.isoformat(),
                "expires_at": (current + _CONFIRMATION_TTL).isoformat(),
            }
            _write_private_json(path, confirmation_payload)
            payload["confirmation_callback_id"] = callback_id
            payload["updated_at"] = _utc_now()
            _write_private_json(record.record_path, payload)
            return self._confirmation_from_payload(confirmation_payload, path)

    def pending_confirmation_for_channel(
        self, channel: str, *, now: datetime | None = None
    ) -> ActivationConfirmation | None:
        """Return the current opaque card handle for a trusted gateway channel."""

        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._locked():
            for path in sorted(self.confirmations.glob("*.json")):
                payload = _read_private_object(path, description="activation confirmation")
                confirmation = self._confirmation_from_payload(payload, path)
                if (
                    payload.get("status") != "pending"
                    or confirmation.channel != channel
                    or current >= self._confirmation_datetime(payload.get("expires_at"))
                ):
                    continue
                activation_payload, activation = self._load_record(confirmation.activation_id)
                if (
                    activation.state == "awaiting_confirmation"
                    and activation.candidate_digest == confirmation.candidate_digest
                    and activation_payload.get("confirmation_callback_id") == confirmation.callback_id
                ):
                    return confirmation
        return None

    def _resolve_gateway_confirmation(
        self,
        callback_id: str,
        *,
        capability: object,
        owner_lane: str,
        channel: str,
        choice: str = "confirm",
        now: datetime | None = None,
    ) -> ActivationRecord:
        """Consume one authenticated callback and enter the authorized state.

        The callback identifier is only a routing handle.  Authorization is
        bound to gateway-authenticated owner context, exact channel, private
        derived-secret verification, exact candidate digest, and a durable CAS.
        """

        normalized = choice.strip().lower()
        if normalized == "always":
            normalized = "confirm"
        if normalized not in {"confirm", "deny"}:
            raise ActivationConflict("unsupported activation confirmation choice")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if capability is not _GATEWAY_RESOLVER_CAPABILITY:
            raise ActivationConflict("activation confirmation is gateway-owned")
        with self._locked():
            path = self._confirmation_path(callback_id)
            confirmation_payload = _read_private_object(
                path, description="activation confirmation"
            )
            confirmation = self._confirmation_from_payload(confirmation_payload, path)
            if (
                owner_lane != _CANONICAL_OWNER_LANE
                or channel != confirmation.channel
            ):
                raise ActivationConflict("activation confirmation requires an authenticated owner callback")
            expected_hash = hashlib.sha256(
                self._confirmation_secret_unlocked(confirmation.callback_id)
            ).hexdigest()
            stored_hash = str(confirmation_payload["secret_hash"])
            if not hmac.compare_digest(expected_hash, stored_hash):
                raise ActivationError("activation confirmation secret is invalid")
            if confirmation_payload.get("status") != "pending":
                raise ActivationConflict("activation confirmation was already resolved")
            if current >= self._confirmation_datetime(confirmation_payload.get("expires_at")):
                confirmation_payload["status"] = "expired"
                confirmation_payload["resolved_at"] = current.isoformat()
                _write_private_json(path, confirmation_payload)
                activation_payload, activation = self._load_record(confirmation.activation_id)
                if activation.state == "awaiting_confirmation":
                    self._transition_unlocked(
                        activation_payload,
                        activation,
                        expected="awaiting_confirmation",
                        target="expired",
                        detail="owner confirmation expired",
                    )
                raise ActivationConflict("activation confirmation expired")
            activation_payload, activation = self._load_record(confirmation.activation_id)
            if activation.candidate_digest != confirmation.candidate_digest:
                raise ActivationError("activation confirmation digest is stale")
            if activation_payload.get("confirmation_callback_id") != confirmation.callback_id:
                raise ActivationConflict("activation confirmation was superseded")
            self._verify_staged_unlocked(activation.activation_id)
            self._successful_preflight_unlocked(activation)
            target = "authorized" if normalized == "confirm" else "denied"
            # The activation state is the durable CAS and is committed before
            # anything in a later worker could start.
            result = self._transition_unlocked(
                activation_payload,
                activation,
                expected="awaiting_confirmation",
                target=target,
                detail="owner confirmed exact candidate" if target == "authorized" else "owner declined activation",
            )
            confirmation_payload["status"] = "consumed" if target == "authorized" else "denied"
            confirmation_payload["resolved_at"] = current.isoformat()
            _write_private_json(path, confirmation_payload)
            return result

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
