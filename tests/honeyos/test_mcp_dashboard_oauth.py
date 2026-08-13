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
    activated = []
    monkeypatch.setattr(
        mcp_tool,
        "activate_mcp_server",
        lambda name: activated.append(name) or True,
    )

    flow = DashboardOAuthFlow(
        flow_id="flow-isolated",
        server_name="example",
        profile=None,
        honeyos_home=str(tmp_path),
        redirect_uri="http://127.0.0.1:8642/callback",
        reconnect_live=True,
    )

    run_dashboard_mcp_oauth(flow, {"url": "https://mcp.example.test"})

    assert flow.status == "approved"
    assert flow.worker_done
    assert activated == ["example"]


def test_activate_mcp_server_registers_server_missing_from_runtime(monkeypatch):
    import honeyos.tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "_servers", {})
    monkeypatch.setattr(mcp_tool, "_server_connecting", set())
    monkeypatch.setattr(mcp_tool, "_lazy_server_configs", {})
    monkeypatch.setattr(
        mcp_tool,
        "_load_mcp_config",
        lambda: {"example": {"url": "https://mcp.example.test"}},
    )
    registered = []

    def register(servers):
        registered.append(servers)
        mcp_tool._servers["example"] = object()
        return ["example_tool"]

    monkeypatch.setattr(mcp_tool, "register_mcp_servers", register)

    assert mcp_tool.activate_mcp_server("example") is True
    assert registered == [{"example": {"url": "https://mcp.example.test"}}]


def test_between_turns_activation_only_runs_for_new_config_revision(
    monkeypatch, tmp_path
):
    import honeyos.tools.mcp_tool as mcp_tool

    config_path = tmp_path / "config.yaml"
    config_path.write_text("mcp_servers: {}\n", encoding="utf-8")
    monkeypatch.setattr("honeyos.runtime.config.get_config_path", lambda: config_path)
    monkeypatch.setattr(mcp_tool, "_mcp_config_activation_stamps", {})
    existing_server = object()
    monkeypatch.setattr(mcp_tool, "_servers", {"notion": existing_server})
    monkeypatch.setattr(mcp_tool, "_server_connecting", set())
    monkeypatch.setattr(mcp_tool, "_lazy_server_configs", {})
    monkeypatch.setattr(
        mcp_tool,
        "_load_mcp_config",
        lambda: {
            "notion": {"url": "https://mcp.notion.test"},
            "example": {"url": "https://mcp.example.test"},
        },
    )
    calls = []

    def register(servers):
        calls.append(servers)
        mcp_tool._servers["example"] = object()
        return ["example_tool"]

    monkeypatch.setattr(mcp_tool, "register_mcp_servers", register)

    assert mcp_tool.activate_new_mcp_servers_if_config_changed() == {"example"}
    assert mcp_tool.activate_new_mcp_servers_if_config_changed() == set()
    assert mcp_tool._servers["notion"] is existing_server
    assert calls == [{"example": {"url": "https://mcp.example.test"}}]
