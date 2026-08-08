"""Effect-based permission policy for the HoneyOS companion.

The policy deliberately separates trusted user intent from tool arguments.
Only the current user task may create a short-lived grant; assistant text,
tool output, browsed pages, and installed Skills cannot create one.
"""

from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class RiskTier(str, Enum):
    """User-facing permission tiers."""

    HARD_BLOCK = "hard_block"
    CONSENT = "consent"
    DIRECT = "direct"


@dataclass(frozen=True)
class Effect:
    """A normalized user-visible effect proposed by a tool call."""

    action_class: str
    target: str = ""
    in_workspace: bool = False
    internal_secret: bool = False
    destructive: bool = False
    external_commit: bool = False
    unattended: bool = False
    technical_detail: str = ""


@dataclass(frozen=True)
class IntentGrant:
    """Consent derived from the trusted user task for this turn only."""

    turn_id: str
    action_class: str
    target: str
    scope: str = "exact"


@dataclass(frozen=True)
class PolicyDecision:
    tier: RiskTier
    reason: str
    matched_grant: IntentGrant | None = None


@dataclass(frozen=True)
class PermissionRequest:
    """Platform-neutral request rendered by Feishu, web, or CLI."""

    request_id: str
    session_key: str
    turn_id: str
    action_class: str
    summary: str
    target: str
    boundaries: tuple[str, ...] = ()
    reversibility: str = "reversible"
    technical_detail: str = ""
    allow_scope: bool = False


_turn_intent_grants: contextvars.ContextVar[tuple[IntentGrant, ...]] = (
    contextvars.ContextVar("honeyos_turn_intent_grants", default=())
)

_QUESTION_RE = re.compile(
    r"(?:吗|么|如何|怎么|能不能|可不可以|是否)(?:[？?])?$",
    re.IGNORECASE,
)
_SEND_RE = re.compile(
    r"(?:帮我)?(?:给|向)\s*(?P<target>[^，。,.\s]{1,32}?)\s*"
    r"(?:发|发送|回复|说)",
    re.IGNORECASE,
)
_MUTATION_RE = re.compile(
    r"(?:把|将)\s*(?P<object>[^，。,.]{1,80}?)\s*"
    r"(?P<verb>上传|发布|删掉|删除)(?:到|至)?\s*"
    r"(?P<target>[^，。,.]{0,80})",
    re.IGNORECASE,
)
_SCHEDULE_RE = re.compile(
    r"(?P<schedule>(?:每|每天|每周|明天|今晚|\d+[点时])[^，。,.]{0,80}?)"
    r"(?P<verb>提醒|发送|运行)",
    re.IGNORECASE,
)


def _normalize_target(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "")).strip("：:，,。.")
    for prefix in ("feishu:", "weixin:", "飞书:", "微信:"):
        if normalized.lower().startswith(prefix.lower()):
            return normalized[len(prefix) :]
    return normalized


def grants_from_user_task(user_task: str, *, turn_id: str) -> tuple[IntentGrant, ...]:
    """Extract deliberately narrow grants from the trusted current user task."""

    text = str(user_task or "").strip()
    if not text or _QUESTION_RE.search(text):
        return ()

    grants: list[IntentGrant] = []
    send = _SEND_RE.search(text)
    if send:
        target = _normalize_target(send.group("target"))
        if target:
            grants.append(IntentGrant(turn_id, "send", target))

    mutation = _MUTATION_RE.search(text)
    if mutation:
        verb = mutation.group("verb")
        action_class = "delete" if verb in {"删掉", "删除"} else (
            "upload" if verb == "上传" else "publish"
        )
        target = _normalize_target(mutation.group("target") or mutation.group("object"))
        if target:
            grants.append(IntentGrant(turn_id, action_class, target))

    schedule = _SCHEDULE_RE.search(text)
    if schedule:
        target = _normalize_target(schedule.group("schedule"))
        if target:
            grants.append(IntentGrant(turn_id, "schedule", target, scope="task"))

    return tuple(grants)


def set_turn_intent_grants(
    grants: Iterable[IntentGrant],
) -> contextvars.Token[tuple[IntentGrant, ...]]:
    return _turn_intent_grants.set(tuple(grants))


def reset_turn_intent_grants(
    token: contextvars.Token[tuple[IntentGrant, ...]],
) -> None:
    _turn_intent_grants.reset(token)


def current_intent_grants() -> tuple[IntentGrant, ...]:
    return _turn_intent_grants.get()


def grant_matches(grant: IntentGrant, effect: Effect) -> bool:
    if grant.action_class != effect.action_class:
        return False
    grant_target = _normalize_target(grant.target)
    effect_target = _normalize_target(effect.target)
    if not grant_target or not effect_target:
        return False
    if grant.scope == "subtree":
        return effect_target == grant_target or effect_target.startswith(grant_target + "/")
    if grant.scope == "task":
        return grant_target in effect_target or effect_target in grant_target
    return grant_target == effect_target


def decide_effect(effect: Effect) -> PolicyDecision:
    """Return the runtime-enforced permission tier for one normalized effect."""

    if effect.internal_secret:
        return PolicyDecision(
            RiskTier.HARD_BLOCK,
            "HoneyOS internal credential access",
        )

    matched = next(
        (grant for grant in current_intent_grants() if grant_matches(grant, effect)),
        None,
    )
    if matched is not None:
        return PolicyDecision(
            RiskTier.DIRECT,
            "explicit current-turn instruction",
            matched,
        )

    crosses_workspace = (
        effect.action_class in {"write_file", "directory"}
        and not effect.in_workspace
    )
    if (
        effect.destructive
        or effect.external_commit
        or effect.unattended
        or crosses_workspace
    ):
        return PolicyDecision(
            RiskTier.CONSENT,
            "action crosses a user boundary",
        )

    return PolicyDecision(RiskTier.DIRECT, "ordinary reversible action")
