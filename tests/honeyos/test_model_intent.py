from __future__ import annotations

import pytest

from honeyos.gateway.config import Platform
from honeyos.gateway.platforms.base import MessageEvent
from honeyos.gateway.session import SessionSource


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("换到 Claude Sonnet", "/model sonnet --global"),
        ("帮我切换成 gpt-5", "/model gpt-5 --global"),
        ("以后默认都用 Gemini", "/model gemini --global"),
        ("换模型", "/model"),
        ("这次先用 Sonnet 试试", "/model sonnet --session"),
        ("当前对话换成 DeepSeek", "/model deepseek --session"),
        ("下一条用 Haiku 回答", "/model haiku --once"),
    ],
)
def test_explicit_natural_language_model_switches_become_model_commands(text, expected):
    from honeyos.companion.model_intent import natural_model_command

    assert natural_model_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "怎么换模型？",
        "你能帮我换模型吗？",
        "换模型有什么影响？",
        "不要换模型",
        "如果换成 Sonnet 会怎样？",
        "我觉得以后也许可以换模型",
        "他说‘换到 Sonnet’是什么意思？",
    ],
)
def test_questions_negations_and_quoted_examples_do_not_switch_models(text):
    from honeyos.companion.model_intent import natural_model_command

    assert natural_model_command(text) is None


def test_companion_event_rewrite_is_limited_to_private_text_messages(monkeypatch):
    from honeyos.companion.model_intent import rewrite_companion_model_event

    source = SessionSource(
        platform=Platform.API_SERVER,
        user_id="local-owner",
        chat_id="local-owner",
        chat_type="dm",
    )
    event = MessageEvent(text="换到 Sonnet", source=source)

    monkeypatch.delenv("HONEYOS_RUNTIME_ID", raising=False)
    assert rewrite_companion_model_event(event) is event
    assert event.text == "换到 Sonnet"

    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")
    rewritten = rewrite_companion_model_event(event)
    assert rewritten is not event
    assert rewritten.text == "/model sonnet --global"
    assert rewritten.get_command() == "model"
    assert rewritten.get_command_args() == "sonnet --global"

    group = MessageEvent(
        text="换到 Sonnet",
        source=SessionSource(
            platform=Platform.FEISHU,
            user_id="user-a",
            chat_id="group-a",
            chat_type="group",
        ),
    )
    assert rewrite_companion_model_event(group) is group


def test_companion_prompt_says_model_switching_is_a_user_capability():
    from honeyos.agent.prompt_builder import COMPANION_MODEL_CONTROL_GUIDANCE

    assert "自然语言" in COMPANION_MODEL_CONTROL_GUIDANCE
    assert "全局默认模型" in COMPANION_MODEL_CONTROL_GUIDANCE
    assert "不要声称没有权限" in COMPANION_MODEL_CONTROL_GUIDANCE
    assert "config.yaml" in COMPANION_MODEL_CONTROL_GUIDANCE
