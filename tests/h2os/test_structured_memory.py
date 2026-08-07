from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from h2os_cli.continuity import StructuredMemoryStore


NOW = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)
LANE = "agent:main:weixin:dm:user-a"


def test_four_memory_kinds_are_local_source_backed_and_lane_isolated(tmp_path):
    store = StructuredMemoryStore(tmp_path)

    created = [
        store.record(
            lane_key=LANE,
            kind="open_loop",
            content="下次继续聊跨窗口记忆",
            evidence="user_stated",
            source_session_id="session-a",
            now=NOW,
        ),
        store.record(
            lane_key=LANE,
            kind="temporary_state",
            content="用户今天因为开发混乱而疲惫",
            evidence="user_stated",
            source_session_id="session-a",
            now=NOW,
        ),
        store.record(
            lane_key=LANE,
            kind="commitment",
            content="伴侣答应下一次从交接机制开始",
            evidence="assistant_committed",
            source_session_id="session-a",
            now=NOW,
        ),
        store.record(
            lane_key=LANE,
            kind="episode",
            content="双方共同完成了第一版记忆方案",
            evidence="conversation_event",
            source_session_id="session-a",
            now=NOW,
        ),
    ]

    assert all(item is not None for item in created)
    note = store.context_for_lane(lane_key=LANE, now=NOW)
    assert note is not None
    assert "下次继续聊跨窗口记忆" in note
    assert "用户今天因为开发混乱而疲惫" in note
    assert "伴侣答应下一次从交接机制开始" in note
    assert "双方共同完成了第一版记忆方案" in note
    assert store.context_for_lane(
        lane_key="agent:main:weixin:dm:user-b", now=NOW
    ) is None


def test_inferred_or_identity_relationship_content_is_rejected(tmp_path):
    store = StructuredMemoryStore(tmp_path)

    assert store.record(
        lane_key=LANE,
        kind="temporary_state",
        content="用户看起来爱上了伴侣",
        evidence="inferred",
        source_session_id="session-a",
        now=NOW,
    ) is None
    assert store.record(
        lane_key=LANE,
        kind="temporary_state",
        content="用户今天很累",
        evidence="assistant_committed",
        source_session_id="session-a",
        now=NOW,
    ) is None
    assert store.record(
        lane_key=LANE,
        kind="commitment",
        content="下次陪用户继续讨论",
        evidence="user_stated",
        source_session_id="session-a",
        now=NOW,
    ) is None
    assert store.record(
        lane_key=LANE,
        kind="relationship",
        content="双方是恋人",
        evidence="user_stated",
        source_session_id="session-a",
        now=NOW,
    ) is None


def test_temporary_state_expires_while_episode_remains(tmp_path):
    store = StructuredMemoryStore(tmp_path, temporary_state_ttl=timedelta(days=3))
    store.record(
        lane_key=LANE,
        kind="temporary_state",
        content="用户今天很累",
        evidence="user_stated",
        source_session_id="session-a",
        now=NOW,
    )
    store.record(
        lane_key=LANE,
        kind="episode",
        content="双方一起完成了产品原型",
        evidence="conversation_event",
        source_session_id="session-a",
        now=NOW,
    )

    note = store.context_for_lane(lane_key=LANE, now=NOW + timedelta(days=4))

    assert note is not None
    assert "用户今天很累" not in note
    assert "双方一起完成了产品原型" in note


def test_explicit_semantic_expiry_overrides_three_day_fallback(tmp_path):
    store = StructuredMemoryStore(tmp_path)
    item = store.record(
        lane_key=LANE,
        kind="temporary_state",
        content="用户这周都在出差",
        evidence="user_stated",
        source_session_id="session-a",
        expires_at="2026-08-10T16:00:00+00:00",
        now=NOW,
    )

    assert item is not None
    assert item.expires_at == datetime(2026, 8, 10, 16, 0, tzinfo=timezone.utc)
    assert store.context_for_lane(
        lane_key=LANE, now=datetime(2026, 8, 10, 15, 59, tzinfo=timezone.utc)
    ) is not None
    assert store.context_for_lane(
        lane_key=LANE, now=datetime(2026, 8, 10, 16, 1, tzinfo=timezone.utc)
    ) is None


def test_user_can_extend_a_temporary_state_to_a_new_explicit_date(tmp_path):
    store = StructuredMemoryStore(tmp_path)
    item = store.record(
        lane_key=LANE,
        kind="temporary_state",
        content="用户本周在赶上线",
        evidence="user_stated",
        source_session_id="session-a",
        expires_at="2026-08-10T16:00:00+00:00",
        now=NOW,
    )
    assert item is not None

    assert store.update_content(
        lane_key=LANE,
        item_id=item.id,
        content="用户赶上线延期到下周三",
        expires_at="2026-08-19T16:00:00+00:00",
        now=NOW,
    ) is True

    updated = store.list_active(lane_key=LANE, now=NOW)[0]
    assert updated.expires_at == datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)



def test_open_loop_can_be_resolved_and_memory_can_be_forgotten(tmp_path):
    store = StructuredMemoryStore(tmp_path)
    loop = store.record(
        lane_key=LANE,
        kind="open_loop",
        content="决定短期记忆如何升级",
        evidence="user_stated",
        source_session_id="session-a",
        now=NOW,
    )
    episode = store.record(
        lane_key=LANE,
        kind="episode",
        content="双方一起看了第一部电影",
        evidence="conversation_event",
        source_session_id="session-a",
        now=NOW,
    )
    assert loop is not None and episode is not None

    assert store.change_status(
        lane_key=LANE, item_id=loop.id, action="resolve", now=NOW
    ) is True
    assert store.change_status(
        lane_key=LANE, item_id=episode.id, action="forget", now=NOW
    ) is True
    assert store.context_for_lane(lane_key=LANE, now=NOW) is None


