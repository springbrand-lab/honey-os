# 🍯 HoneyOS

English | [简体中文](README.zh-CN.md)

> A private AI companion in your browser, WeChat, and Feishu | Current beta version: `v0.3.1`

HoneyOS is a locally running, single-user AI agent that stays with you through a browser, WeChat, or Feishu. It gradually develops its own name, personality, and way of interacting with you, while remembering the relationships, preferences, agreements, and shared experiences that both of you have confirmed. All three entry points connect to the same companion, conversation, and long-term memory.

It is more than a chat character. With your permission, it can search the web, manage files, code in local project workspaces, install regular Skills, and create tasks and scheduled jobs. Model API keys, IM credentials, and companion memories stay on your own computer.

> This version is intended for a small, invite-only beta. Each HoneyOS installation serves one user; do not share an installation between multiple users.

## Prerequisites

- A macOS computer (macOS 13 or later is recommended) or a Linux computer.
- An API key for OpenAI, OpenRouter, DeepSeek, or another OpenAI Chat Completions-compatible model service.
- A Base URL when using a custom compatible service.
- Browser chat requires no additional account; WeChat and Feishu are optional.
- Internet access during installation and at least 3 GB of available disk space are recommended.

The official Base URLs for OpenAI, OpenRouter, and DeepSeek are built in. Most users do not need to enter one; HoneyOS asks for a Base URL only when you select a custom compatible endpoint.

## Quick installation (macOS and Linux)

Open Terminal, then paste and run:

```bash
curl -fsSL https://raw.githubusercontent.com/Nicole202504/honeyos/main/install.sh | bash
```

The installer downloads the current HoneyOS release from GitHub, installs it in `~/.local/share/honeyos/app`, and prepares Python, `uv`, and all dependencies. The same command installs and upgrades HoneyOS, so you do not need to download a ZIP file or open a `.command` file.

If you are comfortable with Git, you can also run:

```bash
git clone https://github.com/Nicole202504/honeyos.git
cd honeyos
/bin/sh scripts/install_honeyos.sh
```

## What happens during initial setup

### 1. Connect a model

The installer asks for:

```text
Model service: OpenAI / OpenRouter / DeepSeek / Custom compatible endpoint
API key: input is hidden in the terminal
Model: available models are loaded automatically; use the arrow keys or type to search
```

HoneyOS first loads the models available to the current key and opens a terminal selector. If a custom endpoint does not implement `/models`, you can enter a Model ID manually. HoneyOS still sends a minimal tool-call test immediately. It saves the configuration and continues to IM setup only after the API key, model, and OpenAI Chat Completions tool calling all work.

The browser's **Settings → Model** screen uses the same flow: choose a provider, load and search available models, then validate and save. The API key is never echoed back to the page.

### 2. Choose chat entry points

Browser chat is always available. During initial setup, you can also connect WeChat, Feishu, both, or skip IM for now. You can start with browser chat even without WeChat or Feishu.

#### Browser

The local chat page opens automatically after installation. You can open it again at any time with:

```bash
~/.local/bin/honeyos web
```

The web server listens only on local address `127.0.0.1`; it is not directly exposed to your local network or the internet. The page shows conversations and companion-friendly progress cards, but not hidden reasoning, commands, file paths, or raw tool arguments.

#### WeChat

The terminal displays a Tencent iLink login QR code:

1. Scan the code with WeChat on your phone.
2. Confirm the login on your phone.
3. HoneyOS makes the person who scanned the code the only user allowed to send private messages.
4. Group chat is disabled by default, so no additional pairing code is required.

This connects a WeChat iLink Bot identity. It does not control or read your regular personal WeChat conversations.

#### Feishu

You can scan a QR code to create a bot automatically, or enter an existing App ID and App Secret. HoneyOS connects over WebSocket and does not require a public callback URL. The first private message returns a pairing code; the owner approves it locally with:

```bash
~/.local/bin/honeyos pairing approve feishu PAIRING_CODE
```

