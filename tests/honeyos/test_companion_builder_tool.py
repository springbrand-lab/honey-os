from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


OWNER = "agent:main:companion:dm:owner"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _ready_confirmation(tmp_path: Path, *, channel: str = "feishu"):
    from honeyos.companion.builder_activation import ActivationStore
    from honeyos.companion.builder_workspace import inspect_builder_change, prepare_builder_change

    source = tmp_path / "source"
    (source / "honeyos" / "companion").mkdir(parents=True)
    (source / "honeyos" / "companion" / "persistent_memory.py").write_text("VALUE = 'base'\n")
    (source / "pyproject.toml").write_text("[project]\nname = 'builder-test'\n")
    (source / "uv.lock").write_text("version = 1\n")
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "base")
    prepared = prepare_builder_change(
        source_repo=source,
        goal="improve companion UI",
        allowed_paths=("honeyos/companion/**",),
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="candidate-confirmation-001",
    )
    (prepared.workspace / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "VALUE = 'candidate'\n"
    )
    assert inspect_builder_change(prepared.change_root).status == "review_ready"
    store = ActivationStore(tmp_path / "home", source)
    staged = store.stage(prepared.change_root)
    assert store.preflight(staged.activation_id).success
    store.transition(staged.activation_id, "staged", "awaiting_confirmation")
    return store, staged, store.issue_confirmation(staged.activation_id, OWNER, channel), prepared


def test_confirmation_has_no_public_context_resolver_or_forgeable_capability(tmp_path):
    store, _staged, confirmation, _prepared = _ready_confirmation(tmp_path)
    from honeyos.companion.builder_activation import ActivationConflict

    assert not hasattr(store, "resolve_confirmation")
    with pytest.raises(ActivationConflict, match="gateway-owned"):
        store._resolve_gateway_confirmation(
            confirmation.callback_id,
            capability=object(),
            owner_lane=OWNER,
            channel="feishu",
        )


