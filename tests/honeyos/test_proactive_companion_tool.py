from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import honeyos.tools.proactive_companion_tool as tool_module
from honeyos.companion.topic_pool import TopicCandidate, TopicPoolStore


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def scoped_home(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tool_module, "_tool_scope", lambda: tmp_path)
    return tmp_path


def decode(value: str) -> dict:
    return json.loads(value)


def add_topic(home: Path, suffix: str = "one") -> str:
    item = TopicPoolStore(home, now_fn=lambda: NOW).add_candidates(
        [
            TopicCandidate(
                source_id=suffix,
                source_title="Grounded title",
                source_url=f"https://example.com/{suffix}",
                source_name="Example",
                summary="Verified summary",
                hook="A useful angle",
                category="technology",
                observed_at=NOW,
                expires_at=NOW + timedelta(hours=48),
                score=0.8,
            )
        ]
    )[0]
    return item.id


def test_get_and_set_consent_are_deterministic(scoped_home: Path):
    before = decode(tool_module.proactive_companion_tool(action="get_preferences"))
    enabled = decode(
        tool_module.proactive_companion_tool(
            action="set_consent", consented=True
        )
    )

    assert before["preferences"]["consented"] is False
    assert enabled["success"] is True
    assert enabled["preferences"]["consent_asked"] is True
    assert enabled["preferences"]["consented"] is True


def test_update_preferences_bounds_frequency_and_normalizes_categories(scoped_home: Path):
    result = decode(
        tool_module.proactive_companion_tool(
            action="update_preferences",
            daily_limit=3,
            minimum_interval_hours=3,
            idle_hours=2,
            quiet_start="23:00",
            quiet_end="09:00",
            focus_categories=[" AI ", "游戏", "AI"],
            blocked_categories=["政治"],
        )
    )

    assert result["preferences"]["daily_limit"] == 3
    assert result["preferences"]["focus_categories"] == ["AI", "游戏"]
    assert result["preferences"]["blocked_categories"] == ["政治"]

    invalid = decode(
        tool_module.proactive_companion_tool(
            action="update_preferences", daily_limit=4
        )
    )
    assert invalid["success"] is False
    assert "0 and 3" in invalid["error"]


def test_list_dismiss_and_discuss_topics_return_only_grounded_fields(scoped_home: Path):
    first_id = add_topic(scoped_home)
    listed = decode(tool_module.proactive_companion_tool(action="list_topics"))

    assert listed["topics"][0]["id"] == first_id
    assert listed["topics"][0]["source_url"] == "https://example.com/one"
    assert "selection_reason" not in listed["topics"][0]

    discussed = decode(
        tool_module.proactive_companion_tool(
            action="discuss_topic", topic_id=first_id
        )
    )
    assert discussed["success"] is True
    assert discussed["topic"]["hook"] == "A useful angle"
    assert TopicPoolStore(scoped_home).get_topic(first_id).status == "consumed"

    second_id = add_topic(scoped_home, "two")
    dismissed = decode(
        tool_module.proactive_companion_tool(
            action="dismiss_topic", topic_id=second_id
        )
    )
    assert dismissed == {"success": True, "topic_id": second_id, "status": "dismissed"}


def test_tool_refuses_non_companion_scope(monkeypatch):
    monkeypatch.setattr(tool_module, "_tool_scope", lambda: None)

    result = decode(tool_module.proactive_companion_tool(action="get_preferences"))

    assert result["success"] is False
    assert "private HoneyOS" in result["error"]
