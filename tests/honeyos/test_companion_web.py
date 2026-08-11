from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import json

import pytest
import yaml

from honeyos.companion.activity import project_activity, project_presence
from honeyos.cli.main import _parser
from honeyos.companion.config import initialize_home
from honeyos.companion.setup import _choose_im_platforms
from honeyos.companion.web import (
    companion_profile,
    companion_web_url,
    open_companion_web,
    wait_for_companion_web,
)
from honeyos.gateway.config import Platform
from honeyos.gateway.config import PlatformConfig
from honeyos.gateway.platforms.api_server import (
    APIServerAdapter,
    _companion_approval_event_payload,
    _companion_tool_event_payload,
    _run_completed_event_payload,
    _runtime_provider_identity,
    _security_headers_for_path,
)
from honeyos.gateway.session import SessionSource, build_session_key


def _dm(platform: Platform, chat_id: str) -> SessionSource:
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        chat_type="dm",
        user_id=chat_id,
    )


def test_private_companion_channels_share_one_owner_session(monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")

    web = build_session_key(_dm(Platform.API_SERVER, "local-owner"))
    feishu = build_session_key(_dm(Platform.FEISHU, "ou_123"))
    weixin = build_session_key(_dm(Platform.WEIXIN, "wx_456"))

    assert web == feishu == weixin == "agent:main:companion:dm:owner"


def test_non_companion_runtime_keeps_platform_session_isolation(monkeypatch):
    monkeypatch.delenv("HONEYOS_RUNTIME_ID", raising=False)

    web = build_session_key(_dm(Platform.API_SERVER, "local-owner"))
    feishu = build_session_key(_dm(Platform.FEISHU, "ou_123"))

    assert web != feishu
    assert web == "agent:main:api_server:dm:local-owner"


def test_activity_projection_hides_raw_tool_details():
    activity = project_activity(
        "tool.started",
        "web_search",
        preview="curl https://secret.example?q=private",
        args={"api_key": "sk-secret", "query": "private"},
    )

    assert activity == {
        "activity_id": "activity",
        "kind": "checking",
        "state": "active",
        "title": "正在找相关内容",
        "detail": "我先替你找找看",
    }
    assert "web_search" not in str(activity)
    assert "secret" not in str(activity)


def test_presence_projection_never_contains_reasoning():
    presence = project_presence(preview="private chain of thought")

    assert presence == {
        "activity_id": "presence",
        "kind": "presence",
        "state": "active",
        "title": "我在想你刚才说的事",
        "detail": "",
    }
    assert "private" not in str(presence)


def test_activity_projection_keeps_only_opaque_identifier():
    activity = project_activity(
        "tool.started",
        "web_search",
        activity_id="activity_3",
        preview="curl https://secret.example",
        args={"api_key": "sk-secret"},
    )

    assert activity["activity_id"] == "activity_3"
    assert set(activity) == {
        "activity_id",
        "kind",
        "state",
        "title",
        "detail",
    }
    assert "web_search" not in str(activity)
    assert "secret" not in str(activity)


def test_activity_projection_collapses_success_and_softens_failure():
    completed = project_activity("tool.completed", "web_fetch")
    failed = project_activity("tool.failed", "terminal")

    assert completed == {
        "activity_id": "activity",
        "kind": "checking",
        "state": "completed",
        "title": "已经看过相关内容了",
        "detail": "",
    }
    assert failed == {
        "activity_id": "activity",
        "kind": "handling",
        "state": "failed",
        "title": "刚才没走通，我换个办法",
        "detail": "",
    }


def test_activity_projection_gives_skill_steps_distinct_safe_copy():
    steps = [
        project_activity("tool.completed", "skills_list"),
        project_activity("tool.completed", "skill_view", args={"name": "private-skill"}),
        project_activity(
            "tool.completed",
            "skill_marketplace",
            args={"action": "search", "query": "private image request"},
        ),
        project_activity(
            "tool.completed",
            "skill_marketplace",
            args={"action": "install", "identifier": "private/image-skill"},
        ),
    ]

    assert [step["title"] for step in steps] == [
        "已经看过现有能力了",
        "已经读完使用说明了",
        "找到了可以用的能力",
        "新能力已经准备好了",
    ]
    assert len({step["title"] for step in steps}) == len(steps)
    assert "private" not in str(steps)
    assert "image-skill" not in str(steps)


def test_activity_projection_distinguishes_common_work_without_leaking_details():
    steps = [
        project_activity(
            "tool.completed",
            "web_search",
            args={"query": "private query"},
        ),
        project_activity(
            "tool.completed",
            "web_fetch",
            args={"url": "https://secret.example"},
        ),
        project_activity(
            "tool.completed",
            "write_file",
            args={"path": "/Users/private/secret.html"},
        ),
    ]

    assert [step["title"] for step in steps] == [
        "已经找到相关内容了",
        "已经看过相关内容了",
        "文件已经替你写好了",
    ]
    assert "private" not in str(steps)
    assert "secret" not in str(steps)


def test_initialize_home_enables_loopback_web_without_an_account(tmp_path):
    initialize_home(tmp_path)

    config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")

    api_server = config["platforms"]["api_server"]
    assert api_server["enabled"] is True
    assert api_server["extra"]["host"] == "127.0.0.1"
    assert api_server["extra"]["port"] == 8642
    assert "api_server" in config["platform_toolsets"]
    assert "API_SERVER_KEY=" in env_text
    assert len(env_text.split("API_SERVER_KEY=", 1)[1].splitlines()[0]) >= 32


def test_companion_profile_uses_identity_name_and_never_returns_file_body(tmp_path):
    memories = tmp_path / "memories"
    memories.mkdir(parents=True)
    (memories / "IDENTITY.md").write_text(
        "名字：阿凛\n性格：冷静、毒舌\nAPI Key：sk-never-show",
        encoding="utf-8",
    )

    profile = companion_profile(tmp_path)

    assert profile == {"name": "阿凛", "status": "在这儿"}
    assert "毒舌" not in str(profile)
    assert "sk-never-show" not in str(profile)


def test_companion_web_header_reads_managed_profile_name(tmp_path):
    from honeyos.companion.config import initialize_home
    from honeyos.companion.profile import update_companion_profile

    initialize_home(tmp_path)
    update_companion_profile(
        tmp_path,
        companion_name="小意",
        personality="嘴硬心软",
        source="user_explicit",
    )

    assert companion_profile(tmp_path) == {"name": "小意", "status": "在这儿"}


def test_companion_web_url_is_loopback_only():
    assert companion_web_url() == "http://127.0.0.1:8642/"
    assert companion_web_url(port=9123) == "http://127.0.0.1:9123/"


def test_open_companion_web_uses_the_loopback_url():
    opened = []

    def record(url):
        opened.append(url)
        return True

    assert open_companion_web(open_fn=record) is True
    assert opened == ["http://127.0.0.1:8642/"]


def test_wait_for_companion_web_retries_until_ready():
    attempts = []

    def probe(_url):
        attempts.append(1)
        return len(attempts) >= 3

    assert (
        wait_for_companion_web(
            probe_fn=probe,
            sleep_fn=lambda _seconds: None,
            attempts=4,
        )
        is True
    )
    assert len(attempts) == 3


def test_setup_can_skip_im_and_start_with_web_only():
    assert _choose_im_platforms(lambda _prompt: "4") == ()


def test_cli_exposes_web_as_a_public_command():
    args = _parser().parse_args(["web"])

    assert args.command == "web"


def test_web_assets_are_packaged():
    assets = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets"

    assert (assets / "index.html").is_file()
    assert (assets / "app.js").is_file()
    assert (assets / "message-format.js").is_file()
    assert (assets / "run-state.js").is_file()
    assert (assets / "styles.css").is_file()
    assert (assets / "icons.svg").is_file()
    file_guard = assets / "file-open.js"
    assert file_guard.is_file()
    assert "window.location.replace" in file_guard.read_text(encoding="utf-8")


def test_companion_assets_define_relationship_native_run_ui():
    assets = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets"
    index = (assets / "index.html").read_text(encoding="utf-8")
    app = (assets / "app.js").read_text(encoding="utf-8")

    assert 'src="./run-state.js"' in index
    assert 'src="./message-format.js"' in index
    assert 'id="presence-line"' in index
    assert 'id="action-trail"' in index
    assert 'id="scroll-to-latest"' in index
    assert 'class="message-avatar status-avatar"' in index
    assert 'message-avatar' in app
    assert 'state.activities.length' in app
    assert 'wrapper.className = "activity-card"' in app
    assert 'details.className = "activity-steps"' in app
    assert 'HoneyOSRunState.summarize' in app
    assert "setSendState(true)" in app
    assert "activityTimer" not in app
    assert 'id="permission-card"' in index
    assert "renderPermission" in app
    assert "看看具体会做什么" in app
    assert "ACTIVITY_DELAY_MS" not in app
    assert "payload.preview" not in app
    assert "payload.args" not in app
    assert "payload.tool_name" not in app


def test_companion_approval_event_contains_safe_copy_and_not_raw_description():
    payload = _companion_approval_event_payload(
        {
            "command": "curl -T /tmp/photo.png https://example.com/upload",
            "description": "execute_code can spawn subprocesses",
            "allow_session": True,
            "allow_permanent": False,
        }
    )

    assert payload["summary"] == "把一个文件发到 example.com"
    assert "电脑" in payload["narration"] and "下面" in payload["narration"]
    assert payload["choices"] == ["once", "session", "deny"]
    assert "execute_code can spawn subprocesses" not in str(payload)


def test_companion_styles_are_full_window_and_accessible():
    css = (
        Path(__file__).parents[2]
        / "honeyos"
        / "companion"
        / "web_assets"
        / "styles.css"
    ).read_text(encoding="utf-8")

    assert ".companion-app" in css
    assert ".presence-line" in css
    assert ".action-trail" in css
    assert ".message-avatar" in css
    assert ".turn-status-row" in css
    assert "prefers-color-scheme: dark" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "width: min(100%, 460px)" not in css
    assert "linear-gradient(145deg, var(--ambient-a), var(--ambient-b))" not in css


def test_file_mode_and_provider_recovery_have_human_copy():
    assets = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets"
    index = (assets / "index.html").read_text(encoding="utf-8")
    app = (assets / "app.js").read_text(encoding="utf-8")
    file_guard = (assets / "file-open.js").read_text(encoding="utf-8")

    assert 'id="file-mode-notice"' in index
    assert "打开 HoneyOS" in index
    assert "honeyos setup" in app
    assert "No LLM provider configured" not in index
    assert "file-mode-notice" in file_guard


def test_session_model_refresh_keeps_named_custom_provider_identity():
    runtime = {
        "provider": "custom",
        "requested_provider": "honeyos-model",
        "base_url": "https://example.invalid/v1",
        "api_key": "configured",
    }

    assert _runtime_provider_identity(runtime) == "honeyos-model"
    assert _runtime_provider_identity({"provider": "openrouter"}) == "openrouter"


def test_session_model_agent_refresh_does_not_replace_named_provider_credentials(
    monkeypatch,
):
    import honeyos.gateway.platforms.api_server as api_server
    import honeyos.gateway.run as gateway_run
    import honeyos.run_agent as run_agent

    captured = {}
    refreshed = []

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.provider = kwargs.get("provider")
            self.model = kwargs.get("model")

    def resolve_provider(provider, target_model=None):
        refreshed.append((provider, target_model))
        assert provider == "honeyos-model"
        return {
            "provider": "custom",
            "requested_provider": "honeyos-model",
            "base_url": "https://configured.example/v1",
            "api_key": "configured-key",
            "api_mode": "chat_completions",
        }

    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "custom",
            "requested_provider": "honeyos-model",
            "base_url": "https://configured.example/v1",
            "api_key": "configured-key",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(gateway_run, "_resolve_gateway_model", lambda: "default-model")
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(
        api_server, "_resolve_request_runtime_agent_kwargs", resolve_provider
    )

    adapter = _api_adapter()
    monkeypatch.setattr(adapter, "_ensure_session_db", lambda: None)
    adapter._create_agent(
        session_id="session-1",
        gateway_session_key="owner",
        session_model="deepseek-v4-flash",
    )

    assert refreshed == [("honeyos-model", "deepseek-v4-flash")]
    assert captured["api_key"] == "configured-key"
    assert captured["base_url"] == "https://configured.example/v1"
    assert captured["requested_provider"] == "honeyos-model"


def test_companion_stream_payloads_never_include_raw_tool_or_reasoning_data():
    tool_payload = _companion_tool_event_payload(
        event_type="tool.started",
        message_id="message-1",
        tool_name="terminal",
        activity_id="activity-1",
        preview="curl https://private.example",
        args={"api_key": "secret"},
    )
    completed_payload = _run_completed_event_payload(
        companion_view=True,
        session_id="session-1",
        message_id="message-1",
        turn_messages=[{"role": "assistant", "reasoning": "private"}],
        usage={"input_tokens": 99},
        runtime={"provider": "custom", "model": "test"},
    )

    assert set(tool_payload) == {"message_id", "activity"}
    assert "terminal" not in str(tool_payload)
    assert "private" not in str(tool_payload)
    assert completed_payload == {
        "session_id": "session-1",
        "message_id": "message-1",
        "completed": True,
        "runtime": {"provider": "custom", "model": "test"},
    }


def _api_adapter() -> APIServerAdapter:
    return APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "host": "127.0.0.1",
                "port": 8642,
                "key": "a" * 32,
            },
        )
    )


