from __future__ import annotations

import shutil

import yaml

import h2os_cli.config as config_module
from h2os_cli.config import initialize_home


def test_initialize_home_creates_companion_contract(tmp_path):
    result = initialize_home(tmp_path, platform="weixin")
    config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))

    assert config["agent"]["mode"] == "companion"
    assert config["agent"]["max_turns"] == 8
    assert "max_iterations" not in config["agent"]
    assert config["agent"]["tool_use_enforcement"] is False
    assert config["agent"]["task_completion_guidance"] is False
    assert config["agent"]["parallel_tool_call_guidance"] is False
    assert config["agent"]["environment_probe"] is False
    assert hasattr(config_module, "COMPANION_TOOLSETS")
    assert config["platform_toolsets"]["weixin"] == list(
        config_module.COMPANION_TOOLSETS
    )
    assert config["platform_toolsets"]["weixin"] == [
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
    ]
    assert config["web"]["backend"] == "ddgs"
    assert config["terminal"]["backend"] == "docker"
    assert config["terminal"]["docker_mount_cwd_to_workspace"] is False
    assert config["terminal"]["docker_volumes"] == []
    assert config["terminal"]["docker_forward_env"] == []
    assert config["terminal"]["env_passthrough"] == []
    assert config["approvals"]["mode"] == "off"
    assert config["security"]["allow_proxy_fake_ips"] is True
    assert config["memory"]["memory_enabled"] is True
    assert config["memory"]["user_profile_enabled"] is True
    assert config["memory"]["nudge_interval"] == 0
    assert config["memory"]["provider"] == ""
    assert config["memory"]["distillation"] == {
        "enabled": True,
        "trigger_messages": 20,
        "min_tail_messages": 6,
        "max_batch_messages": 40,
        "max_operations": 6,
        "max_attempts": 3,
        "max_daily_runs": 12,
    }
    assert config["auxiliary"]["memory_distillation"] == {
        "provider": "auto",
        "model": "auto",
        "timeout": 60,
        "max_concurrency": 1,
    }
    assert config["skills"]["creation_nudge_interval"] == 0
    assert config["mcp_servers"] == {}
    assert config["platforms"]["weixin"]["extra"]["dm_policy"] == "pairing"
    assert config["platforms"]["weixin"]["extra"]["group_policy"] == "disabled"
    assert (tmp_path / ".no-bundled-skills").exists()
    assert "亲密关系伴侣" in (tmp_path / "SOUL.md").read_text(encoding="utf-8")
    assert (tmp_path / "memories" / "USER.md").exists()
    assert (tmp_path / "memories" / "MEMORY.md").exists()
    assert (tmp_path / "memories" / "IDENTITY.md").exists()
    assert (tmp_path / "memories" / "RELATIONSHIP.md").exists()
    seeded_skills = {
        path.name for path in (tmp_path / "skills").iterdir() if path.is_dir()
    }
    assert {
        "relationship-continuity",
        "shared-rituals",
        "emotional-repair",
        "celebration-and-surprise",
        "date-and-life-ideas",
        "honey-os-self-extension",
        "maps",
        "youtube-content",
        "ocr-and-documents",
        "grounded-citations",
    }.issubset(seeded_skills)
    assert "hermes-agent" not in seeded_skills
    assert result.home == tmp_path.resolve()


def test_initialize_home_is_idempotent_and_preserves_user_owned_files(tmp_path):
    initialize_home(tmp_path)
    (tmp_path / "SOUL.md").write_text("user-owned-soul", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("user_owned: true\n", encoding="utf-8")
    (tmp_path / "memories" / "USER.md").write_text(
        "user-owned-memory", encoding="utf-8"
    )

    second = initialize_home(tmp_path)

    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "user-owned-soul"
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == "user_owned: true\n"
    assert (
        tmp_path / "memories" / "USER.md"
    ).read_text(encoding="utf-8") == "user-owned-memory"
    assert second.created == ()


def test_initialize_home_rejects_unsupported_platform(tmp_path):
    try:
        initialize_home(tmp_path, platform="telegram")
    except ValueError as exc:
        assert "weixin" in str(exc)
    else:
        raise AssertionError("unsupported platform was accepted")


def test_upgrade_companion_capabilities_is_idempotent_and_preserves_user_state(tmp_path):
    initialize_home(tmp_path)
    config_path = tmp_path / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["providers"] = {"user-provider": {"base_url": "https://example.test/v1"}}
    config["user_owned"] = {"keep": True}
    config["platform_toolsets"]["weixin"] = ["memory", "session_search"]
    config["terminal"]["backend"] = "local"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("# My formed identity\n\nKeep me.\n", encoding="utf-8")

    assert hasattr(config_module, "upgrade_companion_capabilities")
    changed = config_module.upgrade_companion_capabilities(tmp_path)
    first_config = config_path.read_text(encoding="utf-8")
    first_soul = soul_path.read_text(encoding="utf-8")
    changed_again = config_module.upgrade_companion_capabilities(tmp_path)

    migrated = yaml.safe_load(first_config)
    assert changed is True
    assert changed_again is False
    assert config_path.read_text(encoding="utf-8") == first_config
    assert soul_path.read_text(encoding="utf-8") == first_soul
    assert migrated["providers"] == config["providers"]
    assert migrated["user_owned"] == {"keep": True}
    assert migrated["platform_toolsets"]["weixin"] == list(
        config_module.COMPANION_TOOLSETS
    )
    assert migrated["terminal"]["backend"] == "docker"
    assert migrated["security"]["allow_proxy_fake_ips"] is True
    assert migrated["memory"]["distillation"]["trigger_messages"] == 20
    assert migrated["memory"]["distillation"]["max_daily_runs"] == 12
    assert migrated["auxiliary"]["memory_distillation"]["provider"] == "auto"
    assert first_soul.startswith("# My formed identity")
    assert first_soul.count("# Capability Growth") == 1
    assert (tmp_path / "skills" / "relationship-continuity" / "SKILL.md").exists()


def test_upgrade_migrates_legacy_product_brand_without_touching_identity(tmp_path):
    initialize_home(tmp_path)
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text(
        "# My formed identity\n\nKeep me.\n\n不得修改 H2OS 核心 Runtime。\n",
        encoding="utf-8",
    )
    old_skill = tmp_path / "skills" / "h2os-self-extension"
    new_skill = tmp_path / "skills" / "honey-os-self-extension"
    shutil.copytree(new_skill, old_skill)
    for relative in ("SKILL.md", "agents/openai.yaml"):
        path = old_skill / relative
        path.write_text(
            path.read_text(encoding="utf-8").replace("Honey OS", "H2OS"),
            encoding="utf-8",
        )
    with (old_skill / "SKILL.md").open("a", encoding="utf-8") as handle:
        handle.write("\nPreserve this user customization.\n")

    changed = config_module.upgrade_companion_capabilities(tmp_path)

    assert changed is True
    assert "Keep me." in soul_path.read_text(encoding="utf-8")
    assert "你运行在 Honey OS" in soul_path.read_text(encoding="utf-8")
    assert "Honey OS" in soul_path.read_text(encoding="utf-8")
    assert "H2OS" not in soul_path.read_text(encoding="utf-8")
    assert new_skill.is_dir()
    assert not old_skill.exists()
    assert "H2OS" not in (new_skill / "SKILL.md").read_text(encoding="utf-8")
    assert "Preserve this user customization." in (new_skill / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "H2OS" not in (new_skill / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )
