"""Browser-friendly QR linking for HoneyOS private IM channels."""

from __future__ import annotations

import base64
import io
import secrets
import time
import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable


AsyncChannelRequest = Callable[[str, dict[str, Any] | None], Awaitable[dict[str, Any]]]
AsyncWeixinRequest = Callable[[str, str], Awaitable[dict[str, Any]]]


def _qr_data_url(value: str) -> str:
    try:
        import qrcode

        image = qrcode.make(value)
        output = io.BytesIO()
        image.save(output, format="PNG")
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return ""


class ChannelLinkManager:
    """Keep opaque QR sessions and expose only safe browser state."""

    def __init__(
        self,
        home: Path | str,
        *,
        drivers: dict[str, Any] | None = None,
        token_fn: Callable[[], str] | None = None,
        qr_encoder: Callable[[str], str] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.home = Path(home).expanduser().resolve()
        self.drivers = drivers or _real_drivers()
        self.token_fn = token_fn or (lambda: secrets.token_urlsafe(24))
        self.qr_encoder = qr_encoder or _qr_data_url
        self.now_fn = now_fn or time.time
        self._sessions: dict[str, dict[str, Any]] = {}

    async def start(self, platform: str) -> dict[str, Any]:
        name = str(platform or "").strip().lower()
        driver = self.drivers.get(name)
        if driver is None:
            raise ValueError("只支持微信和飞书扫码连接")
        started = await driver.start()
        qr_url = str(started.get("qr_url") or "").strip()
        if not qr_url:
            raise RuntimeError("渠道没有返回可用的二维码")
        expires_in = max(30, min(int(started.get("expires_in") or 300), 900))
        interval = max(1, min(int(started.get("interval") or 2), 15))
        link_id = self.token_fn()
        now = self.now_fn()
        self._sessions[link_id] = {
            "platform": name,
            "driver": driver,
            "state": started.get("_state") or {},
            "expires_at": now + expires_in,
            "next_poll_at": now,
            "interval": interval,
        }
        return {
            "link_id": link_id,
            "platform": name,
            "status": "waiting",
            "qr_url": qr_url,
            "qr_image": self.qr_encoder(qr_url),
            "expires_in": expires_in,
        }

    async def poll(self, link_id: str, *, force: bool = False) -> dict[str, Any]:
        token = str(link_id or "").strip()
        session = self._sessions.get(token)
        if session is None:
            raise ValueError("扫码连接已失效，请重新开始")
        now = self.now_fn()
        if now >= session["expires_at"]:
            self._sessions.pop(token, None)
            return {"link_id": token, "platform": session["platform"], "status": "expired"}
        if not force and now < session["next_poll_at"]:
            return {"link_id": token, "platform": session["platform"], "status": "waiting"}
        session["next_poll_at"] = now + session["interval"]
        result = await session["driver"].poll(session["state"])
        status = str(result.get("status") or "waiting").strip().lower()
        if result.get("_state") is not None:
            session["state"] = result["_state"]
        if status == "connected":
            credentials = result.get("credentials")
            if not isinstance(credentials, dict):
                raise RuntimeError("渠道返回的连接凭据不完整")
            session["driver"].persist(self.home, credentials)
            self._sessions.pop(token, None)
            return {
                "link_id": token,
                "platform": session["platform"],
                "status": "connected",
                "restart_required": True,
            }
        if status in {"expired", "denied", "error"}:
            self._sessions.pop(token, None)
        return {"link_id": token, "platform": session["platform"], "status": status}


class FeishuLinkDriver:
    """Adapt Feishu's device-code registration to one browser poll at a time."""

    def __init__(self, *, request: AsyncChannelRequest | None = None) -> None:
        self._request = request or self._real_request

    @staticmethod
    async def _real_request(
        action: str, state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        from honeyos.plugins.platforms.feishu.adapter import (
            _accounts_base_url,
            _begin_registration,
            _init_registration,
            _post_registration,
        )

        if action == "begin":
            await asyncio.to_thread(_init_registration, "feishu")
            return await asyncio.to_thread(_begin_registration, "feishu")
        if action != "poll" or not state:
            raise RuntimeError("飞书扫码状态无效")
        domain = str(state.get("domain") or "feishu")
        body = {
            "action": "poll",
            "device_code": str(state.get("device_code") or ""),
            "tp": "ob_app",
        }
        return await asyncio.to_thread(
            _post_registration, _accounts_base_url(domain), body
        )

    async def start(self) -> dict[str, Any]:
        result = await self._request("begin", None)
        device_code = str(result.get("device_code") or "").strip()
        if not device_code:
            raise RuntimeError("飞书没有返回扫码凭据")
        return {
            "qr_url": str(result.get("qr_url") or ""),
            "interval": int(result.get("interval") or 5),
            "expires_in": int(result.get("expire_in") or 600),
            "_state": {"device_code": device_code, "domain": "feishu"},
        }

    async def poll(self, state: dict[str, Any]) -> dict[str, Any]:
        result = await self._request("poll", state)
        user_info = result.get("user_info")
        user_info = user_info if isinstance(user_info, dict) else {}
        domain = str(state.get("domain") or "feishu")
        if user_info.get("tenant_brand") == "lark":
            domain = "lark"
        app_id = str(result.get("client_id") or "").strip()
        app_secret = str(result.get("client_secret") or "").strip()
        if app_id and app_secret:
            return {
                "status": "connected",
                "credentials": {
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "domain": domain,
                    "open_id": str(user_info.get("open_id") or "").strip(),
                },
            }
        error = str(result.get("error") or "").strip().lower()
        if error == "access_denied":
            return {"status": "denied"}
        if error == "expired_token":
            return {"status": "expired"}
        return {"status": "waiting", "_state": {**state, "domain": domain}}

    def persist(self, home: Path, credentials: dict[str, Any]) -> None:
        from honeyos.companion.setup import _set_env_value

        values = {
            "FEISHU_APP_ID": credentials.get("app_id"),
            "FEISHU_APP_SECRET": credentials.get("app_secret"),
            "FEISHU_DOMAIN": credentials.get("domain") or "feishu",
            "FEISHU_CONNECTION_MODE": "websocket",
            "FEISHU_ALLOW_ALL_USERS": "false",
            "FEISHU_ALLOWED_USERS": "",
            "FEISHU_GROUP_POLICY": "disabled",
        }
        for key, value in values.items():
            _set_env_value(home / ".env", key, str(value or ""))


async def _weixin_request(base_url: str, endpoint: str) -> dict[str, Any]:
    from honeyos.gateway.platforms import weixin

    if not weixin.AIOHTTP_AVAILABLE:
        raise RuntimeError("缺少微信扫码连接依赖")
    async with weixin.aiohttp.ClientSession(
        trust_env=True, connector=weixin._make_ssl_connector()
    ) as session:
        return await weixin._api_get(
            session,
            base_url=base_url,
            endpoint=endpoint,
            timeout_ms=weixin.QR_TIMEOUT_MS,
        )


class WeixinLinkDriver:
    """Adapt Weixin iLink QR login to browser-managed polling."""

    def __init__(self, *, request: AsyncWeixinRequest | None = None) -> None:
        self._request = request or _weixin_request

    async def start(self) -> dict[str, Any]:
        from honeyos.gateway.platforms.weixin import EP_GET_BOT_QR, ILINK_BASE_URL

        result = await self._request(ILINK_BASE_URL, f"{EP_GET_BOT_QR}?bot_type=3")
        qrcode = str(result.get("qrcode") or "").strip()
        qr_url = str(result.get("qrcode_img_content") or qrcode).strip()
        if not qrcode:
            raise RuntimeError("微信没有返回扫码凭据")
        return {
            "qr_url": qr_url,
            "interval": 1,
            "expires_in": 480,
            "_state": {"qrcode": qrcode, "base_url": ILINK_BASE_URL},
        }

    async def poll(self, state: dict[str, Any]) -> dict[str, Any]:
        from honeyos.gateway.platforms.weixin import EP_GET_QR_STATUS, ILINK_BASE_URL

        qrcode = str(state.get("qrcode") or "")
        result = await self._request(
            str(state.get("base_url") or ILINK_BASE_URL),
            f"{EP_GET_QR_STATUS}?qrcode={qrcode}",
        )
        status = str(result.get("status") or "wait").strip().lower()
        if status == "scaned_but_redirect":
            redirect = str(result.get("redirect_host") or "").strip()
            next_state = dict(state)
            if redirect:
                next_state["base_url"] = f"https://{redirect}"
            return {"status": "scanned", "_state": next_state}
        if status == "scaned":
            return {"status": "scanned"}
        if status == "expired":
            return {"status": "expired"}
        if status != "confirmed":
            return {"status": "waiting"}
        account_id = str(result.get("ilink_bot_id") or "").strip()
        token = str(result.get("bot_token") or "").strip()
        user_id = str(result.get("ilink_user_id") or "").strip()
        if not account_id or not token or not user_id:
            return {"status": "error"}
        return {
            "status": "connected",
            "credentials": {
                "account_id": account_id,
                "token": token,
                "base_url": str(result.get("baseurl") or ILINK_BASE_URL),
                "user_id": user_id,
            },
        }

    def persist(self, home: Path, credentials: dict[str, Any]) -> None:
        from honeyos.companion.setup import _set_env_value
        from honeyos.gateway.platforms.weixin import save_weixin_account

        account_id = str(credentials.get("account_id") or "")
        token = str(credentials.get("token") or "")
        base_url = str(credentials.get("base_url") or "")
        user_id = str(credentials.get("user_id") or "")
        save_weixin_account(
            str(home),
            account_id=account_id,
            token=token,
            base_url=base_url,
            user_id=user_id,
        )
        values = {
            "WEIXIN_ACCOUNT_ID": account_id,
            "WEIXIN_TOKEN": token,
            "WEIXIN_BASE_URL": base_url,
            "WEIXIN_CDN_BASE_URL": "https://novac2c.cdn.weixin.qq.com/c2c",
            "WEIXIN_DM_POLICY": "allowlist",
            "WEIXIN_ALLOW_ALL_USERS": "false",
            "WEIXIN_ALLOWED_USERS": user_id,
            "WEIXIN_GROUP_POLICY": "disabled",
            "WEIXIN_GROUP_ALLOWED_USERS": "",
            "WEIXIN_HOME_CHANNEL": user_id,
        }
        for key, value in values.items():
            _set_env_value(home / ".env", key, value)


def _real_drivers() -> dict[str, Any]:
    return {"feishu": FeishuLinkDriver(), "weixin": WeixinLinkDriver()}