def test_api_server_registers_companion_web_routes():
    adapter = _api_adapter()
    routes = {(method, path) for method, path, _handler in adapter._http_route_table()}

    assert ("GET", "/") in routes
    assert ("GET", "/file-open.js") in routes
    assert ("GET", "/message-format.js") in routes
    assert ("GET", "/run-state.js") in routes
    assert ("GET", "/app.js") in routes
    assert ("GET", "/styles.css") in routes
    assert ("GET", "/icons.svg") in routes
    assert ("GET", "/honeyos/run-state.js") in routes
    assert ("GET", "/honeyos/message-format.js") in routes
    assert ("GET", "/honeyos/app.js") in routes
    assert ("GET", "/honeyos/styles.css") in routes
    assert ("GET", "/honeyos/icons.svg") in routes
    assert ("GET", "/api/companion/bootstrap") in routes
    assert ("GET", "/api/companion/settings") in routes
    assert ("POST", "/api/companion/settings/models") in routes
    assert ("POST", "/api/companion/settings/model") in routes
    assert ("POST", "/api/companion/channels/{platform}/link") in routes
    assert ("GET", "/api/companion/channels/link/{link_id}") in routes
    assert ("POST", "/api/companion/new") in routes
    assert ("POST", "/api/companion/profile") in routes
    assert ("POST", "/api/companion/memories/{memory_id}") in routes
    assert ("GET", "/api/companion/topics") in routes
    assert ("POST", "/api/companion/topics/{topic_id}/discuss") in routes
    assert ("POST", "/api/companion/topics/{topic_id}/dismiss") in routes
    assert ("GET", "/api/companion/proactive-preferences") in routes
    assert ("POST", "/api/companion/proactive/claim") in routes
    assert (
        "POST",
        "/api/companion/proactive/{delivery_id}/complete",
    ) in routes


