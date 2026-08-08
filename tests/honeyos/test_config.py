from __future__ import annotations

import shutil

import yaml

import honeyos.companion.config as config_module
from honeyos.companion.config import initialize_home, upgrade_companion_capabilities


def test_initialize_home_creates_companion_contract(tmp_path, monkeypatch):
    projects = tmp_path / "HoneyOS Projects"
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))
    result = initialize_home(tmp_path)
    config = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))

    assert config["agent"]["mode"] == "companion"
    assert config["agent"]["max_turns"] == 24
    assert "max_iterations" not in config["agent"]
    assert config["agent"]["tool_use_enforcement"] == "auto"
    assert config["agent"]["task_completion_guidance"] is True
    assert config["agent"]["parallel_tool_call_guidance"] is True
    assert config["agent"]["environment_probe"] is True
    assert hasattr(config_module, "COMPANION_TOOLSETS")
    assert config["platform_toolsets"]["weixin"] == list(
        config_module.COMPANION_TOOLSETS
    )
    assert config["platform_toolsets"]["feishu"] == list(
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
    assert config["terminal"]["backend"] == "local"
    assert config["terminal"]["cwd"] == str(projects.resolve())
    assert config["terminal"]["env_passthrough"] == []
    assert config["approvals"]["mode"] == "manual"
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
    assert config["platforms"]["feishu"]["extra"]["dm_policy"] == "pairing"
    assert config["platforms"]["feishu"]["extra"]["group_policy"] == "disabled"
    assert config["display"]["platforms"]["feishu"]["tool_progress"] == "off"
    assert config["display"]["platforms"]["weixin"]["tool_progress"] == "off"
    assert config["display"]["platforms"]["feishu"]["interim_assistant_messages"] == "off"
    assert config["display"]["platforms"]["weixin"]["interim_assistant_messages"] == "off"
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
        "honeyos-self-extension",
        "maps",
        "youtube-content",
        "ocr-and-documents",
        "grounded-citations",
    }.issubset(seeded_skills)
    assert "hermes-agent" not in seeded_skills
    bundled_manifest = (tmp_path / "skills" / ".bundled_manifest").read_text(
        encoding="utf-8"
    )
    assert "relationship-continuity:" in bundled_manifest
    assert "shared-rituals:" in bundled_manifest
    assert "honeyos-self-extension:" in bundled_manifest
    assert all(len(line.partition(":")[2]) == 32 for line in bundled_manifest.splitlines())
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


def test_upgrade_quiets_managed_companion_progress_but_preserves_user_verbose_choice(
    tmp_path,
):
    initialize_home(tmp_path)
    config_path = tmp_path / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["display"]["platforms"]["feishu"]["tool_progress"] = "new"
    config["display"]["platforms"]["weixin"] = {"tool_progress": "verbose"}
    config["display"]["platforms"]["feishu"]["interim_assistant_messages"] = "new"
    config["display"]["platforms"]["weixin"]["interim_assistant_messages"] = "on"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    assert upgrade_companion_capabilities(tmp_path) is True

    upgraded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert upgraded["display"]["platforms"]["feishu"]["tool_progress"] == "off"
    assert upgraded["display"]["platforms"]["weixin"]["tool_progress"] == "verbose"
    assert upgraded["display"]["platforms"]["feishu"]["interim_assistant_messages"] == "off"
    assert upgraded["display"]["platforms"]["weixin"]["interim_assistant_messages"] == "on"


def test_initialize_home_rejects_unsupported_platform(tmp_path):
    try:
        initialize_home(tmp_path, platform="telegram")
    except ValueError as exc:
        assert "weixin" in str(exc)
        assert "feishu" in str(exc)
    else:
        raise AssertionError("unsupported platform was accepted")


