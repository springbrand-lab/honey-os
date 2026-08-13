"""Dashboard-mediated callback bridge for MCP OAuth.

The MCP SDK remains responsible for discovery, DCR, PKCE, state validation and
token exchange. This module only moves the two human/browser callbacks from a
loopback listener into the already-authenticated dashboard session.
"""

from __future__ import annotations

import asyncio
import contextvars
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse


@dataclass
class DashboardOAuthFlow:
    flow_id: str
    server_name: str
    profile: str | None
    honeyos_home: str
    redirect_uri: str
    reconnect_live: bool = False
    created_at: float = field(default_factory=time.time)
    status: str = "starting"
    authorization_url: str | None = None
    error: str | None = None
    tools: list[dict] = field(default_factory=list)
    expected_state: str | None = field(default=None, init=False)
    _callback: tuple[str, str | None] | None = field(
        default=None, init=False, repr=False
    )
    _callback_error: str | None = field(default=None, init=False, repr=False)
    _authorization_ready: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _callback_ready: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _worker_done: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    async def publish_authorization_url(self, url: str) -> None:
        state = parse_qs(urlparse(url).query).get("state", [None])[0]
        if not state:
            raise ValueError("OAuth authorization URL did not include state")
        with self._lock:
            if self.status in {"approved", "error"}:
                raise RuntimeError("OAuth flow already ended")
            self.expected_state = state
            self.authorization_url = url
            self.status = "authorization_required"
            self._authorization_ready.set()

    async def wait_for_authorization_url(self, timeout: float = 30.0) -> str | None:
        ready = await asyncio.to_thread(self._authorization_ready.wait, timeout)
        if not ready:
            raise TimeoutError("Timed out waiting for MCP authorization URL")
        if self.status == "approved":
            return None
        if not self.authorization_url:
            raise RuntimeError(
                self.error or "MCP OAuth flow ended before authorization"
            )
        return self.authorization_url

    def deliver_callback(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> None:
        with self._lock:
            if self._callback_ready.is_set():
                raise ValueError("OAuth callback already received")
            if (
                self.expected_state is None
                or state is None
                or not secrets.compare_digest(self.expected_state, state)
            ):
                raise ValueError("OAuth callback state mismatch")
            if error:
                self._callback_error = error
            elif code:
                self._callback = (code, state)
            else:
                self._callback_error = "OAuth callback did not include code or error"
            self._callback_ready.set()

    async def wait_for_callback(self, timeout: float = 300.0) -> tuple[str, str | None]:
        ready = await asyncio.to_thread(self._callback_ready.wait, timeout)
        if not ready:
            raise TimeoutError("Timed out waiting for MCP OAuth callback")
        if self._callback_error:
            raise RuntimeError(f"OAuth authorization failed: {self._callback_error}")
        if self._callback is None:
            raise RuntimeError("OAuth callback did not include an authorization code")
        return self._callback

    def mark_approved(self) -> None:
        with self._lock:
            if self.status == "error":
                raise RuntimeError("OAuth flow already ended")
            self.status = "approved"
            self.error = None
            self._authorization_ready.set()

    def mark_error(self, error: str) -> None:
        with self._lock:
            if self.status == "approved":
                return
            self.status = "error"
            self.error = error
            self._authorization_ready.set()
            self._callback_ready.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "flow_id": self.flow_id,
                "server_name": self.server_name,
                "status": self.status,
                "authorization_url": self.authorization_url,
                "error": self.error,
            }

    def mark_worker_done(self) -> None:
        self._worker_done.set()

    @property
    def worker_done(self) -> bool:
        return self._worker_done.is_set()


_current_dashboard_flow: contextvars.ContextVar[DashboardOAuthFlow | None] = (
    contextvars.ContextVar("mcp_dashboard_oauth_flow", default=None)
)
_oauth_transactions: dict[tuple[str, str], threading.Lock] = {}
_oauth_transactions_lock = threading.Lock()


