from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _source() -> SessionSource:
    return SessionSource(
        platform=Platform.WEIXIN,
        user_id="user-a",
        chat_id="chat-a",
        user_name="tester",
        chat_type="dm",
    )


def _event() -> MessageEvent:
    return MessageEvent(text="/new", source=_source(), message_id="m1")


def _runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.WEIXIN: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.WEIXIN: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner._session_model_overrides = {}
    runner._session_reasoning_overrides = {}
    runner._pending_model_notes = {}
    runner._background_tasks = set()

    session_key = build_session_key(_source())
    old_entry = SessionEntry(
        session_key=session_key,
        session_id="old-session",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        origin=_source(),
        platform=Platform.WEIXIN,
        chat_type="dm",
    )
    new_entry = SessionEntry(
        session_key=session_key,
        session_id="new-session",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        origin=_source(),
        platform=Platform.WEIXIN,
        chat_type="dm",
        is_fresh_reset=True,
    )
    runner.session_store = MagicMock()
    runner.session_store._entries = {session_key: old_entry}
    runner.session_store._generate_session_key.return_value = session_key
    runner.session_store.reset_session.return_value = new_entry
    runner.session_store.get_or_create_session.return_value = new_entry
    runner.session_store.load_transcript.return_value = [
        {"role": "user", "content": "我们下次继续聊记忆。"},
        {"role": "assistant", "content": "好，我答应你。"},
    ]
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_db = None
    runner._agent_cache_lock = None
    runner._is_user_authorized = lambda _source: True
    runner._format_session_info = lambda: ""
    return runner


@pytest.mark.asyncio
@patch("h2os_cli.continuity.record_reset_handoff")
async def test_new_records_old_to_new_handoff_without_blocking_reset(
    record_reset_handoff, monkeypatch, tmp_path
):
    monkeypatch.setenv("H2OS_HOME", str(tmp_path))
    monkeypatch.setenv("H2OS_RUNTIME_ID", "h2os-companion-v0.2")
    runner = _runner()

    await runner._handle_reset_command(_event())

    record_reset_handoff.assert_called_once()
    call = record_reset_handoff.call_args.kwargs
    assert call["source_session_id"] == "old-session"
    assert call["target_session_id"] == "new-session"
    assert call["chat_type"] == "dm"
    assert call["messages"][-1]["content"] == "好，我答应你。"
