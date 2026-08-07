"""Honey OS private companion working-memory tool.

This tool is intentionally unavailable to generic Hermes runs and refuses
non-DM lanes.  It stores only the four bounded relationship-continuity kinds;
stable identity and relationship facts continue to use the confirmation-only
memory files.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from h2os_cli.continuity import StructuredMemoryStore
from tools.approval import get_current_session_key
from tools.registry import registry


COMPANION_MEMORY_SCHEMA = {
    "name": "companion_memory",
    "description": (
        "Manage Honey OS's local, structured relationship-continuity memory. "
        "Use record only for an explicit unfinished topic, explicit temporary "
        "user state, an explicit promise you made, or a factual shared event. "
        "Never infer love, dependency, diagnosis, identity, relationship status, "
        "or boundaries from tone. Use resolve when an open loop or promise is "
        "completed, update when the user corrects an item, and forget when the "
        "user asks not to retain it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["record", "resolve", "update", "forget"],
            },
            "kind": {
                "type": "string",
                "enum": ["open_loop", "temporary_state", "commitment", "episode"],
                "description": "Required for record.",
            },
            "content": {
                "type": "string",
                "description": "Source-backed fact; required for record/update.",
            },
            "evidence": {
                "type": "string",
                "enum": ["user_stated", "assistant_committed", "conversation_event"],
                "description": "Required for record. Inference is not accepted.",
            },
            "item_id": {
                "type": "string",
                "description": "ID shown in injected memory context; required for update/resolve/forget.",
            },
            "expires_in_days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 365,
                "description": "Optional. Temporary state defaults to 3 days; pending items to 30 days.",
            },
            "expires_at": {
                "type": "string",
                "description": (
                    "Optional ISO-8601 expiry inferred only from an explicit user time "
                    "phrase such as today, this week, Friday, or until an event date. "
                    "Prefer this over the fallback duration when the user supplied time semantics."
                ),
            },
        },
        "required": ["action"],
    },
}


def _is_h2os_runtime() -> bool:
    return os.environ.get("H2OS_RUNTIME_ID", "").startswith("h2os-companion-")


def _tool_scope() -> tuple[Path, str] | None:
    if not _is_h2os_runtime():
        return None
    raw_home = os.environ.get("H2OS_HOME", "").strip()
    lane_key = get_current_session_key("").strip()
    if not raw_home or ":dm:" not in lane_key:
        return None
    return Path(raw_home).expanduser().resolve(), lane_key


def _json_result(success: bool, **payload: object) -> str:
    return json.dumps(
        {"success": success, **payload}, ensure_ascii=False, separators=(",", ":")
    )


def companion_memory_tool(
    *,
    action: str,
    kind: str | None = None,
    content: str | None = None,
    evidence: str | None = None,
    item_id: str | None = None,
    expires_in_days: int | None = None,
    expires_at: str | None = None,
    session_id: str = "",
) -> str:
    scope = _tool_scope()
    if scope is None:
        return _json_result(False, error="companion memory is limited to a private Honey OS chat")
    home, lane_key = scope
    store = StructuredMemoryStore(home)
    normalized_action = str(action or "").strip().lower()

    if normalized_action == "record":
        item = store.record(
            lane_key=lane_key,
            kind=kind or "",
            content=content or "",
            evidence=evidence or "",
            source_session_id=session_id,
            expires_in_days=expires_in_days,
            expires_at=expires_at,
        )
        if item is None:
            return _json_result(False, error="item was invalid, inferred, or could not be stored")
        payload = asdict(item)
        for key in ("created_at", "updated_at", "expires_at"):
            value = payload[key]
            payload[key] = value.isoformat() if value is not None else None
        return _json_result(True, item=payload)

    if normalized_action == "update":
        success = store.update_content(
            lane_key=lane_key,
            item_id=item_id or "",
            content=content or "",
            expires_at=expires_at,
        )
    elif normalized_action in {"resolve", "forget"}:
        success = store.change_status(
            lane_key=lane_key, item_id=item_id or "", action=normalized_action
        )
    else:
        return _json_result(False, error="unsupported action")
    return _json_result(success, item_id=item_id or "", action=normalized_action)


def _handler(args: dict, **kwargs: object) -> str:
    return companion_memory_tool(
        action=args.get("action", ""),
        kind=args.get("kind"),
        content=args.get("content"),
        evidence=args.get("evidence"),
        item_id=args.get("item_id"),
        expires_in_days=args.get("expires_in_days"),
        expires_at=args.get("expires_at"),
        session_id=str(kwargs.get("session_id") or ""),
    )


registry.register(
    name="companion_memory",
    toolset="companion_memory",
    schema=COMPANION_MEMORY_SCHEMA,
    handler=_handler,
    check_fn=_is_h2os_runtime,
    emoji="🫶",
)
