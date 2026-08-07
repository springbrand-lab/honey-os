"""One-pass HONEYOS onboarding: model, Weixin, then background service."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from honeyos.companion import PRODUCT_NAME


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
RECOMMENDED_OPENROUTER_MODEL = "z-ai/glm-5.2"


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    base_url: str
    key_env: str


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _set_env_value(path: Path, key: str, value: str) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{key}={value}"
    output: list[str] = []
    replaced = False
    for line in existing:
        if line.strip().startswith(f"{key}="):
            if not replaced:
                output.append(replacement)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(replacement)
    _atomic_write(path, "\n".join(output).rstrip() + "\n")


def configure_model(home: Path, choice: ModelChoice, api_key: str) -> None:
    """Persist model behavior in YAML and the secret only in ``.env``."""

    resolved = home.expanduser().resolve()
    config_path = resolved / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError("config.yaml 不是有效的配置映射")
    runtime_provider = choice.provider
    if choice.provider == "custom":
        runtime_provider = "honeyos-model"
        providers = config.get("providers")
        if not isinstance(providers, dict):
            providers = {}
            config["providers"] = providers
        providers[runtime_provider] = {
            "name": runtime_provider,
            "base_url": choice.base_url,
            "key_env": choice.key_env,
            "api_mode": "chat_completions",
            "default_model": choice.model,
        }
    config["model"] = {
        "default": choice.model,
        "provider": runtime_provider,
        "base_url": choice.base_url,
        "api_mode": "chat_completions",
    }
    _atomic_write(
        config_path,
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    )
    _set_env_value(resolved / ".env", choice.key_env, api_key)


def validate_model_key(choice: ModelChoice, api_key: str) -> None:
    """Verify the selected model with a real OpenAI-compatible chat request."""

    url = f"{choice.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": choice.model,
            "messages": [{"role": "user", "content": "Reply with OK only."}],
            "max_tokens": 16,
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if not 200 <= int(response.status) < 300:
                raise ValueError(f"模型服务返回 HTTP {response.status}")
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "模型服务没有返回有效的 OpenAI Chat Completions JSON"
                ) from exc
            choices = payload.get("choices") if isinstance(payload, dict) else None
            message = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError(
                    "模型服务不兼容 OpenAI Chat Completions，请检查 Base URL 和模型"
                )
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("API Key 无效或没有访问权限") from exc
        raise ValueError(f"模型服务返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"无法连接模型服务：{exc.reason}") from exc


def _choose_model(input_fn: Callable[[str], str]) -> ModelChoice:
    provider = input_fn(
        "模型服务：1) OpenAI 兼容服务（默认）  2) OpenRouter [1]: "
    ).strip()
    if provider in {"", "1"}:
        base_url = input_fn("Base URL（例如 https://api.example.com/v1）: ").strip()
        model = input_fn("Model ID: ").strip()
        if not base_url.startswith(("https://", "http://")) or not model:
            raise ValueError("需要有效的 Base URL 和 Model ID")
        return ModelChoice("custom", model, base_url.rstrip("/"), "HONEYOS_MODEL_API_KEY")
    if provider == "2":
        model = input_fn(
            f"模型 [{RECOMMENDED_OPENROUTER_MODEL}]: "
        ).strip() or RECOMMENDED_OPENROUTER_MODEL
        return ModelChoice("openrouter", model, OPENROUTER_BASE_URL, "OPENROUTER_API_KEY")
    raise ValueError("请选择 1 或 2")


def _has_weixin_credentials(home: Path) -> bool:
    env_path = home / ".env"
    if not env_path.exists():
        return False
    keys = {
        line.split("=", 1)[0].strip()
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    return {"WEIXIN_ACCOUNT_ID", "WEIXIN_TOKEN"}.issubset(keys)


def _has_feishu_credentials(home: Path) -> bool:
    env_path = home / ".env"
    if not env_path.exists():
        return False
    keys = {
        line.split("=", 1)[0].strip()
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    return {"FEISHU_APP_ID", "FEISHU_APP_SECRET"}.issubset(keys)


def _choose_im_platforms(input_fn: Callable[[str], str]) -> tuple[str, ...]:
    choice = input_fn(
        "连接 IM：1) 微信  2) 飞书  3) 微信 + 飞书（默认）[3]: "
    ).strip()
    if choice in {"", "3"}:
        return ("weixin", "feishu")
    if choice == "1":
        return ("weixin",)
    if choice == "2":
        return ("feishu",)
    raise ValueError("请选择 1、2 或 3")


def run_setup(
    home: Path,
    *,
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = getpass.getpass,
    validate_fn: Callable[[ModelChoice, str], None] = validate_model_key,
    weixin_setup_fn=None,
    feishu_setup_fn=None,
    gateway_run_fn=None,
    ready_check_fn=None,
) -> int:
    """Run the setup flow in the only valid product order."""

    resolved = home.expanduser().resolve()
    if weixin_setup_fn is None:
        from honeyos.companion.channels import setup_weixin

        weixin_setup_fn = setup_weixin
    if feishu_setup_fn is None:
        from honeyos.companion.channels import setup_feishu

        feishu_setup_fn = setup_feishu
    if gateway_run_fn is None:
        from honeyos.companion.runtime import run_gateway_command

        gateway_run_fn = run_gateway_command
    if ready_check_fn is None:
        from honeyos.companion.health import print_first_start_report

        ready_check_fn = print_first_start_report

    print(f"{PRODUCT_NAME} 设置：Base URL / 模型 / API Key → IM → 启动")
    try:
        choice = _choose_model(input_fn)
        api_key = secret_fn("API Key（输入不会显示）: ").strip()
        if not api_key:
            raise ValueError("API Key 不能为空")
        print("正在验证模型服务…")
        validate_fn(choice, api_key)
        configure_model(resolved, choice, api_key)
        print(f"✓ 模型已连接：{choice.model}")
        selected_platforms = _choose_im_platforms(input_fn)
    except (ValueError, KeyboardInterrupt) as exc:
        message = str(exc) if str(exc) else "设置已取消"
        print(f"{PRODUCT_NAME} 设置失败：{message}", file=os.sys.stderr)
        return 1

    for platform in selected_platforms:
        if platform == "weixin":
            has_credentials = _has_weixin_credentials(resolved)
            setup_fn = weixin_setup_fn
            label = "微信"
        else:
            has_credentials = _has_feishu_credentials(resolved)
            setup_fn = feishu_setup_fn
            label = "飞书"
        if has_credentials:
            reuse = input_fn(
                f"检测到已连接{label}，继续使用？[Y/n]: "
            ).strip().lower()
            if reuse in {"", "y", "yes"}:
                print(f"✓ 继续使用已连接的{label}")
                continue
        channel_result = setup_fn(resolved)
        if channel_result != 0:
            return channel_result

    installed = gateway_run_fn(
        "install", home=resolved, arguments=("--no-start-now",)
    )
    if installed != 0:
        return installed
    started = gateway_run_fn("start", home=resolved)
    if started == 0:
        if not ready_check_fn(resolved):
            print(
                f"{PRODUCT_NAME} 首次启动检查未通过，请按上面的提示处理。",
                file=os.sys.stderr,
            )
            return 1
        print(f"✓ {PRODUCT_NAME} 已启动，现在可以去微信或飞书聊天。")
    return started
