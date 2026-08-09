from __future__ import annotations

from datetime import datetime, timedelta, timezone

from honeyos.companion.topic_delivery import build_proactive_event
from honeyos.companion.topic_pool import (
    ChannelActivity,
    DeliveryReservation,
    TopicItem,
)
from honeyos.gateway.config import Platform
from honeyos.gateway.session import SessionSource


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def reservation() -> DeliveryReservation:
    item = TopicItem(
        id="topic-1",
        source_id="source-1",
        source_title="A grounded source",
        source_url="https://example.com/story",
        source_name="Example",
        summary="A verified fact with a surprising consequence.",
        hook="The consequence is worth talking about.",
        category="technology",
        language="zh",
        observed_at=NOW,
        published_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=24),
        status="reserved",
        score=0.9,
        selection_reason="internal score reason",
        reserved_at=NOW,
        delivery_id="delivery-1",
    )
    channel = ChannelActivity(
        platform="feishu",
        source_json='{"platform":"feishu","chat_id":"oc_dm","chat_type":"dm","user_id":"owner"}',
        last_user_message_at=NOW - timedelta(hours=3),
    )
    return DeliveryReservation("delivery-1", item, channel, NOW)


def test_proactive_event_is_internal_grounded_and_persona_directed():
    source = SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_dm",
        chat_type="dm",
        user_id="owner",
    )

    event = build_proactive_event(reservation(), source)

    assert event.internal is True
    assert event.source is source
    assert event.metadata["honeyos_proactive_topic_id"] == "topic-1"
    assert event.metadata["honeyos_proactive_delivery_id"] == "delivery-1"
    assert "IDENTITY.md" in event.text
    assert "RELATIONSHIP.md" in event.text
    assert "https://example.com/story" in event.text
    assert "internal score reason" not in event.text
    assert "今日资讯" in event.text
    assert "不得" in event.text

