from __future__ import annotations

from honeyos.tools.tirith_security import _is_benign_emoji_variation_selector_finding


def test_normal_emoji_presentation_selector_is_not_a_command_warning():
    finding = {
        "rule_id": "variation_selector",
        "title": "Variation selector characters detected",
    }

    assert _is_benign_emoji_variation_selector_finding(
        finding, "printf '⚖️' > game/index.html"
    )


def test_supplemental_variation_selectors_remain_security_warnings():
    finding = {
        "rule_id": "variation_selector",
        "title": "Variation selector characters detected",
    }

    assert not _is_benign_emoji_variation_selector_finding(
        finding, "printf 'hidden\U000e0100' > game/index.html"
    )
