"""Generate the minimal, single-companion HONEYOS home contract."""

from __future__ import annotations

import os
import hashlib
import secrets
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from honeyos.migration.legacy import (
    migrate_legacy_model_credentials,
    migrate_legacy_skill_directory,
    rewrite_legacy_product_text,
)

from honeyos.companion import PRODUCT_NAME


DEFAULT_IM_PLATFORMS = ("weixin", "feishu")
COMPANION_WEB_PLATFORM = "api_server"
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
    ("relationship-continuity", "honeyos", None),
    ("shared-rituals", "honeyos", None),
    ("emotional-repair", "honeyos", None),
    ("celebration-and-surprise", "honeyos", None),
    ("date-and-life-ideas", "honeyos", None),
    ("honeyos-self-extension", "honeyos", None),
    ("maps", "honeyos", None),
    ("youtube-content", "honeyos", None),
    ("ocr-and-documents", "honeyos", None),
    ("grounded-citations", "honeyos", None),
    ("computer-use", "honeyos", "cua-driver"),
    ("apple-reminders", "honeyos", "remindctl"),
    ("apple-notes", "honeyos", "memo"),
)


@dataclass(frozen=True)
class InitResult:
    home: Path
    created: tuple[Path, ...]


def _companion_skill_source(name: str, category: str) -> Path:
    if category == "honeyos":
        return Path(__file__).parent / "companion_skills" / name
    return Path(__file__).parents[1] / "skills" / category / name


def seed_companion_skills(home: Path) -> tuple[Path, ...]:
    """Seed only the curated HONEYOS skills, preserving existing copies."""

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
            (home / ".skills_prompt_snapshot.json").unlink()
        except FileNotFoundError:
            pass
    return tuple(created)