Feishu updates tool progress in the same message, so long-running work does not appear to stall. Group chat is disabled by default to keep private companion memories out of workplace groups.

### 3. First-start checks

Before starting, HoneyOS checks that:

- The local data directory is writable.
- The model and API key have passed a real conversation test.
- The local web page can open; if you selected WeChat or Feishu, their connections are checked too.
- Local project workspaces and Computer Use are available.

HoneyOS can code without Docker. If Computer Use is unavailable, HoneyOS shows a yellow warning, but chat, memory, search, files, coding, Skills, tasks, and scheduled jobs still work. Computer Use is needed only for desktop control.

When you see the startup confirmation, open the browser or return to the connected WeChat or Feishu chat:

```text
✓ HoneyOS is running. You can now open the local web chat.
```

For your first message, try:

```text
Hi, let's get to know each other first.
```

If you already have a clear persona in mind, describe it directly. If not, the companion can develop naturally through your interactions, but it will not invent relationships or shared experiences that you have not confirmed together.

## Does `/new` erase memory?

Send lowercase `/new` in a private browser, WeChat, or Feishu conversation:

```text
/new
```

This ends the current short-term conversation context and starts a new session without deleting long-term memory.

HoneyOS keeps:

- The companion's name, personality, speaking style, and stable preferences.
- Confirmed relationships, nicknames, boundaries, rituals, and agreements.
- Long-term information you explicitly asked it to remember.
- Shared experiences that really happened and were confirmed for storage.
- Skills, tasks, scheduled jobs, settings, and past sessions.

HoneyOS clears:

- Temporary context from the current conversation window.
- Unsaved temporary task and tool-execution state.

When you mention “last time” or “our previous agreement,” HoneyOS can search past conversations to verify it. Information mentioned casually in chat but never saved as long-term memory may not return automatically after `/new`.

## Proactive conversations and “Recently Seen”

HoneyOS can find a small number of worthwhile topics on public web pages, verify their sources, filter and deduplicate them, and temporarily store them in a local Topic Pool. This feature is built in: it requires neither an additional Skill nor a separate search API key.

It does not start pushing content immediately after an update. The companion first asks naturally, in its current persona, whether it may occasionally start a conversation. Collection and delivery begin only after explicit consent. By default:

- Public sources are checked every 6 hours, with at most 3 topics kept per round; keeping none is allowed.
- The companion starts at most 3 conversations per day, at least 3 hours apart.
- Quiet hours are 23:00–09:00, and the companion waits until you have been away for at least 2 hours.
- Topics go to the channel where you most recently sent a real message. Feishu and WeChat can receive them directly; the browser receives them only while the page is open and never pretends a topic was delivered while it was closed.
- The current companion persona writes the final opening message using your nickname, relationship, and recent conversations, so it does not turn into a news-summary bot.

Open the **Recently Seen** drawer from the top-right corner of the browser. Choose **Talk about this** to return to the same shared conversation, or **Save for later** to ignore only that topic without changing long-term memory.

You can change every setting in natural language, for example:

```text
When you find something interesting, you can start a conversation with me.
Start at most one conversation per day.
Don't disturb me between 11 PM and 9 AM.
Show me less entertainment gossip and more AI and film news.
Don't start any conversations today.
Stop proactively suggesting topics from now on.
```

The topic pool is stored in `~/.honeyos/state/topic_pool.db`, separately from `IDENTITY.md`, `RELATIONSHIP.md`, and long-term memory. Upgrades, model changes, and `/new` do not clear relationship memories or turn external topics you never discussed into shared experiences.

## Switch models in a conversation

In the browser, WeChat, or Feishu, simply say:

```text
Switch to Claude Sonnet.
```

HoneyOS validates the existing provider and credentials, makes the new model this companion's global default, and hot-switches immediately. No restart is needed: the next message uses the new model, and the choice persists across the browser, WeChat, Feishu, `/new`, and computer restarts. Persona, relationship, and long-term memory do not change.

