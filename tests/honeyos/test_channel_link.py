from __future__ import annotations

from pathlib import Path

import pytest


class FakeChannelDriver:
    def __init__(self):
        self.persisted = None

    async def start(self):
        return {
            "qr_url": "https://scan.example/link",
            "expires_in": 120,
            "interval": 1,
            "_state": {"device_code": "never-return-this"},
        }

    async def poll(self, state):
        assert state == {"device_code": "never-return-this"}
        return {
            "status": "connected",
            "credentials": {"app_secret": "never-return-this-either"},
        }

    def persist(self, home, credentials):
        self.persisted = (home, credentials)


@pytest.mark.asyncio
async def test_channel_link_hides_flow_secrets_and_persists_only_on_success(tmp_path: Path):
    from honeyos.companion.channel_link import ChannelLinkManager

    driver = FakeChannelDriver()
    manager = ChannelLinkManager(
        tmp_path,
        drivers={"feishu": driver},
        token_fn=lambda: "link-safe-token",
        qr_encoder=lambda _url: "data:image/png;base64,safe-image",
    )

    started = await manager.start("feishu")
    assert started == {
        "link_id": "link-safe-token",
        "platform": "feishu",
        "status": "waiting",
        "qr_url": "https://scan.example/link",
        "qr_image": "data:image/png;base64,safe-image",
        "expires_in": 120,
    }
    assert "device_code" not in str(started)

    completed = await manager.poll("link-safe-token", force=True)
    assert completed == {
        "link_id": "link-safe-token",
        "platform": "feishu",
        "status": "connected",
        "restart_required": True,
    }
    assert "app_secret" not in str(completed)
    assert driver.persisted == (
        tmp_path.resolve(),
        {"app_secret": "never-return-this-either"},
    )


@pytest.mark.asyncio
async def test_feishu_driver_maps_device_flow_and_persists_private_defaults(tmp_path: Path):
    from honeyos.companion.channel_link import FeishuLinkDriver

    responses = iter(
        [
            {
                "device_code": "private-device-code",
                "qr_url": "https://accounts.feishu.cn/qr",
                "interval": 3,
                "expire_in": 600,
            },
            {
                "client_id": "cli_public",
                "client_secret": "private-secret",
                "user_info": {"open_id": "ou_owner"},
            },
        ]
    )

    async def request(action, _state=None):
        assert action in {"begin", "poll"}
        return next(responses)

    driver = FeishuLinkDriver(request=request)
    started = await driver.start()
    assert started["qr_url"] == "https://accounts.feishu.cn/qr"
    assert started["_state"]["device_code"] == "private-device-code"

    result = await driver.poll(started["_state"])
    assert result["status"] == "connected"
    driver.persist(tmp_path, result["credentials"])

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "FEISHU_APP_ID=cli_public" in env_text
    assert "FEISHU_APP_SECRET=private-secret" in env_text
    assert "FEISHU_ALLOW_ALL_USERS=false" in env_text
    assert "FEISHU_GROUP_POLICY=disabled" in env_text


@pytest.mark.asyncio
async def test_weixin_driver_maps_scan_states_and_binds_scanning_owner(tmp_path: Path):
    from honeyos.companion.channel_link import WeixinLinkDriver

    responses = iter(
        [
            {
                "qrcode": "private-qr-token",
                "qrcode_img_content": "https://weixin.qq.com/scan-this",
            },
            {
                "status": "confirmed",
                "ilink_bot_id": "wx_bot",
                "bot_token": "private-token",
                "baseurl": "https://ilink.example",
                "ilink_user_id": "wx_owner",
            },
        ]
    )

    async def request(_base_url, endpoint):
        assert "qrcode" in endpoint
        return next(responses)

    driver = WeixinLinkDriver(request=request)
    started = await driver.start()
    assert started["qr_url"] == "https://weixin.qq.com/scan-this"

    result = await driver.poll(started["_state"])
    assert result["status"] == "connected"
    driver.persist(tmp_path, result["credentials"])

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "WEIXIN_ACCOUNT_ID=wx_bot" in env_text
    assert "WEIXIN_TOKEN=private-token" in env_text
    assert "WEIXIN_ALLOWED_USERS=wx_owner" in env_text
    assert "WEIXIN_GROUP_POLICY=disabled" in env_text
    account = tmp_path / "weixin" / "accounts" / "wx_bot.json"
    assert account.is_file()
