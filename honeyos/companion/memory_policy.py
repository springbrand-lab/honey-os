"""Companion-specific memory write policy and local audit trail."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns

import yaml

from honeyos.agent.redact import redact_sensitive_text
from honeyos.core.constants import get_honeyos_home


_MUTATING_ACTIONS = frozenset({"add", "replace", "remove", "batch"})
_EXTRA_SECRET_RE = re.compile(
    r"(?i)(?:night[_-][a-z0-9_-]{16,}|(?:api[_ -]?key|token|secret|password|authorization)\s*[:=]\s*\S+)"
)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class MemoryAuditEvent:
    target: str
    action: str
    origin: str
    content: str = ""
    session_id: str = ""
    message_id: str = ""


def is_companion_mode() -> bool:
    """Read the active home's explicit agent mode without using global caches."""

    config_path = get_honeyos_home() / "config.yaml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(config, dict):
        return False
    agent = config.get("agent", {})
    if not isinstance(agent, dict):
        return False
    return str(agent.get("mode", "assistant") or "assistant").strip().lower() == "companion"


def check_companion_write(*, origin: str, action: str) -> PolicyDecision:
    """Reject autonomous background mutations for a companion home."""

    normalized_action = (action or "").strip().lower()
    if not is_companion_mode() or normalized_action not in _MUTATING_ACTIONS:
        return PolicyDecision(True)
    if (origin or "foreground").strip().lower() == "background_review":
        return PolicyDecision(
            False,
            "Companion memory requires an explicit foreground conversation; "
            "background review writes are disabled.",
        )
    return PolicyDecision(True)


def contains_sensitive_memory_content(content: str) -> bool:
    """Fail closed when durable companion memory contains reusable credentials."""

    text = str(content or "")
    if not text:
        return False
    if _EXTRA_SECRET_RE.search(text):
        return True
    return redact_sensitive_text(
        text,
        force=True,
        redact_url_credentials=True,
    ) != text


def _write_private(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time_ns()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def scrub_sensitive_companion_state(home: Path) -> bool:
    """Remove legacy credentials from durable memories and their audit previews."""

    root = Path(home).expanduser().resolve()
    changed = False
    for filename in ("MEMORY.md", "USER.md"):
        path = root / "memories" / filename
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        entries = raw.split("\n§\n") if raw else []
        safe = [entry for entry in entries if not contains_sensitive_memory_content(entry)]
        if len(safe) == len(entries):
            continue
        sanitized_backup = path.with_name(f"{path.name}.bak.{time_ns()}")
        removed_count = len(entries) - len(safe)
        backup_body = "\n§\n".join(safe + [f"[REMOVED {removed_count} SENSITIVE ENTRIES]"])
        _write_private(sanitized_backup, backup_body.rstrip() + "\n")
        _write_private(path, "\n§\n".join(safe).rstrip() + ("\n" if safe else ""))
        changed = True

    audit_path = root / "logs" / "memory-audit.jsonl"
    try:
        audit_lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        audit_lines = []
    rendered: list[str] = []
    audit_changed = False
    for line in audit_lines:
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            rendered.append(line)
            continue
        content = str(payload.get("content") or "") if isinstance(payload, dict) else ""
        if isinstance(payload, dict) and contains_sensitive_memory_content(content):
            payload["content"] = "[removed sensitive credential]"
            audit_changed = True
        rendered.append(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    if audit_changed:
        _write_private(audit_path, "\n".join(rendered).rstrip() + "\n")
        changed = True
    return changed


def audit_memory_write(event: MemoryAuditEvent) -> None:
    """Append one bounded, non-secret-metadata audit row for companion writes."""

    if not is_companion_mode():
        return
    audit_path = get_honeyos_home() / "logs" / "memory-audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(event)
    payload["content"] = (payload.get("content") or "")[:4000]
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    line = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)
    try:
        Path(audit_path).chmod(0o600)
    except OSError:
        pass
