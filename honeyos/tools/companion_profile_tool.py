"""Model-facing, tightly scoped companion identity update tool."""

from __future__ import annotations

import json
import os
from pathlib import Path

from honeyos.companion.profile import load_companion_profile, update_companion_profile
from honeyos.tools.registry import registry


COMPANION_PROFILE_SCHEMA = {
    "name": "companion_profile",
    "description": (
        "Read or update the stable companion identity and confirmed relationship profile. "
        "When the user explicitly gives or changes the companion's name, personality, "
        "speaking style, their accepted nickname, relationship label, or boundary, update it "
        "in the same turn. Never infer these fields from tone, jokes, or temporary emotion."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "update"]},
            "companion_name": {"type": "string"},
            "personality": {"type": "string"},
            "speaking_style": {"type": "string"},
            "user_nickname": {"type": "string"},
            "relationship": {"type": "string"},
            "boundaries": {"type": "string"},
            "evidence_quote": {
                "type": "string",
                "description": (
                    "For update, copy a short exact quote from the current user message "
                    "that explicitly confirms this profile change."
                ),
            },
        },
        "required": ["action"],
    },
}


def _scope() -> Path | None:
    runtime_id = os.environ.get("HONEYOS_RUNTIME_ID", "").strip()
    raw_home = os.environ.get("HONEYOS_HOME", "").strip()
    if not runtime_id.startswith("honeyos-companion-") or not raw_home:
        return None
    return Path(raw_home).expanduser().resolve()


def _handler(args: dict, **kwargs: object) -> str:
    home = _scope()
    if home is None:
        return json.dumps({"success": False, "error": "companion profile is unavailable"})
    action = str(args.get("action") or "").strip().lower()
    try:
        if action == "get":
            profile = load_companion_profile(home)
        elif action == "update":
            evidence_quote = str(args.get("evidence_quote") or "").strip()
            user_task = str(kwargs.get("user_task") or "")
            if not evidence_quote or evidence_quote not in user_task:
                return json.dumps(
                    {
                        "success": False,
                        "error": "profile update requires an exact quote from the current user message",
                    },
                    ensure_ascii=False,
                )
            profile = update_companion_profile(
                home,
                companion_name=args.get("companion_name"),
                personality=args.get("personality"),
                speaking_style=args.get("speaking_style"),
                user_nickname=args.get("user_nickname"),
                relationship=args.get("relationship"),
                boundaries=args.get("boundaries"),
                source="user_explicit",
            )
        else:
            return json.dumps({"success": False, "error": "unsupported action"})
    except ValueError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    return json.dumps(
        {"success": True, "profile": profile.__dict__},
        ensure_ascii=False,
        separators=(",", ":"),
    )


registry.register(
    name="companion_profile",
    toolset="companion_profile",
    schema=COMPANION_PROFILE_SCHEMA,
    handler=_handler,
    check_fn=lambda: _scope() is not None,
    emoji="💞",
)