@contextmanager
def dashboard_oauth_flow(flow: DashboardOAuthFlow) -> Iterator[None]:
    token = _current_dashboard_flow.set(flow)
    try:
        yield
    finally:
        _current_dashboard_flow.reset(token)


def get_dashboard_oauth_flow() -> DashboardOAuthFlow | None:
    return _current_dashboard_flow.get()


def _oauth_transaction(flow: DashboardOAuthFlow) -> threading.Lock:
    key = (flow.honeyos_home, flow.server_name)
    with _oauth_transactions_lock:
        return _oauth_transactions.setdefault(key, threading.Lock())


def _probe_server_isolated(
    server_name: str, cfg: dict, *, connect_timeout: float
) -> list[tuple[str, str]]:
    """Probe an interactive OAuth server without the runtime's shared MCP loop."""
    from honeyos.tools.mcp_tool import _connect_server

    async def probe() -> list[tuple[str, str]]:
        server = await asyncio.wait_for(
            _connect_server(server_name, cfg), timeout=connect_timeout
        )
        try:
            return [
                (tool.name, (getattr(tool, "description", "") or "")[:80])
                for tool in server._tools
            ]
        finally:
            await server.shutdown()

    return asyncio.run(probe())


def run_dashboard_mcp_oauth(flow: DashboardOAuthFlow, cfg: dict) -> None:
    """Run the normal MCP probe with browser-mediated redirect callbacks."""
    from honeyos.runtime.mcp_config import (
        _oauth_tokens_present,
        _save_mcp_server,
    )

    try:
        from honeyos.agent.secret_scope import (
            build_profile_secret_scope,
            reset_secret_scope,
            set_secret_scope,
        )
        from honeyos.core.constants import (
            reset_honeyos_home_override,
            set_honeyos_home_override,
        )
        from honeyos.tools.mcp_oauth import HoneyOSTokenStorage, force_interactive_oauth
        from honeyos.tools.mcp_oauth_manager import get_manager

        home_token = set_honeyos_home_override(flow.honeyos_home)
        secret_token = set_secret_scope(
            build_profile_secret_scope(Path(flow.honeyos_home))
        )
        try:
            with (
                _oauth_transaction(flow),
                force_interactive_oauth(),
                dashboard_oauth_flow(flow),
            ):
                manager = get_manager()
                storage = HoneyOSTokenStorage(flow.server_name)
                backup = storage.snapshot()
                previous_entry = None
                try:
                    previous_entry = manager.remove(
                        flow.server_name,
                        honeyos_home=flow.honeyos_home,
                    )
                    tools = _probe_server_isolated(
                        flow.server_name,
                        cfg,
                        connect_timeout=max(
                            float(cfg.get("connect_timeout", 0) or 0), 315
                        ),
                    )
                    if not _oauth_tokens_present(flow.server_name):
                        raise RuntimeError(
                            "The server responded, but no OAuth token was obtained — "
                            "this provider may require a manually-registered OAuth client."
                        )
                    _save_mcp_server(flow.server_name, cfg)
                    flow.tools = [
                        {"name": name, "description": desc} for name, desc in tools
                    ]
                    flow.mark_approved()
                    if flow.reconnect_live:
                        from honeyos.tools.mcp_tool import reconnect_mcp_server

                        reconnect_mcp_server(flow.server_name)
                except Exception:
                    storage.restore(backup, only_if_absent=True)
                    manager.restore_entry(
                        flow.server_name,
                        previous_entry,
                        honeyos_home=flow.honeyos_home,
                    )
                    raise
        finally:
            reset_secret_scope(secret_token)
            reset_honeyos_home_override(home_token)
    except Exception as exc:
        message = str(exc)
        try:
            from honeyos.tools.mcp_oauth import humanize_oauth_registration_error

            humanized = humanize_oauth_registration_error(
                flow.server_name,
                exc,
                server_url=cfg.get("url") if isinstance(cfg, dict) else None,
            )
            if humanized:
                message = humanized
        except Exception:
            pass
        flow.mark_error(message)
    finally:
        flow.mark_worker_done()