def _skill_tree_hash(directory: Path) -> str:
    """Return the bundled-manifest MD5 used by the embedded Skill runtime."""

    digest = hashlib.md5(usedforsecurity=False)
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def record_companion_bundled_skills(home: Path) -> bool:
    """Mark curated companion Skills as installed system bundles."""

    manifest = home / "skills" / ".bundled_manifest"
    entries: dict[str, str] = {}
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition(":")
            if name.strip():
                entries[name.strip()] = value.strip() if separator else ""
    except OSError:
        pass

    for name, category, command in _COMPANION_SKILLS:
        if command and shutil.which(command) is None:
            continue
        source = _companion_skill_source(name, category)
        destination = home / "skills" / name
        if (source / "SKILL.md").is_file() and (destination / "SKILL.md").is_file():
            entries[name] = _skill_tree_hash(source)

    rendered = "".join(
        f"{name}:{value}\n" for name, value in sorted(entries.items())
    )
    try:
        current = manifest.read_text(encoding="utf-8")
    except OSError:
        current = ""
    if rendered == current:
        return False
    _atomic_replace(manifest, rendered, mode=0o600)
    return True


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
            name: list(COMPANION_TOOLSETS)
            for name in (*platforms, COMPANION_WEB_PLATFORM)
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
            **{
                name: {
                    "extra": {
                        "dm_policy": "pairing",
                        "group_policy": "disabled",
                    }
                }
                for name in platforms
            },
            COMPANION_WEB_PLATFORM: {
                "enabled": True,
                "extra": {
                    "host": "127.0.0.1",
                    "port": 8642,
                }
            },
        },
        "mcp_servers": {},
        "display": {
            "memory_notifications": "off",
            "platforms": {
                name: {
                    "tool_progress": "off",
                    "interim_assistant_messages": "off",
                }
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


def _ensure_local_web_secret(home: Path) -> bool:
    """Create the loopback API secret once without replacing user secrets."""

    env_path = home / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    for line in existing.splitlines():
        if line.strip().startswith("API_SERVER_KEY=") and line.split("=", 1)[1].strip():
            return False
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    _atomic_replace(
        env_path,
        existing + suffix + f"API_SERVER_KEY={secrets.token_hex(32)}\n",
        mode=0o600,
    )
    return True


def initialize_home(home: Path, *, platform: str | None = None) -> InitResult:
    """Create a safe HONEYOS home without overwriting user-owned state."""

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
    _ensure_local_web_secret(resolved)
    created = created_files + seed_companion_skills(resolved)
    if record_companion_bundled_skills(resolved):
        created += (resolved / "skills" / ".bundled_manifest",)
    return InitResult(home=resolved, created=created)


def upgrade_companion_capabilities(home: Path) -> bool:
    """Migrate an existing HONEYOS home to the controlled growth policy."""

    resolved = home.expanduser().resolve()
    config_path = resolved / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a mapping")
    original_config = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    credential_migrated, migrated_env = migrate_legacy_model_credentials(
        resolved, config
    )
    if migrated_env is not None:
        _atomic_replace(resolved / ".env", migrated_env, mode=0o600)

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
    for platform in (*DEFAULT_IM_PLATFORMS, COMPANION_WEB_PLATFORM):
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
    web_platform = platforms.setdefault(COMPANION_WEB_PLATFORM, {})
    if not isinstance(web_platform, dict):
        web_platform = {}
        platforms[COMPANION_WEB_PLATFORM] = web_platform
    web_platform["enabled"] = True
    web_extra = web_platform.setdefault("extra", {})
    if not isinstance(web_extra, dict):
        web_extra = {}
        web_platform["extra"] = web_extra
    web_extra["host"] = "127.0.0.1"
    web_extra.setdefault("port", 8642)

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
        current_interim = platform_display.get("interim_assistant_messages")
        if current_interim in {None, "new"}:
            platform_display["interim_assistant_messages"] = "off"

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
    changed = credential_migrated or rendered_config != original_config
    if changed:
        _atomic_replace(config_path, rendered_config, mode=0o600)

    if _ensure_local_web_secret(resolved):
        changed = True

    for directory in ("skills", "sandboxes"):
        (resolved / directory).mkdir(parents=True, exist_ok=True)

    for filename in ("IDENTITY.md", "RELATIONSHIP.md"):
        if _create_file(resolved / "memories" / filename, "", mode=0o600):
            changed = True

    if migrate_legacy_skill_directory(resolved):
        changed = True

    if seed_companion_skills(resolved):
        changed = True
    if record_companion_bundled_skills(resolved):
        changed = True

    soul_path = resolved / "SOUL.md"
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    branded_soul = rewrite_legacy_product_text(soul)
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
        if category != "honeyos":
            continue
        for relative in ("SKILL.md", "agents/openai.yaml"):
            skill_file = resolved / "skills" / skill_name / relative
            if not skill_file.is_file():
                continue
            skill_text = skill_file.read_text(encoding="utf-8")
            branded_skill_text = rewrite_legacy_product_text(skill_text)
            if branded_skill_text != skill_text:
                _atomic_replace(
                    skill_file,
                    branded_skill_text,
                    mode=0o644,
                )
                changed = True

    extension_skill = resolved / "skills" / "honeyos-self-extension" / "SKILL.md"
    if extension_skill.is_file():
        extension_text = extension_skill.read_text(encoding="utf-8")
        source_text = (
            Path(__file__).parent
            / "companion_skills"
            / "honeyos-self-extension"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        for extension_marker in (
            "## Installed Skills and Marketplace",
            "## Source Identity and Verification",
        ):
            if extension_marker in extension_text:
                continue
            _prefix, separator, managed_section = source_text.partition(extension_marker)
            if separator:
                extension_text = (
                    extension_text.rstrip()
                    + "\n\n"
                    + extension_marker
                    + managed_section.split("\n## ", 1)[0].rstrip()
                    + "\n"
                )
                changed = True
        if extension_text != extension_skill.read_text(encoding="utf-8"):
            _atomic_replace(extension_skill, extension_text, mode=0o644)

    marker = resolved / ".no-bundled-skills"
    if marker.is_file():
        marker_text = marker.read_text(encoding="utf-8")
        branded_marker = rewrite_legacy_product_text(marker_text)
        branded_marker = branded_marker.replace(
            "Bundled HoneyOS skills", "Upstream bundled skills"
        )
        if branded_marker != marker_text:
            _atomic_replace(marker, branded_marker, mode=0o644)
            changed = True

    return changed
