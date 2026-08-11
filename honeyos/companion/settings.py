"""Safe, user-facing settings for the local HoneyOS companion web app."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


MODEL_KEY_ENV = "HONEYOS_MODEL_API_KEY"


def _read_env(home: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    path = home / ".env"
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _read_config(home: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    except OSError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def companion_settings(home: Path | str) -> dict[str, Any]:
    """Return editable settings without returning any credential value."""

    resolved = Path(home).expanduser().resolve()
    config = _read_config(resolved)
    env = _read_env(resolved)
    model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
    provider = str(model_cfg.get("provider") or "").strip()
    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    provider_cfg = providers.get(provider) if isinstance(providers.get(provider), dict) else {}
    model = str(
        model_cfg.get("default")
        or provider_cfg.get("default_model")
        or provider_cfg.get("model")
        or ""
    ).strip()
    base_url = str(
        model_cfg.get("base_url") or provider_cfg.get("base_url") or ""
    ).strip()
    key_env = str(
        model_cfg.get("key_env") or provider_cfg.get("key_env") or MODEL_KEY_ENV
    ).strip()
    model_key_configured = bool(
        env.get(key_env)
        or model_cfg.get("api_key")
        or provider_cfg.get("api_key")
    )

    feishu_app_id = str(env.get("FEISHU_APP_ID") or "").strip()
    feishu_secret_configured = bool(env.get("FEISHU_APP_SECRET"))
    weixin_account_id = str(env.get("WEIXIN_ACCOUNT_ID") or "").strip()
    weixin_token_configured = bool(env.get("WEIXIN_TOKEN"))

    return {
        "model": {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_key_configured": model_key_configured,
        },
        "channels": {
            "feishu": {
                "configured": bool(feishu_app_id and feishu_secret_configured),
                "app_id": feishu_app_id,
                "app_secret_configured": feishu_secret_configured,
                "restart_required": True,
            },
            "weixin": {
                "configured": bool(weixin_account_id and weixin_token_configured),
                "account_id": weixin_account_id,
                "token_configured": weixin_token_configured,
                "setup_command": "honeyos channel setup weixin",
                "restart_required": True,
            },
        },
    }


def update_companion_model(
    home: Path | str,
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Persist an OpenAI-compatible model while keeping its key in ``.env``."""

    resolved = Path(home).expanduser().resolve()
    normalized_url = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
    model_id = str(model or "").strip()
    if not model_id or len(model_id) > 240:
        raise ValueError("Model ID 不能为空且不能超过 240 个字符")
    if len(normalized_url) > 2048:
        raise ValueError("Base URL 过长")
    submitted_key = str(api_key).strip() if api_key is not None else ""
    if not submitted_key and not _read_env(resolved).get(MODEL_KEY_ENV):
        raise ValueError("API Key 不能为空")

    config = _read_config(resolved)
    providers = config.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        config["providers"] = providers
    providers["honeyos-model"] = {
        "name": "honeyos-model",
        "base_url": normalized_url,
        "key_env": MODEL_KEY_ENV,
        "api_mode": "chat_completions",
        "default_model": model_id,
    }
    config["model"] = {
        "default": model_id,
        "provider": "honeyos-model",
        "base_url": normalized_url,
        "api_mode": "chat_completions",
    }

    from honeyos.companion.setup import _atomic_write, _set_env_value

    _atomic_write(
        resolved / "config.yaml",
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    )
    if submitted_key:
        _set_env_value(resolved / ".env", MODEL_KEY_ENV, submitted_key)
    return companion_settings(resolved)
