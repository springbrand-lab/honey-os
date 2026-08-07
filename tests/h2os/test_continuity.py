from __future__ import annotations

from datetime import datetime, timedelta, timezone

from h2os_cli.continuity import (
    ContinuityStore,
    note_for_reset_session,
    record_reset_handoff,
)


NOW = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


def _messages() -> list[dict]:
    return [
        {"role": "system", "content": "internal prompt"},
        {"role": "user", "content": "我今天开发 HoneyOS 搞得很乱。"},
        {"role": "assistant", "content": "听起来你已经被这件事耗了一整天。"},
        {"role": "tool", "content": "private tool output"},
        {"role": "user", "content": "明天继续聊跨窗口记忆吧。"},
        {"role": "assistant", "content": "好，下一次我们从 /new 的交接开始。"},
    ]


def test_handoff_is_available_only_to_its_target_session_and_lane(tmp_path):
    store = ContinuityStore(tmp_path)

    saved = store.record_transition(
        lane_key="weixin:dm:user-a",
        source_session_id="old-session",
        target_session_id="new-session",
        messages=_messages(),
        now=NOW,
    )

    assert saved is True
    note = store.note_for_session(
        lane_key="weixin:dm:user-a",
        target_session_id="new-session",
        now=NOW + timedelta(minutes=1),
    )
    assert note is not None
    assert "old-session" in note
    assert "明天继续聊跨窗口记忆吧" in note
    assert "下一次我们从 /new 的交接开始" in note
    assert "internal prompt" not in note
    assert "private tool output" not in note
    assert "仅在与用户当前消息相关时" in note

    assert store.note_for_session(
        lane_key="weixin:dm:user-b",
        target_session_id="new-session",
        now=NOW,
    ) is None
    assert store.note_for_session(
        lane_key="weixin:dm:user-a",
        target_session_id="different-session",
        now=NOW,
    ) is None


def test_expired_handoff_is_not_injected(tmp_path):
    store = ContinuityStore(tmp_path, ttl=timedelta(hours=24))
    store.record_transition(
        lane_key="weixin:dm:user-a",
        source_session_id="old-session",
        target_session_id="new-session",
        messages=_messages(),
        now=NOW,
    )

    note = store.note_for_session(
        lane_key="weixin:dm:user-a",
        target_session_id="new-session",
        now=NOW + timedelta(hours=25),
    )

    assert note is None


def test_empty_or_non_conversational_transcript_does_not_create_handoff(tmp_path):
    store = ContinuityStore(tmp_path)

    assert store.record_transition(
        lane_key="weixin:dm:user-a",
        source_session_id="old-session",
        target_session_id="new-session",
        messages=[
            {"role": "system", "content": "prompt"},
            {"role": "tool", "content": "result"},
        ],
        now=NOW,
    ) is False


def test_handoff_is_bounded_to_recent_messages_and_characters(tmp_path):
    store = ContinuityStore(tmp_path, max_messages=4, max_chars=180)
    messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn-{index}-" + "很长" * 30}
        for index in range(12)
    ]

    assert store.record_transition(
        lane_key="weixin:dm:user-a",
        source_session_id="old-session",
        target_session_id="new-session",
        messages=messages,
        now=NOW,
    ) is True

    handoff = store.get_handoff(
        lane_key="weixin:dm:user-a",
        target_session_id="new-session",
        now=NOW,
    )
    assert handoff is not None
    assert len(handoff.recent_exchange) <= 4
    assert sum(len(message.content) for message in handoff.recent_exchange) <= 180
    assert all("turn-0-" not in message.content for message in handoff.recent_exchange)


def test_storage_failure_degrades_without_blocking_the_caller(tmp_path, monkeypatch):
    store = ContinuityStore(tmp_path)
    monkeypatch.setattr(store, "_connect", lambda: (_ for _ in ()).throw(OSError("locked")))

    assert store.record_transition(
        lane_key="weixin:dm:user-a",
        source_session_id="old-session",
        target_session_id="new-session",
        messages=_messages(),
        now=NOW,
    ) is False
    assert store.note_for_session(
        lane_key="weixin:dm:user-a",
        target_session_id="new-session",
        now=NOW,
    ) is None


def test_runtime_helpers_only_share_continuity_inside_h2os_private_dm(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("H2OS_HOME", str(tmp_path))
    monkeypatch.setenv("H2OS_RUNTIME_ID", "h2os-companion-v0.2")

    assert record_reset_handoff(
        lane_key="agent:main:weixin:dm:user-a",
        chat_type="dm",
        source_session_id="old-session",
        target_session_id="new-session",
        messages=_messages(),
        now=NOW,
    ) is True
    assert note_for_reset_session(
        lane_key="agent:main:weixin:dm:user-a",
        chat_type="dm",
        target_session_id="new-session",
        now=NOW,
    ) is not None

    assert record_reset_handoff(
        lane_key="agent:main:weixin:group:group-a",
        chat_type="group",
        source_session_id="old-group-session",
        target_session_id="new-group-session",
        messages=_messages(),
        now=NOW,
    ) is False

    monkeypatch.delenv("H2OS_RUNTIME_ID")
    assert note_for_reset_session(
        lane_key="agent:main:weixin:dm:user-a",
        chat_type="dm",
        target_session_id="new-session",
        now=NOW,
    ) is None
