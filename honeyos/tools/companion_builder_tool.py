"""Narrow model-facing Builder control plane.

The model may stage a reviewed candidate and ask the gateway to render a
confirmation card.  It cannot resolve that card, grant itself authorization,
or start/switch any service.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from honeyos.companion.builder_activation import (
    ActivationConflict,
    ActivationError,
    ActivationStore,
)
from honeyos.tools.approval import get_current_session_key
from honeyos.tools.registry import registry


_OWNER_LANE = "agent:main:companion:dm:owner"

COMPANION_BUILDER_SCHEMA = {
    "name": "companion_builder",
    "description": (
        "Manage a reviewed HoneyOS Builder candidate in the private owner chat. "
        "Use stage after the Builder Skill has prepared a candidate, "
        "request_activation to ask the owner for a one-time confirmation, and "
        "status to check progress. This tool can never approve, switch, restart, "
        "or run a candidate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["stage", "request_activation", "status"]},
            "change_root": {
                "type": "string",
                "description": "Prepared HoneyOS Builder change directory; required for stage.",
            },
            "activation_id": {
                "type": "string",
                "description": "Activation id returned by stage; required for request_activation/status.",
            },
        },
        "required": ["action"],
    },
}


def _is_honeyos_runtime() -> bool:
    return os.environ.get("HONEYOS_RUNTIME_ID", "").startswith("honeyos-companion-")


def _tool_scope() -> tuple[Path, str, str] | None:
    if not _is_honeyos_runtime():
        return None
    home = os.environ.get("HONEYOS_HOME", "").strip()
    lane = get_current_session_key("").strip()
    if not home or lane != _OWNER_LANE:
        return None
    try:
        from honeyos.gateway.session_context import get_session_env

        channel = get_session_env("HONEYOS_SESSION_PLATFORM", "").strip()
    except Exception:
        channel = os.environ.get("HONEYOS_SESSION_PLATFORM", "").strip()
    if not channel:
        return None
    return Path(home).expanduser().resolve(), lane, channel


def _bundled_root() -> Path:
    configured = os.environ.get("HONEYOS_BUNDLED_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else Path(__file__).parents[2]


def _result(success: bool, **payload: object) -> str:
    return json.dumps({"success": success, **payload}, ensure_ascii=False, separators=(",", ":"))


def companion_builder_tool(
    *, action: str, change_root: str | None = None, activation_id: str | None = None
) -> str:
    """Stage/request/status only; confirmation stays entirely gateway-owned."""

    scope = _tool_scope()
    if scope is None:
        return _result(False, error="Builder activation is available only in the authenticated owner chat")
    home, lane, channel = scope
    store = ActivationStore(home, bundled_root=_bundled_root())
    normalized = str(action or "").strip().lower()
    try:
        if normalized == "stage":
            if not change_root:
                return _result(False, error="change_root is required to stage a reviewed Builder candidate")
            staged = store.stage(Path(change_root))
            receipt = store.preflight(staged.activation_id)
            if not receipt.success:
                return _result(False, activation_id=staged.activation_id, error="static validation did not pass")
            ready = store.transition(staged.activation_id, "staged", "awaiting_confirmation")
            return _result(
                True,
                activation_id=ready.activation_id,
                candidate_digest=ready.candidate_digest,
                state=ready.state,
            )
        if normalized == "request_activation":
            if not activation_id:
                return _result(False, error="activation_id is required to request activation")
            # Deliberately do not expose the callback id or any derived secret
            # in model-visible text.  The gateway reads the private record to
            # render its authenticated confirmation control.
            confirmation = store.issue_confirmation(activation_id, lane, channel)
            return _result(
                True,
                activation_id=confirmation.activation_id,
                candidate_digest=confirmation.candidate_digest,
                state="awaiting_owner_confirmation",
                expires_at=confirmation.expires_at,
            )
        if normalized == "status":
            if not activation_id:
                return _result(False, error="activation_id is required to check Builder status")
            record = store.verify_staged(activation_id)
            return _result(
                True,
                activation_id=record.activation_id,
                candidate_digest=record.candidate_digest,
                state=record.state,
            )
    except (ActivationError, OSError, ValueError) as exc:
        return _result(False, error=str(exc))
    return _result(False, error="unsupported Builder action")


def _handler(args: dict, **_kwargs: object) -> str:
    return companion_builder_tool(
        action=str(args.get("action") or ""),
        change_root=args.get("change_root"),
        activation_id=args.get("activation_id"),
    )


registry.register(
    name="companion_builder",
    toolset="companion_builder",
    schema=COMPANION_BUILDER_SCHEMA,
    handler=_handler,
    check_fn=_is_honeyos_runtime,
    emoji="🧩",
)
