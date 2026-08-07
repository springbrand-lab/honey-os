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
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_TTL = timedelta(days=7)
DEFAULT_MAX_MESSAGES = 8
DEFAULT_MAX_CHARS = 3000
STRUCTURED_MEMORY_KINDS = frozenset(
    {"open_loop", "temporary_state", "commitment", "episode"}
)
STRUCTURED_MEMORY_EVIDENCE = frozenset(
    {"user_stated", "assistant_committed", "conversation_event"}
)
STRUCTURED_MEMORY_EVIDENCE_BY_KIND = {
    "open_loop": frozenset({"user_stated", "conversation_event"}),
    "temporary_state": frozenset({"user_stated"}),
    "commitment": frozenset({"assistant_committed"}),
    "episode": frozenset({"user_stated", "conversation_event"}),
}
DEFAULT_TEMPORARY_STATE_TTL = timedelta(days=3)
DEFAULT_PENDING_ITEM_TTL = timedelta(days=30)
DEFAULT_MAX_MEMORY_ITEMS = 16
DEFAULT_MAX_MEMORY_CHARS = 4000


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


@dataclass(frozen=True)
class StructuredMemoryItem:
    id: str
    lane_key: str
    kind: str
    content: str
    status: str
    evidence: str
    source_session_id: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    source_message_ids: tuple[int, ...] = ()
    importance: str = "medium"
    created_by: str = "foreground"
    distillation_run_id: str | None = None


