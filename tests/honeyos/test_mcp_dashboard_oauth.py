from __future__ import annotations

import pytest

from honeyos.tools.mcp_dashboard_oauth import DashboardOAuthFlow


@pytest.mark.asyncio
async def test_approved_flow_wakes_authorization_waiter_without_url(tmp_path):
    flow = DashboardOAuthFlow(
        flow_id="flow-1",
        server_name="example",
        profile=None,
        honeyos_home=str(tmp_path),
        redirect_uri="http://127.0.0.1:8642/callback",
    )

    flow.mark_approved()

    assert await flow.wait_for_authorization_url(timeout=0.01) is None


def test_dashboard_oauth_probe_does_not_use_shared_runtime_loop(monkeypatch, tmp_path):
    import asyncio

    import honeyos.tools.mcp_tool as mcp_tool
    from honeyos.tools.mcp_dashboard_oauth import run_dashboard_mcp_oauth

    class FakeServer:
        _tools = []

        async def shutdown(self):
            return None

    async def connect_server(_name, _config):
        assert asyncio.get_running_loop() is not shared_loop
        return FakeServer()

    class FakeManager:
        def remove(self, *_args, **_kwargs):
            return None

        def restore_entry(self, *_args, **_kwargs):
            return None

    mcp_tool._ensure_mcp_loop()
    shared_loop = mcp_tool._mcp_loop
    monkeypatch.setattr(mcp_tool, "_connect_server", connect_server)
    monkeypatch.setattr(
        "honeyos.tools.mcp_oauth_manager.get_manager", lambda: FakeManager()
    )
    monkeypatch.setattr(
        "honeyos.runtime.mcp_config._oauth_tokens_present", lambda _name: True
    )
    monkeypatch.setattr(
        "honeyos.runtime.mcp_config._save_mcp_server", lambda *_args: None
    )

    flow = DashboardOAuthFlow(
        flow_id="flow-isolated",
        server_name="example",
        profile=None,
        honeyos_home=str(tmp_path),
        redirect_uri="http://127.0.0.1:8642/callback",
    )

    run_dashboard_mcp_oauth(flow, {"url": "https://mcp.example.test"})

    assert flow.status == "approved"
    assert flow.worker_done
