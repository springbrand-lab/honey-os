from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from honeyos.companion.channels import setup_weixin


def test_weixin_setup_uses_honeyos_home_before_adapter_import(monkeypatch, tmp_path):
    observed = []
    saved = {}

    async def qr_login(home):
        observed.append((home, os.environ["HONEYOS_HOME"]))
        return {
            "account_id": "bot-account",
            "token": "weixin-token",
            "base_url": "https://ilink.example.com",
            "user_id": "owner-user-id",
        }

    monkeypatch.setitem(
        sys.modules,
        "honeyos.gateway.platforms.weixin",
        SimpleNamespace(
            check_weixin_requirements=lambda: True,
            qr_login=qr_login,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "honeyos.runtime.config",
        SimpleNamespace(save_env_value=lambda key, value: saved.__setitem__(key, value)),
    )

    assert setup_weixin(tmp_path) == 0
    assert observed == [(str(tmp_path.resolve()), str(tmp_path.resolve()))]
    assert os.environ["HONEYOS_HOME"] == str(tmp_path.resolve())
    assert "HERMES_HOME" not in os.environ
    assert "H2OS_HOME" not in os.environ
    assert saved == {
        "WEIXIN_ACCOUNT_ID": "bot-account",
        "WEIXIN_TOKEN": "weixin-token",
        "WEIXIN_BASE_URL": "https://ilink.example.com",
        "WEIXIN_CDN_BASE_URL": "https://novac2c.cdn.weixin.qq.com/c2c",
        "WEIXIN_DM_POLICY": "allowlist",
        "WEIXIN_ALLOW_ALL_USERS": "false",
        "WEIXIN_ALLOWED_USERS": "owner-user-id",
        "WEIXIN_GROUP_POLICY": "disabled",
        "WEIXIN_GROUP_ALLOWED_USERS": "",
        "WEIXIN_HOME_CHANNEL": "owner-user-id",
    }


def test_weixin_setup_returns_clean_error_without_traceback(
    monkeypatch, tmp_path, capsys
):
    async def fail(_home):
        raise RuntimeError("scan failed")

    monkeypatch.setitem(
        sys.modules,
        "honeyos.gateway.platforms.weixin",
        SimpleNamespace(check_weixin_requirements=lambda: True, qr_login=fail),
    )

    assert setup_weixin(tmp_path) == 1
    captured = capsys.readouterr()
    assert "scan failed" in captured.err
    assert "Traceback" not in captured.err


def test_weixin_setup_requires_scanning_user_id_for_private_binding(
    monkeypatch, tmp_path, capsys
):
    async def qr_login(_home):
        return {"account_id": "bot-account", "token": "token", "user_id": ""}

    monkeypatch.setitem(
        sys.modules,
        "honeyos.gateway.platforms.weixin",
        SimpleNamespace(check_weixin_requirements=lambda: True, qr_login=qr_login),
    )

    assert setup_weixin(tmp_path) == 1
    assert "无法识别扫码用户" in capsys.readouterr().err
