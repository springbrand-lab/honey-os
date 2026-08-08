from __future__ import annotations

import json

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

    assert payload["text"].startswith("我得借一下你电脑的能力")
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

    assert text.startswith("我得借一下你电脑的能力")
    assert "运行本机上的构建脚本" in text
    assert "如果愿意" in text
    assert "Command Approval Required" not in text
