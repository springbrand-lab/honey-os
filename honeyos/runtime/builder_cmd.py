"""``honeyos builder`` CLI for review-only HoneyOS self-improvement drafts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from honeyos.companion.builder_workspace import (
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
        help="Prepare and inspect review-only HoneyOS product changes",
        description=(
            "Create an isolated, review-only candidate checkout under HoneyOS Projects. "
            "Builder never installs or replaces the running HoneyOS version."
        ),
    )
    sub = parser.add_subparsers(dest="builder_action")

    prepare = sub.add_parser("prepare", help="Create an isolated candidate checkout")
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
                "installation": "review_only",
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
            }
        else:
            print(f"builder: unknown action: {action}", file=sys.stderr)
            return 2
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"builder: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
