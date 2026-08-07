"""Companion-specific memory write policy and local audit trail."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from honeyos.core.constants import get_honeyos_home


_MUTATING_ACTIONS = frozenset({"add", "replace", "remove", "batch"})


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