class StructuredMemoryStore:
    """Source-backed companion working memory in the H2OS local database."""

    def __init__(
        self,
        home: Path,
        *,
        temporary_state_ttl: timedelta = DEFAULT_TEMPORARY_STATE_TTL,
        pending_item_ttl: timedelta = DEFAULT_PENDING_ITEM_TTL,
        max_items: int = DEFAULT_MAX_MEMORY_ITEMS,
        max_chars: int = DEFAULT_MAX_MEMORY_CHARS,
    ) -> None:
        self.home = Path(home).expanduser().resolve()
        self.db_path = self.home / "continuity.db"
        self.temporary_state_ttl = temporary_state_ttl
        self.pending_item_ttl = pending_item_ttl
        self.max_items = max(1, int(max_items))
        self.max_chars = max(1, int(max_chars))

    def _connect(self) -> sqlite3.Connection:
        self.home.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS structured_memories (
                id TEXT PRIMARY KEY,
                lane_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                normalized_content TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            )
            """
        )
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(structured_memories)")
        }
        migrations = {
            "source_message_ids": "TEXT NOT NULL DEFAULT '[]'",
            "importance": "TEXT NOT NULL DEFAULT 'medium'",
            "created_by": "TEXT NOT NULL DEFAULT 'foreground'",
            "distillation_run_id": "TEXT",
        }
        for column, declaration in migrations.items():
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE structured_memories ADD COLUMN {column} {declaration}"
                )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_structured_memories_active
            ON structured_memories (lane_key, status, updated_at DESC)
            """
        )
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        return connection

    @staticmethod
    def _clean_content(content: str) -> str:
        if not isinstance(content, str):
            return ""
        return " ".join(content.replace("\x00", "").split()).strip()[:500]

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> StructuredMemoryItem:
        expires_at = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
        try:
            source_message_ids = tuple(
                int(value) for value in json.loads(row["source_message_ids"] or "[]")
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            source_message_ids = ()
        return StructuredMemoryItem(
            id=row["id"],
            lane_key=row["lane_key"],
            kind=row["kind"],
            content=row["content"],
            status=row["status"],
            evidence=row["evidence"],
            source_session_id=row["source_session_id"],
            created_at=_as_utc(datetime.fromisoformat(row["created_at"])),
            updated_at=_as_utc(datetime.fromisoformat(row["updated_at"])),
            expires_at=_as_utc(expires_at) if expires_at else None,
            source_message_ids=source_message_ids,
            importance=row["importance"],
            created_by=row["created_by"],
            distillation_run_id=row["distillation_run_id"],
        )

    def _expiry_for(
        self,
        *,
        kind: str,
        now: datetime,
        expires_in_days: int | None,
        explicit_expires_at: datetime | str | None,
    ) -> datetime | None:
        if explicit_expires_at is not None:
            if isinstance(explicit_expires_at, str):
                parsed = datetime.fromisoformat(
                    explicit_expires_at.strip().replace("Z", "+00:00")
                )
            elif isinstance(explicit_expires_at, datetime):
                parsed = explicit_expires_at
            else:
                raise ValueError("expires_at must be an ISO timestamp")
            parsed = _as_utc(parsed)
            if parsed <= now:
                raise ValueError("expires_at must be in the future")
            return parsed
        if kind == "episode" and expires_in_days is None:
            return None
        default_ttl = (
            self.temporary_state_ttl
            if kind == "temporary_state"
            else self.pending_item_ttl
        )
        if expires_in_days is None:
            return now + default_ttl
        maximum = 14 if kind == "temporary_state" else 365
        days = max(1, min(int(expires_in_days), maximum))
        return now + timedelta(days=days)

    @staticmethod
    def _purge_expired(connection: sqlite3.Connection, now: datetime) -> None:
        connection.execute(
            "DELETE FROM structured_memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now.isoformat(),),
        )

    def record(
        self,
        *,
        lane_key: str,
        kind: str,
        content: str,
        evidence: str,
        source_session_id: str,
        expires_in_days: int | None = None,
        expires_at: datetime | str | None = None,
        source_message_ids: Iterable[int] = (),
        importance: str = "medium",
        created_by: str = "foreground",
        distillation_run_id: str | None = None,
        now: datetime | None = None,
    ) -> StructuredMemoryItem | None:
        """Record one explicit/factual item; inferred and unknown lanes fail closed."""

        normalized_kind = str(kind or "").strip().lower()
        normalized_evidence = str(evidence or "").strip().lower()
        cleaned = self._clean_content(content)
        if (
            not lane_key
            or not source_session_id
            or normalized_kind not in STRUCTURED_MEMORY_KINDS
            or normalized_evidence not in STRUCTURED_MEMORY_EVIDENCE
            or normalized_evidence
            not in STRUCTURED_MEMORY_EVIDENCE_BY_KIND.get(normalized_kind, ())
            or not cleaned
        ):
            return None
        normalized_content = cleaned.casefold()
        timestamp = _as_utc(now or _utc_now())
        try:
            resolved_expires_at = self._expiry_for(
                kind=normalized_kind,
                now=timestamp,
                expires_in_days=expires_in_days,
                explicit_expires_at=expires_at,
            )
            normalized_source_ids = tuple(
                dict.fromkeys(int(value) for value in source_message_ids)
            )
            normalized_importance = str(importance or "medium").strip().lower()
            if normalized_importance not in {"low", "medium", "high"}:
                normalized_importance = "medium"
            normalized_created_by = str(created_by or "foreground").strip().lower()
            if normalized_created_by not in {"foreground", "background"}:
                return None
            with self._connect() as connection:
                self._purge_expired(connection, timestamp)
                existing = connection.execute(
                    """
                    SELECT * FROM structured_memories
                    WHERE lane_key = ? AND kind = ? AND normalized_content = ?
                          AND status = 'active'
                    LIMIT 1
                    """,
                    (lane_key, normalized_kind, normalized_content),
                ).fetchone()
                item_id = existing["id"] if existing is not None else uuid.uuid4().hex[:12]
                created_at = (
                    existing["created_at"] if existing is not None else timestamp.isoformat()
                )
                effective_source_ids = normalized_source_ids
                effective_importance = normalized_importance
                effective_created_by = normalized_created_by
                effective_run_id = distillation_run_id
                if existing is not None:
                    try:
                        previous_ids = tuple(
                            int(value)
                            for value in json.loads(existing["source_message_ids"] or "[]")
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        previous_ids = ()
                    effective_source_ids = tuple(
                        dict.fromkeys((*previous_ids, *normalized_source_ids))
                    )
                    importance_rank = {"low": 0, "medium": 1, "high": 2}
                    previous_importance = str(existing["importance"] or "medium")
                    if importance_rank.get(previous_importance, 1) > importance_rank[
                        normalized_importance
                    ]:
                        effective_importance = previous_importance
                    if existing["created_by"] == "foreground":
                        effective_created_by = "foreground"
                        effective_run_id = existing["distillation_run_id"]
                    previous_expiry = existing["expires_at"]
                    if previous_expiry is None:
                        resolved_expires_at = None
                    elif resolved_expires_at is not None:
                        resolved_expires_at = max(
                            _as_utc(datetime.fromisoformat(previous_expiry)),
                            resolved_expires_at,
                        )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO structured_memories (
                        id, lane_key, kind, content, normalized_content, status,
                        evidence, source_session_id, created_at, updated_at, expires_at,
                        source_message_ids, importance, created_by, distillation_run_id
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        lane_key,
                        normalized_kind,
                        cleaned,
                        normalized_content,
                        normalized_evidence,
                        source_session_id,
                        created_at,
                        timestamp.isoformat(),
                        resolved_expires_at.isoformat() if resolved_expires_at else None,
                        json.dumps(effective_source_ids, separators=(",", ":")),
                        effective_importance,
                        effective_created_by,
                        effective_run_id,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM structured_memories WHERE id = ?", (item_id,)
                ).fetchone()
            return self._row_to_item(row) if row is not None else None
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return None

    def list_active(
        self, *, lane_key: str, now: datetime | None = None
    ) -> tuple[StructuredMemoryItem, ...]:
        if not lane_key:
            return ()
        timestamp = _as_utc(now or _utc_now())
        try:
            with self._connect() as connection:
                self._purge_expired(connection, timestamp)
                rows = connection.execute(
                    """
                    SELECT * FROM structured_memories
                    WHERE lane_key = ? AND status = 'active'
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (lane_key, self.max_items),
                ).fetchall()
            return tuple(self._row_to_item(row) for row in rows)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return ()

    def prune_background(self, *, lane_key: str, max_items: int = 50) -> int:
        """Remove oldest low-priority automatic items, never foreground ones."""

        if not lane_key:
            return 0
        limit = max(1, int(max_items))
        try:
            with self._connect() as connection:
                count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM structured_memories
                        WHERE lane_key = ? AND status = 'active'
                              AND created_by = 'background'
                        """,
                        (lane_key,),
                    ).fetchone()[0]
                )
                excess = max(0, count - limit)
                if excess == 0:
                    return 0
                rows = connection.execute(
                    """
                    SELECT id FROM structured_memories
                    WHERE lane_key = ? AND status = 'active'
                          AND created_by = 'background'
                    ORDER BY
                        CASE importance WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                        updated_at ASC
                    LIMIT ?
                    """,
                    (lane_key, excess),
                ).fetchall()
                ids = [row["id"] for row in rows]
                connection.executemany(
                    "DELETE FROM structured_memories WHERE id = ?",
                    ((item_id,) for item_id in ids),
                )
            return len(ids)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return 0

    def change_status(
        self,
        *,
        lane_key: str,
        item_id: str,
        action: str,
        now: datetime | None = None,
    ) -> bool:
        status = {"resolve": "resolved", "forget": "forgotten"}.get(
            str(action or "").strip().lower()
        )
        if not lane_key or not item_id or status is None:
            return False
        timestamp = _as_utc(now or _utc_now())
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE structured_memories
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND lane_key = ? AND status = 'active'
                    """,
                    (status, timestamp.isoformat(), item_id, lane_key),
                )
            return cursor.rowcount == 1
        except (OSError, sqlite3.Error):
            return False

    def update_content(
        self,
        *,
        lane_key: str,
        item_id: str,
        content: str,
        expires_at: datetime | str | None = None,
        source_message_ids: Iterable[int] = (),
        distillation_run_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        cleaned = self._clean_content(content)
        if not lane_key or not item_id or not cleaned:
            return False
        timestamp = _as_utc(now or _utc_now())
        try:
            with self._connect() as connection:
                existing = connection.execute(
                    """
                    SELECT kind, expires_at, source_message_ids, created_by,
                           distillation_run_id
                    FROM structured_memories
                    WHERE id = ? AND lane_key = ? AND status = 'active'
                    """,
                    (item_id, lane_key),
                ).fetchone()
                if existing is None:
                    return False
                resolved_expires_at = existing["expires_at"]
                if expires_at is not None:
                    parsed_expiry = self._expiry_for(
                        kind=existing["kind"],
                        now=timestamp,
                        expires_in_days=None,
                        explicit_expires_at=expires_at,
                    )
                    resolved_expires_at = (
                        parsed_expiry.isoformat() if parsed_expiry is not None else None
                    )
                try:
                    previous_source_ids = tuple(
                        int(value)
                        for value in json.loads(existing["source_message_ids"] or "[]")
                    )
                    new_source_ids = tuple(int(value) for value in source_message_ids)
                except (TypeError, ValueError, json.JSONDecodeError):
                    return False
                merged_source_ids = tuple(
                    dict.fromkeys((*previous_source_ids, *new_source_ids))
                )
                effective_run_id = existing["distillation_run_id"]
                if existing["created_by"] == "background" and distillation_run_id:
                    effective_run_id = distillation_run_id
                cursor = connection.execute(
                    """
                    UPDATE structured_memories
                    SET content = ?, normalized_content = ?, updated_at = ?, expires_at = ?,
                        source_message_ids = ?, distillation_run_id = ?
                    WHERE id = ? AND lane_key = ? AND status = 'active'
                    """,
                    (
                        cleaned,
                        cleaned.casefold(),
                        timestamp.isoformat(),
                        resolved_expires_at,
                        json.dumps(merged_source_ids, separators=(",", ":")),
                        effective_run_id,
                        item_id,
                        lane_key,
                    ),
                )
            return cursor.rowcount == 1
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return False

    def context_for_lane(
        self, *, lane_key: str, now: datetime | None = None
    ) -> str | None:
        items = self.list_active(lane_key=lane_key, now=now)
        if not items:
            return None
        labels = {
            "open_loop": "未聊完/待继续",
            "temporary_state": "近期临时状态",
            "commitment": "伴侣已做承诺",
            "episode": "真实共同经历",
        }
        lines = [
            "[HoneyOS 关系连续性记忆：以下条目来自本地记录，仅在与当前消息相关时自然使用。",
            "不得据此推断或升级用户的身份、感情、关系、依赖、诊断或长期边界。",
            "条目 ID 可用于完成、纠正或忘记记忆。]",
        ]
        remaining = self.max_chars
        for item in items:
            line = f"- [{item.id}] {labels[item.kind]}：{item.content}"
            if len(line) > remaining:
                break
            lines.append(line)
            remaining -= len(line)
        return "\n".join(lines) if len(lines) > 3 else None


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
            "[HoneyOS 连续性交接：以下是上一段真实对话的有界摘录，不是永久记忆。",
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


def structured_memory_note(
    *,
    lane_key: str,
    chat_type: str,
    now: datetime | None = None,
) -> str | None:
    """Best-effort per-turn adapter for private HoneyOS working memory."""

    home = _active_h2os_home(chat_type)
    if home is None:
        return None
    return StructuredMemoryStore(home).context_for_lane(lane_key=lane_key, now=now)