@pytest.mark.asyncio
async def test_companion_model_settings_endpoint_never_echoes_api_key(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    monkeypatch.setattr(
        "honeyos.companion.setup.validate_model_key",
        lambda _choice, _key: None,
    )
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")
    adapter = _api_adapter()
    adapter._read_json_body = AsyncMock(
        return_value=(
            {
                "base_url": "https://models.example/v1",
                "model": "companion-model",
                "api_key": "sk-private-value",
            },
            None,
        )
    )
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
    )

    response = await adapter._handle_companion_model_settings(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["settings"]["model"]["model"] == "companion-model"
    assert payload["settings"]["model"]["api_key_configured"] is True
    assert "sk-private-value" not in response.text


@pytest.mark.asyncio
async def test_companion_model_discovery_endpoint_returns_ids_without_echoing_key(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    monkeypatch.setattr(
        "honeyos.companion.settings.discover_companion_models",
        lambda home, **kwargs: ["model-a", "model-b"],
    )
    adapter = _api_adapter()
    adapter._read_json_body = AsyncMock(
        return_value=(
            {
                "provider": "custom",
                "base_url": "https://models.example/v1",
                "api_key": "sk-private-value",
            },
            None,
        )
    )
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
    )

    response = await adapter._handle_companion_model_discovery(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload == {"models": ["model-a", "model-b"]}
    assert "sk-private-value" not in response.text


@pytest.mark.asyncio
async def test_companion_channel_link_endpoints_return_only_safe_qr_state(tmp_path):
    adapter = _api_adapter()
    manager = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "link_id": "safe-link",
                "platform": "feishu",
                "status": "waiting",
                "qr_url": "https://scan.example",
                "qr_image": "data:image/png;base64,image",
                "expires_in": 300,
            }
        ),
        poll=AsyncMock(
            return_value={
                "link_id": "safe-link",
                "platform": "feishu",
                "status": "connected",
                "restart_required": True,
            }
        ),
    )
    adapter._companion_link_manager = manager
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={"platform": "feishu"},
    )

    started = await adapter._handle_companion_channel_link(request)
    request.match_info = {"link_id": "safe-link"}
    completed = await adapter._handle_companion_channel_link_status(request)

    assert json.loads(started.text)["qr_image"].startswith("data:image/png")
    assert json.loads(completed.text)["status"] == "connected"
    assert "secret" not in started.text.lower()
    assert "secret" not in completed.text.lower()


