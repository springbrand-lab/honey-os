from __future__ import annotations

import json

import pytest

from honeyos.companion.config import initialize_home
from honeyos.companion.memory_policy import (
    MemoryAuditEvent,
    audit_memory_write,
    check_companion_write,
    scrub_sensitive_companion_state,
)
from honeyos.tools.memory_tool import MemoryStore, memory_tool
from honeyos.tools.skill_provenance import reset_current_write_origin, set_current_write_origin


@pytest.fixture()
def companion_home(tmp_path, monkeypatch):
    initialize_home(tmp_path)
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def store(tmp_path, monkeypatch):
    memory_dir = tmp_path / "store"
    monkeypatch.setattr("honeyos.tools.memory_tool.get_memory_dir", lambda: memory_dir)
    result = MemoryStore(memory_char_limit=500, user_char_limit=300)
    result.load_from_disk()
    return result


def test_background_review_write_is_blocked_in_companion_mode(companion_home):
    decision = check_companion_write(origin="background_review", action="add")

    assert decision.allowed is False
    assert "companion" in decision.reason.lower()


def test_foreground_write_is_allowed_and_audited(companion_home):
    decision = check_companion_write(origin="foreground", action="add")
    assert decision.allowed is True

    audit_memory_write(
        MemoryAuditEvent(
            target="user",
            action="add",
            origin="foreground",
            content="用户明确偏好短回复",
        )
    )

    rows = (companion_home / "logs" / "memory-audit.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    row = json.loads(rows[0])
    assert row["target"] == "user"
    assert row["action"] == "add"
    assert row["origin"] == "foreground"
    assert row["content"] == "用户明确偏好短回复"
    assert "api_key" not in json.dumps(row).lower()


def test_memory_tool_rejects_background_review_without_mutating(
    companion_home, store
):
    token = set_current_write_origin("background_review")
    try:
        result = json.loads(
            memory_tool(action="add", target="user", content="未经确认的推断", store=store)
        )
    finally:
        reset_current_write_origin(token)

    assert result["success"] is False
    assert store.user_entries == []


def test_memory_tool_audits_successful_foreground_write(companion_home, store):
    result = json.loads(
        memory_tool(action="add", target="user", content="用户明确偏好短回复", store=store)
    )

    assert result["success"] is True
    rows = (companion_home / "logs" / "memory-audit.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert json.loads(rows[-1])["content"] == "用户明确偏好短回复"


@pytest.mark.parametrize(
    "content",
    [
        "API_KEY=sk-test-secret-1234567890",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "Night key: night_nak_abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_companion_memory_rejects_credential_bearing_content(
    companion_home, store, content
):
    result = json.loads(
        memory_tool(action="add", target="memory", content=content, store=store)
    )

    assert result["success"] is False
    assert store.memory_entries == []
    assert content not in (companion_home / "logs" / "memory-audit.jsonl").read_text(
        encoding="utf-8"
    ) if (companion_home / "logs" / "memory-audit.jsonl").exists() else True


def test_assistant_mode_preserves_background_memory_behavior(
    companion_home, store
):
    (companion_home / "config.yaml").write_text(
        "agent:\n  mode: assistant\nmemory:\n  write_approval: false\n",
        encoding="utf-8",
    )
    token = set_current_write_origin("background_review")
    try:
        result = json.loads(
            memory_tool(action="add", target="memory", content="assistant fact", store=store)
        )
    finally:
        reset_current_write_origin(token)

    assert result["success"] is True
    assert "assistant fact" in store.memory_entries
    assert not (companion_home / "logs" / "memory-audit.jsonl").exists()


def test_upgrade_scrubs_legacy_credentials_but_keeps_safe_memory(companion_home):
    memory_path = companion_home / "memories" / "MEMORY.md"
    memory_path.write_text(
        "用户喜欢短回复\n§\nNight key: night_nak_abcdefghijklmnopqrstuvwxyz123456\n",
        encoding="utf-8",
    )
    audit_path = companion_home / "logs" / "memory-audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "target": "memory",
                "action": "add",
                "content": "Night key: night_nak_abcdefghijklmnopqrstuvwxyz123456",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    changed = scrub_sensitive_companion_state(companion_home)

    assert changed is True
    assert memory_path.read_text(encoding="utf-8").strip() == "用户喜欢短回复"
    assert "night_nak_" not in audit_path.read_text(encoding="utf-8")
    assert list((companion_home / "memories").glob("MEMORY.md.bak.*"))
