"""Exact-label background service management for HoneyOS."""

from __future__ import annotations

import os
import platform
import plistlib
import shlex
import subprocess
import sys
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
            "honeyos",
            "gateway",
            "run",
        )


def _run(argv: Sequence[str], **kwargs) -> int:
    completed = subprocess.run(list(argv), check=False, **kwargs)
    return completed.returncode


def _returncode(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(getattr(value, "returncode", 1))


def render_launchd_plist(identity: ServiceIdentity) -> str:
    logs = identity.data_home / "logs"
    payload = {
        "Label": identity.macos_label,
        "ProgramArguments": list(identity.command_argv()),
        "EnvironmentVariables": {"HONEYOS_HOME": str(identity.data_home)},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(logs / "gateway.log"),
        "StandardErrorPath": str(logs / "gateway.error.log"),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")


def render_systemd_unit(identity: ServiceIdentity) -> str:
    command = " ".join(shlex.quote(item) for item in identity.command_argv())
    return "\n".join(
        (
            "[Unit]",
            "Description=HoneyOS Companion Gateway",
            "After=network-online.target",
            "",
            "[Service]",
            f"Environment=HONEYOS_HOME={identity.data_home}",
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
        runner(["launchctl", "bootout", f"{domain}/{identity.macos_label}"])
        return _returncode(runner(["launchctl", "bootstrap", domain, str(path)]))
    if system == "Linux":
        path = systemd_unit_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_systemd_unit(identity), encoding="utf-8")
        path.chmod(0o600)
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
    return _returncode(runner(["systemctl", "--user", "start", identity.linux_unit]))


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
    return _returncode(runner(["systemctl", "--user", "stop", identity.linux_unit]))


def restart_service(identity: ServiceIdentity, runner: Runner = _run) -> int:
    if platform.system() == "Darwin":
        # launchctl bootout unregisters the job entirely, so a subsequent
        # kickstart cannot find it. Re-render and bootstrap the exact HoneyOS
        # service definition instead.
        return install_service(identity, runner=runner)
    return _returncode(runner(["systemctl", "--user", "restart", identity.linux_unit]))


def service_status(identity: ServiceIdentity, runner: Runner = _run) -> int:
    if platform.system() == "Darwin":
        return _returncode(
            runner(["launchctl", "print", f"gui/{os.getuid()}/{identity.macos_label}"])
        )
    return _returncode(runner(["systemctl", "--user", "is-active", identity.linux_unit]))
