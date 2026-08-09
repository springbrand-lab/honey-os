from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from honeyos.companion.topic_pool import TopicCandidate, TopicPoolStore


CN = timezone(timedelta(hours=8))


class Clock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **delta) -> None:
        self.value += timedelta(**delta)


def candidate(
    *,
    url: str = "https://example.com/story",
    title: str = "A useful story",
    source_id: str | None = "source-1",
    observed_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> TopicCandidate:
    observed = observed_at or datetime(2026, 8, 9, 10, 0, tzinfo=CN)
    return TopicCandidate(
        source_id=source_id,
        source_title=title,
        source_url=url,
        source_name="Example",
        summary="A grounded summary.",
        hook="There is one surprising point worth discussing.",
        category="technology",
        language="zh",
        observed_at=observed,
        published_at=observed - timedelta(hours=1),
        expires_at=expires_at or observed + timedelta(hours=48),
        score=0.9,
        selection_reason="relevant and conversational",
    )


def enable(store: TopicPoolStore) -> None:
    store.update_preferences(consented=True, consent_asked=True)


def test_default_preferences_are_opt_in_and_capped_at_three(tmp_path: Path):
    store = TopicPoolStore(tmp_path)

    preferences = store.preferences()

    assert preferences.consent_asked is False
    assert preferences.consented is False
    assert preferences.daily_limit == 3
    assert preferences.minimum_interval_hours == 3
    assert preferences.idle_hours == 2
    assert preferences.quiet_start == "23:00"
    assert preferences.quiet_end == "09:00"
    assert preferences.route_mode == "recent"


def test_topic_pool_deduplicates_normalized_urls_and_expires(tmp_path: Path):
    clock = Clock(datetime(2026, 8, 9, 10, 0, tzinfo=CN))
    store = TopicPoolStore(tmp_path, now_fn=clock)
    first = store.add_candidates(
        [candidate(url="https://Example.com/story/?utm_source=test#fragment")]
    )
    second = store.add_candidates(
        [candidate(url="https://example.com/story", source_id=None)]
    )

    assert len(first) == 1
    assert second == ()
    assert len(store.list_open_topics()) == 1

    clock.advance(hours=49)

    assert store.list_open_topics() == ()
    assert store.get_topic(first[0].id).status == "expired"


def test_same_source_id_is_deduplicated_even_when_url_changes(tmp_path: Path):
    store = TopicPoolStore(tmp_path)

    first = store.add_candidates([candidate(url="https://example.com/a")])
    second = store.add_candidates([candidate(url="https://example.com/b")])

    assert len(first) == 1
    assert second == ()


def test_channel_activity_uses_latest_owner_message(tmp_path: Path):
    store = TopicPoolStore(tmp_path)
    feishu = {
        "platform": "feishu",
        "chat_id": "oc_feishu",
        "chat_type": "dm",
        "user_id": "owner",
    }
    web = {
        "platform": "api_server",
        "chat_id": "companion",
        "chat_type": "dm",
        "user_id": "owner",
    }
    store.record_channel_activity(
        feishu, at=datetime(2026, 8, 9, 8, 0, tzinfo=CN)
    )
    store.record_channel_activity(
        web, at=datetime(2026, 8, 9, 9, 0, tzinfo=CN)
    )

    latest = store.latest_channel()

    assert latest is not None
    assert latest.platform == "api_server"
    assert json.loads(latest.source_json)["chat_id"] == "companion"


def test_delivery_requires_consent_idle_time_and_open_topic(tmp_path: Path):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=CN)
    store = TopicPoolStore(tmp_path, now_fn=lambda: now)
    store.add_candidates([candidate(observed_at=now)])
    store.record_channel_activity(
        {"platform": "feishu", "chat_id": "dm", "chat_type": "dm"},
        at=now - timedelta(hours=3),
    )

    assert store.reserve_due_delivery(now=now) is None

    enable(store)
    reservation = store.reserve_due_delivery(now=now)

    assert reservation is not None
    assert reservation.channel.platform == "feishu"
    assert reservation.item.status == "reserved"


def test_delivery_respects_quiet_hours_and_minimum_interval(tmp_path: Path):
    store = TopicPoolStore(tmp_path)
    enable(store)
    topics = store.add_candidates(
        [
            candidate(url="https://example.com/1", source_id="1"),
            candidate(url="https://example.com/2", source_id="2"),
        ]
    )
    store.record_channel_activity(
        {"platform": "feishu", "chat_id": "dm", "chat_type": "dm"},
        at=datetime(2026, 8, 9, 6, 0, tzinfo=CN),
    )

    assert store.reserve_due_delivery(
        now=datetime(2026, 8, 9, 8, 30, tzinfo=CN)
    ) is None

    first = store.reserve_due_delivery(
        now=datetime(2026, 8, 9, 10, 0, tzinfo=CN)
    )
    assert first is not None
    store.finish_delivery(first.delivery_id, success=True, at=datetime(2026, 8, 9, 10, 1, tzinfo=CN))

    assert store.reserve_due_delivery(
        now=datetime(2026, 8, 9, 12, 59, tzinfo=CN)
    ) is None
    second = store.reserve_due_delivery(
        now=datetime(2026, 8, 9, 13, 1, tzinfo=CN)
    )
    assert second is not None
    assert second.item.id != topics[0].id


def test_delivery_daily_cap_is_three_and_failed_send_reopens_topic(tmp_path: Path):
    store = TopicPoolStore(tmp_path)
    enable(store)
    store.update_preferences(minimum_interval_hours=1)
    store.add_candidates(
        [candidate(url=f"https://example.com/{i}", source_id=str(i)) for i in range(5)]
    )
    store.record_channel_activity(
        {"platform": "feishu", "chat_id": "dm", "chat_type": "dm"},
        at=datetime(2026, 8, 9, 6, 0, tzinfo=CN),
    )

    failed = store.reserve_due_delivery(now=datetime(2026, 8, 9, 10, 0, tzinfo=CN))
    assert failed is not None
    store.finish_delivery(failed.delivery_id, success=False, error="offline")
    assert store.get_topic(failed.item.id).status == "open"

    for hour, minute in ((10, 5), (11, 10), (12, 15)):
        reservation = store.reserve_due_delivery(
            now=datetime(2026, 8, 9, hour, minute, tzinfo=CN)
        )
        assert reservation is not None
        store.finish_delivery(
            reservation.delivery_id,
            success=True,
            at=datetime(2026, 8, 9, hour, minute + 1, tzinfo=CN),
        )

    assert store.reserve_due_delivery(
        now=datetime(2026, 8, 9, 15, 0, tzinfo=CN)
    ) is None


def test_initialization_preserves_existing_companion_memories(tmp_path: Path):
    memories = tmp_path / "memories"
    memories.mkdir()
    identity = memories / "IDENTITY.md"
    relationship = memories / "RELATIONSHIP.md"
    identity.write_text("name: 小意\n", encoding="utf-8")
    relationship.write_text("user_nickname: 小酒\n", encoding="utf-8")

    TopicPoolStore(tmp_path)

    assert identity.read_text(encoding="utf-8") == "name: 小意\n"
    assert relationship.read_text(encoding="utf-8") == "user_nickname: 小酒\n"
    assert (tmp_path / "state" / "topic_pool.db").is_file()
