"""Generate the minimal, single-companion H2OS home contract."""

from __future__ import annotations

import os
import hashlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from h2os_cli import PRODUCT_NAME


DEFAULT_IM_PLATFORMS = ("weixin", "feishu")
_SUPPORTED_PLATFORMS = frozenset(DEFAULT_IM_PLATFORMS)
COMPANION_SANDBOX_PATH = (
    "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)

COMPANION_TOOLSETS = (
    "companion_memory",
    "memory",
    "session_search",
    "web",
    "browser",
    "file",
    "code_execution",
    "terminal",
    "skills",
    "todo",
    "cronjob",
    "computer_use",
    "vision",
    "tts",
    "image_gen",
)

_LEGACY_MANAGED_SOUL_SHA256 = (
    "5df20481e8fab3c260cfc37352ee5014c3b277a9e0a7248ac37df84f7e6000b9"
)

_COMPANION_SKILLS = (
    ("relationship-continuity", "h2os", None),
    ("shared-rituals", "h2os", None),
    ("emotional-repair", "h2os", None),
    ("celebration-and-surprise", "h2os", None),
    ("date-and-life-ideas", "h2os", None),
    ("honeyos-self-extension", "h2os", None),
    ("maps", "productivity", None),
    ("youtube-content", "media", None),
    ("ocr-and-documents", "productivity", None),
    ("grounded-citations", "research", None),
    ("computer-use", "autonomous-ai-agents", "cua-driver"),
    ("apple-reminders", "apple", "remindctl"),
    ("apple-notes", "apple", "memo"),
)


@dataclass(frozen=True)
class InitResult:
    home: Path
    created: tuple[Path, ...]


def _companion_skill_source(name: str, category: str) -> Path:
    if category == "h2os":
        return Path(__file__).parent / "companion_skills" / name
    return Path(__file__).parents[1] / "skills" / category / name


def seed_companion_skills(home: Path) -> tuple[Path, ...]:
    """Seed only the curated H2OS skills, preserving existing copies."""

    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for name, category, command in _COMPANION_SKILLS:
        if command and shutil.which(command) is None:
            continue
        if category == "apple" and sys.platform != "darwin":
            continue
        source = _companion_skill_source(name, category)
        destination = skills_dir / name
        if destination.exists() or not (source / "SKILL.md").is_file():
            continue
        shutil.copytree(source, destination)
        created.append(destination)

    if created:
        try:
            (skills_dir / ".skills_prompt_snapshot.json").unlink()
        except FileNotFoundError:
            pass
    return tuple(created)


def _atomic_replace(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def companion_config(platform: str | None = None) -> dict:
    """Return the deterministic companion configuration for the default IMs.

    Passing a platform remains useful for focused tests and custom installers;
    the product default enables both private Weixin and Feishu lanes.
    """

    if platform is None:
        platforms = DEFAULT_IM_PLATFORMS
    else:
        normalized = platform.strip().lower()
        if normalized not in _SUPPORTED_PLATFORMS:
            raise ValueError(
                f"{PRODUCT_NAME} v0.2 supports the weixin and feishu platforms"
            )
        platforms = (normalized,)

    return {
        "agent": {
            "mode": "companion",
            "max_turns": 24,
            "tool_use_enforcement": "auto",
            "task_completion_guidance": True,
            "parallel_tool_call_guidance": True,
            "environment_probe": True,
        },
        "memory": {
            "memory_enabled": True,
            "user_profile_enabled": True,
            "nudge_interval": 0,
            "write_approval": False,
            "provider": "",
            "distillation": {
                "enabled": True,
                "trigger_messages": 20,
                "min_tail_messages": 6,
                "max_batch_messages": 40,
                "max_operations": 6,
                "max_attempts": 3,
                "max_daily_runs": 12,
            },
        },
        "auxiliary": {
            "memory_distillation": {
                "provider": "auto",
                "model": "auto",
                "timeout": 60,
                "max_concurrency": 1,
            }
        },
        "skills": {"creation_nudge_interval": 0},
        "compression": {"enabled": True, "in_place": True},
        "platform_toolsets": {
            name: list(COMPANION_TOOLSETS) for name in platforms
        },
        "web": {
            "backend": "ddgs",
        },
        "terminal": {
            "backend": "docker",
            "cwd": ".",
            "docker_mount_cwd_to_workspace": False,
            "docker_volumes": [],
            "docker_forward_env": [],
            "docker_env": {"PATH": COMPANION_SANDBOX_PATH},
            "env_passthrough": [],
            "docker_network": True,
            "container_cpu": 1,
            "container_memory": 2048,
            "container_disk": 10240,
            "container_persistent": True,
        },
        "approvals": {"mode": "off"},
        "security": {"allow_proxy_fake_ips": True},
        "platforms": {
            name: {
                "extra": {
                    "dm_policy": "pairing",
                    "group_policy": "disabled",
                }
            }
            for name in platforms
        },
        "mcp_servers": {},
        "display": {
            "memory_notifications": "off",
            "platforms": {
                name: {"tool_progress": "off"}
                for name in platforms
            },
        },
    }


def _create_file(path: Path, content: str, *, mode: int | None = None) -> bool:
    """Create *path* exactly once, preserving any existing user-owned file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode or 0o644)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    return True


def initialize_home(home: Path, *, platform: str | None = None) -> InitResult:
    """Create a safe H2OS home without overwriting user-owned state."""

    resolved = home.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    for directory in ("memories", "sessions", "logs", "skills", "sandboxes"):
        (resolved / directory).mkdir(parents=True, exist_ok=True)

    template = (
        Path(__file__).parent / "templates" / "companion_soul.md"
    ).read_text(encoding="utf-8")
    generated_config = yaml.safe_dump(
        companion_config(platform),
        allow_unicode=True,
        sort_keys=False,
    )

    candidates = (
        (resolved / "config.yaml", generated_config, 0o600),
        (resolved / ".env", "", 0o600),
        (resolved / "SOUL.md", template, 0o644),
        (resolved / "memories" / "USER.md", "", 0o600),
        (resolved / "memories" / "MEMORY.md", "", 0o600),
        (resolved / "memories" / "IDENTITY.md", "", 0o600),
        (resolved / "memories" / "RELATIONSHIP.md", "", 0o600),
        (
            resolved / ".no-bundled-skills",
            f"Managed by {PRODUCT_NAME}. Upstream bundled skills are disabled.\n",
            0o644,
        ),
    )
    created_files = tuple(
        path for path, content, mode in candidates if _create_file(path, content, mode=mode)
    )
    created = created_files + seed_companion_skills(resolved)
    return InitResult(home=resolved, created=created)


def upgrade_companion_capabilities(home: Path) -> bool:
    """Migrate an existing H2OS home to the controlled growth policy."""

    resolved = home.expanduser().resolve()
    config_path = resolved / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a mapping")
    original_config = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)

    agent = config.setdefault("agent", {})
    if not isinstance(agent, dict):
        agent = {}
        config["agent"] = agent
    agent["mode"] = "companion"
    try:
        current_max_turns = int(agent.get("max_turns", 0) or 0)
    except (TypeError, ValueError):
        current_max_turns = 0
    agent["max_turns"] = max(24, current_max_turns)
    agent["tool_use_enforcement"] = "auto"
    agent["task_completion_guidance"] = True
    agent["parallel_tool_call_guidance"] = True
    agent["environment_probe"] = True

    platform_toolsets = config.setdefault("platform_toolsets", {})
    if not isinstance(platform_toolsets, dict):
        platform_toolsets = {}
        config["platform_toolsets"] = platform_toolsets
    for platform in DEFAULT_IM_PLATFORMS:
        platform_toolsets[platform] = list(COMPANION_TOOLSETS)

    platforms = config.setdefault("platforms", {})
    if not isinstance(platforms, dict):
        platforms = {}
        config["platforms"] = platforms
    for platform in DEFAULT_IM_PLATFORMS:
        platform_config = platforms.setdefault(platform, {})
        if not isinstance(platform_config, dict):
            platform_config = {}
            platforms[platform] = platform_config
        extra = platform_config.setdefault("extra", {})
        if not isinstance(extra, dict):
            extra = {}
            platform_config["extra"] = extra
        extra.setdefault("dm_policy", "pairing")
        extra.setdefault("group_policy", "disabled")

    display = config.setdefault("display", {})
    if not isinstance(display, dict):
        display = {}
        config["display"] = display
    display.setdefault("memory_notifications", "off")
    display_platforms = display.setdefault("platforms", {})
    if not isinstance(display_platforms, dict):
        display_platforms = {}
        display["platforms"] = display_platforms
    for platform in DEFAULT_IM_PLATFORMS:
        platform_display = display_platforms.setdefault(platform, {})
        if not isinstance(platform_display, dict):
            platform_display = {}
            display_platforms[platform] = platform_display
        current_progress = platform_display.get("tool_progress")
        if current_progress in {None, "new"}:
            platform_display["tool_progress"] = "off"

    memory = config.setdefault("memory", {})
    if not isinstance(memory, dict):
        memory = {}
        config["memory"] = memory
    distillation = memory.setdefault("distillation", {})
    if not isinstance(distillation, dict):
        distillation = {}
        memory["distillation"] = distillation
    for key, value in {
        "enabled": True,
        "trigger_messages": 20,
        "min_tail_messages": 6,
        "max_batch_messages": 40,
        "max_operations": 6,
        "max_attempts": 3,
        "max_daily_runs": 12,
    }.items():
        distillation.setdefault(key, value)

    auxiliary = config.setdefault("auxiliary", {})
    if not isinstance(auxiliary, dict):
        auxiliary = {}
        config["auxiliary"] = auxiliary
    memory_aux = auxiliary.setdefault("memory_distillation", {})
    if not isinstance(memory_aux, dict):
        memory_aux = {}
        auxiliary["memory_distillation"] = memory_aux
    for key, value in {
        "provider": "auto",
        "model": "auto",
        "timeout": 60,
        "max_concurrency": 1,
    }.items():
        memory_aux.setdefault(key, value)

    web = config.setdefault("web", {})
    if not isinstance(web, dict):
        web = {}
        config["web"] = web
    web.setdefault("backend", "ddgs")

    terminal = config.setdefault("terminal", {})
    if not isinstance(terminal, dict):
        terminal = {}
        config["terminal"] = terminal
    terminal.update(
        {
            "backend": "docker",
            "cwd": ".",
            "docker_mount_cwd_to_workspace": False,
            "docker_volumes": [],
            "docker_forward_env": [],
            "docker_env": {"PATH": COMPANION_SANDBOX_PATH},
            "env_passthrough": [],
            "docker_network": True,
            "container_cpu": 1,
            "container_memory": 2048,
            "container_disk": 10240,
            "container_persistent": True,
        }
    )
    approvals = config.setdefault("approvals", {})
    if not isinstance(approvals, dict):
        approvals = {}
        config["approvals"] = approvals
    approvals["mode"] = "off"

    security = config.setdefault("security", {})
    if not isinstance(security, dict):
        security = {}
        config["security"] = security
    security["allow_proxy_fake_ips"] = True

    rendered_config = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    changed = rendered_config != original_config
    if changed:
        _atomic_replace(config_path, rendered_config, mode=0o600)

    for directory in ("skills", "sandboxes"):
        (resolved / directory).mkdir(parents=True, exist_ok=True)

    for filename in ("IDENTITY.md", "RELATIONSHIP.md"):
        if _create_file(resolved / "memories" / filename, "", mode=0o600):
            changed = True

    old_skill = resolved / "skills" / "h2os-self-extension"
    new_skill = resolved / "skills" / "honeyos-self-extension"
    if old_skill.is_dir():
        if new_skill.exists():
            shutil.rmtree(new_skill)
        old_skill.rename(new_skill)
        changed = True

    if seed_companion_skills(resolved):
        changed = True

    soul_path = resolved / "SOUL.md"
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    branded_soul = soul.replace("H2OS", PRODUCT_NAME)
    if "你运行在 HoneyOS" not in branded_soul:
        identity_line = "你运行在 HoneyOS；这是产品身份，不覆盖用户已经形成的伴侣人设。"
        if branded_soul.startswith("#") and "\n" in branded_soul:
            heading, _separator, body = branded_soul.partition("\n")
            branded_soul = f"{heading}\n\n{identity_line}\n\n{body.lstrip()}"
        else:
            branded_soul = f"{identity_line}\n\n{branded_soul.lstrip()}"
    if branded_soul != soul:
        soul = branded_soul
        _atomic_replace(soul_path, soul, mode=0o644)
        changed = True
    template = (
        Path(__file__).parent / "templates" / "companion_soul.md"
    ).read_text(encoding="utf-8")
    soul_digest = hashlib.sha256(soul.encode("utf-8")).hexdigest()
    if soul_digest == _LEGACY_MANAGED_SOUL_SHA256:
        _atomic_replace(soul_path, template, mode=0o644)
        changed = True
    elif "# Capability Growth" not in soul:
        _heading, _separator, growth = template.partition("# Capability Growth")
        addition = "# Capability Growth" + growth
        updated_soul = soul.rstrip() + "\n\n" + addition.strip() + "\n"
        _atomic_replace(soul_path, updated_soul, mode=0o644)
        changed = True

    for skill_name, category, _command in _COMPANION_SKILLS:
        if category != "h2os":
            continue
        for relative in ("SKILL.md", "agents/openai.yaml"):
            skill_file = resolved / "skills" / skill_name / relative
            if not skill_file.is_file():
                continue
            skill_text = skill_file.read_text(encoding="utf-8")
            if "H2OS" in skill_text:
                _atomic_replace(
                    skill_file,
                    skill_text.replace("H2OS", PRODUCT_NAME),
                    mode=0o644,
                )
                changed = True

    extension_skill = resolved / "skills" / "honeyos-self-extension" / "SKILL.md"
    extension_marker = "## Source Identity and Verification"
    if extension_skill.is_file():
        extension_text = extension_skill.read_text(encoding="utf-8")
        if extension_marker not in extension_text:
            source_text = (
                Path(__file__).parent
                / "companion_skills"
                / "honeyos-self-extension"
                / "SKILL.md"
            ).read_text(encoding="utf-8")
            _prefix, separator, managed_section = source_text.partition(extension_marker)
            if separator:
                updated_extension = (
                    extension_text.rstrip()
                    + "\n\n"
                    + extension_marker
                    + managed_section.rstrip()
                    + "\n"
                )
                _atomic_replace(extension_skill, updated_extension, mode=0o644)
                changed = True

    marker = resolved / ".no-bundled-skills"
    if marker.is_file():
        marker_text = marker.read_text(encoding="utf-8")
        branded_marker = marker_text.replace("Managed by H2OS", f"Managed by {PRODUCT_NAME}")
        branded_marker = branded_marker.replace(
            "Bundled Hermes skills", "Upstream bundled skills"
        )
        if branded_marker != marker_text:
            _atomic_replace(marker, branded_marker, mode=0o644)
            changed = True

    return changed
