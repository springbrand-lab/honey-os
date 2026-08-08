"""The only public command-line entrypoint for HoneyOS."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from honeyos import PRODUCT_NAME, RUNTIME_ID
from honeyos.cli.bootstrap import activate_home
from honeyos.cli.service import (
    ServiceIdentity,
    install_service,
    restart_service,
    service_status,
    start_service,
    stop_service,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="honeyos",
        description=f"Run your private {PRODUCT_NAME} AI companion.",
        exit_on_error=False,
    )
    parser.add_argument("--home", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Connect a model and private chat channel")
    commands.add_parser("init", help="Initialize the private companion")
    commands.add_parser("start", help="Start the background companion")
    commands.add_parser("web", help="Open the private local chat")
    commands.add_parser("stop", help="Stop the background companion")
    commands.add_parser("restart", help="Restart the background companion")
    commands.add_parser("status", help="Show companion status")
    commands.add_parser("logs", help="Show companion logs")
    commands.add_parser("doctor", help="Check the installation")

    channel = commands.add_parser("channel", help="Connect a private chat channel")
    channel_commands = channel.add_subparsers(dest="channel_command", required=True)
    channel_setup = channel_commands.add_parser("setup")
    channel_setup.add_argument("platform", choices=("weixin", "feishu"))

    pairing = commands.add_parser("pairing", help="Manage private-chat access")
    pairing_commands = pairing.add_subparsers(dest="pairing_action", required=True)
    pairing_commands.add_parser("list")
    approve = pairing_commands.add_parser("approve")
    approve.add_argument("platform", choices=("weixin", "feishu"))
    approve.add_argument("code")
    revoke = pairing_commands.add_parser("revoke")
    revoke.add_argument("platform", choices=("weixin", "feishu"))
    revoke.add_argument("user_id")
    pairing_commands.add_parser("clear-pending")

    gateway = commands.add_parser("gateway", help=argparse.SUPPRESS)
    gateway_commands = gateway.add_subparsers(dest="gateway_command", required=True)
    gateway_commands.add_parser("run", help=argparse.SUPPRESS)
    return parser


def _runtime_environment(home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for legacy_variable in (
        "HONEYOS_HOME",
        "HONEYOS_HOME",
        "HONEYOS_RUNTIME_ID",
        "HONEYOS_PRODUCT_NAME",
    ):
        environment.pop(legacy_variable, None)
    environment["HONEYOS_HOME"] = str(home)
    environment["HONEYOS_RUNTIME_ID"] = RUNTIME_ID
    environment["HONEYOS_PRODUCT_NAME"] = PRODUCT_NAME
    return environment


def _run_embedded(arguments: Sequence[str], home: Path) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "honeyos.runtime.main", *arguments],
        env=_runtime_environment(home),
        check=False,
    )
    return completed.returncode


def _initialize_embedded(home: Path) -> None:
    previous = os.environ.copy()
    os.environ.update(_runtime_environment(home))
    try:
        from honeyos.companion.config import initialize_home, upgrade_companion_capabilities
        from honeyos.companion.runtime import write_runtime_identity

        initialize_home(home)
        upgrade_companion_capabilities(home)
        write_runtime_identity(home)
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _run_setup(home: Path, identity: ServiceIdentity) -> int:
    previous = os.environ.copy()
    os.environ.update(_runtime_environment(home))
    try:
        from honeyos.companion.setup import run_setup

        def lifecycle(command: str, **_kwargs) -> int:
            if command == "install":
                return install_service(identity)
            if command == "start":
                return start_service(identity)
            raise ValueError(f"unsupported setup lifecycle command: {command}")

        return run_setup(home, gateway_run_fn=lifecycle)
    finally:
        os.environ.clear()
        os.environ.update(previous)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except argparse.ArgumentError as exc:
        print(f"honeyos: error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)

    explicit_home = Path(args.home) if args.home else None
    home = activate_home(explicit_home)
    identity = ServiceIdentity.default(home)

    if args.command == "init":
        _initialize_embedded(home)
        print(f"✓ {PRODUCT_NAME} initialized: {home}")
        return 0
    if args.command == "setup":
        _initialize_embedded(home)
        return _run_setup(home, identity)
    if args.command == "start":
        _initialize_embedded(home)
        installed = install_service(identity)
        return start_service(identity) if installed == 0 else installed
    if args.command == "web":
        _initialize_embedded(home)
        installed = install_service(identity)
        started = start_service(identity) if installed == 0 else installed
        if started != 0:
            return started
        from honeyos.companion.web import (
            companion_web_url,
            open_companion_web,
            wait_for_companion_web,
        )

        url = companion_web_url()
        print(f"{PRODUCT_NAME} 本地聊天：{url}")
        wait_for_companion_web()
        open_companion_web()
        return 0
    if args.command == "stop":
        return stop_service(identity)
    if args.command == "restart":
        return restart_service(identity)
    if args.command == "status":
        return service_status(identity)
    if args.command == "logs":
        return _run_embedded(["logs"], home)
    if args.command == "doctor":
        _initialize_embedded(home)
        previous = os.environ.copy()
        os.environ.update(_runtime_environment(home))
        try:
            from honeyos.companion.doctor import print_doctor

            return print_doctor(home)
        finally:
            os.environ.clear()
            os.environ.update(previous)
    if args.command == "channel":
        _initialize_embedded(home)
        from honeyos.companion.channels import setup_feishu, setup_weixin

        setup_channel = setup_weixin if args.platform == "weixin" else setup_feishu
        return setup_channel(home)
    if args.command == "pairing":
        arguments = ["pairing", args.pairing_action]
        if args.pairing_action == "approve":
            arguments.extend([args.platform, args.code])
        elif args.pairing_action == "revoke":
            arguments.extend([args.platform, args.user_id])
        return _run_embedded(arguments, home)
    if args.command == "gateway" and args.gateway_command == "run":
        return _run_embedded(["gateway", "run", "--replace"], home)
    print(f"honeyos: error: unsupported command {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
