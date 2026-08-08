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

    del preview, args
    kind = activity_kind(tool_name)
    normalized_event = str(event_type or "").strip().lower()
    if normalized_event in {"tool.completed", "completed", "done"}:
        return {
            "activity_id": str(activity_id or "activity"),
            "kind": kind,
            "state": "completed",
            "title": _COMPLETED_COPY[kind],
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
    title, detail = _ACTIVE_COPY[kind]
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