@pytest.mark.asyncio
async def test_companion_channel_link_hides_transport_failure_details():
    adapter = _api_adapter()
    adapter._companion_link_manager = SimpleNamespace(
        start=AsyncMock(side_effect=OSError("private transport detail"))
    )
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={"platform": "feishu"},
    )

    response = await adapter._handle_companion_channel_link(request)

    assert response.status == 502
    assert "private transport detail" not in response.text


def test_companion_web_message_records_real_recent_channel():
    adapter = object.__new__(APIServerAdapter)
    runner = MagicMock()
    runner._record_topic_pool_channel_activity.return_value = True
    adapter.gateway_runner = runner

    assert adapter._record_companion_web_activity(companion_view=True) is True

    event, source = runner._record_topic_pool_channel_activity.call_args.args
    assert event.internal is False
    assert source.platform == Platform.API_SERVER
    assert source.chat_id == "local-owner"
    assert source.chat_type == "dm"
    assert source.user_id == "local-owner"
    assert runner._record_topic_pool_channel_activity.call_args.kwargs == {
        "is_internal": False
    }


def test_non_companion_api_message_does_not_change_recent_channel():
    adapter = object.__new__(APIServerAdapter)
    runner = MagicMock()
    adapter.gateway_runner = runner

    assert adapter._record_companion_web_activity(companion_view=False) is False
    runner._record_topic_pool_channel_activity.assert_not_called()


