"""Durable local Topic Pool state for the HoneyOS private companion.

The pool is deliberately separate from relationship memory.  It stores short-
lived, source-backed conversation seeds plus the deterministic policy state
needed to decide whether a proactive message may be attempted.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "source",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return _as_utc(parsed)


def normalize_source_url(value: str) -> str:
    """Return a stable public URL identity without tracking or fragments."""

    raw = str(value or "").strip()
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("source_url must be an absolute http(s) URL")
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
            continue
        query.append((key, item))
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def _fingerprint(normalized_url: str, title: str) -> str:
    payload = f"{normalized_url}\n{' '.join(str(title).lower().split())}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TopicCandidate:
    source_title: str
    source_url: str
    source_name: str
    summary: str
    hook: str
    category: str
    observed_at: datetime
    expires_at: datetime
    source_id: str | None = None
    language: str = "zh"
    published_at: datetime | None = None
    score: float = 0.0
    selection_reason: str = ""


@dataclass(frozen=True)
class TopicItem:
    id: str
    source_id: str | None
    source_title: str
    source_url: str
    source_name: str
    summary: str
    hook: str
    category: str
    language: str
    observed_at: datetime
    published_at: datetime | None
    expires_at: datetime
    status: str
    score: float
    selection_reason: str
    reserved_at: datetime | None = None
    consumed_at: datetime | None = None
    delivery_id: str | None = None


@dataclass(frozen=True)
class ProactivePreferences:
    consent_asked: bool = False
    consented: bool = False
    paused: bool = False
    daily_limit: int = 3
    minimum_interval_hours: int = 3
    idle_hours: int = 2
    quiet_start: str = "23:00"
    quiet_end: str = "09:00"
    route_mode: str = "recent"
    fixed_platform: str | None = None
    focus_categories: tuple[str, ...] = ()
    blocked_categories: tuple[str, ...] = ()
    paused_until: datetime | None = None


@dataclass(frozen=True)
class ChannelActivity:
    platform: str
    source_json: str
    last_user_message_at: datetime

    @property
    def source(self) -> dict[str, Any]:
        try:
            value = json.loads(self.source_json)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class DeliveryReservation:
    delivery_id: str
    item: TopicItem
    channel: ChannelActivity
    reserved_at: datetime


class TopicPoolStore:
    """SQLite-backed Topic Pool and proactive-delivery policy."""

    def __init__(
        self,
        home: Path,
        *,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.home = Path(home).expanduser().resolve()
        self.path = self.home / "state" / "topic_pool.db"
        self.now_fn = now_fn
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS topic_pool_items (
                    id TEXT PRIMARY KEY,
                    source_id TEXT,
                    source_key TEXT,
                    source_title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    hook TEXT NOT NULL,
                    category TEXT NOT NULL,
                    language TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    published_at TEXT,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    selection_reason TEXT NOT NULL DEFAULT '',
                    fingerprint TEXT NOT NULL,
                    reserved_at TEXT,
                    consumed_at TEXT,
                    delivery_id TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_pool_fingerprint
                    ON topic_pool_items(fingerprint);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_pool_url
                    ON topic_pool_items(normalized_url);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_pool_source_key
                    ON topic_pool_items(source_key) WHERE source_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_topic_pool_open
                    ON topic_pool_items(status, expires_at, score);

                CREATE TABLE IF NOT EXISTS proactive_preferences (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    consent_asked INTEGER NOT NULL DEFAULT 0,
                    consented INTEGER NOT NULL DEFAULT 0,
                    paused INTEGER NOT NULL DEFAULT 0,
                    daily_limit INTEGER NOT NULL DEFAULT 3,
                    minimum_interval_hours INTEGER NOT NULL DEFAULT 3,
                    idle_hours INTEGER NOT NULL DEFAULT 2,
                    quiet_start TEXT NOT NULL DEFAULT '23:00',
                    quiet_end TEXT NOT NULL DEFAULT '09:00',
                    route_mode TEXT NOT NULL DEFAULT 'recent',
                    fixed_platform TEXT,
                    focus_categories TEXT NOT NULL DEFAULT '[]',
                    blocked_categories TEXT NOT NULL DEFAULT '[]',
                    paused_until TEXT
                );
                INSERT OR IGNORE INTO proactive_preferences(id) VALUES (1);

                CREATE TABLE IF NOT EXISTS channel_activity (
                    platform TEXT PRIMARY KEY,
                    source_json TEXT NOT NULL,
                    last_user_message_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proactive_deliveries (
                    id TEXT PRIMARY KEY,
                    topic_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(topic_id) REFERENCES topic_pool_items(id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_topic_delivery
                    ON proactive_deliveries(topic_id)
                    WHERE status IN ('reserved', 'sent');
                CREATE INDEX IF NOT EXISTS idx_delivery_sent_at
                    ON proactive_deliveries(status, sent_at);

                CREATE TABLE IF NOT EXISTS topic_pool_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _topic_from_row(row: sqlite3.Row) -> TopicItem:
        return TopicItem(
            id=str(row["id"]),
            source_id=row["source_id"],
            source_title=str(row["source_title"]),
            source_url=str(row["source_url"]),
            source_name=str(row["source_name"]),
            summary=str(row["summary"]),
            hook=str(row["hook"]),
            category=str(row["category"]),
            language=str(row["language"]),
            observed_at=_parse_datetime(row["observed_at"]) or _utc_now(),
            published_at=_parse_datetime(row["published_at"]),
            expires_at=_parse_datetime(row["expires_at"]) or _utc_now(),
            status=str(row["status"]),
            score=float(row["score"] or 0),
            selection_reason=str(row["selection_reason"] or ""),
            reserved_at=_parse_datetime(row["reserved_at"]),
            consumed_at=_parse_datetime(row["consumed_at"]),
            delivery_id=row["delivery_id"],
        )

    @staticmethod
    def _channel_from_row(row: sqlite3.Row) -> ChannelActivity:
        return ChannelActivity(
            platform=str(row["platform"]),
            source_json=str(row["source_json"]),
            last_user_message_at=(
                _parse_datetime(row["last_user_message_at"]) or _utc_now()
            ),
        )

    def _expire(self, connection: sqlite3.Connection, now: datetime) -> None:
        connection.execute(
            """
            UPDATE topic_pool_items
               SET status = 'expired', reserved_at = NULL, delivery_id = NULL
             WHERE status IN ('open', 'reserved') AND expires_at <= ?
            """,
            (_iso(now),),
        )

    def add_candidates(
        self, candidates: Iterable[TopicCandidate]
    ) -> tuple[TopicItem, ...]:
        inserted_ids: list[str] = []
        with self._connect() as connection:
            for candidate in candidates:
                title = str(candidate.source_title or "").strip()
                summary = str(candidate.summary or "").strip()
                hook = str(candidate.hook or "").strip()
                source_name = str(candidate.source_name or "").strip()
                if not title or not summary or not hook or not source_name:
                    continue
                try:
                    normalized_url = normalize_source_url(candidate.source_url)
                except ValueError:
                    continue
                topic_id = str(uuid.uuid4())
                source_id = str(candidate.source_id).strip() if candidate.source_id else None
                source_key = (
                    f"{source_name.lower()}:{source_id}" if source_id else None
                )
                try:
                    connection.execute(
                        """
                        INSERT INTO topic_pool_items(
                            id, source_id, source_key, source_title, source_url,
                            normalized_url, source_name, summary, hook, category,
                            language, observed_at, published_at, expires_at,
                            status, score, selection_reason, fingerprint
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                  'open', ?, ?, ?)
                        """,
                        (
                            topic_id,
                            source_id,
                            source_key,
                            title,
                            normalized_url,
                            normalized_url,
                            source_name,
                            summary,
                            hook,
                            str(candidate.category or "general").strip()[:80],
                            str(candidate.language or "zh").strip()[:16],
                            _iso(candidate.observed_at),
                            _iso(candidate.published_at) if candidate.published_at else None,
                            _iso(candidate.expires_at),
                            max(0.0, min(float(candidate.score), 1.0)),
                            str(candidate.selection_reason or "").strip()[:1000],
                            _fingerprint(normalized_url, title),
                        ),
                    )
                except sqlite3.IntegrityError:
                    continue
                inserted_ids.append(topic_id)
        return tuple(item for item_id in inserted_ids if (item := self.get_topic(item_id)))

    def get_topic(self, topic_id: str) -> TopicItem | None:
        now = self.now_fn()
        with self._connect() as connection:
            self._expire(connection, now)
            row = connection.execute(
                "SELECT * FROM topic_pool_items WHERE id = ?", (str(topic_id),)
            ).fetchone()
        return self._topic_from_row(row) if row else None

    def list_open_topics(self, *, limit: int = 50) -> tuple[TopicItem, ...]:
        now = self.now_fn()
        safe_limit = max(1, min(int(limit), 200))
        with self._connect() as connection:
            self._expire(connection, now)
            rows = connection.execute(
                """
                SELECT * FROM topic_pool_items
                 WHERE status = 'open'
                 ORDER BY score DESC, observed_at DESC
                 LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return tuple(self._topic_from_row(row) for row in rows)

    def dismiss_topic(self, topic_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE topic_pool_items
                   SET status = 'dismissed', reserved_at = NULL, delivery_id = NULL
                 WHERE id = ? AND status = 'open'
                """,
                (str(topic_id),),
            )
        return cursor.rowcount == 1

    def preferences(self) -> ProactivePreferences:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM proactive_preferences WHERE id = 1"
            ).fetchone()
        if not row:
            return ProactivePreferences()

        def categories(key: str) -> tuple[str, ...]:
            try:
                raw = json.loads(row[key])
            except (TypeError, ValueError):
                return ()
            if not isinstance(raw, list):
                return ()
            return tuple(str(item) for item in raw if str(item).strip())

        return ProactivePreferences(
            consent_asked=bool(row["consent_asked"]),
            consented=bool(row["consented"]),
            paused=bool(row["paused"]),
            daily_limit=int(row["daily_limit"]),
            minimum_interval_hours=int(row["minimum_interval_hours"]),
            idle_hours=int(row["idle_hours"]),
            quiet_start=str(row["quiet_start"]),
            quiet_end=str(row["quiet_end"]),
            route_mode=str(row["route_mode"]),
            fixed_platform=row["fixed_platform"],
            focus_categories=categories("focus_categories"),
            blocked_categories=categories("blocked_categories"),
            paused_until=_parse_datetime(row["paused_until"]),
        )

    @staticmethod
    def _validate_hhmm(value: str) -> str:
        raw = str(value or "").strip()
        try:
            datetime.strptime(raw, "%H:%M")
        except ValueError as exc:
            raise ValueError("quiet time must use HH:MM") from exc
        return raw

    def update_preferences(self, **changes: Any) -> ProactivePreferences:
        allowed = {
            "consent_asked",
            "consented",
            "paused",
            "daily_limit",
            "minimum_interval_hours",
            "idle_hours",
            "quiet_start",
            "quiet_end",
            "route_mode",
            "fixed_platform",
            "focus_categories",
            "blocked_categories",
            "paused_until",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported preference fields: {sorted(unknown)}")
        normalized: dict[str, Any] = {}
        for key, value in changes.items():
            if key in {"consent_asked", "consented", "paused"}:
                normalized[key] = int(bool(value))
            elif key == "daily_limit":
                parsed = int(value)
                if not 0 <= parsed <= 3:
                    raise ValueError("daily_limit must be between 0 and 3")
                normalized[key] = parsed
            elif key in {"minimum_interval_hours", "idle_hours"}:
                parsed = int(value)
                if not 0 <= parsed <= 24:
                    raise ValueError(f"{key} must be between 0 and 24")
                normalized[key] = parsed
            elif key in {"quiet_start", "quiet_end"}:
                normalized[key] = self._validate_hhmm(str(value))
            elif key == "route_mode":
                route = str(value).strip().lower()
                if route not in {"recent", "fixed"}:
                    raise ValueError("route_mode must be recent or fixed")
                normalized[key] = route
            elif key == "fixed_platform":
                normalized[key] = str(value).strip().lower() or None
            elif key in {"focus_categories", "blocked_categories"}:
                items = []
                for item in value or ():
                    clean = " ".join(str(item).split())[:80]
                    if clean and clean not in items:
                        items.append(clean)
                normalized[key] = json.dumps(items[:20], ensure_ascii=False)
            elif key == "paused_until":
                normalized[key] = _iso(value) if isinstance(value, datetime) else None
        if normalized:
            assignments = ", ".join(f"{key} = ?" for key in normalized)
            with self._connect() as connection:
                connection.execute(
                    f"UPDATE proactive_preferences SET {assignments} WHERE id = 1",
                    tuple(normalized.values()),
                )
        return self.preferences()

    def record_channel_activity(
        self,
        source: dict[str, Any],
        *,
        at: datetime | None = None,
    ) -> ChannelActivity:
        if not isinstance(source, dict):
            raise ValueError("source must be a mapping")
        platform = str(source.get("platform") or "").strip().lower()
        chat_id = str(source.get("chat_id") or "").strip()
        if not platform or not chat_id:
            raise ValueError("source requires platform and chat_id")
        payload = {
            key: value
            for key, value in source.items()
            if key
            in {
                "platform",
                "chat_id",
                "chat_name",
                "chat_type",
                "user_id",
                "user_name",
                "thread_id",
                "user_id_alt",
                "chat_id_alt",
                "scope_id",
                "parent_chat_id",
                "profile",
            }
            and value is not None
        }
        timestamp = at or self.now_fn()
        source_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO channel_activity(platform, source_json, last_user_message_at)
                VALUES (?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    source_json = excluded.source_json,
                    last_user_message_at = excluded.last_user_message_at
                WHERE channel_activity.last_user_message_at <= excluded.last_user_message_at
                """,
                (platform, source_json, _iso(timestamp)),
            )
        return ChannelActivity(platform, source_json, _as_utc(timestamp))

    def latest_channel(self, *, platform: str | None = None) -> ChannelActivity | None:
        with self._connect() as connection:
            if platform:
                row = connection.execute(
                    """
                    SELECT * FROM channel_activity
                     WHERE platform = ? ORDER BY last_user_message_at DESC LIMIT 1
                    """,
                    (str(platform).strip().lower(),),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM channel_activity ORDER BY last_user_message_at DESC LIMIT 1"
                ).fetchone()
        return self._channel_from_row(row) if row else None

    @staticmethod
    def _is_quiet(now: datetime, start: str, end: str) -> bool:
        start_time = time.fromisoformat(start)
        end_time = time.fromisoformat(end)
        current = now.timetz().replace(tzinfo=None)
        if start_time == end_time:
            return False
        if start_time < end_time:
            return start_time <= current < end_time
        return current >= start_time or current < end_time

    def reserve_due_delivery(
        self, *, now: datetime | None = None
    ) -> DeliveryReservation | None:
        local_now = now or self.now_fn()
        utc_now = _as_utc(local_now)
        preferences = self.preferences()
        if not preferences.consented or preferences.paused or preferences.daily_limit <= 0:
            return None
        if preferences.paused_until and preferences.paused_until > utc_now:
            return None
        if self._is_quiet(local_now, preferences.quiet_start, preferences.quiet_end):
            return None
        channel = self.latest_channel(
            platform=preferences.fixed_platform
            if preferences.route_mode == "fixed"
            else None
        )
        if channel is None:
            return None
        if utc_now - channel.last_user_message_at < timedelta(hours=preferences.idle_hours):
            return None

        delivery_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._expire(connection, utc_now)
            sent_rows = connection.execute(
                """
                SELECT sent_at FROM proactive_deliveries
                 WHERE status = 'sent' AND sent_at IS NOT NULL
                 ORDER BY sent_at DESC
                """
            ).fetchall()
            sent_times = [
                parsed
                for row in sent_rows
                if (parsed := _parse_datetime(row["sent_at"])) is not None
            ]
            local_date = local_now.date()
            sent_today = sum(
                1 for sent in sent_times if sent.astimezone(local_now.tzinfo).date() == local_date
            )
            if sent_today >= preferences.daily_limit:
                connection.rollback()
                return None
            if sent_times and utc_now - max(sent_times) < timedelta(
                hours=preferences.minimum_interval_hours
            ):
                connection.rollback()
                return None
            row = connection.execute(
                """
                SELECT * FROM topic_pool_items
                 WHERE status = 'open' AND expires_at > ?
                 ORDER BY score DESC, observed_at ASC
                 LIMIT 1
                """,
                (_iso(utc_now),),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            topic_id = str(row["id"])
            cursor = connection.execute(
                """
                UPDATE topic_pool_items
                   SET status = 'reserved', reserved_at = ?, delivery_id = ?
                 WHERE id = ? AND status = 'open'
                """,
                (_iso(utc_now), delivery_id, topic_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            try:
                connection.execute(
                    """
                    INSERT INTO proactive_deliveries(
                        id, topic_id, platform, source_json, status, created_at
                    ) VALUES (?, ?, ?, ?, 'reserved', ?)
                    """,
                    (
                        delivery_id,
                        topic_id,
                        channel.platform,
                        channel.source_json,
                        _iso(utc_now),
                    ),
                )
            except sqlite3.IntegrityError:
                connection.rollback()
                return None
            reserved_row = connection.execute(
                "SELECT * FROM topic_pool_items WHERE id = ?", (topic_id,)
            ).fetchone()
            connection.commit()
        return DeliveryReservation(
            delivery_id=delivery_id,
            item=self._topic_from_row(reserved_row),
            channel=channel,
            reserved_at=utc_now,
        )

    def finish_delivery(
        self,
        delivery_id: str,
        *,
        success: bool,
        error: str = "",
        at: datetime | None = None,
    ) -> bool:
        timestamp = at or self.now_fn()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM proactive_deliveries WHERE id = ? AND status = 'reserved'",
                (str(delivery_id),),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            topic_id = str(row["topic_id"])
            if success:
                connection.execute(
                    """
                    UPDATE proactive_deliveries
                       SET status = 'sent', sent_at = ?, error = '' WHERE id = ?
                    """,
                    (_iso(timestamp), str(delivery_id)),
                )
                connection.execute(
                    """
                    UPDATE topic_pool_items
                       SET status = 'consumed', consumed_at = ?, reserved_at = NULL
                     WHERE id = ? AND delivery_id = ?
                    """,
                    (_iso(timestamp), topic_id, str(delivery_id)),
                )
            else:
                connection.execute(
                    """
                    UPDATE proactive_deliveries
                       SET status = 'failed', error = ? WHERE id = ?
                    """,
                    (str(error or "delivery failed")[:1000], str(delivery_id)),
                )
                connection.execute(
                    """
                    UPDATE topic_pool_items
                       SET status = 'open', reserved_at = NULL, delivery_id = NULL
                     WHERE id = ? AND delivery_id = ?
                    """,
                    (topic_id, str(delivery_id)),
                )
            connection.commit()
        return True

    def collection_due(self, *, hours: int = 6, now: datetime | None = None) -> bool:
        current = _as_utc(now or self.now_fn())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM topic_pool_meta WHERE key = 'last_collection_at'"
            ).fetchone()
        last = _parse_datetime(row["value"]) if row else None
        return last is None or current - last >= timedelta(hours=max(1, int(hours)))

    def mark_collection(self, *, at: datetime | None = None) -> None:
        timestamp = _iso(at or self.now_fn())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO topic_pool_meta(key, value) VALUES ('last_collection_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (timestamp,),
            )

    def preferences_payload(self) -> dict[str, Any]:
        payload = asdict(self.preferences())
        if payload["paused_until"] is not None:
            payload["paused_until"] = payload["paused_until"].isoformat()
        return payload

