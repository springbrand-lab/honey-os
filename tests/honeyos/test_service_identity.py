from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path


def _service_module():
    try:
        spec = importlib.util.find_spec("honeyos.cli.service")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "the HoneyOS service layer must exist"
    return importlib.import_module("honeyos.cli.service")


def test_service_identity_has_only_honeyos_names(tmp_path: Path) -> None:
    service = _service_module()

    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")

    assert identity.macos_label == "ai.honeyos.gateway"
    assert identity.linux_unit == "honeyos-gateway"
    assert identity.data_home == (tmp_path / ".honeyos").resolve()


def test_service_command_runs_gateway_as_the_launchd_process(tmp_path: Path) -> None:
    service = _service_module()
    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")

    assert identity.command_argv() == (
        str(Path(sys.executable)),
        "-m",
        "honeyos.runtime.main",
        "gateway",
        "run",
        "--replace",
    )


def test_service_command_preserves_virtualenv_interpreter_symlink(
    monkeypatch, tmp_path: Path
) -> None:
    service = _service_module()
    base_python = tmp_path / "managed-python" / "bin" / "python3.11"
    base_python.parent.mkdir(parents=True)
    base_python.touch()
    virtualenv_python = tmp_path / "project" / ".venv" / "bin" / "python3"
    virtualenv_python.parent.mkdir(parents=True)
    virtualenv_python.symlink_to(base_python)
    monkeypatch.setattr(service.sys, "executable", str(virtualenv_python))

    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")

    assert identity.command_argv()[0] == str(virtualenv_python)
    assert identity.command_argv()[0] != str(base_python)


def test_generated_service_definitions_contain_only_honeyos_runtime(
    monkeypatch, tmp_path: Path,
) -> None:
    service = _service_module()
    monkeypatch.setattr(
        service.sys, "executable", "/opt/honeyos/.venv/bin/python3"
    )
    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")

    launchd = service.render_launchd_plist(identity)
    systemd = service.render_systemd_unit(identity)

    for definition in (launchd, systemd):
        assert "honeyos" in definition.lower()
        assert str(identity.data_home) in definition
        assert "springbrand" not in definition.lower()
        assert "h2os" not in definition.lower()
        assert "hermes" not in definition.lower()


def test_service_uses_the_complete_current_builder_slot_when_present(tmp_path: Path) -> None:
    import json

    service = _service_module()
    home = tmp_path / ".honeyos"
    slot_source = home / "runtime" / "slots" / "candidate" / "source"
    slot_source.mkdir(parents=True)
    (home / "runtime" / "current-slot.json").write_text(
        json.dumps({"activation_id": "candidate", "source_root": str(slot_source)}),
        encoding="utf-8",
    )

    launchd = service.render_launchd_plist(service.ServiceIdentity.default(home))
    systemd = service.render_systemd_unit(service.ServiceIdentity.default(home))

    assert str(slot_source) in launchd
    assert f"PYTHONPATH={slot_source}" in systemd


def test_lifecycle_addresses_only_exact_honeyos_service(monkeypatch, tmp_path: Path) -> None:
    service = _service_module()
    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")
    calls: list[tuple[str, ...]] = []

    def record(argv, **_kwargs):
        calls.append(tuple(argv))
        return 0

    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    service.start_service(identity, runner=record)
    service.stop_service(identity, runner=record)

    assert calls == [
        ("launchctl", "kickstart", f"gui/{service.os.getuid()}/{identity.macos_label}"),
        ("launchctl", "bootout", f"gui/{service.os.getuid()}/{identity.macos_label}"),
    ]