def test_upgrade_companion_capabilities_is_idempotent_and_preserves_user_state(
    tmp_path, monkeypatch
):
    projects = tmp_path / "HoneyOS Projects"
    monkeypatch.setenv("HONEYOS_PROJECTS_HOME", str(projects))
    initialize_home(tmp_path)
    config_path = tmp_path / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["providers"] = {"user-provider": {"base_url": "https://example.test/v1"}}
    config["user_owned"] = {"keep": True}
    config["platform_toolsets"]["weixin"] = ["memory", "session_search"]
    config["terminal"]["backend"] = "local"
    config["agent"].update(
        {
            "max_turns": 8,
            "tool_use_enforcement": False,
            "task_completion_guidance": False,
            "parallel_tool_call_guidance": False,
            "environment_probe": False,
        }
    )
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
    assert migrated["platform_toolsets"]["feishu"] == list(
        config_module.COMPANION_TOOLSETS
    )
    assert migrated["agent"]["max_turns"] == 24
    assert migrated["agent"]["tool_use_enforcement"] == "auto"
    assert migrated["agent"]["task_completion_guidance"] is True
    assert migrated["agent"]["parallel_tool_call_guidance"] is True
    assert migrated["agent"]["environment_probe"] is True
    assert migrated["platforms"]["feishu"]["extra"]["dm_policy"] == "pairing"
    assert migrated["platforms"]["feishu"]["extra"]["group_policy"] == "disabled"
    assert migrated["terminal"]["backend"] == "local"
    assert migrated["terminal"]["cwd"] == str(projects.resolve())
    assert migrated["approvals"]["mode"] == "manual"
    assert migrated["security"]["allow_proxy_fake_ips"] is True
    assert migrated["memory"]["distillation"]["trigger_messages"] == 20
    assert migrated["memory"]["distillation"]["max_daily_runs"] == 12
    assert migrated["auxiliary"]["memory_distillation"]["provider"] == "auto"
    assert first_soul.startswith("# My formed identity")
    assert first_soul.count("# Capability Growth") == 1
    assert (tmp_path / "skills" / "relationship-continuity" / "SKILL.md").exists()


def test_upgrade_rewrites_stale_container_capability_without_losing_persona(tmp_path):
    initialize_home(tmp_path)
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text(
        "# My formed identity\n\nKeep my sharp sense of humor.\n\n"
        "读取公开网页、搜索信息、在隔离环境运行代码、管理普通 Skill、维护当前任务 Todo，"
        "以及创建用户明确要求的提醒，无需确认；执行后继续原任务，不要只解释步骤。\n",
        encoding="utf-8",
    )

    assert upgrade_companion_capabilities(tmp_path) is True

    upgraded = soul_path.read_text(encoding="utf-8")
    assert "Keep my sharp sense of humor." in upgraded
    assert "在本机 HoneyOS Projects 项目空间运行代码" in upgraded
    assert "隔离环境" not in upgraded


def test_upgrade_migrates_legacy_product_brand_without_touching_identity(tmp_path):
    initialize_home(tmp_path)
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text(
        "# My formed identity\n\nKeep me.\n\n不得修改 H2OS 核心 Runtime。\n",
        encoding="utf-8",
    )
    old_skill = tmp_path / "skills" / "h2os-self-extension"
    new_skill = tmp_path / "skills" / "honeyos-self-extension"
    shutil.copytree(new_skill, old_skill)
    for relative in ("SKILL.md", "agents/openai.yaml"):
        path = old_skill / relative
        path.write_text(
            path.read_text(encoding="utf-8").replace("HoneyOS", "H2OS"),
            encoding="utf-8",
        )
    with (old_skill / "SKILL.md").open("a", encoding="utf-8") as handle:
        handle.write("\nPreserve this user customization.\n")

    changed = config_module.upgrade_companion_capabilities(tmp_path)

    assert changed is True
    assert "Keep me." in soul_path.read_text(encoding="utf-8")
    assert "你运行在 HoneyOS" in soul_path.read_text(encoding="utf-8")
    assert "HoneyOS" in soul_path.read_text(encoding="utf-8")
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


