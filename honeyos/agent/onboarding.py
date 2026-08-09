"""
Contextual first-touch onboarding hints.

Instead of blocking first-run questionnaires, show a one-time hint the *first*
time a user hits a behavior fork — message-while-running, first long-running
tool, etc.  Each hint is shown once per install (tracked in ``config.yaml`` under
``onboarding.seen.<flag>``) and then never again.

Keep this module tiny and dependency-free so both the CLI and gateway can import
it without pulling in heavy modules.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Flag names (stable — used as config.yaml keys under onboarding.seen)
# -------------------------------------------------------------------------

BUSY_INPUT_FLAG = "busy_input_prompt"
TOOL_PROGRESS_FLAG = "tool_progress_prompt"
OPENCLAW_RESIDUE_FLAG = "openclaw_residue_cleanup"
PROFILE_BUILD_FLAG = "profile_build_offered"


# -------------------------------------------------------------------------
# Hint content
# -------------------------------------------------------------------------

def busy_input_hint_gateway(mode: str) -> str:
    """Hint shown the first time a user messages while the agent is busy.

    ``mode`` is the effective busy_input_mode that was just applied, so the
    message matches reality ("I just interrupted…" vs "I just queued…").
    """
    if mode == "queue":
        return (
            "💡 First-time tip — I queued your message instead of interrupting. "
            "Send `/busy interrupt` to make new messages stop the current task "
            "immediately, or `/busy status` to check. This notice won't appear again."
        )
    if mode == "steer":
        return (
            "💡 First-time tip — I steered your message into the current run; "
            "it will arrive after the next tool call instead of interrupting. "
            "Send `/busy interrupt` or `/busy queue` to change this, or "
            "`/busy status` to check. This notice won't appear again."
        )
    if mode == "redirect":
        return (
            "💡 First-time tip — I redirected the current run using your message. "
            "Completed work stays in context, and `/stop` still cancels the task. "
            "Send `/busy queue` to wait for a separate turn, or `/busy status` "
            "to check. This notice won't appear again."
        )
    return (
        "💡 First-time tip — I just interrupted my current task to answer you. "
        "Send `/busy queue` to queue follow-ups for after the current task instead, "
        "`/busy steer` to inject them mid-run without interrupting, or "
        "`/busy status` to check. This notice won't appear again."
    )


def busy_input_hint_cli(mode: str) -> str:
    """CLI version of the busy-input hint (plain text, no markdown)."""
    if mode == "queue":
        return (
            "(tip) Your message was queued for the next turn. "
            "Use /busy interrupt to make Enter stop the current run instead, "
            "or /busy steer to inject mid-run. This tip only shows once."
        )
    if mode == "steer":
        return (
            "(tip) Your message was steered into the current run; it arrives "
            "after the next tool call. Use /busy interrupt or /busy queue to "
            "change this. This tip only shows once."
        )
    if mode == "redirect":
        return (
            "(tip) Your correction redirected the current run without discarding "
            "completed work. Use /stop to cancel or /busy queue to wait for a "
            "separate turn. This tip only shows once."
        )
    return (
        "(tip) Your message interrupted the current run. "
        "Use /busy queue to queue messages for the next turn instead, "
        "or /busy steer to inject mid-run. This tip only shows once."
    )


def tool_progress_hint_gateway() -> str:
    return (
        "💡 First-time tip — that tool took a while and I'm streaming every step. "
        "If the progress messages feel noisy, send `/verbose` to cycle modes "
        "(all → new → off). This notice won't appear again."
    )


def tool_progress_hint_cli() -> str:
    return (
        "(tip) That tool ran for a while. Use /verbose to cycle tool-progress "
        "display modes (all -> new -> off -> verbose). This tip only shows once."
    )


def openclaw_residue_hint_cli() -> str:
    """Banner shown the first time HoneyOS starts and finds ``~/.openclaw/``.

    Points users at ``honeyos claw migrate`` (non-destructive port of config,
    memory, and skills) first. ``honeyos claw cleanup`` is mentioned as the
    follow-up step for users who have already migrated and want to archive
    the old directory — with a warning that archiving breaks OpenClaw.
    """
    return (
        "A legacy OpenClaw directory was detected at ~/.openclaw/.\n"
        "To port your config, memory, and skills over to HoneyOS, run "
        "`honeyos claw migrate`.\n"
        "If you've already migrated and want to archive the old directory, "
        "run `honeyos claw cleanup` (renames it to ~/.openclaw.pre-migration — "
        "OpenClaw will stop working after this).\n"
        "This tip only shows once."
    )


def detect_openclaw_residue(home: Optional[Path] = None) -> bool:
    """Return True if an OpenClaw workspace directory is present in ``$HOME``.

    Pure filesystem check — no side effects. ``home`` override exists for tests.
    """
    base = home or Path.home()
    try:
        return (base / ".openclaw").is_dir()
    except OSError:
        return False


# -------------------------------------------------------------------------
# Onboarding profile-build path (opt-in, consent-gated)
# -------------------------------------------------------------------------

def profile_build_mode(config: Mapping[str, Any]) -> str:
    """Resolve the onboarding profile-build mode from config.

    Returns one of:
      ``"ask"``  — on first contact, OFFER to build a profile (default).
      ``"off"``  — never offer; the first-message note stays a plain intro.

    Read from ``config.onboarding.profile_build``. Unknown / missing values
    fall back to ``"ask"`` so the default experience offers the flow. Any
    network/account lookups inside the flow are separately consented to in
    conversation — this setting only governs whether the offer is made.
    """
    if not isinstance(config, Mapping):
        return "ask"
    onboarding = config.get("onboarding")
    if not isinstance(onboarding, Mapping):
        return "ask"
    mode = onboarding.get("profile_build")
    if isinstance(mode, str) and mode.strip().lower() == "off":
        return "off"
    return "ask"


def profile_build_directive() -> str:
    """System-note directive appended to the very first message ever.

    Instructs the agent to run a short, opt-in, consent-gated profile-build
    flow and persist confirmed facts to the user-profile memory store
    (``memory`` tool, ``target="user"``). Phrased so the agent ASKS before any
    lookup and never silently reads connected accounts — directly addressing
    the privacy concern that reading email/accounts unprompted feels invasive.
    """
    return (
        "\n\n[System note: This is the user's very first message ever. "
        "After a one-sentence introduction (mention /help shows commands), "
        "OFFER — do not assume — to build a short profile of them so you can "
        "be more useful, and explain they can decline or do it later. If and "
        "ONLY IF they accept:\n"
        "  1. Ask for whatever they're comfortable sharing (name, what they "
        "do, how they like you to work). Volunteered facts come first.\n"
        "  2. Before ANY external lookup, say what you intend to look up and "
        "get explicit consent for that step. Never read their connected "
        "accounts (email, calendar, etc.) silently — ask each time.\n"
        "  3. With consent, you may use web_search to confirm public details "
        "(e.g. employer, public profiles) from the data points they gave.\n"
        "  4. Save each confirmed, durable fact with the memory tool using "
        "target=\"user\" — keep entries compact and high-signal.\n"
        "If they decline at any point, stop immediately and continue normally. "
        "Keep the whole exchange light and conversational, not an interrogation.]"
    )


def companion_first_contact_directive() -> str:
    """Natural first-contact guidance for the private companion product."""
    return (
        "[System note: 这是用户第一次与 HoneyOS 伴侣对话。"
        "使用用户正在使用的语言，以亲密关系伴侣而不是工作助理或系统向导的身份自然回应。"
        "如果用户已经给出你的名字、性格、说话方式、关系设定或对用户的称呼，直接按该设定回应，"
        "不要再进行首次设置引导。"
        "如果用户还没有给出人设，采用温暖、敏锐、略带俏皮但不擅自使用亲昵称呼的默认人格；"
        "回应用户此刻的话之后，用符合这个人格的一句自然表达告诉用户：可以直接说希望你叫什么、"
        "是什么性格、怎样说话、如何称呼用户，也可以不急着决定，让这些在相处中边聊边形成。"
        "不要主动介绍内部命令、技术能力目录，也不要发起资料问卷或罗列功能。"
        "不要使用配置、参数、初始化等产品术语；一次最多问一个轻量问题。"
        "保持简短、自然、有关系感。]"
    )


def select_first_message_directive(
    config: Mapping[str, Any], *, companion_mode: bool
) -> tuple[str, Optional[str]]:
    """Choose the first-contact note and an optional one-time seen flag."""
    if companion_mode:
        return companion_first_contact_directive(), None
    if profile_build_mode(config) == "ask" and not is_seen(config, PROFILE_BUILD_FLAG):
        return profile_build_directive().strip(), PROFILE_BUILD_FLAG
    return (
        "[System note: This is the user's very first message ever. "
        "Briefly introduce yourself and mention that /help shows available commands. "
        "Keep the introduction concise -- one or two sentences max.]",
        None,
    )


# -------------------------------------------------------------------------
# State read / write
# -------------------------------------------------------------------------

def _get_seen_dict(config: Mapping[str, Any]) -> Mapping[str, Any]:
    onboarding = config.get("onboarding") if isinstance(config, Mapping) else None
    if not isinstance(onboarding, Mapping):
        return {}
    seen = onboarding.get("seen")
    return seen if isinstance(seen, Mapping) else {}


def is_seen(config: Mapping[str, Any], flag: str) -> bool:
    """Return True if the user has already been shown this first-touch hint."""
    return bool(_get_seen_dict(config).get(flag))


def mark_seen(config_path: Path, flag: str) -> bool:
    """Persist ``onboarding.seen.<flag> = True`` to ``config_path``.

    Uses the atomic YAML writer so a concurrent process can't observe a
    partially-written file.  Returns True on success, False on any error
    (including the config file being absent — onboarding is best-effort).
    """
    try:
        import yaml
        from honeyos.runtime.config import atomic_config_write
    except Exception as e:  # pragma: no cover — dependency issue
        logger.debug("onboarding: failed to import yaml/utils: %s", e)
        return False

    try:
        cfg: dict = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        if not isinstance(cfg.get("onboarding"), dict):
            cfg["onboarding"] = {}
        seen = cfg["onboarding"].get("seen")
        if not isinstance(seen, dict):
            seen = {}
            cfg["onboarding"]["seen"] = seen
        if seen.get(flag) is True:
            return True  # already marked — nothing to do
        seen[flag] = True
        atomic_config_write(config_path, cfg)
        return True
    except Exception as e:
        logger.debug("onboarding: failed to mark flag %s: %s", flag, e)
        return False


__all__ = [
    "BUSY_INPUT_FLAG",
    "TOOL_PROGRESS_FLAG",
    "OPENCLAW_RESIDUE_FLAG",
    "PROFILE_BUILD_FLAG",
    "busy_input_hint_gateway",
    "busy_input_hint_cli",
    "tool_progress_hint_gateway",
    "tool_progress_hint_cli",
    "openclaw_residue_hint_cli",
    "detect_openclaw_residue",
    "profile_build_mode",
    "profile_build_directive",
    "companion_first_contact_directive",
    "select_first_message_directive",
    "is_seen",
    "mark_seen",
]
