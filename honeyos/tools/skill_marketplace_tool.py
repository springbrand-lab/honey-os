"""Host-side bridge to HoneyOS's scanned Skill marketplace runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from honeyos.tools.registry import registry


def _run_skills_command(arguments: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "honeyos.runtime.main", "skills", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
        shell=False,
    )


def skill_marketplace(
    action: str,
    *,
    query: str = "",
    identifier: str = "",
    limit: int = 10,
    category: str = "",
) -> str:
    """Search registries or install one scanned Skill into the active profile."""

    normalized = str(action or "").strip().lower()
    if normalized == "search":
        if not query.strip():
            return json.dumps(
                {"success": False, "error": "query is required for search"}
            )
        bounded_limit = max(1, min(int(limit or 10), 25))
        result = _run_skills_command(
            ["search", query.strip(), "--limit", str(bounded_limit), "--json"]
        )
        if result.returncode != 0:
            return json.dumps(
                {
                    "success": False,
                    "error": (result.stderr or result.stdout or "search failed")[-4000:],
                },
                ensure_ascii=False,
            )
        try:
            skills: list[dict[str, Any]] = json.loads(result.stdout or "[]")
        except (TypeError, json.JSONDecodeError):
            return json.dumps(
                {"success": False, "error": "marketplace returned invalid JSON"}
            )
        for skill in skills:
            if isinstance(skill, dict):
                skill["installed"] = False
        return json.dumps(
            {"success": True, "catalog": "marketplace", "skills": skills},
            ensure_ascii=False,
        )

    if normalized == "install":
        if not identifier.strip():
            return json.dumps(
                {"success": False, "error": "identifier is required for install"}
            )
        arguments = ["install", identifier.strip(), "--yes"]
        if category.strip():
            arguments.extend(["--category", category.strip()])
        result = _run_skills_command(arguments, timeout=180)
        output = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )[-8000:]
        installed = result.returncode == 0 and (
            "Installed:" in output or "already installed" in output
        )
        return json.dumps(
            {
                "success": installed,
                "identifier": identifier.strip(),
                "message": output or "Skill installation produced no result.",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {"success": False, "error": "action must be search or install"}
    )


SKILL_MARKETPLACE_SCHEMA = {
    "name": "skill_marketplace",
    "description": (
        "Search for Skills that are not installed, or install one through the "
        "HoneyOS security-scanned marketplace. Use skills_list for the installed "
        "catalog; never offer to install an item returned by skills_list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "install"]},
            "query": {"type": "string", "description": "Natural-language search query"},
            "identifier": {
                "type": "string",
                "description": "Exact identifier returned by marketplace search",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            "category": {"type": "string", "description": "Optional install category"},
        },
        "required": ["action"],
    },
}


registry.register(
    name="skill_marketplace",
    toolset="skills",
    schema=SKILL_MARKETPLACE_SCHEMA,
    handler=lambda args, **_kw: skill_marketplace(
        args.get("action", ""),
        query=args.get("query", ""),
        identifier=args.get("identifier", ""),
        limit=args.get("limit", 10),
        category=args.get("category", ""),
    ),
    emoji="🧩",
)
