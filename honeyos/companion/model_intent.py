"""Deterministic natural-language model controls for the private companion."""

from __future__ import annotations

import dataclasses
import os
import re
from typing import Optional


_QUESTION_MARKERS = (
    "?",
    "？",
    "怎么",
    "如何",
    "为什么",
    "有什么",
    "会怎样",
    "会怎么样",
    "能不能",
    "可以吗",
    "行不行",
    "是什么意思",
)
_NEGATION_MARKERS = ("不要", "别换", "不用换", "不想换", "先别", "别给我")
_SPECULATIVE_MARKERS = ("如果", "假如", "也许", "可能", "我觉得")
_QUOTE_MARKERS = ("‘", "’", "“", "”", '"')

_FRIENDLY_TARGETS = {
    "claude sonnet": "sonnet",
    "claude-sonnet": "sonnet",
    "sonnet": "sonnet",
    "claude opus": "opus",
    "claude-opus": "opus",
    "opus": "opus",
    "claude haiku": "haiku",
    "claude-haiku": "haiku",
    "haiku": "haiku",
    "claude": "claude",
    "gemini": "gemini",
    "deepseek": "deepseek",
}

_MODEL_ID_PREFIXES = (
    "gpt-",
    "o1",
    "o3",
    "o4",
    "claude-",
    "gemini-",
    "deepseek-",
    "qwen",
    "mistral-",
    "llama-",
    "kimi-",
    "doubao-",
    "grok-",
)


def _clean_target(raw: str) -> str:
    target = raw.strip(" \t，,。.!！?？")
    target = re.sub(r"(?:这个)?模型$", "", target, flags=re.IGNORECASE).strip()
    target = re.sub(
        r"(?:来)?(?:回答)?(?:一下|试试|看看)?(?:吧|了|呗)?$",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip(" \t，,。.!！?？")
    return _FRIENDLY_TARGETS.get(target.casefold(), target)


def _looks_like_model_target(raw: str, *, explicit_model_word: bool) -> bool:
    """Keep bare “use X” commands narrow enough to avoid tool-name capture."""

    target = _clean_target(raw)
    folded = target.casefold()
    if not target:
        return False
    if explicit_model_word:
        return True
    if folded in _FRIENDLY_TARGETS or folded in _FRIENDLY_TARGETS.values():
        return True
    if any(char.isspace() for char in target):
        return False
    if "/" in target:
        provider, _, model = target.partition("/")
        return bool(provider and model)
    return folded.startswith(_MODEL_ID_PREFIXES)


def natural_model_command(text: str) -> Optional[str]:
    """Return a canonical ``/model`` command for an explicit user instruction.

    The recognizer is intentionally narrow. Questions, negations, speculation,
    and quoted examples stay in the normal conversation path.
    """

    value = " ".join((text or "").strip().split())
    if not value or value.startswith("/") or "\n" in (text or ""):
        return None
    if any(marker in value for marker in _QUESTION_MARKERS):
        return None
    if any(marker in value for marker in _NEGATION_MARKERS):
        return None
    if any(marker in value for marker in _SPECULATIVE_MARKERS):
        return None
    if any(marker in value for marker in _QUOTE_MARKERS):
        return None

    bare = value.rstrip("。.!！")
    if bare in {"换模型", "切换模型", "更换模型", "选择模型"}:
        return "/model"

    scope = "--global"
    if re.match(r"^(?:下一条|下条|下一句)", value):
        scope = "--once"
        value = re.sub(r"^(?:下一条|下条|下一句)(?:回复)?", "", value).strip()
    elif re.match(r"^(?:这次|这一轮|本轮|当前对话)", value):
        scope = "--session"
        value = re.sub(r"^(?:这次|这一轮|本轮|当前对话)(?:先)?", "", value).strip()
    else:
        value = re.sub(r"^(?:以后|今后)(?:默认)?(?:都)?", "", value).strip()

    value = re.sub(r"^(?:请|麻烦|帮我|给我)(?:把)?", "", value).strip()
    patterns = (
        (
            r"^(?:把)?(?:模型)?(?:切换|切|换|更换|改)(?:模型)?(?:到|成|为|用)?\s*(.+)$",
            False,
        ),
        (r"^(?:默认)?(?:都)?(?:改用|使用|用)\s*(.+)$", True),
    )
    target = ""
    for pattern, require_model_like in patterns:
        match = re.match(pattern, value, flags=re.IGNORECASE)
        if match:
            if require_model_like and not _looks_like_model_target(
                match.group(1), explicit_model_word="模型" in value
            ):
                continue
            target = _clean_target(match.group(1))
            break
    if not target or target in {"模型", "一个模型"}:
        return None
    return f"/model {target} {scope}"


def rewrite_companion_model_event(event):
    """Rewrite explicit private companion requests into the existing command path."""

    if not os.environ.get("HONEYOS_RUNTIME_ID", "").startswith("honeyos-companion-"):
        return event
    source = getattr(event, "source", None)
    if str(getattr(source, "chat_type", "") or "").lower() != "dm":
        return event
    if getattr(event, "media_urls", None):
        return event
    command = natural_model_command(getattr(event, "text", ""))
    if not command:
        return event
    return dataclasses.replace(event, text=command)
