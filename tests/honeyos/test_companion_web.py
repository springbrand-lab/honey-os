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
        "title": "正在认真核对",
        "detail": "我在看几处相关内容",
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
        "title": "已经替你核对过了",
        "detail": "",
    }
    assert failed == {
        "activity_id": "activity",
        "kind": "handling",
        "state": "failed",
        "title": "刚才没走通，我换个办法",
        "detail": "",
    }


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
    assert 'aria-expanded' in app
    assert 'action-details' in app
    assert 'HoneyOSRunState.summarize' in app
    assert 'elements.send.textContent = "处理中"' in app
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
    assert ("GET", "/honeyos/run-state.js") in routes
    assert ("GET", "/honeyos/message-format.js") in routes
    assert ("GET", "/honeyos/app.js") in routes
    assert ("GET", "/honeyos/styles.css") in routes
    assert ("GET", "/api/companion/bootstrap") in routes


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
    assert "找到几个，我再看看。" not in response.text
    assert "reasoning" not in response.text
    assert "raw command output" not in response.text


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