“Use Sonnet for this conversation” affects only the current short-term session. “Use Haiku for the next reply” affects only the next response. If the target model has no valid credentials, HoneyOS explains what is missing instead of asking you to edit `config.yaml` manually.

## Where coding projects are stored

HoneyOS uses a real local terminal on your computer and stores games, websites, and coding projects under:

```text
~/HoneyOS Projects
```

Each task gets its own project subdirectory. HoneyOS can create and edit files, use Git, install project-specific Python or Node dependencies, run tests, and start browser previews that listen only on the local machine. You can open the files directly in Finder, an editor, or a browser; finished projects no longer disappear inside Docker.

Regular coding commands inside a project do not require confirmation one by one. `sudo`, system changes, dangerous deletion, and other high-risk commands are still confirmed or blocked. HoneyOS model, Feishu, and WeChat credentials are never passed to project processes as environment variables.

If an older version created files in Docker, an upgrade copies recoverable workspace contents to:

```text
~/HoneyOS Projects/从旧版本恢复
```

This directory name means “Recovered from an older version.” Recovery never overwrites files with the same name or deletes the original container data. Companion identity, relationship memory, chat history, and configuration remain in `~/.honeyos` and are independent of project recovery. Docker support remains available to advanced users who need stronger isolation, but it is no longer required for default installation or coding.

## Let HoneyOS modify its own product layer

HoneyOS includes the `honeyos-builder` Skill. It activates only when you explicitly ask to change HoneyOS itself: its pages, companion activity copy, regular built-in companion Skills, or stable extension points. Regular Skill installation, user-project coding, persona and memory changes, and model or voice settings do not use this release flow.

Builder copies only explicitly allowed product files into a candidate workspace. After you confirm, HoneyOS preserves the previous version, switches to the candidate, and restarts automatically. If the new version fails its health check, HoneyOS restores the previous version. Model configuration, IM credentials, relationship memory, and chat history always remain in the original `~/.honeyos` directory and are never copied into candidate source directories.

See the [HoneyOS Builder developer guide](docs/HONEYOS_BUILDER.md) for directory boundaries, the state machine, CLI commands, and test entry points.

## Common management commands

```bash
~/.local/bin/honeyos status
~/.local/bin/honeyos doctor
~/.local/bin/honeyos logs
~/.local/bin/honeyos restart
~/.local/bin/honeyos stop
~/.local/bin/honeyos start
```

To enter model settings again or reconnect IM:

```bash
~/.local/bin/honeyos setup
```

To upgrade, run the installation command again:

```bash
curl -fsSL https://raw.githubusercontent.com/Nicole202504/honeyos/main/install.sh | bash
```

When the installer finds an existing HoneyOS installation, it upgrades and restarts the service, then opens the browser without asking you to configure the model or IM again.

Upgrades preserve the companion persona, relationship memory, chat history, Skills, tasks, scheduled jobs, model configuration, and WeChat and Feishu connections. User data remains safely stored in `~/.honeyos`.

## Data and privacy

Each user's data is stored by default in:

```text
~/.honeyos
```

This directory contains configuration, IM credentials, companion memory, session history, Skills, and logs. API keys and WeChat or Feishu credentials are never written to the Git repository.

Uninstalling the code does not automatically delete `~/.honeyos`, so downloading HoneyOS again reconnects to the same companion. To erase all data, stop HoneyOS first, then delete this directory only after the user explicitly confirms the action.

## Beta feedback checklist

During the beta, please note:

- Whether the first conversation feels like meeting a companion rather than a generic assistant.
- Whether its personality develops naturally when no persona is specified.
- Whether names, relationships, and important memories remain consistent after `/new`.
- Whether web search, files, Skills, tasks, and scheduled jobs complete successfully.
- Whether failure messages make the next step clear to non-technical users.

When reporting an issue, include the time it occurred and the output of `~/.local/bin/honeyos doctor`. Never send API keys, WeChat tokens, Feishu App Secrets, or the entire `~/.honeyos` directory.