def test_confirmation_is_single_use_and_always_is_still_one_time(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-test")
    store, staged, confirmation, _prepared = _ready_confirmation(tmp_path, channel="api_server")
    from honeyos.companion.builder_activation import ActivationConflict
    from honeyos.gateway.builder_confirmation import resolve_local_web_callback

    result = resolve_local_web_callback(store.home, confirmation.callback_id, choice="always")

    assert result.state == "authorized"
    assert result.activation_id == staged.activation_id
    with pytest.raises(ActivationConflict, match="already resolved"):
        resolve_local_web_callback(store.home, confirmation.callback_id, choice="confirm")
    with pytest.raises(ActivationConflict, match="owner confirmation"):
        store.transition(staged.activation_id, "authorized", "switching")


def test_confirmation_persists_across_restart_and_never_exposes_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-test")
    store, staged, confirmation, _prepared = _ready_confirmation(tmp_path, channel="api_server")
    from honeyos.companion.builder_activation import ActivationStore
    from honeyos.gateway.builder_confirmation import resolve_local_web_callback

    payload = json.loads(confirmation.record_path.read_text(encoding="utf-8"))
    assert "secret" not in json.dumps({key: value for key, value in payload.items() if key != "secret_hash"})
    restarted = ActivationStore(store.home, store.bundled_root)

    assert resolve_local_web_callback(restarted.home, confirmation.callback_id, choice="confirm").state == "authorized"
    assert restarted.verify_staged(staged.activation_id).state == "authorized"


def test_feishu_gateway_callback_requires_verified_owner_dm_event(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-test")
    store, _staged, confirmation, _prepared = _ready_confirmation(tmp_path, channel="feishu")
    from honeyos.companion.builder_activation import ActivationConflict
    from honeyos.gateway.builder_confirmation import resolve_feishu_callback
    from honeyos.gateway.config import Platform
    from honeyos.gateway.platforms.base import MessageEvent
    from honeyos.gateway.session import SessionSource

    owner_event = MessageEvent(
        text="",
        source=SessionSource(
            platform=Platform.FEISHU,
            chat_id="owner-chat",
            chat_type="dm",
            user_id="owner",
        ),
    )
    assert resolve_feishu_callback(
        store.home, confirmation.callback_id, choice="confirm", event=owner_event
    ).state == "authorized"

    store2, _staged2, confirmation2, _prepared2 = _ready_confirmation(tmp_path / "group", channel="feishu")
    group_event = MessageEvent(
        text="",
        source=SessionSource(
            platform=Platform.FEISHU,
            chat_id="group-chat",
            chat_type="group",
            user_id="owner",
        ),
    )
    with pytest.raises(ActivationConflict, match="authenticated owner"):
        resolve_feishu_callback(
            store2.home, confirmation2.callback_id, choice="confirm", event=group_event
        )


def test_confirmation_expiry_and_candidate_digest_tamper_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-test")
    store, staged, confirmation, _prepared = _ready_confirmation(tmp_path, channel="api_server")
    from honeyos.companion.builder_activation import ActivationConflict, ActivationError
    from honeyos.gateway.builder_confirmation import resolve_local_web_callback

    expired = datetime.fromisoformat(confirmation.expires_at) + timedelta(seconds=1)
    with pytest.raises(ActivationConflict, match="expired"):
        resolve_local_web_callback(
            store.home, confirmation.callback_id, choice="confirm", now=expired
        )

    store2, staged2, confirmation2, _prepared2 = _ready_confirmation(tmp_path / "tamper", channel="api_server")
    candidate = staged2.slot_root / "source" / "honeyos" / "companion" / "persistent_memory.py"
    candidate.chmod(0o600)
    candidate.write_text("VALUE = 'tampered'\n")
    with pytest.raises(ActivationError, match="slot tree digest"):
        resolve_local_web_callback(store2.home, confirmation2.callback_id, choice="confirm")


def test_model_tool_stages_and_requests_but_never_returns_callback_or_authorizes(tmp_path, monkeypatch):
    from honeyos.tools.approval import reset_current_session_key, set_current_session_key
    from honeyos.tools.companion_builder_tool import companion_builder_tool

    _store, _staged, _confirmation, prepared = _ready_confirmation(tmp_path)
    # Start a fresh activation so the tool owns its stage/request flow.
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-test")
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path / "tool-home"))
    monkeypatch.setenv("HONEYOS_BUNDLED_ROOT", str(tmp_path / "source"))
    monkeypatch.setenv("HONEYOS_SESSION_PLATFORM", "feishu")
    token = set_current_session_key(OWNER)
    try:
        staged_result = json.loads(companion_builder_tool(action="stage", change_root=str(prepared.change_root)))
        assert staged_result["success"] is True
        asked = json.loads(
            companion_builder_tool(action="request_activation", activation_id=staged_result["activation_id"])
        )
    finally:
        reset_current_session_key(token)
    assert asked["success"] is True
    assert asked["state"] == "awaiting_owner_confirmation"
    assert "callback" not in asked
    assert "secret" not in asked


@pytest.mark.parametrize(
    ("command", "code"),
    [
        (
            "python -c 'from honeyos.companion.builder_activation import ActivationStore'",
            "from honeyos.companion.builder_activation import ActivationStore",
        ),
        (
            "cat ~/.honeyos/runtime/confirmations/opaque.json",
            "open('/tmp/runtime/activations/a.json').read()",
        ),
        (
            "honeyos builder authorized activation-id",
            "state = 'switching'; print(state)",
        ),
    ],
)
def test_model_terminal_and_code_paths_cannot_access_builder_control_plane(command, code):
    from honeyos.tools.code_execution_tool import execute_code
    from honeyos.tools.terminal_tool import terminal_tool

    terminal = json.loads(terminal_tool(command))
    code = json.loads(execute_code(code))

    assert terminal["status"] == "blocked"
    assert "gateway-owned" in terminal["error"]
    assert "gateway-owned" in code["error"]
