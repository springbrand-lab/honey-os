"""Human-readable first-start checks for a private HONEYOS installation."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from honeyos.companion import PRODUCT_NAME


@dataclass(frozen=True)
class HealthItem:
    ready: bool
    required: bool
    success: str
    failure: str


@dataclass(frozen=True)
class FirstStartReport:
    items: tuple[HealthItem, ...]

    @property
    def ready(self) -> bool:
        return all(item.ready for item in self.items if item.required)

    def render(self) -> str:
        lines = [f"{PRODUCT_NAME} 首次启动检查"]
        for item in self.items:
            if item.ready:
                lines.append(f"✓ {item.success}")
            elif item.required:
                lines.append(f"✗ {item.failure}")
            else:
                lines.append(f"⚠ {item.failure}")
        return "\n".join(lines)


def _env_values(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    return {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }


def _model_key_env(config: dict) -> str:
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    provider = str(model.get("provider") or "")
    if provider == "openrouter":
        return "OPENROUTER_API_KEY"
    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    provider_config = providers.get(provider) if isinstance(providers.get(provider), dict) else {}
    return str(provider_config.get("key_env") or "")


def first_start_report(
    home: Path,
    *,
    command_lookup: Callable[[str], str | None] = shutil.which,
) -> FirstStartReport:
    """Check required onboarding state and report optional local capabilities."""

    resolved = home.expanduser().resolve()
    try:
        config = yaml.safe_load((resolved / "config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    env_values = _env_values(resolved / ".env")
    model_key = _model_key_env(config)
    model_ready = bool(
        model.get("default") and model.get("base_url") and env_values.get(model_key)
    )
    weixin_ready = all(
        env_values.get(key)
        for key in ("WEIXIN_ACCOUNT_ID", "WEIXIN_TOKEN", "WEIXIN_ALLOWED_USERS")
    )
    feishu_ready = all(
        env_values.get(key) for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET")
    )
    im_ready = weixin_ready or feishu_ready
    storage_ready = resolved.exists() and os.access(resolved, os.W_OK)
    docker_ready = command_lookup("docker") is not None
    computer_ready = command_lookup("cua-driver") is not None

    return FirstStartReport(
        (
            HealthItem(storage_ready, True, "本地数据目录可写", "本地数据目录不可写"),
            HealthItem(model_ready, True, "模型与 API Key 已验证", "模型或 API Key 尚未配置"),
            HealthItem(
                im_ready,
                True,
                "至少一个 IM 已连接",
                "微信和飞书均未连接",
            ),
            HealthItem(
                weixin_ready,
                False,
                "微信已绑定扫码本人",
                "微信尚未绑定扫码本人",
            ),
            HealthItem(
                feishu_ready,
                False,
                "飞书已连接",
                "飞书尚未连接",
            ),
            HealthItem(
                docker_ready,
                False,
                "Docker 已安装，可使用隔离代码执行",
                "Docker 未安装：聊天可用，隔离代码执行暂不可用",
            ),
            HealthItem(
                computer_ready,
                False,
                "Computer Use 已安装",
                "Computer Use 未安装：聊天可用，桌面控制暂不可用",
            ),
        )
    )


def print_first_start_report(home: Path) -> bool:
    report = first_start_report(home)
    print(report.render())
    return report.ready
