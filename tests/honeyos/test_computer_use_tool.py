from honeyos.tools.computer_use.tool import (
    _DESTRUCTIVE_ACTIONS,
    _computer_effect_requires_consent,
)


def test_reversible_navigation_actions_do_not_use_the_legacy_approval_gate():
    assert "scroll" not in _DESTRUCTIVE_ACTIONS
    assert "focus_app" not in _DESTRUCTIVE_ACTIONS
    assert "cua_browser_navigate" not in _DESTRUCTIVE_ACTIONS
    assert "cua_browser_pointer" not in _DESTRUCTIVE_ACTIONS


def test_declared_external_commit_requires_consent():
    assert _computer_effect_requires_consent({"action": "click", "effect": "submit"})
    assert _computer_effect_requires_consent({"action": "type", "effect": "credential"})


def test_ordinary_reversible_click_has_no_commit_effect():
    assert not _computer_effect_requires_consent({"action": "click"})
