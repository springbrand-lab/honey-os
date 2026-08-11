"""Safe, user-facing settings for the local HoneyOS companion web app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
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
    from honeyos.companion.setup import PROVIDER_OPTIONS

    if provider in PROVIDER_OPTIONS:
        key_env = PROVIDER_OPTIONS[provider].key_env
    display_provider = "custom" if provider == "honeyos-model" else provider
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
            "provider": display_provider,
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
    provider: str = "custom",
    base_url: str,
    model: str,
    api_key: str | None = None,
    validate_fn: Callable[[Any, str], None] | None = None,
) -> dict[str, Any]:
    """Validate then persist a model while keeping its key in ``.env``."""

    resolved = Path(home).expanduser().resolve()
    from honeyos.companion.setup import (
        configure_model,
        model_choice,
        validate_model_key,
    )

    choice = model_choice(provider, model, base_url=base_url)
    parsed = urlparse(choice.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
    if len(choice.base_url) > 2048:
        raise ValueError("Base URL 过长")
    submitted_key = str(api_key).strip() if api_key is not None else ""
    saved_key = _read_env(resolved).get(choice.key_env, "").strip()
    resolved_key = submitted_key or saved_key
    if not resolved_key:
        raise ValueError("API Key 不能为空")
    (validate_fn or validate_model_key)(choice, resolved_key)
    configure_model(resolved, choice, resolved_key)
    return companion_settings(resolved)


def discover_companion_models(
    home: Path | str,
    *,
    provider: str,
    base_url: str = "",
    api_key: str | None = None,
    discover_fn: Callable[[str, str], list[str]] | None = None,
) -> list[str]:
    """Discover models using a submitted key or the provider's saved key."""

    resolved = Path(home).expanduser().resolve()
    from honeyos.companion.setup import discover_model_ids, model_choice

    # The model value is only needed to resolve the provider's trusted endpoint.
    choice = model_choice(provider, "discovery-probe", base_url=base_url)
    submitted_key = str(api_key).strip() if api_key is not None else ""
    resolved_key = submitted_key or _read_env(resolved).get(choice.key_env, "").strip()
    if not resolved_key:
        raise ValueError("请先填写 API Key")
    return (discover_fn or discover_model_ids)(choice.base_url, resolved_key)
