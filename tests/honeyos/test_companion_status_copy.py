import pytest
from pathlib import Path

from honeyos.companion.status_copy import (
    busy_acknowledgement,
    gateway_transition_acknowledgement,
    long_running_acknowledgement,
    queued_command_acknowledgement,
)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            "steer",
            "我还在处理你上一句话，这句也看见了。我会按你刚说的调整，等我一下。",
        ),
        (
            "redirect",
            "我还在处理你上一句话，这句也看见了。我会按你刚说的调整，等我一下。",
        ),
        (
            "queue",
            "我还在处理上一句，这句先替你收好了。等我忙完就接着回你。",
        ),
        (
            "interrupt",
            "我看见了。我先停一下刚才的事，马上回来回你。",
        ),
    ],
)
def test_busy_acknowledgements_sound_like_a_companion(state, expected):
    assert busy_acknowledgement(state) == expected


def test_companion_status_copy_never_exposes_runtime_vocabulary():
    messages = [
        busy_acknowledgement("steer"),
        busy_acknowledgement("redirect"),
        busy_acknowledgement("queue"),
        busy_acknowledgement("interrupt"),
        long_running_acknowledgement(),
        gateway_transition_acknowledgement(queued=True),
        gateway_transition_acknowledgement(queued=False),
        queued_command_acknowledgement(1),
        queued_command_acknowledgement(3),
    ]
    forbidden = (
        "Redirected",
        "iteration",
        "terminal",
        "Subagent",
        "Compressing",
        "Gateway",
        "Working",
        "/busy",
        "/stop",
    )

    for message in messages:
        assert not any(term in message for term in forbidden)


def test_long_running_and_transition_copy_reassures_without_debug_details():
    assert long_running_acknowledgement() == "我还在弄，没消失。弄好就回来告诉你。"
    assert gateway_transition_acknowledgement(queued=True) == (
        "我正在重新连回来，这句话先替你收好，等我一下。"
    )
    assert gateway_transition_acknowledgement(queued=False) == (
        "我正在重新连回来，等我一下，很快就好。"
    )


def test_queued_command_acknowledgement_reports_depth_in_plain_language():
    assert queued_command_acknowledgement(1) == "这句先替你收好了，等我忙完就接着回你。"
    assert queued_command_acknowledgement(3) == "都替你收好了，现在还有 3 句。等我忙完就接着回你。"


def test_gateway_routes_honeyos_status_surfaces_through_companion_copy():
    run_source = (
        Path(__file__).parents[2] / "honeyos" / "gateway" / "run.py"
    ).read_text(encoding="utf-8")

    assert "busy_acknowledgement(" in run_source
    assert "long_running_acknowledgement(" in run_source
    assert "gateway_transition_acknowledgement(" in run_source
    assert "queued_command_acknowledgement(" in run_source
    assert "if not _is_honeyos_runtime():\n            # First-touch onboarding" in run_source
