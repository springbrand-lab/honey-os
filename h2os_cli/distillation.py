"""Asynchronous, source-backed memory distillation for HoneyOS.

The gateway only asks whether a persisted transcript is due for review and
runs the returned coroutine in its existing background-task pool.  Trigger
accounting, retries, idempotency, strict parsing, evidence validation, and
SQLite writes stay behind :class:`MemoryDistiller`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping

from h2os_cli.continuity import StructuredMemoryItem, StructuredMemoryStore


Extractor = Callable[
    ["DistillationJob", tuple[StructuredMemoryItem, ...], Mapping[str, Any]],
    Awaitable[str],
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class DistillationSettings:
    enabled: bool = True
    trigger_messages: int = 20
    min_tail_messages: int = 6
    max_batch_messages: int = 40
    max_operations: int = 6
    max_attempts: int = 3
    max_daily_runs: int = 12


@dataclass(frozen=True)
class DistillationJob:
    run_id: str
    lane_key: str
    session_id: str
    reason: str
    messages: tuple[dict[str, Any], ...]
    source_start_id: int
    source_end_id: int
    source_hash: str
    now: datetime
    max_operations: int


@dataclass(frozen=True)
class DistillationResult:
    run_id: str
    status: str
    applied: int = 0
    rejected: int = 0
    error: str = ""


def load_distillation_settings(home: Path) -> DistillationSettings:
    """Load product settings without making the gateway understand their shape."""

    try:
        import yaml

        config = yaml.safe_load(
            (Path(home).expanduser().resolve() / "config.yaml").read_text(encoding="utf-8")
        ) or {}
        memory = config.get("memory", {}) if isinstance(config, dict) else {}
        raw = memory.get("distillation", {}) if isinstance(memory, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}

    def positive_int(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return DistillationSettings(
        enabled=bool(raw.get("enabled", True)),
        trigger_messages=positive_int("trigger_messages", 20),
        min_tail_messages=positive_int("min_tail_messages", 6),
        max_batch_messages=positive_int("max_batch_messages", 40),
        max_operations=positive_int("max_operations", 6),
        max_attempts=positive_int("max_attempts", 3),
        max_daily_runs=positive_int("max_daily_runs", 12),
    )


def _main_runtime_from_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly()
    except Exception:
        return {}
    model = config.get("model", {}) if isinstance(config, dict) else {}
    if not isinstance(model, dict):
        return {}
    result = {
        "provider": model.get("provider"),
        "model": model.get("default") or model.get("model"),
        "base_url": model.get("base_url"),
        "api_mode": model.get("api_mode"),
    }
    return {key: value for key, value in result.items() if isinstance(value, str) and value}


def _memory_distillation_task_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly()
    except Exception:
        return {}
    auxiliary = config.get("auxiliary", {}) if isinstance(config, dict) else {}
    raw = auxiliary.get("memory_distillation", {}) if isinstance(auxiliary, dict) else {}
    return dict(raw) if isinstance(raw, dict) else {}


async def extract_with_auxiliary_model(
    job: DistillationJob,
    active_items: tuple[StructuredMemoryItem, ...],
    main_runtime: Mapping[str, Any] | None,
    *,
    task_config: Mapping[str, Any] | None = None,
) -> str:
    """Call the configured auxiliary model without silently changing providers."""

    from agent.auxiliary_client import async_call_llm

    runtime = dict(main_runtime or _main_runtime_from_config())
    config = dict(task_config or _memory_distillation_task_config())
    configured_provider = str(config.get("provider") or "auto").strip().lower()
    configured_model = str(config.get("model") or "auto").strip()

    call_overrides: dict[str, Any] = {}
    if configured_provider in {"", "auto"}:
        provider = str(runtime.get("provider") or "").strip()
        model = (
            configured_model
            if configured_model.lower() not in {"", "auto"}
            else str(runtime.get("model") or "").strip()
        )
        if not provider or not model:
            raise RuntimeError("main model runtime is unavailable for memory distillation")
        call_overrides.update(provider=provider, model=model)
        for key in ("base_url", "api_mode"):
            value = runtime.get(key)
            if isinstance(value, str) and value.strip():
                call_overrides[key] = value.strip()

    active_payload = [
        {"id": item.id, "kind": item.kind, "content": item.content}
        for item in active_items
    ]
    transcript = [
        {
            "message_id": int(message["_row_id"]),
            "role": message["role"],
            "content": message["content"],
        }
        for message in job.messages
    ]
    try:
        from hermes_time import get_timezone

        local_now = job.now.astimezone(get_timezone())
    except Exception:
        local_now = job.now
    system_prompt = f"""You distill HoneyOS companion conversations into strict JSON.
