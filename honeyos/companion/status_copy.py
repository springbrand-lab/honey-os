"""Stable, non-technical status copy for the HoneyOS companion experience."""

from __future__ import annotations


def busy_acknowledgement(state: str) -> str:
    """Explain a follow-up received during an active turn without runtime jargon."""
    if state in {"steer", "redirect"}:
        return "我还在处理你上一句话，这句也看见了。我会按你刚说的调整，等我一下。"
    if state == "queue":
        return "我还在处理上一句，这句先替你收好了。等我忙完就接着回你。"
    return "我看见了。我先停一下刚才的事，马上回来回你。"


def long_running_acknowledgement() -> str:
    return "我还在弄，没消失。弄好就回来告诉你。"


def gateway_transition_acknowledgement(*, queued: bool) -> str:
    if queued:
        return "我正在重新连回来，这句话先替你收好，等我一下。"
    return "我正在重新连回来，等我一下，很快就好。"


def queued_command_acknowledgement(depth: int) -> str:
    if depth <= 1:
        return "这句先替你收好了，等我忙完就接着回你。"
    return f"都替你收好了，现在还有 {depth} 句。等我忙完就接着回你。"


__all__ = [
    "busy_acknowledgement",
    "gateway_transition_acknowledgement",
    "long_running_acknowledgement",
    "queued_command_acknowledgement",
]
