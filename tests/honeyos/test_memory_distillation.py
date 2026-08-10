from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from honeyos.companion.distillation import (
    DistillationSettings,
    MemoryDistiller,
    _main_runtime_from_config,
    extract_with_auxiliary_model,
    repair_legacy_completed_rejections,
    repair_legacy_distillation_failures,
)
from honeyos.companion.continuity import StructuredMemoryStore
from honeyos.agent.auxiliary_client import _validate_llm_response


NOW = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
LANE = "agent:main:weixin:dm:user-a"


def _messages(count: int) -> list[dict]:
    return [
        {
            "_row_id": index + 1,
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"message-{index + 1}",
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_periodic_distillation_waits_for_twenty_new_messages(tmp_path):
    calls = []

    async def extractor(_job, _active, _runtime):
        calls.append(True)
        return '{"operations":[]}'

    distiller = MemoryDistiller(
        tmp_path,
        settings=DistillationSettings(trigger_messages=20),
        extractor=extractor,
    )

    assert await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(19),
        reason="periodic",
        now=NOW,
    ) is None
    assert calls == []

    result = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )

    assert result is not None
    assert result.status == "completed"
    assert calls == [True]


@pytest.mark.asyncio
async def test_auxiliary_distillation_accepts_main_runtime_api_mode(monkeypatch, tmp_path):
    captured = {}

    class _Message:
        content = '{"operations":[]}'

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    async def fake_call_llm(**kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(
        "honeyos.agent.auxiliary_client.async_call_llm", fake_call_llm
    )
    distiller = MemoryDistiller(tmp_path)
    job = distiller._prepare(
        lane_key=LANE,
        session_id="session-api-mode",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )
    assert job is not None

    raw = await extract_with_auxiliary_model(
        job,
        (),
        {
            "provider": "custom",
            "model": "deepseek-v4-flash",
            "base_url": "https://example.invalid/v1",
            "api_mode": "chat_completions",
        },
        task_config={"provider": "auto", "model": "auto"},
    )

    assert raw == '{"operations":[]}'
    assert captured["main_runtime"]["api_mode"] == "chat_completions"
    assert "api_mode" not in {
        key for key in captured if key != "main_runtime"
    }


@pytest.mark.asyncio
async def test_auxiliary_distillation_inherits_configured_main_credential(
    monkeypatch, tmp_path
):
    captured = {}

    class _Message:
        content = '{"operations":[]}'

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    async def fake_call_llm(**kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(
        "honeyos.agent.auxiliary_client.async_call_llm", fake_call_llm
    )
    monkeypatch.setattr(
        "honeyos.companion.distillation._main_runtime_from_config",
        lambda: {
            "provider": "custom",
            "model": "deepseek-v4-flash",
            "base_url": "https://configured.example/v1",
            "api_key": "current-main-key",
            "api_mode": "chat_completions",
        },
    )
    distiller = MemoryDistiller(tmp_path)
    job = distiller._prepare(
        lane_key=LANE,
        session_id="session-current-credential",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )
    assert job is not None

    await extract_with_auxiliary_model(
        job,
        (),
        {
            "provider": "custom",
            "model": "deepseek-v4-flash",
            "base_url": "https://configured.example/v1",
            "api_mode": "chat_completions",
        },
        task_config={"provider": "auto", "model": "auto"},
    )

    assert captured["main_runtime"]["api_key"] == "current-main-key"
    assert captured["api_key"] == "current-main-key"


def test_main_runtime_from_config_resolves_named_provider_credentials(monkeypatch):
    monkeypatch.setattr(
        "honeyos.runtime.config.load_config_readonly",
        lambda: {
            "model": {
                "provider": "honeyos-model",
                "default": "deepseek-v4-flash",
                "base_url": "https://configured.example/v1",
                "api_mode": "chat_completions",
            }
        },
    )
    monkeypatch.setattr(
        "honeyos.runtime.runtime_provider.resolve_runtime_provider",
        lambda requested, target_model=None: {
            "provider": "custom",
            "requested_provider": requested,
            "model": target_model,
            "base_url": "https://configured.example/v1",
            "api_key": "current-main-key",
            "api_mode": "chat_completions",
        },
    )

    runtime = _main_runtime_from_config()

    assert runtime["provider"] == "custom"
    assert runtime["requested_provider"] == "honeyos-model"
    assert runtime["api_key"] == "current-main-key"


def test_auxiliary_validation_recovers_sse_text_from_compatible_endpoint():
    frames = [
        {
            "code": 0,
            "choices": [
                {"index": 0, "delta": {"content": '{"operations":'}}
            ],
        },
        {
            "code": 0,
            "choices": [{"index": 0, "delta": {"content": "[]}"}}],
        },
    ]
    response = "\n\n".join(
        f"data: {json.dumps(frame, ensure_ascii=False)}" for frame in frames
    ) + "\n\ndata: [DONE]\n"

    recovered = _validate_llm_response(
        response,
        task="memory_distillation",
    )

    assert recovered.choices[0].message.content == '{"operations":[]}'


def test_upgrade_reopens_runs_exhausted_by_legacy_api_mode_bug(tmp_path):
    distiller = MemoryDistiller(tmp_path)
    with distiller._connect() as connection:
        connection.execute(
            """
            INSERT INTO distillation_runs (
                id, lane_key, session_id, reason, source_start_id,
                source_end_id, source_hash, status, attempts, error, created_at
            ) VALUES ('legacy', ?, 's', 'periodic', 1, 20, 'hash',
                      'failed', 3, ?, ?)
            """,
            (LANE, "TypeError: async_call_llm() got an unexpected keyword argument 'api_mode'", NOW.isoformat()),
        )

    assert repair_legacy_distillation_failures(tmp_path) == 1
    with distiller._connect() as connection:
        row = connection.execute(
            "SELECT status, attempts, error FROM distillation_runs WHERE id='legacy'"
        ).fetchone()
        assert tuple(row) == ("failed", 0, "")


def test_upgrade_replays_completed_batches_when_legacy_validator_stored_nothing(tmp_path):
    distiller = MemoryDistiller(tmp_path)
    with distiller._connect() as connection:
        connection.execute(
            """
            INSERT INTO distillation_runs (
                id, lane_key, session_id, reason, source_start_id,
                source_end_id, source_hash, status, attempts, error,
                created_at, completed_at
            ) VALUES ('swallowed', ?, 's', 'periodic', 1, 20, 'hash',
                      'completed', 1, '', ?, ?)
            """,
            (LANE, NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO distillation_state (
                lane_key, session_id, last_source_row_id, updated_at
            ) VALUES (?, 's', 20, ?)
            """,
            (LANE, NOW.isoformat()),
        )

    assert repair_legacy_completed_rejections(tmp_path) == 1
    assert repair_legacy_completed_rejections(tmp_path) == 0
    with distiller._connect() as connection:
        run = connection.execute(
            "SELECT status, attempts, error FROM distillation_runs WHERE id='swallowed'"
        ).fetchone()
        state = connection.execute("SELECT * FROM distillation_state").fetchone()
    assert tuple(run) == ("failed", 0, "legacy evidence validation replay")
    assert state is None


@pytest.mark.asyncio
async def test_new_distills_six_message_tail_and_persists_source_ids(tmp_path):
    async def extractor(_job, _active, _runtime):
        return json.dumps(
            {
                "operations": [
                    {
                        "action": "record",
                        "kind": "open_loop",
                        "content": "下次继续聊记忆",
                        "evidence": "user_stated",
                        "evidence_message_ids": [1, 5],
                        "importance": "medium",
                    }
                ]
            },
            ensure_ascii=False,
        )

    distiller = MemoryDistiller(
        tmp_path,
        settings=DistillationSettings(min_tail_messages=6),
        extractor=extractor,
    )

    result = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(6),
        reason="new",
        now=NOW,
    )

    assert result is not None and result.applied == 1
    items = StructuredMemoryStore(tmp_path).list_active(lane_key=LANE, now=NOW)
    assert len(items) == 1
    assert items[0].source_message_ids == (1, 5)
    assert items[0].created_by == "background"
    assert items[0].distillation_run_id == result.run_id


@pytest.mark.asyncio
async def test_distillation_is_idempotent_for_the_same_message_range(tmp_path):
    calls = 0

    async def extractor(_job, _active, _runtime):
        nonlocal calls
        calls += 1
        return '{"operations":[]}'

    distiller = MemoryDistiller(tmp_path, extractor=extractor)
    first = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )
    second = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )

    assert first is not None
    assert second is None
    assert calls == 1


@pytest.mark.asyncio
async def test_exhausted_failed_run_recovers_after_cooldown(tmp_path):
    calls = 0

    async def extractor(_job, _active, _runtime):
        nonlocal calls
        calls += 1
        return '{"operations":[]}'

    distiller = MemoryDistiller(tmp_path, extractor=extractor)
    messages = _messages(20)
    prepared = distiller._prepare(
        lane_key=LANE,
        session_id="session-recover",
        messages=messages,
        reason="periodic",
        now=NOW - timedelta(hours=1),
    )
    assert prepared is not None
    with distiller._connect() as connection:
        connection.execute(
            "UPDATE distillation_runs SET status='failed', attempts=3 WHERE id=?",
            (prepared.run_id,),
        )

    result = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-recover",
        messages=messages,
        reason="periodic",
        now=NOW,
    )

    assert result is not None and result.status == "completed"
    assert calls == 1


@pytest.mark.asyncio
async def test_invalid_inference_and_unbound_evidence_are_not_written(tmp_path):
    async def extractor(_job, _active, _runtime):
        return json.dumps(
            {
                "operations": [
                    {
                        "action": "record",
                        "kind": "temporary_state",
                        "content": "用户很依赖伴侣",
                        "evidence": "inferred",
                        "evidence_message_ids": [1],
                    },
                    {
                        "action": "record",
                        "kind": "open_loop",
                        "content": "不存在来源",
                        "evidence": "user_stated",
                        "evidence_message_ids": [999],
                    },
                ]
            },
            ensure_ascii=False,
        )

    result = await MemoryDistiller(tmp_path, extractor=extractor).distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )

    assert result is not None and result.applied == 0 and result.rejected == 2
    assert StructuredMemoryStore(tmp_path).list_active(lane_key=LANE, now=NOW) == ()


@pytest.mark.asyncio
async def test_missing_evidence_is_safely_derived_from_kind_and_source_role(tmp_path):
    async def extractor(_job, _active, _runtime):
        return json.dumps(
            {
                "operations": [
                    {
                        "action": "record",
                        "kind": "open_loop",
                        "content": "用户想下次继续聊记忆",
                        "evidence_message_ids": [1],
                    },
                    {
                        "action": "record",
                        "kind": "commitment",
                        "content": "伴侣答应下次提醒用户",
                        "evidence_message_ids": [2],
                    },
                ]
            },
            ensure_ascii=False,
        )

    result = await MemoryDistiller(tmp_path, extractor=extractor).distill_if_due(
        lane_key=LANE,
        session_id="session-missing-evidence",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )

    assert result is not None and result.applied == 2 and result.rejected == 0
    items = StructuredMemoryStore(tmp_path).list_active(lane_key=LANE, now=NOW)
    assert {item.evidence for item in items} == {"user_stated", "assistant_committed"}


@pytest.mark.asyncio
async def test_all_rejected_operations_fail_run_without_advancing_cursor(tmp_path):
    calls = 0

    async def extractor(_job, _active, _runtime):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "operations": [
                    {
                        "action": "record",
                        "kind": "temporary_state",
                        "content": "没有用户来源",
                        "evidence_message_ids": [2],
                    }
                ]
            },
            ensure_ascii=False,
        )

    distiller = MemoryDistiller(tmp_path, extractor=extractor)
    first = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-rejected",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )
    second = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-rejected",
        messages=_messages(20),
        reason="periodic",
        now=NOW + timedelta(minutes=1),
    )

    assert first is not None and first.status == "failed"
    assert first.applied == 0 and first.rejected == 1
    assert second is not None and second.run_id == first.run_id
    assert calls == 2


@pytest.mark.asyncio
async def test_failed_run_retries_without_advancing_the_cursor(tmp_path):
    calls = 0

    async def extractor(_job, _active, _runtime):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return '{"operations":[]}'

    distiller = MemoryDistiller(tmp_path, extractor=extractor)
    failed = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )
    completed = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )

    assert failed is not None and failed.status == "failed"
    assert completed is not None and completed.status == "completed"
    assert completed.run_id == failed.run_id
    assert calls == 2


@pytest.mark.asyncio
async def test_auto_model_mode_stays_on_captured_main_provider(monkeypatch):
    captured = {}

    async def fake_call_llm(**kwargs):
        captured.update(kwargs)

        class Message:
            content = '{"operations":[]}'

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        return Response()

    monkeypatch.setattr(
        "honeyos.agent.auxiliary_client.async_call_llm", fake_call_llm
    )
    monkeypatch.setattr(
        "honeyos.core.time.get_timezone", lambda: timezone(timedelta(hours=8))
    )
    job = type(
        "Job",
        (),
        {
            "messages": tuple(_messages(6)),
            "now": NOW,
            "reason": "new",
            "run_id": "run-a",
            "max_operations": 6,
        },
    )()

    await extract_with_auxiliary_model(
        job,
        active_items=(),
        main_runtime={
            "provider": "openai-codex",
            "model": "gpt-main",
            "base_url": "https://example.invalid/v1",
        },
        task_config={"provider": "auto", "model": "auto"},
    )

    assert captured["task"] == "memory_distillation"
    assert captured["provider"] == "openai-codex"
    assert captured["model"] == "gpt-main"
    assert captured["base_url"] == "https://example.invalid/v1"
    assert "2026-08-07T16:00:00+08:00" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_daily_run_limit_prevents_unbounded_background_cost(tmp_path):
    calls = 0

    async def extractor(_job, _active, _runtime):
        nonlocal calls
        calls += 1
        return '{"operations":[]}'

    settings = DistillationSettings(trigger_messages=1, max_daily_runs=1)
    distiller = MemoryDistiller(tmp_path, settings=settings, extractor=extractor)

    first = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(1),
        reason="periodic",
        now=NOW,
    )
    second = await distiller.distill_if_due(
        lane_key=LANE,
        session_id="session-b",
        messages=_messages(1),
        reason="periodic",
        now=NOW,
    )

    assert first is not None
    assert second is None
    assert calls == 1


@pytest.mark.asyncio
async def test_background_correction_updates_expiry_and_keeps_new_evidence(tmp_path):
    store = StructuredMemoryStore(tmp_path)
    existing = store.record(
        lane_key=LANE,
        kind="open_loop",
        content="本周完成上线",
        evidence="user_stated",
        source_session_id="session-a",
        expires_at="2026-08-10T16:00:00+00:00",
        source_message_ids=(1,),
        now=NOW,
    )
    assert existing is not None

    async def extractor(_job, _active, _runtime):
        return json.dumps(
            {
                "operations": [
                    {
                        "action": "update",
                        "item_id": existing.id,
                        "content": "上线延期到下周三",
                        "expires_at": "2026-08-19T16:00:00+00:00",
                        "evidence_message_ids": [5],
                    }
                ]
            },
            ensure_ascii=False,
        )

    result = await MemoryDistiller(tmp_path, extractor=extractor).distill_if_due(
        lane_key=LANE,
        session_id="session-a",
        messages=_messages(20),
        reason="periodic",
        now=NOW,
    )

    assert result is not None and result.applied == 1
    updated = store.list_active(lane_key=LANE, now=NOW)[0]
    assert updated.content == "上线延期到下周三"
    assert updated.expires_at == datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)
    assert updated.source_message_ids == (1, 5)
