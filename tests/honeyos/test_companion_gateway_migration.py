from __future__ import annotations

import shutil
from types import SimpleNamespace

from honeyos.companion.config import initialize_home


def test_gateway_run_repairs_missing_companion_capabilities_before_dispatch(
    monkeypatch, tmp_path
):
    import honeyos.runtime.main as runtime_main

    initialize_home(tmp_path)
    shutil.rmtree(tmp_path / "skills" / "honeyos-builder")
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))
    events = []
    monkeypatch.setattr(runtime_main, "_sync_bundled_skills_quietly", lambda: events.append("sync"))
    monkeypatch.setattr(
        "honeyos.runtime.gateway.gateway_command",
        lambda _args: events.append("dispatch"),
    )

    runtime_main.cmd_gateway(SimpleNamespace(gateway_command="run"))

    assert (tmp_path / "skills" / "honeyos-builder" / "SKILL.md").is_file()
    assert (tmp_path / "runtime.json").is_file()
    assert events == ["sync", "dispatch"]


def test_gateway_status_does_not_mutate_an_uninitialized_home(monkeypatch, tmp_path):
    import honeyos.runtime.main as runtime_main

    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path))
    monkeypatch.setattr(runtime_main, "_sync_bundled_skills_quietly", lambda: None)
    monkeypatch.setattr("honeyos.runtime.gateway.gateway_command", lambda _args: None)

    runtime_main.cmd_gateway(SimpleNamespace(gateway_command="status"))

    assert list(tmp_path.iterdir()) == []
