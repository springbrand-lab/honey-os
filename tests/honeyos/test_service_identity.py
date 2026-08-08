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


def test_service_command_uses_current_python_and_honeyos_module(tmp_path: Path) -> None:
    service = _service_module()
    identity = service.ServiceIdentity.default(home=tmp_path / ".honeyos")

    assert identity.command_argv() == (
        str(Path(sys.executable)),
        "-m",
        "honeyos",
        "gateway",
        "run",
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
