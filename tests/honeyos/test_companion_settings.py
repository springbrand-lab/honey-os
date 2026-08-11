from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from honeyos.companion.config import initialize_home


def test_companion_settings_never_returns_model_or_channel_secrets(tmp_path: Path):
    from honeyos.companion.settings import companion_settings

    initialize_home(tmp_path)
    (tmp_path / ".env").write_text(
        "HONEYOS_MODEL_API_KEY=sk-model-secret\n"
        "FEISHU_APP_ID=cli_a123\n"
        "FEISHU_APP_SECRET=feishu-secret\n"
        "WEIXIN_ACCOUNT_ID=wx-account\n"
        "WEIXIN_TOKEN=weixin-secret\n",
        encoding="utf-8",
    )

    settings = companion_settings(tmp_path)

    assert settings["model"]["api_key_configured"] is True
    assert settings["channels"]["feishu"] == {
        "configured": True,
        "app_id": "cli_a123",
        "app_secret_configured": True,
        "restart_required": True,
    }
    assert settings["channels"]["weixin"] == {
        "configured": True,
        "account_id": "wx-account",
        "token_configured": True,
        "setup_command": "honeyos channel setup weixin",
        "restart_required": True,
    }
    serialized = str(settings)
    assert "sk-model-secret" not in serialized
    assert "feishu-secret" not in serialized
    assert "weixin-secret" not in serialized


def test_update_companion_model_keeps_api_key_out_of_yaml(tmp_path: Path):
    from honeyos.companion.settings import update_companion_model

    initialize_home(tmp_path)

    updated = update_companion_model(
        tmp_path,
        provider="custom",
        base_url="https://models.example.com/v1/",
        model="companion-model",
        api_key="sk-private-model-key",
        validate_fn=lambda _choice, _key: None,
    )

    config_text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    config = yaml.safe_load(config_text)
    assert config["model"] == {
        "default": "companion-model",
        "provider": "honeyos-model",
        "base_url": "https://models.example.com/v1",
        "api_mode": "chat_completions",
    }
    assert config["providers"]["honeyos-model"]["key_env"] == (
        "HONEYOS_MODEL_API_KEY"
    )
    assert "sk-private-model-key" not in config_text
    assert "HONEYOS_MODEL_API_KEY=sk-private-model-key" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")
    assert updated["model"]["api_key_configured"] is True
    assert "sk-private-model-key" not in str(updated)


def test_update_companion_model_rejects_non_http_base_url(tmp_path: Path):
    from honeyos.companion.settings import update_companion_model

    initialize_home(tmp_path)

    with pytest.raises(ValueError, match="Base URL"):
        update_companion_model(
            tmp_path,
            provider="custom",
            base_url="file:///tmp/model",
            model="companion-model",
            api_key="secret",
            validate_fn=lambda _choice, _key: None,
        )


def test_update_deepseek_model_uses_builtin_endpoint_and_validates_before_save(
    tmp_path: Path,
):
    from honeyos.companion.settings import update_companion_model

    initialize_home(tmp_path)
    observed = []

    updated = update_companion_model(
        tmp_path,
        provider="deepseek",
        base_url="https://attacker.example/v1",
        model="deepseek-v4-flash",
        api_key="deepseek-secret",
        validate_fn=lambda choice, key: observed.append((choice, key)),
    )

    config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert observed[0][0].base_url == "https://api.deepseek.com/v1"
    assert observed[0][0].key_env == "DEEPSEEK_API_KEY"
    assert observed[0][1] == "deepseek-secret"
    assert config["model"]["provider"] == "deepseek"
    assert config["model"]["base_url"] == "https://api.deepseek.com/v1"
    assert "DEEPSEEK_API_KEY=deepseek-secret" in (tmp_path / ".env").read_text(
        encoding="utf-8"
    )
    assert updated["model"]["provider"] == "deepseek"


def test_failed_model_validation_does_not_change_existing_settings(tmp_path: Path):
    from honeyos.companion.settings import update_companion_model

    initialize_home(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=old-secret\n", encoding="utf-8")
    before_config = (tmp_path / "config.yaml").read_bytes()
    before_env = (tmp_path / ".env").read_bytes()

    with pytest.raises(ValueError, match="模型不可用"):
        update_companion_model(
            tmp_path,
            provider="openai-api",
            base_url="",
            model="wrong-model",
            api_key="new-secret",
            validate_fn=lambda _choice, _key: (_ for _ in ()).throw(
                ValueError("模型不可用")
            ),
        )

    assert (tmp_path / "config.yaml").read_bytes() == before_config
    assert (tmp_path / ".env").read_bytes() == before_env


def test_discover_companion_models_uses_saved_provider_key(tmp_path: Path):
    from honeyos.companion.settings import discover_companion_models

    initialize_home(tmp_path)
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=saved-secret\n", encoding="utf-8"
    )
    observed = []

    models = discover_companion_models(
        tmp_path,
        provider="deepseek",
        base_url="https://ignored.example/v1",
        api_key=None,
        discover_fn=lambda base_url, key: observed.append((base_url, key))
        or ["deepseek-v4-flash", "deepseek-v4-pro"],
    )

    assert models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert observed == [("https://api.deepseek.com/v1", "saved-secret")]
