"""``honeyos builder`` CLI for controlled companion product improvements."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from honeyos.companion.builder_workspace import (
    _load_trusted_policy,
    inspect_builder_change,
    prepare_builder_change,
)
from honeyos.companion.projects import project_root
from honeyos.core.constants import get_honeyos_home


def build_parser(
    parent_subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = parent_subparsers.add_parser(
        "builder",
        help="Prepare, review, and enable a companion product change",
        description=(
            "Create a partial candidate workspace under HoneyOS Projects. "
            "After a user explicitly confirms it, Builder can switch to a checked slot "
            "and automatically roll back if it does not become healthy."
        ),
    )
    sub = parser.add_subparsers(dest="builder_action")

    prepare = sub.add_parser("prepare", help="Create an isolated candidate workspace")
    prepare.add_argument("--source", required=True, help="Local HoneyOS Git checkout")
    prepare.add_argument("--goal", required=True, help="User-visible improvement goal")
    prepare.add_argument(
        "--allow",
        action="append",
        required=True,
        dest="allowed_paths",
        help="Repo-relative path or glob the candidate may change; repeatable",
    )
    prepare.add_argument(
        "--change-id",
        required=True,
        help="Stable lowercase identifier, for example memory-upgrade-001",
    )

    inspect = sub.add_parser("inspect", help="Classify the candidate diff")
    inspect.add_argument("change_id", help="Identifier returned by builder prepare")
    activate = sub.add_parser(
        "activate",
        help="Enable a reviewed change after the user has said to switch it on",
    )
    activate.add_argument("change_id", help="Identifier returned by builder prepare")
    parser.set_defaults(_builder_parser=parser)
    return parser


def builder_command(args: argparse.Namespace) -> int:
    action = getattr(args, "builder_action", None)
    if not action:
        args._builder_parser.print_help()
        return 0
    try:
        root = project_root() / "HoneyOS Builder"
        if action == "prepare":
            prepared = prepare_builder_change(
                source_repo=args.source,
                goal=args.goal,
                allowed_paths=args.allowed_paths,
                builder_root=root,
                change_id=args.change_id,
                state_root=get_honeyos_home() / "builder",
            )
            payload = {
                "change_id": prepared.change_id,
                "workspace": str(prepared.workspace),
                "manifest": str(prepared.manifest_path),
                "installation": "awaiting_user_confirmation",
            }
        elif action == "inspect":
            report = inspect_builder_change(
                get_honeyos_home() / "builder" / "changes" / args.change_id
            )
            payload = {
                "change_id": args.change_id,
                "status": report.status,
                "allowed_changes": list(report.allowed_changes),
                "protected_changes": list(report.protected_changes),
                "out_of_scope_changes": list(report.out_of_scope_changes),
                "installable": report.installable,
                "report": str(report.report_path),
                "candidate_digest": report.candidate_digest,
            }
        elif action == "activate":
            from honeyos.companion.builder_activation import ActivationError, ActivationStore

            change_root = get_honeyos_home() / "builder" / "changes" / args.change_id
            policy, _policy_digest = _load_trusted_policy(change_root)
            source_repo = Path(str(policy["source_repo"])).expanduser().resolve()
            store = ActivationStore(get_honeyos_home(), bundled_root=source_repo)
            staged = store.stage(change_root)
            receipt = store.preflight(staged.activation_id)
            if not receipt.success:
                raise ActivationError("candidate did not pass static checks")
            store.transition(
                staged.activation_id,
                "staged",
                "awaiting_confirmation",
                detail="user confirmed product switch",
            )
            activated = store.activate_confirmed(staged.activation_id)
            payload = {
                "change_id": args.change_id,
                "activation_id": activated.activation_id,
                "state": activated.state,
                "installation": "activated" if activated.state == "healthy" else "rolled_back",
            }
        else:
            print(f"builder: unknown action: {action}", file=sys.stderr)
            return 2
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"builder: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
