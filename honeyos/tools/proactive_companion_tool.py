"""Restricted natural-language controls for HoneyOS proactive companionship."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from honeyos.companion.topic_pool import TopicItem, TopicPoolStore
from honeyos.tools.approval import get_current_session_key
from honeyos.tools.registry import registry


PROACTIVE_COMPANION_SCHEMA = {
    "name": "proactive_companion",
    "description": (
        "Manage the private companion's opt-in proactive conversation settings "
        "and short-lived, source-backed Topic Pool. Use this when the user "
        "accepts/declines proactive messages, changes frequency or quiet hours, "
        "states topic preferences, asks what you have seen lately, chooses one "
        "topic to discuss, or dismisses a topic. This is already built into "
        "HoneyOS; never ask the user to install it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_preferences",
                    "set_consent",
                    "update_preferences",
                    "list_topics",
                    "dismiss_topic",
                    "discuss_topic",
                ],
            },
            "consented": {
                "type": "boolean",
                "description": "Required for set_consent. False also records that consent was asked.",
            },
            "paused": {"type": "boolean"},
            "daily_limit": {"type": "integer", "minimum": 0, "maximum": 3},
            "minimum_interval_hours": {
                "type": "integer",
                "minimum": 0,
                "maximum": 24,
            },
            "idle_hours": {"type": "integer", "minimum": 0, "maximum": 24},
            "quiet_start": {
                "type": "string",
                "description": "Local 24-hour time in HH:MM form.",
            },
            "quiet_end": {
                "type": "string",
                "description": "Local 24-hour time in HH:MM form.",
            },
            "focus_categories": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 20,
            },
            "blocked_categories": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 20,
            },
            "route_mode": {"type": "string", "enum": ["recent", "fixed"]},
            "fixed_platform": {
                "type": "string",
                "enum": ["api_server", "feishu", "weixin"],
            },
            "topic_id": {
                "type": "string",
                "description": "Required for dismiss_topic and discuss_topic.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Optional list_topics result limit.",
            },
        },
        "required": ["action"],
    },
}


def _is_honeyos_runtime() -> bool:
    return os.environ.get("HONEYOS_RUNTIME_ID", "").startswith("honeyos-companion-")


def _tool_scope() -> Path | None:
    if not _is_honeyos_runtime():
        return None
    raw_home = os.environ.get("HONEYOS_HOME", "").strip()
    lane_key = get_current_session_key("").strip()
    if not raw_home or ":dm:" not in lane_key:
        return None
    return Path(raw_home).expanduser().resolve()


def _json_result(success: bool, **payload: Any) -> str:
    return json.dumps(
        {"success": success, **payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _preferences_payload(store: TopicPoolStore) -> dict[str, Any]:
    payload = store.preferences_payload()
    for key in ("focus_categories", "blocked_categories"):
        payload[key] = list(payload.get(key) or ())
    return payload


def _topic_payload(item: TopicItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "hook": item.hook,
        "summary": item.summary,
        "category": item.category,
        "source_title": item.source_title,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "observed_at": item.observed_at.isoformat(),
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "expires_at": item.expires_at.isoformat(),
    }


def proactive_companion_tool(
    *,
    action: str,
    consented: bool | None = None,
    paused: bool | None = None,
    daily_limit: int | None = None,
    minimum_interval_hours: int | None = None,
    idle_hours: int | None = None,
    quiet_start: str | None = None,
    quiet_end: str | None = None,
    focus_categories: list[str] | None = None,
    blocked_categories: list[str] | None = None,
    route_mode: str | None = None,
    fixed_platform: str | None = None,
    topic_id: str | None = None,
    limit: int | None = None,
) -> str:
    home = _tool_scope()
    if home is None:
        return _json_result(
            False,
            error="proactive companionship is limited to a private HoneyOS chat",
        )
    store = TopicPoolStore(home)
    normalized_action = str(action or "").strip().lower()
    try:
        if normalized_action == "get_preferences":
            return _json_result(True, preferences=_preferences_payload(store))
        if normalized_action == "set_consent":
            if consented is None:
                return _json_result(False, error="consented is required for set_consent")
            store.update_preferences(consent_asked=True, consented=bool(consented))
            return _json_result(True, preferences=_preferences_payload(store))
        if normalized_action == "update_preferences":
            fields = {
                "paused": paused,
                "daily_limit": daily_limit,
                "minimum_interval_hours": minimum_interval_hours,
                "idle_hours": idle_hours,
                "quiet_start": quiet_start,
                "quiet_end": quiet_end,
                "focus_categories": focus_categories,
                "blocked_categories": blocked_categories,
                "route_mode": route_mode,
                "fixed_platform": fixed_platform,
            }
            changes = {key: value for key, value in fields.items() if value is not None}
            if not changes:
                return _json_result(False, error="no preference changes were supplied")
            store.update_preferences(**changes)
            return _json_result(True, preferences=_preferences_payload(store))
        if normalized_action == "list_topics":
            topics = store.list_open_topics(limit=limit or 5)
            return _json_result(True, topics=[_topic_payload(item) for item in topics])
        if normalized_action in {"dismiss_topic", "discuss_topic"}:
            clean_id = str(topic_id or "").strip()
            if not clean_id:
                return _json_result(False, error="topic_id is required")
            if normalized_action == "dismiss_topic":
                if not store.dismiss_topic(clean_id):
                    return _json_result(False, error="topic is unavailable or already handled")
                return _json_result(True, topic_id=clean_id, status="dismissed")
            item = store.consume_topic(clean_id)
            if item is None:
                return _json_result(False, error="topic is unavailable or already handled")
            return _json_result(
                True,
                topic=_topic_payload(item),
                instruction=(
                    "Continue naturally in the current companion persona. Use the "
                    "verified source as a conversation seed, not a news digest."
                ),
            )
        return _json_result(False, error="unsupported action")
    except (TypeError, ValueError) as exc:
        return _json_result(False, error=str(exc))


def _handler(args: dict, **kwargs: Any) -> str:
    allowed = {
        "action",
        "consented",
        "paused",
        "daily_limit",
        "minimum_interval_hours",
        "idle_hours",
        "quiet_start",
        "quiet_end",
        "focus_categories",
        "blocked_categories",
        "route_mode",
        "fixed_platform",
        "topic_id",
        "limit",
    }
    return proactive_companion_tool(
        **{key: value for key, value in args.items() if key in allowed}
    )


registry.register(
    name="proactive_companion",
    toolset="proactive_companion",
    schema=PROACTIVE_COMPANION_SCHEMA,
    handler=_handler,
    check_fn=_is_honeyos_runtime,
    emoji="💭",
)
