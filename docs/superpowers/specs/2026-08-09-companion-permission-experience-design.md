# HoneyOS Companion Permission Experience Design

Date: 2026-08-09
Status: approved for implementation

## Objective

Replace Hermes-style technical approval prompts with a HoneyOS-native permission system that preserves the companion relationship while retaining enforceable safety boundaries.

The product should let the companion complete ordinary coding, web, Skill, memory, reminder, and project work without interruptions. When an action genuinely crosses a user boundary, the companion should ask naturally in its current persona and present a small, factual consent control. Catastrophic operations and direct access to HoneyOS-owned secrets remain impossible even with consent.

## Product principles

1. Judge the effect, not the API spelling. Importing `os`, using a heredoc, invoking an interpreter, or calling `subprocess` is not by itself a user-facing risk.
2. An explicit instruction is consent for the ordinary effects necessary to complete that instruction. “Send Xiaowang this message” does not require a second confirmation.
3. Consent is scoped. It applies to the described action, target, app or directory, not to an entire technical primitive such as all future `execute_code` calls.
4. The runtime, not the model, enforces the final allow/deny decision.
5. The model may express the request in character, but it must not invent or omit the trusted action facts supplied by the runtime.
6. Technical detail is available but secondary. It is collapsed by default in Feishu and the web client.
7. The same permission event and decision semantics are shared by web, Feishu and CLI.

## Three policy tiers

### Tier 0: hard block

These actions are refused and do not present a Continue button:

- destructive operations against the root filesystem, home directory, raw block devices or critical system directories;
- shutdown, reboot, fork bombs and kill-all operations that can take down the host;
- direct reading or copying of HoneyOS provider credentials, OAuth tokens, internal message secrets and MCP token stores;
- known attempts to bypass the permission system or modify its policy files directly;
- destructive secure-session keyboard shortcuts.

The companion explains briefly that it cannot perform that action and offers a safer alternative when one exists.

### Tier 1: companion consent

These actions require consent unless the current user instruction already explicitly requests the same action and target:

- destructive changes to source or user data, including uncertain recursive deletion, hard reset and history rewriting;
- operations outside the managed HoneyOS Projects root;
- reading user-owned credentials or private files that are not HoneyOS internal secrets;
- modifying system configuration, services, login files or permissions, or using privilege escalation;
- downloading and directly executing remote scripts;
- sending, posting, uploading, purchasing, deleting or otherwise committing an external side effect that the user did not explicitly request;
- creating an unattended task that will later execute code, send a message or mutate external state;
- desktop actions at an externally consequential commit boundary;
- unrestricted local Python that can bypass the normal HoneyOS tool boundary.

### Tier 2: direct execution

No additional confirmation is shown for:

- reading, creating, editing and running ordinary files under HoneyOS Projects;
- ordinary project commands, local previews, tests and project-local environments;
- interpreter `-c` calls and heredocs whose assessed effects remain inside the project boundary;
- read-only web search, browsing, HTTP GET and API reads;
- installing ordinary project dependencies and ordinary Skills;
- memory updates, To-dos, reminders and non-executing scheduled reminders;
- model switching through the HoneyOS model-control path;
- Computer Use capture, wait, scroll, window listing, focus changes and reversible navigation;
- sending or publishing when the current user instruction explicitly names the action and destination;
- proxy-only `execute_code` programs whose side effects pass through HoneyOS tools.

## Explicit-consent model

Each turn derives a short-lived `UserIntentGrant` from the trusted user message. It is not generated from tool output or browsed content.

```text
UserIntentGrant
  turn_id
  action_class       send | publish | upload | delete | desktop | schedule | directory | other
  target             normalized recipient, path, app, URL or resource
  scope              exact | subtree | task
  expires_at_turn_end
  source_excerpt_hash
```

The grant only suppresses a prompt when the proposed effect matches its action class and target. A request to send a message to Xiaowang does not authorize sending to another person, attaching files, or creating a future recurring message unless those effects were also explicit.

When matching is uncertain, HoneyOS asks rather than inferring broad consent.

## Permission event contract

All approval surfaces consume one structured event:

```text
CompanionPermissionRequest
  request_id
  session_key
  turn_id
  action_class
  risk_tier
  summary             trusted plain-language effect
  target              redacted display target
  boundaries[]        files, recipients, apps, hosts or future schedule
  reversibility       reversible | costly | irreversible
  technical_detail    redacted command/tool information
  persona_context     companion name and voice traits, never secrets
  choices             continue_once | deny | allow_scope
  expires_at
```

`allow_scope` is optional and appears only inside expanded details. Its key must include action class, normalized target and boundary. Broad permanent grants such as “all execute_code” are not offered.

## Companion rendering

### Persona message

The runtime first creates the trusted factual summary. A narrow narration step converts that summary into one short line consistent with the current companion persona. The factual card remains deterministic, so a stylistic model failure cannot change the action being authorized.

If persona narration fails validation or times out, use a warm neutral fallback:

> 我需要直接操作一下你的电脑，才能把这件事继续做完。只会做下面写的这一步。让我继续吗？

### Feishu — selected option A

1. Send a normal companion message using the current avatar, name and persona.
2. Send a compact card containing one factual sentence.
3. Primary actions are `好，你继续` and `先别动`.
4. `查看具体会做什么` is a native collapsed panel containing the redacted command, target, scope and optional scoped future grant.
5. After a decision, update the same card to a compact resolved state and continue or cancel the paused tool call.