def test_local_web_cookie_auth_is_loopback_only():
    adapter = _api_adapter()
    cookie = adapter._local_web_token

    local_request = SimpleNamespace(
        cookies={"honeyos_local": cookie},
        remote="127.0.0.1",
        headers={},
    )
    remote_request = SimpleNamespace(
        cookies={"honeyos_local": cookie},
        remote="192.168.1.20",
        headers={},
    )

    assert adapter._check_auth(local_request) is None
    assert adapter._check_auth(remote_request).status == 401


def test_same_origin_loopback_browser_request_is_allowed():
    adapter = _api_adapter()

    assert adapter._origin_allowed("http://127.0.0.1:8642") is True
    assert adapter._origin_allowed("http://localhost:8642") is True
    assert adapter._origin_allowed("https://attacker.example") is False


def test_companion_page_csp_allows_only_its_own_assets_and_stream():
    page_policy = _security_headers_for_path("/")["Content-Security-Policy"]
    api_policy = _security_headers_for_path("/v1/models")["Content-Security-Policy"]

    assert "default-src 'self'" in page_policy
    assert "connect-src 'self'" in page_policy
    assert "script-src 'self'" in page_policy
    assert api_policy == "default-src 'none'; frame-ancestors 'none'"


@pytest.mark.asyncio
async def test_companion_index_establishes_an_http_only_local_session():
    adapter = _api_adapter()
    request = SimpleNamespace(remote="127.0.0.1")

    response = await adapter._handle_companion_index(request)

    assert response.status == 200
    assert b"HoneyOS" in response.body
    cookie = response.cookies["honeyos_local"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Strict"


@pytest.mark.asyncio
async def test_companion_bootstrap_returns_only_safe_shared_chat_messages(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")
    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "IDENTITY.md").write_text(
        "名字：阿凛\n性格：冷静",
        encoding="utf-8",
    )
    (tmp_path / "memories" / "MEMORY.md").write_text(
        "用户喜欢晚上散步。",
        encoding="utf-8",
    )

    adapter = _api_adapter()
    store = SimpleNamespace(
        get_or_create_session=AsyncMock(
            return_value=SimpleNamespace(session_id="shared-session")
        )
    )
    adapter.gateway_runner = SimpleNamespace(async_session_store=store)
    db = MagicMock()
    db.resolve_resume_session_id.return_value = "shared-session"
    db.get_messages.return_value = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "在呢。"},
        {
            "role": "assistant",
            "content": "找到几个，我再看看。",
            "tool_calls": [{"id": "call-1", "function": {"name": "web_search"}}],
        },
        {"role": "tool", "content": "raw command output"},
        {"role": "assistant", "content": "查好了，给你看。", "tool_calls": None},
        {
            "role": "user",
            "content": "[HoneyOS proactive topic seed; internal, not user-authored] hidden",
        },
        {
            "role": "user",
            "content": "[HoneyOS selected topic; user chose this card] hidden",
        },
        {"role": "assistant", "content": None, "reasoning": "hidden"},
    ]
    adapter._ensure_session_db_async = AsyncMock(return_value=db)
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        app={},
    )

    response = await adapter._handle_companion_bootstrap(request)
    payload = json.loads(response.text)

    assert payload["profile"] == {"name": "阿凛", "status": "在这儿"}
    assert payload["session_id"] == "shared-session"
    assert payload["session_key"] == "agent:main:companion:dm:owner"
    assert payload["messages"] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "在呢。"},
        {"role": "assistant", "content": "查好了，给你看。"},
    ]
    assert len(payload["memories"]) == 1
    assert payload["memories"][0]["kind"] == "long_term_memory"
    assert payload["memories"][0]["content"] == "用户喜欢晚上散步。"
    assert payload["memories"][0]["evidence"] == "persistent_memory"
    assert "找到几个，我再看看。" not in response.text
    assert "reasoning" not in response.text
    assert "raw command output" not in response.text
    assert "proactive topic seed" not in response.text
    assert "selected topic" not in response.text


