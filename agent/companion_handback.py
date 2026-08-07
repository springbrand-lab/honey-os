"""Request-only companion identity handback after tool execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from agent.redact import redact_sensitive_text
from hermes_constants import get_hermes_home


_DEFAULT_IDENTITY = (
    "使用 HoneyOS 默认人格：温暖、敏锐、自信，有自己的判断；表达简短、自然、"
    "口语化，可以轻微俏皮和暧昧，但不机械撒娇或强行使用亲昵称呼。"
)
_DEFAULT_RELATIONSHIP = "私人亲密关系伴侣；双方尚未明确命名更具体的关系、称呼或仪式。"
_PROFILE_FILE_LIMIT = 2400


def _read_profile_file(home: Path, filename: str, fallback: str) -> str:
    try:
        content = (home / "memories" / filename).read_text(encoding="utf-8").strip()
    except OSError:
        content = ""
    if not content:
        return fallback
    return redact_sensitive_text(content, force=True)[:_PROFILE_FILE_LIMIT].strip()


def _has_current_turn_tool_result(
    messages: Sequence[Mapping[str, Any]], current_turn_user_idx: int
) -> bool:
    start = max(int(current_turn_user_idx) + 1, 0)
    return any(
        isinstance(message, Mapping) and message.get("role") == "tool"
        for message in messages[start:]
    )


def build_companion_handback(home: Path) -> str:
    """Render a bounded persona-aware reminder for the post-tool model call."""

    resolved = Path(home).expanduser().resolve()
    identity = _read_profile_file(resolved, "IDENTITY.md", _DEFAULT_IDENTITY)
    relationship = _read_profile_file(
        resolved, "RELATIONSHIP.md", _DEFAULT_RELATIONSHIP
    )
    return f"""<companion_handback>
你刚刚为了用户调用了工具。继续执行，直到任务真实完成；如果还需要工具，继续调用。

当你最终向用户交付结果时，必须以当前这个具体伴侣的身份表达，而不是匿名搜索引擎、客服、工作助理或通用 Agent。

当前伴侣身份：
{identity}

当前关系：
{relationship}

先准确交付专业结果，再选择一项与当前话题真正相关的关系动作：关心用户为什么需要结果、表达符合上面的具体人格的判断或反应、联系双方正在进行的事情，或主动承接一个确实有价值的下一步。

关系动作和语言必须符合上面的具体人格及关系阶段。不要机械添加昵称、追问、撒娇或情话；严肃、紧急、医疗、法律和工作场景保持合适分寸。不要为了表现亲密而稀释事实、代码、结论或风险提示。
</companion_handback>"""


def append_companion_handback(
    effective_system: str,
    agent: Any,
    messages: Sequence[Mapping[str, Any]],
    current_turn_user_idx: int,
    *,
    home: Path | None = None,
) -> str:
    """Append a request-only handback when this companion turn used tools."""

    if getattr(agent, "_agent_mode", "assistant") != "companion":
        return effective_system
    if not _has_current_turn_tool_result(messages, current_turn_user_idx):
        return effective_system
    handback = build_companion_handback(home or get_hermes_home())
    return (
        f"{effective_system.rstrip()}\n\n{handback}" if effective_system else handback
    )


__all__ = ["append_companion_handback", "build_companion_handback"]
