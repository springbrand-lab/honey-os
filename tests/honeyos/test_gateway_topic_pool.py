from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from honeyos.companion.topic_pool import TopicCandidate, TopicPoolStore
from honeyos.companion.topic_delivery import build_proactive_event
from honeyos.gateway.config import Platform
from honeyos.gateway.platforms.base import MessageEvent, MessageType
from honeyos.gateway.run import GatewayRunner
from honeyos.gateway.session import SessionSource


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def source(platform: Platform = Platform.FEISHU, *, chat_type: str = "dm") -> SessionSource:
    return SessionSource(
        platform=platform,
        chat_id="oc_dm",
        chat_type=chat_type,
        user_id="owner",
        user_name="Owner",
    )


def prepared_store(tmp_path: Path) -> TopicPoolStore:
    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    store.update_preferences(
        consent_asked=True,
        consented=True,
        quiet_start="23:00",
        quiet_end="09:00",
    )
    store.record_channel_activity(source().to_dict(), at=NOW - timedelta(hours=3))
    store.add_candidates(
        [
            TopicCandidate(
                source_id="one",
                source_title="Grounded",
                source_url="https://example.com/one",
                source_name="Example",
                summary="Verified summary",
                hook="Interesting angle",
                category="technology",
                observed_at=NOW,
                expires_at=NOW + timedelta(hours=24),
                score=0.9,
            )
        ]
    )
    return store


class FakeRunner:
    _topic_pool_store_instance = GatewayRunner._topic_pool_store_instance
    _record_topic_pool_channel_activity = GatewayRunner._record_topic_pool_channel_activity
    _run_topic_pool_pulse = GatewayRunner._run_topic_pool_pulse
    _finish_proactive_topic_event = GatewayRunner._finish_proactive_topic_event
    _register_proactive_topic_delivery_completion = (
        GatewayRunner._register_proactive_topic_delivery_completion
    )

    def __init__(self, store: TopicPoolStore, *, adapter=object()):
        self._topic_pool_store = store
        self.adapter = adapter
        self.enqueued: list[tuple[str, MessageEvent, object]] = []
        self._running_agents = {}

    def _adapter_for_source(self, inbound_source):
        return self.adapter

    def _session_key_for_source(self, inbound_source):
        return f"agent:main:{inbound_source.platform.value}:dm:owner"

    def _enqueue_fifo(self, key, event, adapter):
        self.enqueued.append((key, event, adapter))


def test_only_real_private_owner_messages_update_recent_channel(tmp_path: Path):
    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    runner = FakeRunner(store)

    runner._record_topic_pool_channel_activity(
        MessageEvent(text="hello", source=source(), timestamp=NOW),
        source(),
        is_internal=False,
    )
    runner._record_topic_pool_channel_activity(
        MessageEvent(text="internal", source=source(), internal=True, timestamp=NOW + timedelta(hours=1)),
        source(),
        is_internal=True,
    )
    runner._record_topic_pool_channel_activity(
        MessageEvent(text="group", source=source(chat_type="group"), timestamp=NOW + timedelta(hours=2)),
        source(chat_type="group"),
        is_internal=False,
    )

    latest = store.latest_channel()
    assert latest is not None
    assert latest.last_user_message_at == NOW


@pytest.mark.asyncio
async def test_parallel_pulses_enqueue_one_topic_seed(tmp_path: Path):
    store = prepared_store(tmp_path)
    runner = FakeRunner(store)

    await asyncio.gather(
        runner._run_topic_pool_pulse(now=NOW),
        runner._run_topic_pool_pulse(now=NOW),
    )

    assert len(runner.enqueued) == 1
    event = runner.enqueued[0][1]
    assert event.internal is True
    assert event.metadata["honeyos_proactive_topic_id"]


@pytest.mark.asyncio
async def test_missing_recent_adapter_reopens_reserved_topic(tmp_path: Path):
    store = prepared_store(tmp_path)
    runner = FakeRunner(store, adapter=None)

    result = await runner._run_topic_pool_pulse(now=NOW)

    assert result is False
    assert store.list_open_topics()[0].status == "open"


@pytest.mark.asyncio
async def test_non_push_web_adapter_leaves_topic_for_browser_claim(tmp_path: Path):
    store = prepared_store(tmp_path)
    store.record_channel_activity(
        source(Platform.API_SERVER).to_dict(),
        at=NOW - timedelta(hours=3),
    )

    class NonPushAdapter:
        supports_async_delivery = False

    runner = FakeRunner(store, adapter=NonPushAdapter())

    result = await runner._run_topic_pool_pulse(now=NOW)

    assert result is False
    assert runner.enqueued == []
    assert store.list_open_topics()[0].status == "open"


@pytest.mark.asyncio
async def test_topic_is_consumed_only_after_post_delivery_callback(tmp_path: Path):
    store = prepared_store(tmp_path)
    reservation = store.reserve_due_delivery(now=NOW)
    assert reservation is not None

    class CallbackAdapter:
        callback = None

        def register_post_delivery_callback(self, key, callback, *, generation=None):
            self.callback = callback

    adapter = CallbackAdapter()
    runner = FakeRunner(store, adapter=adapter)
    event = build_proactive_event(reservation, source())

    await runner._register_proactive_topic_delivery_completion(
        event=event,
        source=source(),
        session_key="agent:main:feishu:dm:owner",
        run_generation=1,
        agent_result={"final_response": "有件事我刚看到，想起你了。"},
    )

    assert store.get_topic(reservation.item.id).status == "reserved"
    assert adapter.callback is not None
    await adapter.callback()
    assert store.get_topic(reservation.item.id).status == "consumed"


@pytest.mark.asyncio
async def test_empty_companion_turn_reopens_topic(tmp_path: Path):
    store = prepared_store(tmp_path)
    reservation = store.reserve_due_delivery(now=NOW)
    assert reservation is not None
    runner = FakeRunner(store)
    event = build_proactive_event(reservation, source())

    await runner._register_proactive_topic_delivery_completion(
        event=event,
        source=source(),
        session_key="agent:main:feishu:dm:owner",
        run_generation=1,
        agent_result={"final_response": ""},
    )

    assert store.get_topic(reservation.item.id).status == "open"