def test_exact_duplicate_updates_existing_item_instead_of_growing(tmp_path):
    store = StructuredMemoryStore(tmp_path)
    first = store.record(
        lane_key=LANE,
        kind="open_loop",
        content="周五一起看电影",
        evidence="user_stated",
        source_session_id="session-a",
        now=NOW,
    )
    second = store.record(
        lane_key=LANE,
        kind="open_loop",
        content=" 周五一起看电影 ",
        evidence="user_stated",
        source_session_id="session-b",
        now=NOW + timedelta(hours=1),
    )

    assert first is not None and second is not None
    assert second.id == first.id
    assert len(store.list_active(lane_key=LANE, now=NOW + timedelta(hours=1))) == 1


def test_background_duplicate_never_downgrades_foreground_memory(tmp_path):
    store = StructuredMemoryStore(tmp_path)
    foreground = store.record(
        lane_key=LANE,
        kind="episode",
        content="双方一起完成了第一版原型",
        evidence="user_stated",
        source_session_id="session-a",
        source_message_ids=(1,),
        importance="high",
        created_by="foreground",
        now=NOW,
    )
    duplicate = store.record(
        lane_key=LANE,
        kind="episode",
        content="双方一起完成了第一版原型",
        evidence="conversation_event",
        source_session_id="session-a",
        source_message_ids=(3,),
        importance="low",
        created_by="background",
        distillation_run_id="run-a",
        now=NOW + timedelta(hours=1),
    )

    assert foreground is not None and duplicate is not None
    assert duplicate.id == foreground.id
    assert duplicate.created_by == "foreground"
    assert duplicate.importance == "high"
    assert duplicate.source_message_ids == (1, 3)
    assert duplicate.distillation_run_id is None


def test_background_memory_cap_prunes_old_low_priority_items_only(tmp_path):
    store = StructuredMemoryStore(tmp_path, max_items=100)
    protected = store.record(
        lane_key=LANE,
        kind="episode",
        content="用户明确保存的共同经历",
        evidence="user_stated",
        source_session_id="session-a",
        created_by="foreground",
        now=NOW,
    )
    for index in range(51):
        store.record(
            lane_key=LANE,
            kind="episode",
            content=f"后台共同经历 {index}",
            evidence="conversation_event",
            source_session_id="session-a",
            importance="low",
            created_by="background",
            now=NOW + timedelta(minutes=index + 1),
        )

    assert store.prune_background(lane_key=LANE, max_items=50) == 1
    items = store.list_active(lane_key=LANE, now=NOW + timedelta(hours=2))
    assert len(items) == 51
    assert any(item.id == protected.id for item in items if protected is not None)
    assert all(item.content != "后台共同经历 0" for item in items)


def test_companion_memory_tool_uses_current_private_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("H2OS_HOME", str(tmp_path))
    monkeypatch.setenv("H2OS_RUNTIME_ID", "h2os-companion-v0.2")
    from tools.approval import reset_current_session_key, set_current_session_key
    from tools.companion_memory_tool import companion_memory_tool

    token = set_current_session_key(LANE)
    try:
        result = json.loads(
            companion_memory_tool(
                action="record",
                kind="open_loop",
                content="明天继续聊记忆",
                evidence="user_stated",
                session_id="session-a",
            )
        )
    finally:
        reset_current_session_key(token)

    assert result["success"] is True
    assert result["item"]["kind"] == "open_loop"


def test_companion_memory_tool_fails_closed_outside_private_h2os_lane(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("H2OS_HOME", str(tmp_path))
    monkeypatch.setenv("H2OS_RUNTIME_ID", "h2os-companion-v0.2")
    from tools.approval import reset_current_session_key, set_current_session_key
    from tools.companion_memory_tool import companion_memory_tool

    token = set_current_session_key("agent:main:weixin:group:group-a")
    try:
        result = json.loads(
            companion_memory_tool(
                action="record",
                kind="open_loop",
                content="不应保存",
                evidence="user_stated",
                session_id="session-a",
            )
        )
    finally:
        reset_current_session_key(token)

    assert result["success"] is False


def test_structured_memory_runtime_note_is_private_h2os_only(tmp_path, monkeypatch):
    from h2os_cli.continuity import structured_memory_note

    monkeypatch.setenv("H2OS_HOME", str(tmp_path))
    monkeypatch.setenv("H2OS_RUNTIME_ID", "h2os-companion-v0.2")
    StructuredMemoryStore(tmp_path).record(
        lane_key=LANE,
        kind="open_loop",
        content="下次继续",
        evidence="user_stated",
        source_session_id="session-a",
        now=NOW,
    )

    assert structured_memory_note(
        lane_key=LANE, chat_type="dm", now=NOW
    ) is not None
    assert structured_memory_note(
        lane_key=LANE, chat_type="group", now=NOW
    ) is None
    monkeypatch.delenv("H2OS_RUNTIME_ID")
    assert structured_memory_note(
        lane_key=LANE, chat_type="dm", now=NOW
    ) is None