The card must not use warning-yellow styling, “Command Approval Required”, raw stack traces or English security jargon.

### Web

Render the same event as a companion bubble followed by a compact inline permission card. The card participates in the existing agent-event stream, exposes a collapsed detail region, and changes in place when resolved.

### CLI

Use the same Chinese product copy and factual summary. Technical detail remains available on demand. CLI support must not retain Hermes naming.

## Policy corrections from the current runtime

### Terminal

- Keep the hardline blocklist intact.
- Split dangerous-pattern results into effect categories rather than rendering every match identically.
- Recursively assess interpreter payloads instead of prompting merely for `-c`, `-e` or heredoc syntax.
- Stop treating every project-local `config.yaml` as HoneyOS security configuration.
- Make deletion path-aware: known project caches and build output may be cleared directly; source and uncertain recursive deletion require consent.
- Preserve consent for system changes, remote-script execution, destructive Git operations, service/container lifecycle and SQL destruction.
- Add terminal-side protection for sensitive reads; file-tool read denial alone is not a security boundary.
- Detect uploads and outbound writes that include local files or private content.

### Execute code

- Keep proxy-only `honeyos_tools` orchestration direct.
- Avoid `execute_code` for ordinary writes and commands through system guidance and tool selection.
- Replace the broad permanent `execute_code` allowlist with one-shot or tightly scoped grants.
- Direct arbitrary host Python remains Tier 1 until HoneyOS has an enforceable host execution broker that can constrain filesystem, process and network effects without Docker.

### Computer Use

- Remove prompts for capture, wait, scroll, pointer movement, window listing, focus and reversible navigation.
- Treat an explicit desktop task as consent for the reversible interactions required to perform it.
- Ask at an unrequested external commit boundary: send, submit, publish, purchase, destructive delete, credential disclosure or permission grant.
- Preserve hard blocks for secure-session and destructive system shortcuts.

### Files and directories

- Keep HoneyOS Projects as the default writable host workspace.
- Continue direct reads and writes inside it, except protected credentials.
- Introduce scoped directory authorization rather than permanently hard-blocking every out-of-workspace request.
- A directory grant must resolve symlinks, store the canonical root, expire or be revocable, and never cover HoneyOS internal credential roots.

### Messaging and scheduling

- A direct reply in the current conversation never needs a permission prompt.
- `send_message` to another target is direct only when matched by an explicit current-turn grant; otherwise Tier 1.
- Reactions are reversible and direct when explicitly requested.
- Ordinary reminders are direct.
- Scheduled code execution or future external messages require consent at creation, not on every run. The card states the schedule, target and action.

### Skills, dependencies, memory and models

- Ordinary Skill installation, project dependency installation, memory writes, To-dos and model switching remain direct.
- Remote installer pipelines, global/system installation, persistence hooks or an install that requests credentials remain Tier 1.
- Existing optional memory/Skill write-approval configuration remains supported for advanced operators but is off in the companion product default.

## Migration and compatibility

- Preserve current session history, memory databases, SOUL, IDENTITY and RELATIONSHIP files.
- Migrate old permanent approvals conservatively. Broad keys such as `execute_code` must not silently become broad effect grants; retain them only for display/audit or discard after recording a migration note.
- Existing web and Feishu sessions keep the same session keys.
- Pending legacy approval cards may resolve through the old handler during a short compatibility window; all new requests use the structured contract.

## Failure behavior

- Notification failure, timeout or malformed action response fails closed for Tier 1.
- Persona narration failure falls back to neutral companion copy and does not block delivery of the factual card.
- A stale button cannot resolve a newer request.
- Only the paired owner who received the permission request may resolve it.
- Commands and details are redacted before entering any IM payload or logs.

## Observability

Record structured, redacted events for requested, auto-consented, allowed, denied, expired and hard-blocked outcomes. Include action class and policy rule, never raw secrets or unredacted command bodies. This enables later review of false prompts and missing gates.

## Implementation sequence

1. Add the structured policy/event types and explicit-intent grant matcher.
2. Classify existing terminal and tool gates into the three tiers while retaining the hardline floor.
3. Add sensitive-read and outbound-effect coverage.
4. Refine `execute_code`, Computer Use, messaging, scheduling and directory authorization policies.
5. Implement the Feishu A renderer and shared resolution path.
6. Implement the matching web and CLI renderers.
7. Migrate legacy approval keys and preserve pending-request compatibility.
8. Add unit, integration and cross-channel tests.

## Acceptance criteria

- Creating and running a small HTML game under HoneyOS Projects shows no approval.
- A proxy-only script that uses HoneyOS terminal/web tools shows no outer approval.
- Ordinary HTTP reads and Skill/dependency installs show no approval.
- A user-directed message to a named recipient sends without a duplicate prompt.
- An agent-initiated message, upload or scheduled external action produces the companion A interaction.
- Feishu displays persona text plus a compact card with collapsed technical detail and updates it after resolution.
- Ordinary Computer Use navigation does not prompt; an unrequested external commit does.
- Project `config.yaml` is not confused with HoneyOS security configuration.
- Terminal attempts to read HoneyOS secrets are hard-blocked and cannot bypass the file-tool guard.
- Direct arbitrary host Python never receives a broad permanent grant.
- Catastrophic hardline commands remain impossible in every approval mode.
- Existing memory and conversation continuity survive the upgrade.
