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
OPENAI_BASE_URL = "https://api.openai.com/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


@dataclass(frozen=True)
class ProviderOption:
    provider: str
    label: str
    base_url: str
    key_env: str
    fallback_models: tuple[str, ...]


PROVIDER_OPTIONS: dict[str, ProviderOption] = {
    "openai-api": ProviderOption(
        provider="openai-api",
        label="OpenAI",
        base_url=OPENAI_BASE_URL,
        key_env="OPENAI_API_KEY",
        fallback_models=("gpt-5.6-terra", "gpt-5.4-mini", "gpt-4.1"),
    ),
    "openrouter": ProviderOption(
        provider="openrouter",
        label="OpenRouter",
        base_url=OPENROUTER_BASE_URL,
        key_env="OPENROUTER_API_KEY",
        fallback_models=(RECOMMENDED_OPENROUTER_MODEL,),
    ),
    "deepseek": ProviderOption(
        provider="deepseek",
        label="DeepSeek",
        base_url=DEEPSEEK_BASE_URL,
        key_env="DEEPSEEK_API_KEY",
        fallback_models=("deepseek-v4-flash", "deepseek-v4-pro"),
    ),
}


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    base_url: str
    key_env: str


def model_choice(
    provider: str,
    model: str,
    *,
    base_url: str = "",
) -> ModelChoice:
    """Build a model choice without letting first-party endpoints drift."""

    provider_id = str(provider or "").strip().lower()
    model_id = str(model or "").strip()
    if not model_id or len(model_id) > 240:
        raise ValueError("Model ID 不能为空且不能超过 240 个字符")
    option = PROVIDER_OPTIONS.get(provider_id)
    if option is not None:
        return ModelChoice(
            provider=option.provider,
            model=model_id,
            base_url=option.base_url,
            key_env=option.key_env,
        )
    if provider_id != "custom":
        raise ValueError("不支持的模型服务")
    normalized_url = str(base_url or "").strip().rstrip("/")
    if not normalized_url.startswith(("https://", "http://")):
        raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
    return ModelChoice(
        provider="custom",
        model=model_id,
        base_url=normalized_url,
        key_env="HONEYOS_MODEL_API_KEY",
    )


