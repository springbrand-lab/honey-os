from __future__ import annotations

import json
from types import SimpleNamespace

from honeyos.companion.permission_ui import build_permission_presentation
from honeyos.gateway.relay.adapter import RelayAdapter
from honeyos.gateway.run import _format_exec_approval_fallback
from honeyos.plugins.platforms.feishu.adapter import FeishuAdapter


def test_permission_presentation_separates_relationship_copy_from_trusted_facts():
    presentation = build_permission_presentation(
        command="curl -T /tmp/photo.png https://example.com/upload",
        description="upload a local file to example.com",
        allow_session=True,
        allow_permanent=True,
    )

    assert "电脑" in presentation.narration
    assert presentation.summary == "把一个文件发到 example.com"
    assert presentation.boundaries
    assert "curl" not in presentation.summary
    assert "curl" in presentation.technical_detail


def test_permission_narration_uses_confirmed_user_nickname(tmp_path):
    from honeyos.companion.config import initialize_home
    from honeyos.companion.profile import update_companion_profile

    initialize_home(tmp_path)
    update_companion_profile(
        tmp_path,
        companion_name="小意",
        personality="嘴硬心软，有主见",
        user_nickname="小酒",
        source="user_explicit",
    )

    presentation = build_permission_presentation(
        command="python3 build.py",
        description="execute a local build script",
        allow_session=True,
        allow_permanent=False,
        home=tmp_path,
    )

    assert presentation.narration.startswith("小酒")
    assert "下面" in presentation.narration
    assert presentation.summary == "运行本机上的构建脚本"


def test_permission_narration_does_not_invent_a_nickname(tmp_path):
    from honeyos.companion.config import initialize_home

    initialize_home(tmp_path)
    presentation = build_permission_presentation(
        command="python3 build.py",
        description="execute a local build script",
        allow_session=True,
        allow_permanent=False,
        home=tmp_path,
    )

    assert "小酒" not in presentation.narration


def test_curl_fail_on_http_error_flag_is_not_mislabeled_as_an_upload():
    presentation = build_permission_presentation(
        command="curl -f https://example.com/status",
        description="network request requiring confirmation",
        allow_session=False,
        allow_permanent=False,
    )

    assert presentation.summary != "把一个文件发到 example.com"


def test_feishu_permission_card_is_compact_chinese_and_collapsible():
    presentation = build_permission_presentation(
        command="python3 build.py",
        description="execute a local build script",
        allow_session=True,
        allow_permanent=True,
    )
    card = FeishuAdapter._build_companion_permission_card(
        presentation=presentation,
        approval_id=7,
        smart_denied=False,
    )
    encoded = json.dumps(card, ensure_ascii=False)

    assert "好，你继续" in encoded
    assert "先别动" in encoded
    assert "看看具体会做什么" in encoded
    assert "collapsible_panel" in encoded
    assert '"expanded": false' in encoded
    assert "Command Approval Required" not in encoded
    assert "Allow Once" not in encoded


def test_feishu_resolved_permission_card_has_no_live_buttons():
    accepted = FeishuAdapter._build_resolved_approval_card(
        choice="once", user_name="小酒"
    )
    denied = FeishuAdapter._build_resolved_approval_card(
        choice="deny", user_name="小酒"
    )

    assert "我继续去做了" in json.dumps(accepted, ensure_ascii=False)
    assert "这次先不做" in json.dumps(denied, ensure_ascii=False)
    assert "button" not in json.dumps(accepted, ensure_ascii=False)


def test_relay_permission_prompt_uses_same_companion_copy():
    payload = RelayAdapter._build_companion_approval_prompt(
        command="python3 build.py",
        description="execute a local build script",
        allow_session=True,
        allow_permanent=False,
        smart_denied=False,
    )

    assert "电脑" in payload["text"] and "下面" in payload["text"]
    assert payload["summary"] == "运行本机上的构建脚本"
    assert [item["label"] for item in payload["options"]] == [
        "好，你继续",
        "本次对话都可以",
        "先别动",
    ]
    assert payload["technical_detail"] == "python3 build.py"


def test_plain_text_fallback_is_relationship_native_and_keeps_details_secondary():
    text = _format_exec_approval_fallback(
        "python3 build.py",
        "execute a local build script",
        "/",
        allow_session=True,
        allow_permanent=False,
    )

    assert "电脑" in text and "下面" in text
    assert "运行本机上的构建脚本" in text
    assert "如果愿意" in text
    assert "Command Approval Required" not in text


def test_feishu_dm_owner_can_click_permission_card_in_pairing_mode():
    adapter = object.__new__(FeishuAdapter)
    adapter._approval_state = {
        7: {"session_key": "owner-session", "chat_id": "owner-chat"}
    }
    adapter._admins = set()
    adapter._allowed_group_users = set()
    adapter._get_cached_sender_name = lambda _open_id: "小酒"
    adapter._allow_group_message = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("a private approval must not use the group policy gate")
    )
    submitted = []

    def submit(_loop, coro):
        submitted.append(coro)
        coro.close()
        return True

    adapter._submit_on_loop = submit
    event = SimpleNamespace(
        operator=SimpleNamespace(open_id="owner-open-id", user_id=""),
        context=SimpleNamespace(open_chat_id="owner-chat"),
    )

    adapter._handle_approval_card_action(
        event=event,
        action_value={"approval_id": 7, "honeyos_action": "approve_once"},
        loop=object(),
    )

    assert len(submitted) == 1
