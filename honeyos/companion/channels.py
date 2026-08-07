"""HONEYOS-branded wrappers around inherited messaging adapters."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from honeyos.companion import PRODUCT_NAME
from honeyos.cli.bootstrap import activate_home


def setup_weixin(home: Path) -> int:
    """Connect one scanner to one private HONEYOS instance via Weixin QR login."""

    resolved = activate_home(home)
    print(f"{PRODUCT_NAME} 微信连接 · 数据只保存在 {resolved}")
    print("请用微信扫描终端中的二维码，并在手机上确认。")
    try:
        from honeyos.gateway.platforms.weixin import check_weixin_requirements, qr_login
        from honeyos.runtime.config import save_env_value

        if not check_weixin_requirements():
            raise RuntimeError("缺少微信连接依赖，请重新运行安装程序")
        credentials = asyncio.run(qr_login(str(resolved)))
        if not credentials:
            raise RuntimeError("微信扫码没有完成，请重新运行安装程序")

        account_id = str(credentials.get("account_id") or "").strip()
        token = str(credentials.get("token") or "").strip()
        base_url = str(credentials.get("base_url") or "").strip()
        user_id = str(credentials.get("user_id") or "").strip()
        if not account_id or not token:
            raise RuntimeError("微信没有返回完整的登录凭据，请重新扫码")
        if not user_id:
            raise RuntimeError("无法识别扫码用户，不能安全地自动绑定本人")

        save_env_value("WEIXIN_ACCOUNT_ID", account_id)
        save_env_value("WEIXIN_TOKEN", token)
        if base_url:
            save_env_value("WEIXIN_BASE_URL", base_url)
        save_env_value(
            "WEIXIN_CDN_BASE_URL", "https://novac2c.cdn.weixin.qq.com/c2c"
        )
        save_env_value("WEIXIN_DM_POLICY", "allowlist")
        save_env_value("WEIXIN_ALLOW_ALL_USERS", "false")
        save_env_value("WEIXIN_ALLOWED_USERS", user_id)
        save_env_value("WEIXIN_GROUP_POLICY", "disabled")
        save_env_value("WEIXIN_GROUP_ALLOWED_USERS", "")
        save_env_value("WEIXIN_HOME_CHANNEL", user_id)
    except KeyboardInterrupt:
        print(f"{PRODUCT_NAME} 微信连接已取消。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"{PRODUCT_NAME} 微信连接失败：{exc}", file=sys.stderr)
        return 1
    print("✓ 微信已连接，并且只允许扫码本人私聊；群聊默认关闭。")
    return 0


def setup_feishu(home: Path) -> int:
    """Connect a Feishu bot to one private HONEYOS instance."""

    resolved = activate_home(home)
    print(f"{PRODUCT_NAME} 飞书连接 · 数据只保存在 {resolved}")
    print("可扫码自动创建飞书机器人，也可以填写已有 App ID 和 App Secret。")
    try:
        from honeyos.runtime.config import get_env_value, save_env_value
        from honeyos.plugins.platforms.feishu.adapter import (
            check_feishu_requirements,
            interactive_setup,
        )

        if not check_feishu_requirements():
            raise RuntimeError("缺少飞书连接依赖，请重新运行安装程序")
        interactive_setup(private_only=True)
        if not get_env_value("FEISHU_APP_ID") or not get_env_value(
            "FEISHU_APP_SECRET"
        ):
            raise RuntimeError("飞书机器人设置没有完成，请重新运行连接流程")

        # HoneyOS is a private companion. Keep the richer Feishu transport,
        # but never inherit the upstream wizard's open-DM or group defaults.
        save_env_value("FEISHU_ALLOW_ALL_USERS", "false")
        save_env_value("FEISHU_ALLOWED_USERS", "")
        save_env_value("FEISHU_GROUP_POLICY", "disabled")
    except KeyboardInterrupt:
        print(f"{PRODUCT_NAME} 飞书连接已取消。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"{PRODUCT_NAME} 飞书连接失败：{exc}", file=sys.stderr)
        return 1
    print("✓ 飞书已连接；首次私聊需要配对批准，群聊默认关闭。")
    return 0
