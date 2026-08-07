"""Public H2OS command line.

Only bootstrap-safe modules are imported at module import time. Hermes runtime
imports happen in child processes after ``HERMES_HOME`` is pinned.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from h2os_cli import PRODUCT_NAME
from h2os_cli.bootstrap import activate_h2os_home, resolve_h2os_home


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="honeyos",
        description=f"Run your private {PRODUCT_NAME} AI companion.",
        exit_on_error=False,
    )
    parser.add_argument("--home", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "setup", help=f"Set up model, IM channels, and start {PRODUCT_NAME}"
    )
    subparsers.add_parser("init", help="Initialize the private companion")
    subparsers.add_parser("start", help="Start the background message service")
    subparsers.add_parser("stop", help="Stop the background message service")
    subparsers.add_parser("restart", help="Restart the background message service")
    subparsers.add_parser("status", help="Show companion status")
    subparsers.add_parser("logs", help=f"Show {PRODUCT_NAME} logs")
    subparsers.add_parser("doctor", help=f"Check the {PRODUCT_NAME} installation")
    channel = subparsers.add_parser("channel", help="Configure the chat channel")
    channel_commands = channel.add_subparsers(dest="channel_command", required=True)
    channel_setup = channel_commands.add_parser("setup", help="Connect a chat channel")
    channel_setup.add_argument("platform", choices=("weixin", "feishu"))
    pairing = subparsers.add_parser("pairing", help="Manage private-chat access")
    pairing_commands = pairing.add_subparsers(dest="pairing_action", required=True)
    pairing_commands.add_parser("list", help="List pending and approved users")
    pairing_approve = pairing_commands.add_parser("approve", help="Approve access")
    pairing_approve.add_argument("platform", choices=("weixin", "feishu"))
    pairing_approve.add_argument("code")
    pairing_revoke = pairing_commands.add_parser("revoke", help="Revoke access")
    pairing_revoke.add_argument("platform", choices=("weixin", "feishu"))
    pairing_revoke.add_argument("user_id")
    pairing_commands.add_parser("clear-pending", help="Clear pending requests")
    return parser


def _initialize(home):
    from h2os_cli.config import initialize_home, upgrade_companion_capabilities
    from h2os_cli.runtime import write_runtime_identity

    result = initialize_home(home)
    upgrade_companion_capabilities(home)
    identity = write_runtime_identity(home)
    return result, identity


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except argparse.ArgumentError as exc:
        print(f"honeyos: error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)

    home = activate_h2os_home(resolve_h2os_home(args.home))

    if args.command == "init":
        result, _identity = _initialize(home)
        suffix = "initialized" if result.created else "already initialized"
        print(f"{PRODUCT_NAME} {suffix}: {home}")
        return 0

    if args.command == "setup":
        _initialize(home)
        from h2os_cli.setup import run_setup

        return run_setup(home)

    if args.command == "channel":
        _initialize(home)
        if args.channel_command == "setup" and args.platform == "weixin":
            from h2os_cli.channels import setup_weixin

            return setup_weixin(home)
        if args.channel_command == "setup" and args.platform == "feishu":
            from h2os_cli.channels import setup_feishu

            return setup_feishu(home)
        print("honeyos: error: unsupported channel command", file=sys.stderr)
        return 2

    from h2os_cli.runtime import run_gateway_command, run_hermes_module

    if args.command == "pairing":
        arguments = ["pairing", args.pairing_action]
        if args.pairing_action == "approve":
            arguments.extend([args.platform, args.code])
        elif args.pairing_action == "revoke":
            arguments.extend([args.platform, args.user_id])
        return run_hermes_module(arguments, home=home)

    if args.command == "start":
        _initialize(home)
        installed = run_gateway_command(
            "install", home=home, arguments=("--no-start-now",)
        )
        if installed != 0:
            return installed
        return run_gateway_command("start", home=home)
    if args.command in {"stop", "restart", "status"}:
        return run_gateway_command(args.command, home=home)
    if args.command == "logs":
        return run_hermes_module(["logs"], home=home)
    if args.command == "doctor":
        try:
            from h2os_cli.doctor import print_doctor
        except ImportError:
            print(f"{PRODUCT_NAME} doctor is not available in this build.", file=sys.stderr)
            return 1
        return print_doctor(home)

    print(f"honeyos: error: unknown command {args.command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
