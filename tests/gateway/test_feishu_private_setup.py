from __future__ import annotations


def test_private_feishu_setup_skips_open_access_choices(monkeypatch):
    import hermes_cli.cli_output as output
    import hermes_cli.config as config
    import hermes_cli.setup as setup
    import plugins.platforms.feishu.adapter as feishu

    saved = {}
    choice_prompts = []

    monkeypatch.setattr(config, "get_env_value", lambda _key: "")
    monkeypatch.setattr(
        config, "save_env_value", lambda key, value: saved.__setitem__(key, value)
    )
    monkeypatch.setattr(config, "remove_env_value", lambda _key: False)
    monkeypatch.setattr(
        setup,
        "prompt_choice",
        lambda title, _choices, _default: choice_prompts.append(title) or 0,
    )
    monkeypatch.setattr(output, "prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(output, "prompt_yes_no", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(output, "print_header", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(output, "print_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(output, "print_success", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(output, "print_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(output, "print_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        feishu,
        "qr_register",
        lambda: {
            "app_id": "cli_test",
            "app_secret": "secret",
            "domain": "feishu",
            "open_id": "ou_bot",
            "bot_name": "Honey",
        },
    )

    feishu.interactive_setup(private_only=True)

    assert choice_prompts == ["How would you like to set up Feishu / Lark?"]
    assert saved["FEISHU_ALLOW_ALL_USERS"] == "false"
    assert saved["FEISHU_ALLOWED_USERS"] == ""
    assert saved["FEISHU_GROUP_POLICY"] == "disabled"
