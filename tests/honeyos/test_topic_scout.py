from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from honeyos.companion.topic_pool import TopicPoolStore
from honeyos.companion.topic_scout import (
    RawCandidate,
    SelectedTopic,
    TopicScout,
    VerifiedCandidate,
    parse_filter_response,
    parse_web_search_results,
)


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def raw(identifier: str, *, url: str | None = None) -> RawCandidate:
    return RawCandidate(
        id=identifier,
        title=f"Story {identifier}",
        url=url or f"https://example.com/{identifier}",
        source_name="Example",
        description=f"Description {identifier}",
        published_at=NOW - timedelta(hours=1),
        category="technology",
    )


@pytest.mark.asyncio
async def test_scout_collects_three_or_fewer_verified_unique_topics(tmp_path: Path):
    search_calls: list[str] = []

    async def fake_search(query: str, limit: int):
        search_calls.append(query)
        return [raw("a"), raw("b"), raw("a")]

    async def fake_fetch(item: RawCandidate):
        return VerifiedCandidate(raw=item, excerpt=f"Verified body for {item.id}")

    async def fake_filter(items, preferences, main_runtime):
        return [
            SelectedTopic(
                candidate_id=item.raw.id,
                hook=f"Why {item.raw.id} matters",
                category=item.raw.category,
                score=0.8,
                reason="fresh and conversational",
            )
            for item in items[:3]
        ]

    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    scout = TopicScout(
        tmp_path,
        store=store,
        search_fn=fake_search,
        fetch_fn=fake_fetch,
        filter_fn=fake_filter,
        now_fn=lambda: NOW,
    )

    result = await scout.collect_once()

    assert len(search_calls) == 3
    assert len(result.accepted) == 2
    assert len(store.list_open_topics()) == 2
    assert all(item.source_url.startswith("https://") for item in result.accepted)
    assert all(item.hook.startswith("Why") for item in result.accepted)


@pytest.mark.asyncio
async def test_scout_allows_empty_round_and_does_not_store_unverified_sources(tmp_path: Path):
    async def fake_search(query: str, limit: int):
        return [raw("a")]

    async def always_fail(item: RawCandidate):
        return None

    async def should_not_filter(items, preferences, main_runtime):
        raise AssertionError("filter must not run without verified candidates")

    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    scout = TopicScout(
        tmp_path,
        store=store,
        search_fn=fake_search,
        fetch_fn=always_fail,
        filter_fn=should_not_filter,
        now_fn=lambda: NOW,
    )

    result = await scout.collect_once()

    assert result.accepted == ()
    assert result.verified_count == 0
    assert store.list_open_topics() == ()


@pytest.mark.asyncio
async def test_scout_keeps_one_verified_candidate_when_model_selects_none(tmp_path: Path):
    async def fake_search(query: str, limit: int):
        return [raw("a")]

    async def fake_fetch(item: RawCandidate):
        return VerifiedCandidate(raw=item, excerpt="A verified source body with enough detail")

    async def overcautious_filter(items, preferences, main_runtime):
        return []

    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    scout = TopicScout(
        tmp_path,
        store=store,
        search_fn=fake_search,
        fetch_fn=fake_fetch,
        filter_fn=overcautious_filter,
        now_fn=lambda: NOW,
    )

    result = await scout.collect_once()

    assert len(result.accepted) == 1
    assert result.accepted[0].source_title == "Story a"
    assert result.accepted[0].hook


def test_legacy_naive_collection_timestamp_is_interpreted_as_local_time(
    monkeypatch, tmp_path: Path
):
    from honeyos.companion import topic_pool

    monkeypatch.setattr(topic_pool, "_local_timezone", lambda: timezone(timedelta(hours=8)))
    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    store.update_preferences(consent_asked=True, consented=True)
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO topic_pool_meta(key, value) VALUES ('last_collection_at', ?)",
            ("2026-08-09T19:00:00",),
        )

    assert store.collection_due(hours=6, now=NOW) is False
    assert store.collection_due(hours=6, now=NOW + timedelta(hours=5)) is True


def test_future_collection_timestamp_from_legacy_timezone_bug_is_due_now(tmp_path: Path):
    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO topic_pool_meta(key, value) VALUES ('last_collection_at', ?)",
            ((NOW + timedelta(hours=6)).isoformat(),),
        )

    assert store.collection_due(hours=6, now=NOW) is True


@pytest.mark.asyncio
async def test_collect_if_due_requires_consent_and_marks_attempt(tmp_path: Path):
    calls = 0

    async def fake_search(query: str, limit: int):
        nonlocal calls
        calls += 1
        return []

    store = TopicPoolStore(tmp_path, now_fn=lambda: NOW)
    scout = TopicScout(
        tmp_path,
        store=store,
        search_fn=fake_search,
        now_fn=lambda: NOW,
    )

    disabled = await scout.collect_if_due()
    assert disabled.skipped_reason == "not_consented"
    assert calls == 0

    store.update_preferences(consent_asked=True, consented=True)
    attempted = await scout.collect_if_due()
    assert attempted.skipped_reason == ""
    assert calls == 3
    assert store.collection_due(now=NOW + timedelta(hours=1)) is False

    not_due = await scout.collect_if_due(now=NOW + timedelta(hours=1))
    assert not_due.skipped_reason == "not_due"


def test_web_search_parser_rejects_invalid_and_private_results():
    payload = json.dumps(
        {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Good",
                        "url": "https://example.com/good",
                        "description": "Useful",
                    },
                    {"title": "Local", "url": "http://127.0.0.1/private"},
                    {"title": "Bad", "url": "javascript:alert(1)"},
                ]
            },
        }
    )

    parsed = parse_web_search_results(payload, category="science")

    assert len(parsed) == 1
    assert parsed[0].title == "Good"
    assert parsed[0].category == "science"


def test_filter_response_is_strict_bounded_and_cannot_invent_candidate_ids():
    response = json.dumps(
        {
            "topics": [
                {
                    "candidate_id": "known",
                    "hook": "A specific point worth continuing",
                    "category": "technology",
                    "score": 0.9,
                    "reason": "grounded",
                },
                {
                    "candidate_id": "invented",
                    "hook": "Do not accept",
                    "category": "technology",
                    "score": 1,
                    "reason": "not in input",
                },
                {
                    "candidate_id": "known-2",
                    "hook": "Another useful angle",
                    "category": "science",
                    "score": 8,
                    "reason": "score out of range",
                },
            ]
        }
    )

    selected = parse_filter_response(response, allowed_ids={"known", "known-2"})

    assert [item.candidate_id for item in selected] == ["known"]