Current local time: {local_now.isoformat()}
Return one object with an operations array, maximum {job.max_operations} operations.
Allowed kinds: open_loop, temporary_state, commitment, episode.
Allowed actions: record, resolve, update. Never output forget.
Every operation must cite one or more evidence_message_ids from the supplied transcript.
Evidence must be user_stated for temporary_state, assistant_committed for commitment,
and user_stated or conversation_event for open_loop/episode. Never infer love,
dependency, diagnosis, identity, relationship status, personality, or boundaries.
For temporary states, infer expires_at from explicit time semantics: today, this week,
a named date, or an event deadline. Use an ISO-8601 timestamp. Omit expires_at only
when the user supplied no time clue; the code then applies a conservative fallback.
Resolve or update only IDs present in active_memories. Usually output 0-3 operations.
Do not include prose or markdown."""
    response = await async_call_llm(
        task="memory_distillation",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "reason": job.reason,
                        "active_memories": active_payload,
                        "transcript": transcript,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
        temperature=0,
        max_tokens=1400,
        main_runtime=runtime,
        **call_overrides,
    )
    return str(response.choices[0].message.content or "")


class MemoryDistiller:
    """Plan, execute, validate, and checkpoint one source-backed review."""

    def __init__(
        self,
        home: Path,
        *,
        settings: DistillationSettings | None = None,
        extractor: Extractor | None = None,
    ) -> None:
        self.home = Path(home).expanduser().resolve()
        self.db_path = self.home / "continuity.db"
        self.settings = settings or load_distillation_settings(self.home)
        self.extractor = extractor or extract_with_auxiliary_model
        self.memories = StructuredMemoryStore(self.home)

    def _connect(self) -> sqlite3.Connection:
        self.home.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS distillation_state (
                lane_key TEXT NOT NULL,
                session_id TEXT NOT NULL,
                last_source_row_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (lane_key, session_id)
            );
            CREATE TABLE IF NOT EXISTS distillation_runs (
                id TEXT PRIMARY KEY,
                lane_key TEXT NOT NULL,
                session_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                source_start_id INTEGER NOT NULL,
                source_end_id INTEGER NOT NULL,
                source_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            """
        )
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        return connection

    @staticmethod
    def _conversational_messages(
        messages: Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        selected = []
        for message in messages:
            role = str(message.get("role") or "").strip().lower()
            content = message.get("content")
            row_id = message.get("_row_id")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                continue
            if not isinstance(row_id, int) or not content.strip():
                continue
            if message.get("display_kind") in {"hidden", "auto_continue"}:
                continue
            selected.append(
                {"_row_id": row_id, "role": role, "content": content.strip()[:6000]}
            )
        return tuple(selected)

    @staticmethod
    def _source_hash(session_id: str, messages: tuple[dict[str, Any], ...]) -> str:
        payload = json.dumps(
            [(message["_row_id"], message["role"], message["content"]) for message in messages],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(f"{session_id}\n{payload}".encode("utf-8")).hexdigest()

    def _prepare(
        self,
        *,
        lane_key: str,
        session_id: str,
        messages: Iterable[Mapping[str, Any]],
        reason: str,
        now: datetime,
    ) -> DistillationJob | None:
        if not self.settings.enabled or reason not in {"periodic", "new"}:
            return None
        conversational = self._conversational_messages(messages)
        if not conversational:
            return None
        with self._connect() as connection:
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            daily_runs = connection.execute(
                """
                SELECT COALESCE(SUM(attempts), 0) FROM distillation_runs
                WHERE lane_key = ? AND created_at >= ?
                """,
                (lane_key, day_start.isoformat()),
            ).fetchone()[0]
            if int(daily_runs) >= self.settings.max_daily_runs:
                return None
            state = connection.execute(
                """
                SELECT last_source_row_id FROM distillation_state
                WHERE lane_key = ? AND session_id = ?
                """,
                (lane_key, session_id),
            ).fetchone()
            cursor = int(state[0]) if state is not None else 0
            pending = tuple(message for message in conversational if message["_row_id"] > cursor)
            minimum = (
                self.settings.trigger_messages
                if reason == "periodic"
                else self.settings.min_tail_messages
            )
            if len(pending) < minimum:
                return None
            batch_size = (
                self.settings.trigger_messages
                if reason == "periodic"
                else self.settings.max_batch_messages
            )
            batch = pending[:batch_size]
            source_hash = self._source_hash(session_id, batch)
            existing = connection.execute(
                "SELECT * FROM distillation_runs WHERE source_hash = ?",
                (source_hash,),
            ).fetchone()
            if existing is not None:
                if existing["status"] in {"completed", "pending", "running"}:
                    return None
                if int(existing["attempts"]) >= self.settings.max_attempts:
                    return None
                run_id = existing["id"]
            else:
                run_id = uuid.uuid4().hex
                connection.execute(
                    """
                    INSERT INTO distillation_runs (
                        id, lane_key, session_id, reason, source_start_id,
                        source_end_id, source_hash, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        run_id,
                        lane_key,
                        session_id,
                        reason,
                        batch[0]["_row_id"],
                        batch[-1]["_row_id"],
                        source_hash,
                        now.isoformat(),
                    ),
                )
        return DistillationJob(
            run_id=run_id,
            lane_key=lane_key,
            session_id=session_id,
            reason=reason,
            messages=batch,
            source_start_id=batch[0]["_row_id"],
            source_end_id=batch[-1]["_row_id"],
            source_hash=source_hash,
            now=now,
            max_operations=self.settings.max_operations,
        )

    @staticmethod
    def _parse_operations(raw: str, maximum: int) -> tuple[dict[str, Any], ...]:
        cleaned = str(raw or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("distillation response did not contain a JSON object")
        payload = json.loads(cleaned[start : end + 1])
        operations = payload.get("operations") if isinstance(payload, dict) else None
        if not isinstance(operations, list):
            raise ValueError("distillation response did not contain operations")
        return tuple(operation for operation in operations[:maximum] if isinstance(operation, dict))

    def _apply_operations(
        self, job: DistillationJob, operations: tuple[dict[str, Any], ...]
    ) -> tuple[int, int]:
        valid_source_ids = {message["_row_id"] for message in job.messages}
        active = {item.id: item for item in self.memories.list_active(
            lane_key=job.lane_key, now=job.now
        )}
        applied = rejected = 0
        for operation in operations:
            action = str(operation.get("action") or "").strip().lower()
            raw_ids = operation.get("evidence_message_ids")
            try:
                evidence_ids = tuple(dict.fromkeys(int(value) for value in raw_ids))
            except (TypeError, ValueError):
                evidence_ids = ()
            if not evidence_ids or not set(evidence_ids).issubset(valid_source_ids):
                rejected += 1
                continue
            if action == "record":
                item = self.memories.record(
                    lane_key=job.lane_key,
                    kind=str(operation.get("kind") or ""),
                    content=str(operation.get("content") or ""),
                    evidence=str(operation.get("evidence") or ""),
                    source_session_id=job.session_id,
                    expires_at=operation.get("expires_at"),
                    source_message_ids=evidence_ids,
                    importance=str(operation.get("importance") or "medium"),
                    created_by="background",
                    distillation_run_id=job.run_id,
                    now=job.now,
                )
                if item is None:
                    rejected += 1
                else:
                    applied += 1
                continue
            item_id = str(operation.get("item_id") or "")
            if item_id not in active:
                rejected += 1
                continue
            if action == "resolve":
                success = self.memories.change_status(
                    lane_key=job.lane_key,
                    item_id=item_id,
                    action="resolve",
                    now=job.now,
                )
            elif action == "update":
                success = self.memories.update_content(
                    lane_key=job.lane_key,
                    item_id=item_id,
                    content=str(operation.get("content") or ""),
                    expires_at=operation.get("expires_at"),
                    source_message_ids=evidence_ids,
                    distillation_run_id=job.run_id,
                    now=job.now,
                )
            else:
                success = False
            if success:
                applied += 1
            else:
                rejected += 1
        self.memories.prune_background(lane_key=job.lane_key, max_items=50)
        return applied, rejected

    async def distill_if_due(
        self,
        *,
        lane_key: str,
        session_id: str,
        messages: Iterable[Mapping[str, Any]],
        reason: str,
        main_runtime: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> DistillationResult | None:
        timestamp = _as_utc(now or _utc_now())
        try:
            job = self._prepare(
                lane_key=lane_key,
                session_id=session_id,
                messages=messages,
                reason=reason,
                now=timestamp,
            )
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return None
        if job is None:
            return None

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE distillation_runs
                SET status = 'running', attempts = attempts + 1, error = ''
                WHERE id = ?
                """,
                (job.run_id,),
            )
        try:
            active_items = self.memories.list_active(lane_key=lane_key, now=timestamp)
            raw = await self.extractor(job, active_items, dict(main_runtime or {}))
            operations = self._parse_operations(raw, self.settings.max_operations)
            applied, rejected = self._apply_operations(job, operations)
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO distillation_state (
                        lane_key, session_id, last_source_row_id, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(lane_key, session_id) DO UPDATE SET
                        last_source_row_id = MAX(
                            distillation_state.last_source_row_id,
                            excluded.last_source_row_id
                        ),
                        updated_at = excluded.updated_at
                    """,
                    (lane_key, session_id, job.source_end_id, timestamp.isoformat()),
                )
                connection.execute(
                    """
                    UPDATE distillation_runs
                    SET status = 'completed', completed_at = ?, error = ''
                    WHERE id = ?
                    """,
                    (timestamp.isoformat(), job.run_id),
                )
            return DistillationResult(
                run_id=job.run_id,
                status="completed",
                applied=applied,
                rejected=rejected,
            )
        except asyncio.CancelledError:
            try:
                with self._connect() as connection:
                    connection.execute(
                        "UPDATE distillation_runs SET status = 'failed', error = ? WHERE id = ?",
                        ("cancelled", job.run_id),
                    )
            finally:
                raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:1000]
            try:
                with self._connect() as connection:
                    connection.execute(
                        "UPDATE distillation_runs SET status = 'failed', error = ? WHERE id = ?",
                        (error, job.run_id),
                    )
            except sqlite3.Error:
                pass
            return DistillationResult(run_id=job.run_id, status="failed", error=error)


def active_h2os_distiller() -> MemoryDistiller | None:
    """Return the active local distiller, fail-closed outside HoneyOS."""

    runtime_id = os.environ.get("H2OS_RUNTIME_ID", "")
    raw_home = os.environ.get("H2OS_HOME", "").strip()
    if not runtime_id.startswith("h2os-companion-") or not raw_home:
        return None
    return MemoryDistiller(Path(raw_home))
