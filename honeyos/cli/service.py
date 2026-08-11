"""Exact-label background service management for HoneyOS."""

from __future__ import annotations

import os
import json
import platform
import plistlib
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from honeyos import default_home


Runner = Callable[..., object]


@dataclass(frozen=True)
class ServiceIdentity:
    data_home: Path
    macos_label: str = "ai.honeyos.gateway"
    linux_unit: str = "honeyos-gateway"

    @classmethod
    def default(cls, home: Path | None = None) -> "ServiceIdentity":
        return cls(data_home=(home or default_home()).expanduser().resolve())

    def command_argv(self) -> tuple[str, ...]:
        return (
            str(Path(sys.executable)),
            "-m",
            "honeyos.runtime.main",
            "gateway",
            "run",
            "--replace",
        )


def _run(argv: Sequence[str], **kwargs) -> int:
    completed = subprocess.run(list(argv), check=False, **kwargs)
    return completed.returncode


def _returncode(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(getattr(value, "returncode", 1))


def _current_slot_source(identity: ServiceIdentity) -> Path | None:
    """Read the runtime-owned active slot pointer for the service environment."""

    pointer = identity.data_home / "runtime" / "current-slot.json"
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        source = Path(str(payload["source_root"])).expanduser().resolve()
        slots = (identity.data_home / "runtime" / "slots").resolve()
        source.relative_to(slots)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return source if source.is_dir() and not source.is_symlink() else None


def _service_environment(identity: ServiceIdentity) -> dict[str, str]:
    environment = {"HONEYOS_HOME": str(identity.data_home)}
    source = _current_slot_source(identity)
    if source is not None:
        # The slot is a complete source tree.  Keeping the interpreter/venv
        # unchanged preserves all user dependencies and provider setup.
        environment["PYTHONPATH"] = str(source)
    return environment


def render_launchd_plist(identity: ServiceIdentity) -> str:
    logs = identity.data_home / "logs"
    payload = {
        "Label": identity.macos_label,
        "ProgramArguments": list(identity.command_argv()),
        "EnvironmentVariables": _service_environment(identity),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(logs / "gateway.log"),
        "StandardErrorPath": str(logs / "gateway.error.log"),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")


def render_systemd_unit(identity: ServiceIdentity) -> str:
    command = " ".join(shlex.quote(item) for item in identity.command_argv())
    environment = _service_environment(identity)
    return "\n".join(
        (
            "[Unit]",
            "Description=HoneyOS Companion Gateway",
            "After=network-online.target",
            "",
            "[Service]",
            *(f"Environment={key}={value}" for key, value in environment.items()),
            f"ExecStart={command}",
            "Restart=on-failure",
            "RestartSec=5",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        )
    )


def launchd_plist_path(identity: ServiceIdentity) -> Path:
    del identity
    return Path.home() / "Library" / "LaunchAgents" / "ai.honeyos.gateway.plist"


def systemd_unit_path(identity: ServiceIdentity) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{identity.linux_unit}.service"


def _write_systemd_unit(identity: ServiceIdentity) -> Path:
    path = systemd_unit_path(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_systemd_unit(identity), encoding="utf-8")
    path.chmod(0o600)
    return path


def install_service(identity: ServiceIdentity, runner: Runner = _run) -> int:
    identity.data_home.mkdir(parents=True, exist_ok=True)
    (identity.data_home / "logs").mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Darwin":
        path = launchd_plist_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_launchd_plist(identity), encoding="utf-8")
        path.chmod(0o600)
        domain = f"gui/{os.getuid()}"
        from honeyos.gateway.status import get_running_pid

        old_pid = get_running_pid(identity.data_home / "gateway.pid")
        runner(["launchctl", "bootout", f"{domain}/{identity.macos_label}"])
        if old_pid is not None:
            for attempt in range(120):
                try:
                    os.kill(old_pid, 0)
                except ProcessLookupError:
                    break
                except PermissionError:
                    return 1
                if attempt == 119:
                    print(
                        f"HoneyOS gateway process {old_pid} did not stop.",
                        file=sys.stderr,
                    )
                    return 1
                time.sleep(0.25)
        for attempt in range(40):
            result = _returncode(
                runner(["launchctl", "bootstrap", domain, str(path)])
            )
            if result != 5 or attempt == 39:
                return result
            time.sleep(0.25)
    if system == "Linux":
        _write_systemd_unit(identity)
        if _returncode(runner(["systemctl", "--user", "daemon-reload"])) != 0:
            return 1
        return _returncode(
            runner(["systemctl", "--user", "enable", "--now", identity.linux_unit])
        )
    raise RuntimeError("HoneyOS background service supports macOS and Linux")


def start_service(identity: ServiceIdentity, runner: Runner = _run) -> int:
    if platform.system() == "Darwin":
        return _returncode(
            runner(
                [
                    "launchctl",
                    "kickstart",
                    f"gui/{os.getuid()}/{identity.macos_label}",
                ]
            )
        )
    if platform.system() == "Linux":
        return _returncode(runner(["systemctl", "--user", "start", identity.linux_unit]))
    raise RuntimeError("HoneyOS background service supports macOS and Linux")


def stop_service(identity: ServiceIdentity, runner: Runner = _run) -> int:
    if platform.system() == "Darwin":
        return _returncode(
            runner(
                [
                    "launchctl",
                    "bootout",
                    f"gui/{os.getuid()}/{identity.macos_label}",
                ]
            )
        )
    if platform.system() == "Linux":
        return _returncode(runner(["systemctl", "--user", "stop", identity.linux_unit]))
    raise RuntimeError("HoneyOS background service supports macOS and Linux")


def restart_service(identity: ServiceIdentity, runner: Runner = _run) -> int:
    if platform.system() == "Darwin":
        # launchctl bootout unregisters the job entirely, so a subsequent
        # kickstart cannot find it. Re-render and bootstrap the exact HoneyOS
        # service definition instead.
        return install_service(identity, runner=runner)
    if platform.system() == "Linux":
        # The active slot is selected through PYTHONPATH in the unit.  Render
        # it again before every restart, including a rollback restart.
        _write_systemd_unit(identity)
        if _returncode(runner(["systemctl", "--user", "daemon-reload"])) != 0:
            return 1
        return _returncode(runner(["systemctl", "--user", "restart", identity.linux_unit]))
    raise RuntimeError("HoneyOS background service supports macOS and Linux")


def service_status(identity: ServiceIdentity, runner: Runner = _run) -> int:
    if platform.system() == "Darwin":
        return _returncode(
            runner(["launchctl", "print", f"gui/{os.getuid()}/{identity.macos_label}"])
        )
    if platform.system() == "Linux":
        return _returncode(runner(["systemctl", "--user", "is-active", identity.linux_unit]))
    raise RuntimeError("HoneyOS background service supports macOS and Linux")


def _gateway_health_probe(identity: ServiceIdentity) -> bool:
    """Probe the local gateway endpoint, never merely a service-manager state."""

    port = 8642
    try:
        import yaml

        config = yaml.safe_load((identity.data_home / "config.yaml").read_text(encoding="utf-8"))
        platforms = config.get("platforms", {}) if isinstance(config, dict) else {}
        api_server = platforms.get("api_server", {}) if isinstance(platforms, dict) else {}
        configured = api_server.get("port") if isinstance(api_server, dict) else None
        if configured is not None:
            port = int(configured)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        pass
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.0) as response:
            if not 200 <= int(response.status) < 300:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return isinstance(payload, dict) and payload.get("status") == "ok"


def service_health_check(
    identity: ServiceIdentity,
    *,
    health_probe: Callable[[ServiceIdentity], bool] | None = None,
    status_reader: Callable[[Path], dict | None] | None = None,
    running_probe: Callable[[Path], bool] | None = None,
) -> bool:
    """Require a live gateway health response and source-slot attestation."""

    expected_source = _current_slot_source(identity)
    if expected_source is None:
        return False
    if not (health_probe or _gateway_health_probe)(identity):
        return False
    if status_reader is None or running_probe is None:
        from honeyos.gateway.status import is_gateway_running, read_runtime_status

        status_reader = status_reader or read_runtime_status
        running_probe = running_probe or is_gateway_running
    status = status_reader(identity.data_home / "gateway_state.json")
    if not isinstance(status, dict) or status.get("gateway_state") != "running":
        return False
    if not running_probe(identity.data_home / "gateway.pid"):
        return False
    attestation = status.get("runtime_attestation")
    if not isinstance(attestation, dict):
        return False
    try:
        attested_source = Path(str(attestation["source_root"])).expanduser().resolve()
        expected_pid = int(status["pid"])
        attested_pid = int(attestation["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    return attested_source == expected_source.resolve() and attested_pid == expected_pid
