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
        base_url="https://models.example.com/v1/",
        model="companion-model",
        api_key="sk-private-model-key",
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
            base_url="file:///tmp/model",
            model="companion-model",
            api_key="secret",
        )