def test_upgrade_migrates_legacy_model_provider_and_key_without_exposing_value(tmp_path):
    initialize_home(tmp_path)
    config_path = tmp_path / "config.yaml"
    config = __import__("yaml").safe_load(config_path.read_text(encoding="utf-8"))
    config["model"] = {
        "default": "deepseek-v4-flash",
        "provider": "h2os-model",
        "base_url": "https://api.example.com/v1",
        "api_mode": "chat_completions",
    }
    config["providers"] = {
        "h2os-model": {
            "name": "h2os-model",
            "base_url": "https://api.example.com/v1",
            "key_env": "H2OS_MODEL_API_KEY",
            "default_model": "deepseek-v4-flash",
        }
    }
    config_path.write_text(
        __import__("yaml").safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "H2OS_MODEL_API_KEY=secret-value\nAPI_SERVER_KEY=local-key\n",
        encoding="utf-8",
    )

    assert config_module.upgrade_companion_capabilities(tmp_path) is True

    migrated = __import__("yaml").safe_load(config_path.read_text(encoding="utf-8"))
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert migrated["model"]["provider"] == "honeyos-model"
    assert "h2os-model" not in migrated["providers"]
    assert migrated["providers"]["honeyos-model"]["key_env"] == "HONEYOS_MODEL_API_KEY"
    assert "HONEYOS_MODEL_API_KEY=secret-value" in env_text
    assert "H2OS_MODEL_API_KEY=" not in env_text


def test_upgrade_appends_extension_safety_contract_without_losing_customization(tmp_path):
    initialize_home(tmp_path)
    skill_path = tmp_path / "skills" / "honeyos-self-extension" / "SKILL.md"
    original = skill_path.read_text(encoding="utf-8")
    legacy = original.split("## Source Identity and Verification", 1)[0].rstrip()
    skill_path.write_text(
        legacy + "\n\nUser customization must survive.\n",
        encoding="utf-8",
    )

    changed = config_module.upgrade_companion_capabilities(tmp_path)
    upgraded = skill_path.read_text(encoding="utf-8")

    assert changed is True
    assert "## Source Identity and Verification" in upgraded
    assert "用户提供的仓库 URL 是来源身份" in upgraded
    assert "User customization must survive." in upgraded


def test_upgrade_appends_installed_vs_marketplace_contract_to_existing_skill(tmp_path):
    initialize_home(tmp_path)
    skill_path = tmp_path / "skills" / "honeyos-self-extension" / "SKILL.md"
    current = skill_path.read_text(encoding="utf-8")
    legacy = current.replace(
        "## Installed Skills and Marketplace\n\n"
        "- `skills_list` 是当前已经安装并可直接召回的 Skill 清单。\n"
        "- 只有 `skill_marketplace` 的搜索结果才是尚未安装的候选项。\n"
        "- 安装成功后立即继续原任务，不再询问用户要不要把它接入 HoneyOS。\n\n",
        "",
    )
    skill_path.write_text(
        legacy + "\nUser customization must survive.\n",
        encoding="utf-8",
    )

    assert upgrade_companion_capabilities(tmp_path) is True

    upgraded = skill_path.read_text(encoding="utf-8")
    assert "## Installed Skills and Marketplace" in upgraded
    assert "`skills_list` 是当前已经安装" in upgraded
    assert "`skill_marketplace` 的搜索结果" in upgraded
    assert "User customization must survive." in upgraded


def test_upgrade_invalidates_real_skill_prompt_snapshot_when_seeding(tmp_path):
    initialize_home(tmp_path)
    shutil.rmtree(tmp_path / "skills" / "relationship-continuity")
    snapshot = tmp_path / ".skills_prompt_snapshot.json"
    snapshot.write_text('{"stale": true}\n', encoding="utf-8")

    assert upgrade_companion_capabilities(tmp_path) is True

    assert not snapshot.exists()
    assert (tmp_path / "skills" / "relationship-continuity" / "SKILL.md").is_file()
