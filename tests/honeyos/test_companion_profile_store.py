from __future__ import annotations

import json

from honeyos.companion.config import initialize_home
from honeyos.companion.profile import (
    capture_explicit_profile_assignment,
    load_companion_profile,
    migrate_confirmed_profile_from_memory,
    update_companion_profile,
)


def test_explicit_profile_update_persists_identity_and_relationship(tmp_path):
    initialize_home(tmp_path)

    profile = update_companion_profile(
        tmp_path,
        companion_name="小意",
        personality="嘴硬心软，有主见",
        speaking_style="亲近、简短、略带调侃",
        user_nickname="小酒",
        relationship="恋爱中的亲密伴侣",
        source="user_explicit",
    )

    assert profile.companion_name == "小意"
    assert profile.user_nickname == "小酒"
    assert "嘴硬心软" in (tmp_path / "memories" / "IDENTITY.md").read_text(
        encoding="utf-8"
    )
    assert "小酒" in (tmp_path / "memories" / "RELATIONSHIP.md").read_text(
        encoding="utf-8"
    )
    assert load_companion_profile(tmp_path) == profile


def test_structured_onboarding_payload_is_captured_without_model_cooperation(tmp_path):
    initialize_home(tmp_path)
    payload = json.dumps(
        {
            "companion": {
                "name": "小意",
                "personality": "嘴硬心软，有主见",
                "speaking_style": "亲近、简短",
            },
            "user": {"nickname": "小酒"},
            "relationship": "恋爱中的亲密伴侣",
        },
        ensure_ascii=False,
    )

    captured = capture_explicit_profile_assignment(tmp_path, payload)

    assert captured is not None
    assert captured.companion_name == "小意"
    assert captured.user_nickname == "小酒"


def test_legacy_onboarding_opening_supplies_explicit_user_nickname(tmp_path):
    initialize_home(tmp_path)
    payload = json.dumps(
        {
            "companion": {
                "name": "小意",
                "opening": "小酒，我是小意，以后我就在这儿。",
            }
        },
        ensure_ascii=False,
    )

    captured = capture_explicit_profile_assignment(tmp_path, payload)

    assert captured is not None
    assert captured.user_nickname == "小酒"


def test_clear_natural_language_names_are_captured_but_not_inferred(tmp_path):
    initialize_home(tmp_path)

    captured = capture_explicit_profile_assignment(
        tmp_path, "以后你叫小意，叫我小酒。"
    )

    assert captured is not None
    assert captured.companion_name == "小意"
    assert captured.user_nickname == "小酒"
    before = (tmp_path / "memories" / "RELATIONSHIP.md").read_text(encoding="utf-8")
    assert capture_explicit_profile_assignment(tmp_path, "你今天好像有点傲娇") is None
    assert (tmp_path / "memories" / "RELATIONSHIP.md").read_text(
        encoding="utf-8"
    ) == before


def test_profile_rejects_credentials_in_persona_fields(tmp_path):
    initialize_home(tmp_path)

    try:
        update_companion_profile(
            tmp_path,
            personality="温柔，API_KEY=sk-test-secret-1234567890",
            source="user_explicit",
        )
    except ValueError as exc:
        assert "敏感" in str(exc)
    else:
        raise AssertionError("credential-bearing persona must be rejected")


def test_existing_confirmed_name_and_nickname_migrate_from_generic_memory(tmp_path):
    initialize_home(tmp_path)
    (tmp_path / "memories" / "MEMORY.md").write_text(
        "小酒给我取了名字叫小意，我是小酒的恋爱伴侣。\n§\n一次普通经历。\n",
        encoding="utf-8",
    )

    migrated = migrate_confirmed_profile_from_memory(tmp_path)

    assert migrated is not None
    assert migrated.companion_name == "小意"
    assert migrated.user_nickname == "小酒"
    assert migrated.relationship == "恋爱伴侣"


def test_profile_tool_requires_an_exact_quote_from_the_current_user_turn(
    tmp_path, monkeypatch
):
    initialize_home(tmp_path)
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-test")
    from honeyos.tools.companion_profile_tool import _handler

    rejected = json.loads(
        _handler(
            {
                "action": "update",
                "personality": "占有欲很强",
                "evidence_quote": "你很爱我",
            },
            user_task="你今天看起来很开心。",
        )
    )
    accepted = json.loads(
        _handler(
            {
                "action": "update",
                "personality": "嘴硬心软",
                "evidence_quote": "以后你要嘴硬一点，但其实要心软",
            },
            user_task="以后你要嘴硬一点，但其实要心软。",
        )
    )

    assert rejected["success"] is False
    assert accepted["success"] is True
    assert load_companion_profile(tmp_path).personality == "嘴硬心软"