def discover_model_ids(base_url: str, api_key: str) -> list[str]:
    """Read an OpenAI-compatible ``/models`` catalog without persisting secrets."""

    url = f"{str(base_url or '').strip().rstrip('/')}/models"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if not 200 <= int(response.status) < 300:
                raise ValueError(f"模型服务返回 HTTP {response.status}")
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("模型服务没有返回有效的模型列表") from exc
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("API Key 无效或没有读取模型列表的权限") from exc
        raise ValueError(f"读取模型列表时服务返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"无法读取模型列表：{exc.reason}") from exc

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("该服务没有提供 OpenAI 兼容的模型列表")
    result: list[str] = []
    for row in rows:
        model_id = str(row.get("id") or "").strip() if isinstance(row, dict) else ""
        if model_id and model_id not in result:
            result.append(model_id)
    if not result:
        raise ValueError("该服务没有返回可用模型")
    return result


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
    """Verify the selected model can drive the HoneyOS Agent tool loop."""

    url = f"{choice.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": choice.model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "This is a HoneyOS Agent compatibility test. Please call the "
                        "honeyos_compatibility_probe tool now with value "
                        '"honeyos". Do not answer in text.'
                    ),
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "honeyos_compatibility_probe",
                        "description": "Verify that this model can call HoneyOS tools.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "max_tokens": 64,
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
            if not isinstance(message, dict):
                raise ValueError(
                    "模型服务不兼容 OpenAI Chat Completions，请检查 Base URL 和模型"
                )
            tool_calls = message.get("tool_calls")
            probe_ok = False
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict) or call.get("type") != "function":
                        continue
                    function = call.get("function")
                    if not isinstance(function, dict):
                        continue
                    if function.get("name") != "honeyos_compatibility_probe":
                        continue
                    arguments = function.get("arguments")
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = None
                    if isinstance(arguments, dict) and arguments.get("value") == "honeyos":
                        probe_ok = True
                        break
            if not probe_ok:
                raise ValueError(
                    "模型可以聊天，但没有通过 HoneyOS 工具调用测试。"
                    "请改用支持 Function Calling / Tool Calling 的模型。"
                )
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("API Key 无效或没有访问权限") from exc
        raise ValueError(f"模型服务返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"无法连接模型服务：{exc.reason}") from exc


def _choose_provider(input_fn: Callable[[str], str]) -> tuple[str, str]:
    provider = input_fn(
        "模型服务：1) OpenAI（默认）  2) OpenRouter  3) DeepSeek  "
        "4) 自定义兼容接口 [1]: "
    ).strip()
    provider_ids = {
        "": "openai-api",
        "1": "openai-api",
        "2": "openrouter",
        "3": "deepseek",
        "4": "custom",
    }
    provider_id = provider_ids.get(provider)
    if provider_id is None:
        raise ValueError("请选择 1、2、3 或 4")
    if provider_id == "custom":
        base_url = input_fn("Base URL（例如 https://api.example.com/v1）: ").strip()
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("需要有效的 Base URL")
        return provider_id, base_url.rstrip("/")
    return provider_id, PROVIDER_OPTIONS[provider_id].base_url


def _select_model_from_catalog(models: list[str], recommended: str = "") -> str:
    """Open the existing searchable terminal model picker."""

    ordered = list(dict.fromkeys(models))
    if recommended in ordered:
        ordered.remove(recommended)
        ordered.insert(0, recommended)
    from honeyos.runtime.auth import _prompt_model_selection

    selected = _prompt_model_selection(ordered, current_model=recommended)
    if not selected:
        raise ValueError("没有选择模型")
    return selected


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
        "连接渠道：1) 微信  2) 飞书  3) 微信 + 飞书（默认）  4) 暂时只用网页 [3]: "
    ).strip()
    if choice in {"", "3"}:
        return ("weixin", "feishu")
    if choice == "1":
        return ("weixin",)
    if choice == "2":
        return ("feishu",)
    if choice == "4":
        return ()
    raise ValueError("请选择 1、2、3 或 4")


def run_setup(
    home: Path,
    *,
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = getpass.getpass,
    validate_fn: Callable[[ModelChoice, str], None] = validate_model_key,
    discover_fn: Callable[[str, str], list[str]] = discover_model_ids,
    select_model_fn: Callable[[list[str], str], str] | None = None,
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

    print(f"{PRODUCT_NAME} 设置：模型服务 / API Key / 模型 → IM → 启动")
    try:
        provider_id, base_url = _choose_provider(input_fn)
        api_key = secret_fn("API Key（输入不会显示）: ").strip()
        if not api_key:
            raise ValueError("API Key 不能为空")
        option = PROVIDER_OPTIONS.get(provider_id)
        fallback_models = list(option.fallback_models) if option else []
        recommended = fallback_models[0] if fallback_models else ""
        try:
            models = discover_fn(base_url, api_key)
        except ValueError as exc:
            if provider_id == "custom":
                print(f"暂时无法读取模型列表：{exc}")
                model = input_fn("Model ID（将立即验证）: ").strip()
                if not model:
                    raise ValueError("Model ID 不能为空") from exc
            else:
                print(f"暂时无法读取在线模型列表，将使用内置列表：{exc}")
                models = fallback_models
                if not models:
                    raise
                picker = select_model_fn or _select_model_from_catalog
                model = picker(models, recommended)
        else:
            picker = select_model_fn or _select_model_from_catalog
            model = picker(models, recommended)
        choice = model_choice(provider_id, model, base_url=base_url)
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
        from honeyos.companion.web import companion_web_url

        print(f"✓ {PRODUCT_NAME} 已启动。")
        print(f"  本地聊天：{companion_web_url()}")
        if selected_platforms:
            print("  已连接的微信或飞书也可以继续聊天。")
    return started