def test_macos_restart_reinstalls_service_after_bootout(
    monkeypatch, tmp_path: Path
) -> None:
    service = _service_module()
    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")
    plist_path = tmp_path / "ai.honeyos.gateway.plist"
    calls: list[tuple[str, ...]] = []

    def record(argv, **_kwargs):
        calls.append(tuple(argv))
        return 0

    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service, "launchd_plist_path", lambda _identity: plist_path)

    assert service.restart_service(identity, runner=record) == 0
    assert plist_path.is_file()
    assert calls == [
        (
            "launchctl",
            "bootout",
            f"gui/{service.os.getuid()}/{identity.macos_label}",
        ),
        (
            "launchctl",
            "bootstrap",
            f"gui/{service.os.getuid()}",
            str(plist_path),
        ),
    ]


def test_macos_install_retries_transient_launchd_bootstrap_error(
    monkeypatch, tmp_path: Path
) -> None:
    import time

    service = _service_module()
    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")
    plist_path = tmp_path / "ai.honeyos.gateway.plist"
    bootstrap_results = iter((5, 0))
    calls: list[tuple[str, ...]] = []
    delays: list[float] = []

    def record(argv, **_kwargs):
        calls.append(tuple(argv))
        if argv[1] == "bootstrap":
            return next(bootstrap_results)
        return 0

    monkeypatch.setattr(service.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(service, "launchd_plist_path", lambda _identity: plist_path)
    monkeypatch.setattr(time, "sleep", delays.append)

    assert service.install_service(identity, runner=record) == 0
    assert [call[1] for call in calls] == ["bootout", "bootstrap", "bootstrap"]
    assert delays == [0.25]


def test_linux_restart_rerenders_active_slot_unit_then_reloads_and_restarts(
    monkeypatch, tmp_path: Path
) -> None:
    import json

    service = _service_module()
    home = tmp_path / ".honeyos"
    slot_source = home / "runtime" / "slots" / "candidate" / "source"
    slot_source.mkdir(parents=True)
    (home / "runtime" / "current-slot.json").write_text(
        json.dumps({"activation_id": "candidate", "source_root": str(slot_source)}),
        encoding="utf-8",
    )
    identity = service.ServiceIdentity.default(home)
    unit_path = tmp_path / "honeyos-gateway.service"
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service, "systemd_unit_path", lambda _identity: unit_path)

    assert service.restart_service(
        identity, runner=lambda argv, **_kwargs: calls.append(tuple(argv)) or 0
    ) == 0

    assert f"PYTHONPATH={slot_source}" in unit_path.read_text(encoding="utf-8")
    assert calls == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "restart", identity.linux_unit),
    ]


def test_gateway_health_requires_a_live_attestation_for_the_active_slot(tmp_path: Path) -> None:
    import json

    service = _service_module()
    home = tmp_path / ".honeyos"
    slot_source = home / "runtime" / "slots" / "candidate" / "source"
    slot_source.mkdir(parents=True)
    (home / "runtime" / "current-slot.json").write_text(
        json.dumps({"activation_id": "candidate", "source_root": str(slot_source)}),
        encoding="utf-8",
    )
    identity = service.ServiceIdentity.default(home)
    status = {
        "pid": 8123,
        "gateway_state": "running",
        "runtime_attestation": {"pid": 8123, "source_root": str(slot_source)},
    }

    assert service.service_health_check(
        identity,
        health_probe=lambda _identity: True,
        status_reader=lambda _path: status,
        running_probe=lambda _path: True,
    ) is True

    status["runtime_attestation"]["source_root"] = str(tmp_path / "old-slot")
    assert service.service_health_check(
        identity,
        health_probe=lambda _identity: True,
        status_reader=lambda _path: status,
        running_probe=lambda _path: True,
    ) is False


def test_gateway_runtime_status_records_the_imported_code_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HONEYOS_HOME", str(tmp_path / ".honeyos"))
    from honeyos.gateway.status import read_runtime_status, write_runtime_status
    import honeyos

    write_runtime_status(gateway_state="running")

    status = read_runtime_status()
    assert status is not None
    assert status["runtime_attestation"]["source_root"] == str(
        Path(honeyos.__file__).resolve().parent.parent
    )
    assert status["runtime_attestation"]["pid"] == status["pid"]
