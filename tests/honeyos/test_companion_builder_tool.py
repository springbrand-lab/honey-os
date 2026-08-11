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


def _owner_context(channel: str = "feishu"):
    from honeyos.companion.builder_activation import ActivationInboundContext

    return ActivationInboundContext(lane_key=OWNER, channel=channel, authenticated=True)


def test_confirmation_requires_authenticated_canonical_owner_and_exact_channel(tmp_path):
    store, _staged, confirmation, _prepared = _ready_confirmation(tmp_path)
    from honeyos.companion.builder_activation import ActivationConflict, ActivationInboundContext

    with pytest.raises(ActivationConflict, match="authenticated owner"):
        store.resolve_confirmation(
            confirmation.callback_id,
            ActivationInboundContext(lane_key=OWNER, channel="feishu", authenticated=False),
        )
    with pytest.raises(ActivationConflict, match="authenticated owner"):
        store.resolve_confirmation(
            confirmation.callback_id,
            ActivationInboundContext(lane_key="agent:main:companion:dm:other", channel="feishu", authenticated=True),
        )
    with pytest.raises(ActivationConflict, match="authenticated owner"):
        store.resolve_confirmation(confirmation.callback_id, _owner_context("weixin"))


def test_confirmation_is_single_use_and_always_is_still_one_time(tmp_path):
    store, staged, confirmation, _prepared = _ready_confirmation(tmp_path)
    from honeyos.companion.builder_activation import ActivationConflict

    result = store.resolve_confirmation(confirmation.callback_id, _owner_context(), choice="always")

    assert result.state == "authorized"
    assert result.activation_id == staged.activation_id
    with pytest.raises(ActivationConflict, match="already resolved"):
        store.resolve_confirmation(confirmation.callback_id, _owner_context())
    with pytest.raises(ActivationConflict, match="owner confirmation"):
        store.transition(staged.activation_id, "authorized", "switching")


def test_confirmation_persists_across_restart_and_never_exposes_secret(tmp_path):
    store, staged, confirmation, _prepared = _ready_confirmation(tmp_path)
    from honeyos.companion.builder_activation import ActivationStore

    payload = json.loads(confirmation.record_path.read_text(encoding="utf-8"))
    assert "secret" not in json.dumps({key: value for key, value in payload.items() if key != "secret_hash"})
    restarted = ActivationStore(store.home, store.bundled_root)

    assert restarted.resolve_confirmation(confirmation.callback_id, _owner_context()).state == "authorized"
    assert restarted.verify_staged(staged.activation_id).state == "authorized"


def test_confirmation_expiry_and_candidate_digest_tamper_fail_closed(tmp_path):
    store, staged, confirmation, _prepared = _ready_confirmation(tmp_path)
    from honeyos.companion.builder_activation import ActivationConflict, ActivationError

    expired = datetime.fromisoformat(confirmation.expires_at) + timedelta(seconds=1)
    with pytest.raises(ActivationConflict, match="expired"):
        store.resolve_confirmation(confirmation.callback_id, _owner_context(), now=expired)

    store2, staged2, confirmation2, _prepared2 = _ready_confirmation(tmp_path / "tamper")
    candidate = staged2.slot_root / "source" / "honeyos" / "companion" / "persistent_memory.py"
    candidate.chmod(0o600)
    candidate.write_text("VALUE = 'tampered'\n")
    with pytest.raises(ActivationError, match="slot tree digest"):
        store2.resolve_confirmation(confirmation2.callback_id, _owner_context())


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
