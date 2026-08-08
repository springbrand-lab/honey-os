from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from honeyos.agent.agent_init import _resolve_agent_mode
from honeyos.agent.system_prompt import build_system_prompt_parts
from honeyos.companion.config import initialize_home


def _agent(mode: str):
    return SimpleNamespace(
        _agent_mode=mode,
        load_soul_identity=True,
        skip_context_files=False,
        valid_tool_names={
            "memory",
            "companion_memory",
            "session_search",
            "skills_list",
            "terminal",
        },
        _task_completion_guidance=True,
        _parallel_tool_call_guidance=True,
        _tool_use_enforcement=True,
        _environment_probe=True,
        _kanban_worker_guidance="KANBAN_SENTINEL",
        _memory_store=None,
        _memory_manager=None,
        _memory_enabled=False,
        _user_profile_enabled=False,
        _platform_hint_overrides={},
        model="gpt-test",
        provider="openai",
        platform="weixin",
        pass_session_id=False,
        session_id="",
    )


def _prompt(mode: str, soul: str = "我是私人 AI 伴侣") -> str:
    with (
        patch("honeyos.run_agent.load_soul_md", return_value=soul),
        patch("honeyos.run_agent.build_nous_subscription_prompt", return_value="NOUS_SENTINEL"),
        patch("honeyos.run_agent.build_environment_hints", return_value="ENV_SENTINEL"),
        patch("honeyos.run_agent.build_context_files_prompt", return_value="CONTEXT_SENTINEL"),
        patch("honeyos.run_agent.build_skills_system_prompt", return_value="SKILLS_SENTINEL"),
    ):
        parts = build_system_prompt_parts(_agent(mode))
    return "\n".join(parts.values())


def test_resolve_agent_mode_is_strict_and_backward_compatible():
    assert _resolve_agent_mode({}) == "assistant"
    assert _resolve_agent_mode({"agent": {"mode": " Companion "}}) == "companion"
    assert _resolve_agent_mode({"agent": {"mode": "unknown"}}) == "assistant"
    assert _resolve_agent_mode({"agent": "broken"}) == "assistant"


def test_companion_prompt_keeps_execution_core_without_hermes_identity():
    prompt = _prompt("companion")

    assert "私人 AI 伴侣" in prompt
    assert "You run on Hermes Agent" not in prompt
    assert "Finishing the job" in prompt
    assert "Parallel tool calls" in prompt
    assert "Tool-use enforcement" in prompt
    assert "provided repository URL is the source identity" in prompt
    assert "verify its provenance" in prompt
    assert "continue the user's original task" in prompt
    assert "user's host computer" in prompt
    assert "HoneyOS Projects" in prompt
    assert "Store every user-visible deliverable" in prompt
    assert "persistent isolated container" not in prompt
    assert "not the user's host computer" not in prompt
    assert "Active Hermes profile" not in prompt
    assert "coding agent" not in prompt.lower()
    assert "NOUS_SENTINEL" not in prompt
    assert "ENV_SENTINEL" not in prompt
    assert "CONTEXT_SENTINEL" not in prompt
    assert "SKILLS_SENTINEL" in prompt
    assert "KANBAN_SENTINEL" not in prompt


def test_companion_prompt_keeps_persona_through_the_whole_tool_turn():
    prompt = _prompt("companion")

    assert "所有对用户可见的表达" in prompt
    assert "工具不会改变你的身份" in prompt
    assert "不要逐步播报" in prompt
    assert "状态卡" in prompt
    assert "最终交付" in prompt
    assert "不要机械添加昵称" in prompt


def test_companion_prompt_does_not_duplicate_the_task_voice_contract():
    soul = "# 伴侣人格\n\n# 任务中的人格连续性\n\n所有对用户可见的表达都保持人格。"

    prompt = _prompt("companion", soul=soul)

    assert prompt.count("# 任务中的人格连续性") == 1


def test_companion_prompt_uses_confirmation_only_memory_guidance():
    prompt = _prompt("companion")

    assert "明确" in prompt
    assert "不要根据语气推断" in prompt
    assert "过去对话" in prompt
    assert "open_loop" in prompt
    assert "temporary_state" in prompt
    assert "commitment" in prompt
    assert "episode" in prompt
    assert "身份、感情、关系" in prompt


def test_companion_prompt_treats_bundled_skills_as_installed_and_implicit():
    prompt = _prompt("companion")

    assert "内置 Skill 已经安装并可用" in prompt
    assert "自然语言需求自动匹配" in prompt
    assert "不要询问是否安装已经内置的 Skill" in prompt
    assert "明确询问 Skill 管理" in prompt


def test_companion_fallback_identity_never_names_hermes():
    prompt = _prompt("companion", soul="")

    assert "亲密关系伴侣" in prompt
    assert "HoneyOS" in prompt
    assert "H2OS" not in prompt
    assert "Hermes Agent" not in prompt


def test_self_extension_skill_requires_source_and_runtime_verification(tmp_path):
    initialize_home(tmp_path)
    skill = (
        tmp_path / "skills" / "honeyos-self-extension" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "用户提供的仓库 URL 是来源身份" in skill
    assert "不能根据项目名猜测 PyPI" in skill
    assert "--user" in skill and "持久" in skill
    assert "--help" in skill
    assert "doctor" in skill
    assert "继续完成用户原本的任务" in skill


def test_assistant_prompt_keeps_honeyos_help():
    prompt = _prompt("assistant")

    assert "You run on HoneyOS" in prompt
    assert "NOUS_SENTINEL" in prompt


def test_companion_soul_defines_intimate_identity_and_controlled_growth(tmp_path):
    initialize_home(tmp_path)
    soul = (tmp_path / "SOUL.md").read_text(encoding="utf-8")

    assert "亲密关系伴侣" in soul
    assert "不是普通朋友" in soul
    assert "用户提供" in soul and "优先" in soul
    assert "先回应这个人" in soul
    assert "暧昧" in soul
    assert "不预设" in soul
    assert "内疚" in soul and "制造依赖" in soul
    assert "隔离环境" in soul
    assert "无需确认" in soul
    assert "普通 Skill" in soul
    assert "系统软件" in soul and "明确确认" in soul
    assert "不得修改 HoneyOS 核心" in soul
    assert "不要声称已经搜索、读取、安装或执行" in soul
    assert "内置 Skill 已经安装并可用" in soul
    assert "自然语言需求自动匹配" in soul


def test_companion_home_creates_relationship_context_files(tmp_path):
    initialize_home(tmp_path)

    assert (tmp_path / "memories" / "IDENTITY.md").exists()
    assert (tmp_path / "memories" / "RELATIONSHIP.md").exists()