@pytest.mark.asyncio
async def test_companion_memory_action_updates_only_the_owner_lane(monkeypatch, tmp_path):
    from honeyos.companion.continuity import StructuredMemoryStore

    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")
    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    lane_key = "agent:main:companion:dm:owner"
    item = StructuredMemoryStore(tmp_path).record(
        lane_key=lane_key,
        kind="commitment",
        content="明晚陪用户模拟面试",
        evidence="assistant_committed",
        source_session_id="session-old",
        source_message_ids=(7,),
    )
    assert item is not None

    adapter = _api_adapter()
    adapter._read_json_body = AsyncMock(return_value=({"action": "resolve"}, None))
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={"memory_id": item.id},
    )

    response = await adapter._handle_companion_memory_action(request)

    assert response.status == 200
    assert StructuredMemoryStore(tmp_path).list_active(lane_key=lane_key) == ()


@pytest.mark.asyncio
async def test_companion_memory_action_forgets_the_real_persistent_entry(
    monkeypatch, tmp_path
):
    from honeyos.companion.persistent_memory import list_persistent_memories

    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir()
    memory_path = memory_dir / "MEMORY.md"
    memory_path.write_text("第一条。\n§\n第二条。", encoding="utf-8")
    first, second = list_persistent_memories(tmp_path)

    adapter = _api_adapter()
    adapter._read_json_body = AsyncMock(return_value=({"action": "forget"}, None))
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={"memory_id": first.id},
    )

    response = await adapter._handle_companion_memory_action(request)

    assert response.status == 200
    assert memory_path.read_text(encoding="utf-8") == second.content


@pytest.mark.asyncio
async def test_companion_profile_form_is_an_explicit_profile_update(monkeypatch, tmp_path):
    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    adapter = _api_adapter()
    adapter._read_json_body = AsyncMock(
        return_value=(
            {
                "companion_name": "小树",
                "speaking_style": "温柔、直接、不说教",
                "user_nickname": "宝宝",
            },
            None,
        )
    )
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={},
    )

    response = await adapter._handle_companion_profile_update(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["profile"]["companion_name"] == "小树"
    assert payload["profile"]["user_nickname"] == "宝宝"
    assert "小树" in (tmp_path / "memories" / "IDENTITY.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_companion_new_keeps_a_source_backed_handoff(monkeypatch, tmp_path):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))
    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    old_entry = SimpleNamespace(session_id="session-old")
    new_entry = SimpleNamespace(session_id="session-new")
    store = SimpleNamespace(
        get_or_create_session=AsyncMock(return_value=old_entry),
        load_transcript=AsyncMock(
            return_value=[
                {"role": "user", "content": "我周五要面试", "id": 1},
                {"role": "assistant", "content": "明晚我们准备", "id": 2},
            ]
        ),
        reset_session=AsyncMock(return_value=new_entry),
    )
    scheduler = MagicMock(return_value=True)
    adapter = _api_adapter()
    adapter.gateway_runner = SimpleNamespace(
        async_session_store=store,
        _schedule_honeyos_memory_distillation=scheduler,
    )
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={},
        app={},
    )

    response = await adapter._handle_companion_new(request)
    payload = json.loads(response.text)

    assert payload["session_id"] == "session-new"
    store.reset_session.assert_awaited_once_with("agent:main:companion:dm:owner")
    scheduler.assert_called_once()
    assert (tmp_path / "continuity.db").exists()


@pytest.mark.asyncio
async def test_companion_topic_api_lists_safe_fields_and_handles_actions(
    monkeypatch, tmp_path
):
    from datetime import datetime, timedelta, timezone

    from honeyos.companion.topic_pool import TopicCandidate, TopicPoolStore

    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    now = datetime.now(timezone.utc)
    store = TopicPoolStore(tmp_path, now_fn=lambda: now)
    first, second = store.add_candidates(
        [
            TopicCandidate(
                source_id="one",
                source_title="Source one",
                source_url="https://example.com/one",
                source_name="Example",
                summary="Verified one",
                hook="Worth discussing one",
                category="technology",
                observed_at=now,
                expires_at=now + timedelta(hours=24),
                score=0.9,
                selection_reason="must stay private",
            ),
            TopicCandidate(
                source_id="two",
                source_title="Source two",
                source_url="https://example.com/two",
                source_name="Example",
                summary="Verified two",
                hook="Worth discussing two",
                category="science",
                observed_at=now,
                expires_at=now + timedelta(hours=24),
                score=0.8,
                selection_reason="must stay private too",
            ),
        ]
    )
    adapter = _api_adapter()
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={},
    )

    listed_response = await adapter._handle_companion_topics(request)
    listed = json.loads(listed_response.text)

    assert listed_response.status == 200
    assert listed["topics"][0]["hook"] == "Worth discussing one"
    assert "selection_reason" not in listed_response.text
    assert "score" not in listed_response.text

    request.match_info = {"topic_id": first.id}
    discuss_response = await adapter._handle_companion_topic_discuss(request)
    discussed = json.loads(discuss_response.text)
    assert discussed["success"] is True
    assert discussed["display_text"] == "这个我想听你聊聊"
    assert discussed["prompt"].startswith(
        "[HoneyOS selected topic; user chose this card]"
    )
    assert "https://example.com/one" in discussed["prompt"]

    request.match_info = {"topic_id": second.id}
    dismiss_response = await adapter._handle_companion_topic_dismiss(request)
    assert json.loads(dismiss_response.text) == {
        "success": True,
        "topic_id": second.id,
        "status": "dismissed",
    }


