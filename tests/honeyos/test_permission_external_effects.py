import json
from unittest.mock import patch

from honeyos.tools.permission_policy import (
    grants_from_user_task,
    reset_turn_intent_grants,
    set_turn_intent_grants,
)
from honeyos.tools.send_message_tool import send_message_tool
from honeyos.tools.cronjob_tools import _cron_effect_for_create
from honeyos.tools.permission_policy import RiskTier, decide_effect


def test_explicit_named_message_sends_without_a_second_prompt():
    token = set_turn_intent_grants(
        grants_from_user_task("给小王发送今晚见", turn_id="turn-send")
    )
    try:
        with (
            patch(
                "honeyos.tools.send_message_tool._handle_send",
                return_value='{"success": true}',
            ) as send,
            patch("honeyos.tools.approval.request_tool_approval") as approval,
        ):
            result = send_message_tool(
                {"action": "send", "target": "feishu:小王", "message": "今晚见"}
            )
    finally:
        reset_turn_intent_grants(token)

    assert json.loads(result)["success"] is True
    send.assert_called_once()
    approval.assert_not_called()


def test_agent_initiated_cross_chat_message_requests_consent():
    with (
        patch("honeyos.tools.send_message_tool._handle_send") as send,
        patch(
            "honeyos.tools.approval.request_tool_approval",
            return_value={
                "approved": False,
                "status": "pending_approval",
                "message": "waiting",
                "approval_pending": True,
            },
        ) as approval,
    ):
        result = send_message_tool(
            {"action": "send", "target": "feishu:小王", "message": "今晚见"}
        )

    payload = json.loads(result)
    assert payload["status"] == "pending_approval"
    assert payload["approval_pending"] is True
    approval.assert_called_once()
    send.assert_not_called()


def test_message_listing_and_reactions_do_not_enter_the_external_send_gate():
    with (
        patch("honeyos.tools.send_message_tool._handle_list", return_value="listed"),
        patch("honeyos.tools.approval.request_tool_approval") as approval,
    ):
        result = send_message_tool({"action": "list"})

    assert result == "listed"
    approval.assert_not_called()


def test_ordinary_reminder_has_no_unattended_external_effect():
    effect = _cron_effect_for_create(
        prompt="提醒我起来走一走",
        schedule="0 9 * * *",
        deliver="origin",
        script=None,
        no_agent=False,
    )

    assert effect is None


def test_future_message_or_script_is_an_unattended_effect():
    message_effect = _cron_effect_for_create(
        prompt="给小王发送日报",
        schedule="0 9 * * *",
        deliver="feishu:小王",
        script=None,
        no_agent=False,
    )
    script_effect = _cron_effect_for_create(
        prompt="",
        schedule="*/5 * * * *",
        deliver="origin",
        script="watch.py",
        no_agent=True,
    )

    assert message_effect is not None and message_effect.unattended
    assert script_effect is not None and script_effect.unattended


def test_explicit_schedule_instruction_covers_the_current_schedule_effect():
    token = set_turn_intent_grants(
        grants_from_user_task("每天9点给小王发送日报", turn_id="turn-cron")
    )
    try:
        effect = _cron_effect_for_create(
            prompt="给小王发送日报",
            schedule="0 9 * * *",
            deliver="feishu:小王",
            script=None,
            no_agent=False,
        )
        decision = decide_effect(effect)
    finally:
        reset_turn_intent_grants(token)

    assert decision.tier is RiskTier.DIRECT
