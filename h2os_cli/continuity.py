"""Short-lived, source-backed continuity across H2OS session resets.

The public interface is intentionally small: record one old→new session
transition, then ask for the note belonging to the new session.  Storage,
expiry, transcript filtering, and prompt rendering stay inside this module so
the Hermes gateway only needs two best-effort calls at its existing seams.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_TTL = timedelta(days=7)
DEFAULT_MAX_MESSAGES = 8
DEFAULT_MAX_CHARS = 3000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class HandoffMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ContinuityHandoff:
    lane_key: str
    source_session_id: str
    target_session_id: str
    recent_exchange: tuple[HandoffMessage, ...]
    created_at: datetime
    expires_at: datetime


class ContinuityStore:
    """Persist bounded handoffs without making `/new` depend on an LLM."""

    def __init__(
        self,
        home: Path,
        *,
        ttl: timedelta = DEFAULT_TTL,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self.home = Path(home).expanduser().resolve()
        self.db_path = self.home / "continuity.db"
        self.ttl = ttl
        self.max_messages = max(1, int(max_messages))
        self.max_chars = max(1, int(max_chars))

    def _connect(self) -> sqlite3.Connection:
        self.home.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=1.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS handoffs (
                lane_key TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                target_session_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (lane_key, target_session_id)
            )
            """
        )
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        return connection

    def _bounded_exchange(
        self, messages: Iterable[Mapping[str, object]]
    ) -> tuple[HandoffMessage, ...]:
        conversational: list[HandoffMessage] = []
        for message in messages:
            role = str(message.get("role") or "").strip().lower()
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            if message.get("display_kind") in {
                "hidden",
                "model_switch",
                "async_delegation_complete",
                "auto_continue",
            }:
                continue
            cleaned = " ".join(content.replace("\x00", "").split()).strip()
            if cleaned:
                conversational.append(HandoffMessage(role=role, content=cleaned))

        remaining = self.max_chars
        selected_reversed: list[HandoffMessage] = []
        for message in reversed(conversational[-self.max_messages :]):
            if remaining <= 0:
                break
            content = message.content[:remaining]
            if content:
                selected_reversed.append(HandoffMessage(message.role, content))
                remaining -= len(content)
        return tuple(reversed(selected_reversed))

    def record_transition(
        self,
        *,
        lane_key: str,
        source_session_id: str,
        target_session_id: str,
        messages: Iterable[Mapping[str, object]],
        now: datetime | None = None,
    ) -> bool:
        """Save one source-backed handoff; return False on empty input/failure."""

        if not lane_key or not source_session_id or not target_session_id:
            return False
        exchange = self._bounded_exchange(messages)
        if not exchange:
            return False

        created_at = _as_utc(now or _utc_now())
        expires_at = created_at + self.ttl
        payload = json.dumps(
            [
                {"role": message.role, "content": message.content}
                for message in exchange
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO handoffs (
                        lane_key, source_session_id, target_session_id,
                        payload_json, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lane_key,
                        source_session_id,
                        target_session_id,
                        payload,
                        created_at.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
            return True
        except (OSError, sqlite3.Error):
            return False

    def get_handoff(
        self,
        *,
        lane_key: str,
        target_session_id: str,
        now: datetime | None = None,
    ) -> ContinuityHandoff | None:
        """Return the exact, unexpired handoff for a lane and target session."""

        if not lane_key or not target_session_id:
            return None
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT source_session_id, target_session_id, payload_json,
                           created_at, expires_at
                    FROM handoffs
                    WHERE lane_key = ? AND target_session_id = ?
                    """,
                    (lane_key, target_session_id),
                ).fetchone()
            if row is None:
                return None
            expires_at = datetime.fromisoformat(row[4])
            if _as_utc(now or _utc_now()) >= _as_utc(expires_at):
                return None
            payload = json.loads(row[2])
            exchange = tuple(
                HandoffMessage(role=item["role"], content=item["content"])
                for item in payload
                if isinstance(item, dict)
                and item.get("role") in {"user", "assistant"}
                and isinstance(item.get("content"), str)
            )
            if not exchange:
                return None
            return ContinuityHandoff(
                lane_key=lane_key,
                source_session_id=row[0],
                target_session_id=row[1],
                recent_exchange=exchange,
                created_at=_as_utc(datetime.fromisoformat(row[3])),
                expires_at=_as_utc(expires_at),
            )
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError, KeyError):
            return None

    def note_for_session(
        self,
        *,
        lane_key: str,
        target_session_id: str,
        now: datetime | None = None,
    ) -> str | None:
        """Render a bounded first-turn note, or None when no handoff applies."""

        handoff = self.get_handoff(
            lane_key=lane_key,
            target_session_id=target_session_id,
            now=now,
        )
        if handoff is None:
            return None
        lines = [
            "[Honey OS 连续性交接：以下是上一段真实对话的有界摘录，不是永久记忆。",
            f"来源 Session：{handoff.source_session_id}。",
            "仅在与用户当前消息相关时自然使用；不要主动复述，不要强迫继续旧话题，"
            "不要从中推断或升级身份、感情、关系与长期边界。]",
        ]
        labels = {"user": "用户", "assistant": "伴侣"}
        lines.extend(
            f"{labels[message.role]}：{message.content}"
            for message in handoff.recent_exchange
        )
        return "\n".join(lines)


def _active_h2os_home(chat_type: str) -> Path | None:
    """Resolve the active private-companion home, never generic Hermes state."""

    runtime_id = os.environ.get("H2OS_RUNTIME_ID", "").strip()
    raw_home = os.environ.get("H2OS_HOME", "").strip()
    if not runtime_id.startswith("h2os-companion-") or not raw_home:
        return None
    if str(chat_type or "").strip().lower() != "dm":
        return None
    return Path(raw_home).expanduser().resolve()


def record_reset_handoff(
    *,
    lane_key: str,
    chat_type: str,
    source_session_id: str,
    target_session_id: str,
    messages: Iterable[Mapping[str, object]],
    now: datetime | None = None,
) -> bool:
    """Best-effort gateway adapter for an explicit H2OS session reset."""

    home = _active_h2os_home(chat_type)
    if home is None:
        return False
    return ContinuityStore(home).record_transition(
        lane_key=lane_key,
        source_session_id=source_session_id,
        target_session_id=target_session_id,
        messages=messages,
        now=now,
    )


def note_for_reset_session(
    *,
    lane_key: str,
    chat_type: str,
    target_session_id: str,
    now: datetime | None = None,
) -> str | None:
    """Best-effort gateway adapter for the first turn after `/new`."""

    home = _active_h2os_home(chat_type)
    if home is None:
        return None
    return ContinuityStore(home).note_for_session(
        lane_key=lane_key,
        target_session_id=target_session_id,
        now=now,
    )
