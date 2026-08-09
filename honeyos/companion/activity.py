"""Safe, relationship-native projections of agent tool activity."""

from __future__ import annotations

from typing import Any


_TOOL_KINDS = {
    "checking": frozenset({
        "web_search",
        "web_extract",
        "web_fetch",
        "browser_navigate",
        "browser_search",
        "x_search",
        "maps",
    }),
    "reading": frozenset({
        "read_file",
        "read_many_files",
        "vision_analyze",
        "session_search",
        "memory_get",
    }),
    "making": frozenset({
        "write_file",
        "edit_file",
        "patch",
        "image_generate",
        "document_create",
    }),
    "remembering": frozenset({
        "memory",
        "companion_memory",
        "todo",
        "todo_write",
        "cronjob",
    }),
    "handling": frozenset({
        "terminal",
        "bash",
        "code_execution",
        "computer_use",
        "skills",
        "skills_list",
        "skill_manage",
        "skill_marketplace",
        "mcp",
    }),
}

_ACTIVE_COPY = {
    "checking": ("正在认真核对", "我在看几处相关内容"),
    "reading": ("正在认真看", "我在读你发来的内容"),
    "making": ("正在把它做好", "我在一点点整理"),
    "remembering": ("正在替你记下", "我会把这件事放在心上"),
    "handling": ("正在替你处理", "我还在这里，等我一下"),
}

_COMPLETED_COPY = {
    "checking": "已经替你核对过了",
    "reading": "已经认真看过了",
    "making": "已经替你做好了",
    "remembering": "已经替你记下了",
    "handling": "已经替你处理好了",
}

_TOOL_ACTIVE_COPY = {
    "web_search": ("正在找相关内容", "我先替你找找看"),
    "web_fetch": ("正在看相关内容", "我打开仔细看看"),
    "browser_navigate": ("正在打开页面", "我进去看看里面有什么"),
    "skills_list": ("正在看看现有能力", "我先翻一遍已经会的"),
    "skill_view": ("正在看使用说明", "我先弄清楚怎么用"),
    "write_file": ("正在把文件写好", "我在把内容落下来"),
    "edit_file": ("正在调整内容", "我在把细节改好"),
    "patch": ("正在调整内容", "我在把细节改好"),
    "read_file": ("正在看这个文件", "我先把内容看清楚"),
    "terminal": ("正在执行这一步", "我在替你把它跑完"),
    "bash": ("正在执行这一步", "我在替你把它跑完"),
    "execute_code": ("正在跑一下代码", "我在确认它能正常工作"),
    "code_execution": ("正在跑一下代码", "我在确认它能正常工作"),
    "computer_use": ("正在替你操作", "我在电脑上继续处理"),
}

_TOOL_COMPLETED_COPY = {
    "web_search": "已经找到相关内容了",
    "web_fetch": "已经看过相关内容了",
    "browser_navigate": "这个页面已经看过了",
    "skills_list": "已经看过现有能力了",
    "skill_view": "已经读完使用说明了",
    "write_file": "文件已经替你写好了",
    "edit_file": "内容已经替你改好了",
    "patch": "内容已经替你改好了",
    "read_file": "这个文件已经看过了",
    "terminal": "这一步已经执行完了",
    "bash": "这一步已经执行完了",
    "execute_code": "代码已经跑完了",
    "code_execution": "代码已经跑完了",
    "computer_use": "已经替你操作好了",
}

_TOOL_ACTION_COPY = {
    ("skill_marketplace", "search"): (
        ("正在找合适的能力", "我去看看有没有正好能用的"),
        "找到了可以用的能力",
    ),
    ("skill_marketplace", "install"): (
        ("正在准备新能力", "我把它装好就能继续用了"),
        "新能力已经准备好了",
    ),
    ("skill_manage", "create"): (
        ("正在整理新能力", "我把这套做法收好"),
        "新能力已经整理好了",
    ),
    ("skill_manage", "patch"): (
        ("正在完善这项能力", "我把刚发现的问题补上"),
        "这项能力已经完善好了",
    ),
    ("skill_manage", "edit"): (
        ("正在完善这项能力", "我把刚发现的问题补上"),
        "这项能力已经完善好了",
    ),
}


def _normalized_tool_name(tool_name: str | None) -> str:
    value = str(tool_name or "").strip().lower().replace("-", "_")
    if value.startswith("mcp__"):
        return "mcp"
    return value.rsplit(".", 1)[-1]


def activity_kind(tool_name: str | None) -> str:
    """Return one user-facing semantic kind without exposing the tool name."""

    normalized = _normalized_tool_name(tool_name)
    for kind, names in _TOOL_KINDS.items():
        if normalized in names:
            return kind
        if any(token in normalized for token in names if len(token) >= 5):
            return kind
    return "handling"


def _safe_action(args: Any) -> str:
    """Read only a bounded action discriminator, never user-provided values."""

    if not isinstance(args, dict):
        return ""
    action = args.get("action")
    if not isinstance(action, str):
        return ""
    return action.strip().lower()[:32]


def _activity_copy(tool_name: str | None, args: Any) -> tuple[tuple[str, str], str]:
    normalized = _normalized_tool_name(tool_name)
    action_copy = _TOOL_ACTION_COPY.get((normalized, _safe_action(args)))
    if action_copy is not None:
        return action_copy
    kind = activity_kind(tool_name)
    return (
        _TOOL_ACTIVE_COPY.get(normalized, _ACTIVE_COPY[kind]),
        _TOOL_COMPLETED_COPY.get(normalized, _COMPLETED_COPY[kind]),
    )


def project_activity(
    event_type: str,
    tool_name: str | None,
    *,
    activity_id: str | None = None,
    preview: str | None = None,
    args: Any = None,
) -> dict[str, str]:
    """Project raw tool facts into a safe card payload.

    ``preview`` and ``args`` are accepted at the boundary so callers can pass
    an agent callback through unchanged. They are deliberately never copied to
    the returned payload: commands, paths, queries, and credentials belong in
    logs, not in the companion surface.
    """

    del preview
    kind = activity_kind(tool_name)
    active_copy, completed_copy = _activity_copy(tool_name, args)
    normalized_event = str(event_type or "").strip().lower()
    if normalized_event in {"tool.completed", "completed", "done"}:
        return {
            "activity_id": str(activity_id or "activity"),
            "kind": kind,
            "state": "completed",
            "title": completed_copy,
            "detail": "",
        }
    if normalized_event in {"tool.failed", "failed", "error"}:
        return {
            "activity_id": str(activity_id or "activity"),
            "kind": kind,
            "state": "failed",
            "title": "刚才没走通，我换个办法",
            "detail": "",
        }
    title, detail = active_copy
    return {
        "activity_id": str(activity_id or "activity"),
        "kind": kind,
        "state": "active",
        "title": title,
        "detail": detail,
    }


def project_presence(*, preview: str | None = None) -> dict[str, str]:
    """Return a safe presence cue without exposing model reasoning."""

    del preview
    return {
        "activity_id": "presence",
        "kind": "presence",
        "state": "active",
        "title": "我在想你刚才说的事",
        "detail": "",
    }


__all__ = ["activity_kind", "project_activity", "project_presence"]