@pytest.mark.asyncio
async def test_companion_topic_api_rejects_remote_cookie_request():
    adapter = _api_adapter()
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="192.168.1.20",
        headers={},
        match_info={},
    )

    response = await adapter._handle_companion_topics(request)

    assert response.status == 401


@pytest.mark.asyncio
async def test_companion_web_claims_and_completes_due_proactive_topic(
    monkeypatch, tmp_path
):
    from datetime import datetime, timedelta, timezone

    from honeyos.companion.topic_pool import TopicCandidate, TopicPoolStore

    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    now = datetime.now(timezone.utc)
    store = TopicPoolStore(tmp_path, now_fn=lambda: now)
    store.update_preferences(
        consent_asked=True,
        consented=True,
        quiet_start="00:00",
        quiet_end="00:00",
    )
    source = SessionSource(
        platform=Platform.API_SERVER,
        chat_id="local-owner",
        chat_type="dm",
        user_id="local-owner",
    )
    store.record_channel_activity(source.to_dict(), at=now - timedelta(hours=3))
    item = store.add_candidates(
        [
            TopicCandidate(
                source_id="web-one",
                source_title="Source",
                source_url="https://example.com/web",
                source_name="Example",
                summary="Verified summary",
                hook="This reminded me of you",
                category="technology",
                observed_at=now,
                expires_at=now + timedelta(hours=24),
                score=0.9,
            )
        ]
    )[0]
    adapter = _api_adapter()
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={},
    )

    claim_response = await adapter._handle_companion_proactive_claim(request)
    claimed = json.loads(claim_response.text)

    assert claimed["delivery"]["topic_id"] == item.id
    assert claimed["delivery"]["prompt"].startswith(
        "[HoneyOS proactive topic seed;"
    )
    assert store.get_topic(item.id).status == "reserved"

    request.match_info = {"delivery_id": claimed["delivery"]["id"]}
    adapter._read_json_body = AsyncMock(return_value=({"success": True}, None))
    complete_response = await adapter._handle_companion_proactive_complete(request)

    assert json.loads(complete_response.text)["success"] is True
    assert store.get_topic(item.id).status == "consumed"


@pytest.mark.asyncio
async def test_companion_web_does_not_claim_topic_for_another_recent_channel(
    monkeypatch, tmp_path
):
    from datetime import datetime, timedelta, timezone

    from honeyos.companion.topic_pool import TopicCandidate, TopicPoolStore

    monkeypatch.setattr("honeyos.core.constants.get_honeyos_home", lambda: tmp_path)
    now = datetime.now(timezone.utc)
    store = TopicPoolStore(tmp_path, now_fn=lambda: now)
    store.update_preferences(
        consent_asked=True,
        consented=True,
        quiet_start="00:00",
        quiet_end="00:00",
    )
    store.record_channel_activity(
        _dm(Platform.FEISHU, "owner").to_dict(),
        at=now - timedelta(hours=3),
    )
    store.add_candidates(
        [
            TopicCandidate(
                source_id="feishu-one",
                source_title="Source",
                source_url="https://example.com/feishu",
                source_name="Example",
                summary="Verified",
                hook="Worth a chat",
                category="technology",
                observed_at=now,
                expires_at=now + timedelta(hours=24),
                score=0.9,
            )
        ]
    )
    adapter = _api_adapter()
    request = SimpleNamespace(
        cookies={"honeyos_local": adapter._local_web_token},
        remote="127.0.0.1",
        headers={},
        match_info={},
    )

    response = await adapter._handle_companion_proactive_claim(request)

    assert json.loads(response.text) == {"delivery": None}
    assert store.list_open_topics()[0].status == "open"


