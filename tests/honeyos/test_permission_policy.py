from honeyos.tools.permission_policy import (
    Effect,
    RiskTier,
    decide_effect,
    grants_from_user_task,
    reset_turn_intent_grants,
    set_turn_intent_grants,
)
from honeyos.model_tools import handle_function_call


def test_explicit_send_matches_only_the_same_recipient():
    grants = grants_from_user_task("帮我给小王发一句今晚见", turn_id="turn-1")

    token = set_turn_intent_grants(grants)
    try:
        assert decide_effect(Effect("send", target="小王", external_commit=True)).tier is RiskTier.DIRECT
        assert decide_effect(Effect("send", target="小李", external_commit=True)).tier is RiskTier.CONSENT
    finally:
        reset_turn_intent_grants(token)


def test_capability_question_does_not_create_a_send_grant():
    grants = grants_from_user_task("你可以给小王发消息吗？", turn_id="turn-1")

    assert grants == ()


def test_honeyos_secret_is_always_hard_blocked_even_with_a_grant():
    token = set_turn_intent_grants(
        grants_from_user_task("读取 ~/.honeyos/.env", turn_id="turn-1")
    )
    try:
        decision = decide_effect(
            Effect(
                "read_secret",
                target="~/.honeyos/.env",
                internal_secret=True,
            )
        )
    finally:
        reset_turn_intent_grants(token)

    assert decision.tier is RiskTier.HARD_BLOCK


def test_project_write_is_direct_without_a_grant():
    decision = decide_effect(
        Effect(
            "write_file",
            target="/Users/me/HoneyOS Projects/game/index.html",
            in_workspace=True,
        )
    )

    assert decision.tier is RiskTier.DIRECT


def test_unrequested_external_commit_needs_consent():
    decision = decide_effect(
        Effect("upload", target="example.com", external_commit=True)
    )

    assert decision.tier is RiskTier.CONSENT


def test_intent_grants_are_reset_after_the_tool_scope():
    grants = grants_from_user_task("给小王发送今晚见", turn_id="turn-1")
    token = set_turn_intent_grants(grants)
    reset_turn_intent_grants(token)

    assert decide_effect(Effect("send", target="小王", external_commit=True)).tier is RiskTier.CONSENT


def test_tool_dispatch_receives_current_user_intent_and_resets_it(monkeypatch):
    observed = []

    def fake_dispatch(_name, _args, **_kwargs):
        observed.append(
            decide_effect(Effect("send", target="小王", external_commit=True)).tier
        )
        return '{"ok": true}'

    monkeypatch.setattr("honeyos.model_tools.registry.dispatch", fake_dispatch)

    result = handle_function_call(
        "terminal",
        {"command": "true"},
        user_task="给小王发送今晚见",
        turn_id="turn-2",
        skip_pre_tool_call_hook=True,
        skip_tool_request_middleware=True,
        skip_tool_execution_middleware=True,
    )

    assert result == '{"ok": true}'
    assert observed == [RiskTier.DIRECT]
    assert decide_effect(Effect("send", target="小王", external_commit=True)).tier is RiskTier.CONSENT
