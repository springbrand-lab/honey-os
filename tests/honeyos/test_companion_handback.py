from __future__ import annotations

from types import SimpleNamespace

from honeyos.agent.companion_handback import append_companion_handback


def _agent(mode: str = "companion") -> SimpleNamespace:
    return SimpleNamespace(_agent_mode=mode)


def test_handback_is_only_added_after_a_tool_result(tmp_path):
    before_tools = [{"role": "user", "content": "查一下这个消息"}]
    after_tools = [
        *before_tools,
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "web_search"}}],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "搜索结果"},
    ]

    assert (
        append_companion_handback("BASE", _agent(), before_tools, 0, home=tmp_path)
        == "BASE"
    )

    result = append_companion_handback("BASE", _agent(), after_tools, 0, home=tmp_path)

    assert result.startswith("BASE\n\n<companion_handback>")
    assert "匿名搜索引擎、客服、工作助理或通用 Agent" in result
    assert "温暖、敏锐、自信" in result


def test_handback_uses_current_identity_and_relationship_without_leaking_secrets(
    tmp_path,
):
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "IDENTITY.md").write_text(
        "名字：阿凛\n性格：冷静、毒舌、惜字如金\napi_key=sk-super-secret-value",
        encoding="utf-8",
    )
    (memories / "RELATIONSHIP.md").write_text(
        "关系：恋爱伴侣\n称呼用户：队长",
        encoding="utf-8",
    )
    messages = [
        {"role": "user", "content": "运行测试"},
        {"role": "tool", "tool_call_id": "call-1", "content": "3 passed"},
    ]

    result = append_companion_handback("BASE", _agent(), messages, 0, home=tmp_path)

    assert "阿凛" in result
    assert "冷静、毒舌、惜字如金" in result
    assert "恋爱伴侣" in result
    assert "队长" in result
    assert "sk-super-secret-value" not in result
    assert "符合上面的具体人格" in result
    assert "不要机械添加昵称、追问、撒娇或情话" in result


def test_handback_never_changes_assistant_mode_or_persisted_messages(tmp_path):
    messages = [
        {"role": "user", "content": "运行测试"},
        {"role": "tool", "tool_call_id": "call-1", "content": "3 passed"},
    ]
    original = [dict(message) for message in messages]

    result = append_companion_handback(
        "BASE", _agent("assistant"), messages, 0, home=tmp_path
    )

    assert result == "BASE"
    assert messages == original