@pytest.mark.asyncio
async def test_companion_session_chat_schedules_background_memory_distillation():
    adapter = _api_adapter()
    scheduler = MagicMock(return_value=True)
    adapter.gateway_runner = SimpleNamespace(
        _schedule_honeyos_memory_distillation=scheduler
    )
    adapter._parse_session_key_header = MagicMock(
        return_value=("agent:main:companion:dm:owner", None)
    )
    adapter._get_existing_session_or_404 = AsyncMock(
        return_value=({"id": "shared-session", "model": "deepseek-v4-flash"}, None)
    )
    adapter._read_json_body = AsyncMock(return_value=({"message": "在吗"}, None))
    adapter._effective_session_runtime_request = MagicMock(
        return_value={
            "requested": {},
            "route_source": "global",
            "require_model_lock": False,
        }
    )
    adapter._persist_session_runtime_lock = MagicMock(return_value=True)
    adapter._resolve_route = MagicMock(return_value=None)
    adapter._request_route_conflict_error = MagicMock(return_value=None)
    adapter._conversation_history_for_session = AsyncMock(return_value=[])
    adapter._run_agent = AsyncMock(
        return_value=(
            {
                "session_id": "shared-session",
                "final_response": "在呢。",
                "runtime": {
                    "provider": "custom",
                    "model": "deepseek-v4-flash",
                    "base_url": "https://configured.example/v1",
                    "api_mode": "chat_completions",
                },
            },
            {},
        )
    )
    request = SimpleNamespace(
        match_info={"session_id": "shared-session"},
        headers={"X-HoneyOS-Session-Key": "agent:main:companion:dm:owner"},
    )

    response = await adapter._handle_session_chat.__wrapped__(adapter, request)

    assert response.status == 200
    scheduler.assert_called_once()
    call = scheduler.call_args.kwargs
    assert call["lane_key"] == "agent:main:companion:dm:owner"
    assert call["session_id"] == "shared-session"
    assert call["reason"] == "periodic"
    assert call["main_runtime"]["api_mode"] == "chat_completions"


@pytest.mark.asyncio
async def test_companion_stream_chat_schedules_background_memory_distillation(
    monkeypatch,
):
    adapter = _api_adapter()
    scheduler = MagicMock(return_value=True)
    adapter.gateway_runner = SimpleNamespace(
        _schedule_honeyos_memory_distillation=scheduler
    )
    adapter._parse_session_key_header = MagicMock(
        return_value=("agent:main:companion:dm:owner", None)
    )
    adapter._get_existing_session_or_404 = AsyncMock(
        return_value=({"id": "shared-session", "model": "deepseek-v4-flash"}, None)
    )
    adapter._read_json_body = AsyncMock(return_value=({"message": "在吗"}, None))
    adapter._effective_session_runtime_request = MagicMock(
        return_value={
            "requested": {},
            "route_source": "global",
            "require_model_lock": False,
        }
    )
    adapter._persist_session_runtime_lock = MagicMock(return_value=True)
    adapter._resolve_route = MagicMock(return_value=None)
    adapter._request_route_conflict_error = MagicMock(return_value=None)
    adapter._conversation_history_for_session = AsyncMock(return_value=[])
    adapter._turn_transcript_messages = MagicMock(return_value=[])
    adapter._run_agent = AsyncMock(
        return_value=(
            {
                "session_id": "shared-session",
                "final_response": "在呢。",
                "runtime": {
                    "provider": "custom",
                    "model": "deepseek-v4-flash",
                    "base_url": "https://configured.example/v1",
                    "api_mode": "chat_completions",
                },
            },
            {},
        )
    )

    class FakeStreamResponse:
        def __init__(self, *, status, headers):
            self.status = status
            self.headers = headers
            self.frames = []

        async def prepare(self, _request):
            return self

        async def write(self, frame):
            self.frames.append(frame)

    monkeypatch.setattr(
        "honeyos.gateway.platforms.api_server.web.StreamResponse",
        FakeStreamResponse,
    )
    request = SimpleNamespace(
        match_info={"session_id": "shared-session"},
        headers={
            "X-HoneyOS-Session-Key": "agent:main:companion:dm:owner",
            "X-HoneyOS-Companion-View": "1",
        },
    )

    response = await adapter._handle_session_chat_stream.__wrapped__(
        adapter, request
    )

    assert response.status == 200
    scheduler.assert_called_once()
    assert scheduler.call_args.kwargs["session_id"] == "shared-session"
