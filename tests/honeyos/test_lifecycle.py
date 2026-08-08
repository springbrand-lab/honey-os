from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from honeyos.companion.runtime import gateway_argv, run_gateway_command


def test_lifecycle_dispatches_through_runtime_plugin_manager(monkeypatch):
    from honeyos.runtime import lifecycle, plugins

    observed = []
    monkeypatch.setattr(
        plugins,
        "invoke_hook",
        lambda name, **kwargs: observed.append((name, kwargs)) or ["handled"],
    )
    monkeypatch.setattr(
        "honeyos.runtime.observability.observe_lifecycle",
        lambda *_args, **_kwargs: None,
    )

    assert lifecycle.invoke_hook("pre_llm_call", session_id="session-1") == [
        "handled"
    ]
    assert observed == [("pre_llm_call", {"session_id": "session-1"})]


def test_gateway_command_has_explicit_home_and_python(monkeypatch, tmp_path):
    captured = SimpleNamespace(argv=None, env=None)

    def fake_run(argv, *, env, check):
        captured.argv = argv
        captured.env = env
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert run_gateway_command("status", home=tmp_path) == 0
    assert captured.argv[0] == sys.executable
    assert captured.argv[1:] == ["-m", "honeyos.runtime.main", "gateway", "status"]
    assert captured.env["HONEYOS_HOME"] == str(tmp_path.resolve())
    assert "HERMES_HOME" not in captured.env
    assert "H2OS_HOME" not in captured.env


def test_gateway_command_propagates_child_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=7),
    )

    assert run_gateway_command("start", home=tmp_path) == 7


def test_gateway_argv_rejects_non_lifecycle_commands():
    with pytest.raises(ValueError, match="unsupported"):
        gateway_argv("setup")
