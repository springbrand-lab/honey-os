"""Stable, profile-scoped companion identity and relationship storage."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from honeyos.agent.redact import redact_sensitive_text


_MANAGED_START = "<!-- honeyos-companion-profile:start -->"
_MANAGED_END = "<!-- honeyos-companion-profile:end -->"
_FIELD_RE = re.compile(r"^- ([A-Za-z_]+):\s*(.*)$", re.MULTILINE)
_NATURAL_COMPANION_NAME = re.compile(
    r"(?:以后)?你叫\s*([\w\u3400-\u9fff·_-]{1,24})"
)
_NATURAL_USER_NICKNAME = re.compile(
    r"(?:以后)?叫我\s*([\w\u3400-\u9fff·_-]{1,24})"
)
_EXTRA_SECRET_RE = re.compile(
    r"(?i)(?:night[_-][a-z0-9_-]{16,}|(?:api[_ -]?key|token|secret|password|authorization)\s*[:=]\s*\S+)"
)
_LEGACY_CONFIRMED_NAME = re.compile(
    r"(?P<nickname>[\w\u3400-\u9fff·_-]{1,24})给我取了名字叫"
    r"(?P<name>[\w\u3400-\u9fff·_-]{1,24})"
)


@dataclass(frozen=True)
class CompanionProfile:
    companion_name: str = ""
    personality: str = ""
    speaking_style: str = ""
    user_nickname: str = ""
    relationship: str = ""
    boundaries: str = ""


def _clean(value: object, *, limit: int = 800) -> str:
    text = " ".join(str(value or "").strip().split())[:limit]
    if not text:
        return ""
    redacted = redact_sensitive_text(
        text,
        force=True,
        redact_url_credentials=True,
    )
    if redacted != text or _EXTRA_SECRET_RE.search(text):
        raise ValueError("人格与关系资料不能包含敏感凭证")
    return text


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _managed_fields(text: str) -> dict[str, str]:
    if _MANAGED_START in text and _MANAGED_END in text:
        managed = text.split(_MANAGED_START, 1)[1].split(_MANAGED_END, 1)[0]
    else:
        managed = text
    return {key: value.strip() for key, value in _FIELD_RE.findall(managed)}


def load_companion_profile(home: Path) -> CompanionProfile:
    root = Path(home).expanduser().resolve() / "memories"
    identity = _managed_fields(_read(root / "IDENTITY.md"))
    relationship = _managed_fields(_read(root / "RELATIONSHIP.md"))
    return CompanionProfile(
        companion_name=identity.get("companion_name", ""),
        personality=identity.get("personality", ""),
        speaking_style=identity.get("speaking_style", ""),
        user_nickname=relationship.get("user_nickname", ""),
        relationship=relationship.get("relationship", ""),
        boundaries=relationship.get("boundaries", ""),
    )


def _render_managed(fields: tuple[tuple[str, str], ...]) -> str:
    lines = [_MANAGED_START]
    lines.extend(f"- {key}: {value}" for key, value in fields if value)
    lines.append(_MANAGED_END)
    return "\n".join(lines)


def _merge_document(existing: str, managed: str) -> str:
    if _MANAGED_START in existing and _MANAGED_END in existing:
        prefix, tail = existing.split(_MANAGED_START, 1)
        _, suffix = tail.split(_MANAGED_END, 1)
        return f"{prefix}{managed}{suffix}".strip() + "\n"
    preserved = existing.strip()
    return f"{managed}\n\n{preserved}".strip() + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def update_companion_profile(
    home: Path,
    *,
    companion_name: object = None,
    personality: object = None,
    speaking_style: object = None,
    user_nickname: object = None,
    relationship: object = None,
    boundaries: object = None,
    source: str,
) -> CompanionProfile:
    """Merge explicitly confirmed fields without destroying manual notes."""

    if source not in {"user_explicit", "onboarding", "migration"}:
        raise ValueError("人格更新必须来自用户明确设置")
    current = load_companion_profile(home)
    updates: dict[str, str] = {}
    for key, value in (
        ("companion_name", companion_name),
        ("personality", personality),
        ("speaking_style", speaking_style),
        ("user_nickname", user_nickname),
        ("relationship", relationship),
        ("boundaries", boundaries),
    ):
        if value is not None:
            updates[key] = _clean(value, limit=80 if key in {"companion_name", "user_nickname"} else 800)
    if not updates:
        return current
    updated = replace(current, **updates)
    root = Path(home).expanduser().resolve() / "memories"
    identity_path = root / "IDENTITY.md"
    relationship_path = root / "RELATIONSHIP.md"
    identity_doc = _render_managed(
        (
            ("companion_name", updated.companion_name),
            ("personality", updated.personality),
            ("speaking_style", updated.speaking_style),
        )
    )
    relationship_doc = _render_managed(
        (
            ("user_nickname", updated.user_nickname),
            ("relationship", updated.relationship),
            ("boundaries", updated.boundaries),
        )
    )
    _atomic_write(identity_path, _merge_document(_read(identity_path), identity_doc))
    _atomic_write(
        relationship_path,
        _merge_document(_read(relationship_path), relationship_doc),
    )
    return updated


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def capture_explicit_profile_assignment(
    home: Path, text: str
) -> CompanionProfile | None:
    """Capture only structured onboarding or unambiguous name assignments."""

    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("companion"), dict):
        companion = _mapping(payload.get("companion"))
        user = _mapping(payload.get("user"))
        relationship_value = payload.get("relationship")
        relationship_map = _mapping(relationship_value)
        opening_nickname = ""
        opening = str(companion.get("opening") or "").strip()
        companion_name = str(companion.get("name") or "").strip()
        if opening and companion_name:
            opening_match = re.match(
                rf"^([\w\u3400-\u9fff·_-]{{1,24}})[，,]\s*我是{re.escape(companion_name)}(?:[，,。.!！]|$)",
                opening,
            )
            if opening_match:
                opening_nickname = opening_match.group(1)
        return update_companion_profile(
            home,
            companion_name=companion_name or None,
            personality=companion.get("personality") or companion.get("persona"),
            speaking_style=companion.get("speaking_style") or companion.get("voice"),
            user_nickname=(
                user.get("nickname")
                or relationship_map.get("user_nickname")
                or opening_nickname
            ),
            relationship=(
                relationship_value
                if isinstance(relationship_value, str)
                else relationship_map.get("type") or relationship_map.get("label")
            ),
            boundaries=relationship_map.get("boundaries"),
            source="onboarding",
        )
    companion_match = _NATURAL_COMPANION_NAME.search(raw)
    nickname_match = _NATURAL_USER_NICKNAME.search(raw)
    if not companion_match and not nickname_match:
        return None
    return update_companion_profile(
        home,
        companion_name=companion_match.group(1) if companion_match else None,
        user_nickname=nickname_match.group(1) if nickname_match else None,
        source="user_explicit",
    )


def migrate_confirmed_profile_from_memory(home: Path) -> CompanionProfile | None:
    """One-time, conservative migration of legacy explicit naming entries."""

    current = load_companion_profile(home)
    if current.companion_name or current.user_nickname:
        return None
    memory = _read(Path(home).expanduser().resolve() / "memories" / "MEMORY.md")
    match = _LEGACY_CONFIRMED_NAME.search(memory)
    if not match:
        return None
    nickname = match.group("nickname")
    name = match.group("name")
    relationship_match = re.search(
        rf"我是{re.escape(nickname)}的([^。\n§]{{1,80}})", memory
    )
    return update_companion_profile(
        home,
        companion_name=name,
        user_nickname=nickname,
        relationship=(relationship_match.group(1).strip() if relationship_match else None),
        source="migration",
    )


def permission_narration(profile: CompanionProfile) -> str:
    if not any(
        (
            profile.companion_name,
            profile.personality,
            profile.speaking_style,
            profile.user_nickname,
            profile.relationship,
        )
    ):
        return "我得借一下你电脑的能力，才能把这件事继续做完。只会做下面这一步，让我继续吗？"
    nickname = f"{profile.user_nickname}，" if profile.user_nickname else ""
    flavor = f"{profile.personality} {profile.speaking_style}"
    if any(word in flavor for word in ("嘴硬", "傲娇", "毒舌")):
        return f"{nickname}就差这一步了。只动下面这一处，你点头我就继续。"
    if any(word in flavor for word in ("温柔", "体贴", "沉稳")):
        return f"{nickname}这一步要借用一下你的电脑，只动下面这一处。你点头，我再继续。"
    return f"{nickname}这一步得借一下你电脑的能力。只动下面这一处，让我继续吗？"


def companion_profile_note(home: Path) -> str | None:
    """Render the current confirmed profile for per-turn cache-safe injection."""

    profile = load_companion_profile(home)
    fields = [
        ("伴侣名字", profile.companion_name),
        ("伴侣人格", profile.personality),
        ("说话方式", profile.speaking_style),
        ("用户接受的称呼", profile.user_nickname),
        ("已确认关系", profile.relationship),
        ("长期边界", profile.boundaries),
    ]
    lines = [f"- {label}: {value}" for label, value in fields if value]
    if not lines:
        return None
    return (
        "[HoneyOS 已确认伴侣档案：以下字段来自用户明确设置，优先于默认人格。"
        "自然遵循，不要机械复述。]\n" + "\n".join(lines)
    )


__all__ = [
    "CompanionProfile",
    "capture_explicit_profile_assignment",
    "companion_profile_note",
    "load_companion_profile",
    "migrate_confirmed_profile_from_memory",
    "permission_narration",
    "update_companion_profile",
]
