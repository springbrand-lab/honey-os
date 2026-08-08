"""Trusted, companion-native presentation for permission requests.

The relationship sentence is deliberately separate from the deterministic
facts.  A platform may phrase the former in the current companion's voice,
but it must render the latter unchanged so personality can never widen the
permission being requested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PermissionPresentation:
    narration: str
    summary: str
    boundaries: tuple[str, ...]
    technical_detail: str
    allow_session: bool
    allow_permanent: bool


_URL_RE = re.compile(r"https?://[^\s'\"]+", re.IGNORECASE)


def _host_from_text(text: str) -> str:
    match = _URL_RE.search(text)
    if not match:
        return "外部网站"
    return urlsplit(match.group(0)).hostname or "外部网站"


def _trusted_facts(command: str, description: str) -> tuple[str, tuple[str, ...]]:
    combined = f"{description}\n{command}".lower()
    host = _host_from_text(f"{description} {command}")
    if "curl" in combined and any(flag in combined for flag in (" -t ", "--upload-file", " -f ", "multipart")):
        return (
            f"把一个文件发到 {host}",
            ("会把本机文件发到外部网站", f"接收方是 {host}"),
        )
    if any(word in combined for word in ("upload", "上传")):
        return (
            f"把一个文件发到 {host}",
            ("会把本机文件发到外部网站", f"接收方是 {host}"),
        )
    if "build" in combined or "构建" in combined:
        return "运行本机上的构建脚本", ("脚本会在 HoneyOS 项目空间里运行",)
    if any(word in combined for word in ("delete", "remove", "删除")):
        return "删除一项本机内容", ("删除后可能无法恢复",)
    if any(word in combined for word in ("send", "message", "发送")):
        return "替你向外发送一条消息", ("内容会离开这台电脑",)
    if any(word in combined for word in ("schedule", "cron", "定时")):
        return "建立一个以后会自动执行的安排", ("到时间后会在你不操作时执行",)
    return "使用一次本机能力继续这件事", ("只授权下面显示的这一步",)


def build_permission_presentation(
    *,
    command: str,
    description: str,
    allow_session: bool,
    allow_permanent: bool,
) -> PermissionPresentation:
    summary, boundaries = _trusted_facts(str(command or ""), str(description or ""))
    return PermissionPresentation(
        narration="我得借一下你电脑的能力，才能把这件事继续做完。只会做下面这一步，让我继续吗？",
        summary=summary,
        boundaries=boundaries,
        technical_detail=str(command or ""),
        allow_session=bool(allow_session),
        allow_permanent=bool(allow_permanent and allow_session),
    )


__all__ = ["PermissionPresentation", "build_permission_presentation"]
