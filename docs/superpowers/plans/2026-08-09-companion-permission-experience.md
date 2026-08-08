# HoneyOS Companion Permission Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace API-spelling-based technical approvals with an effect-based HoneyOS permission system and a companion-native Feishu/web/CLI consent experience.

**Architecture:** Add one platform-neutral permission contract and policy classifier ahead of the existing blocking approval queue. Existing terminal, code, messaging, scheduling and Computer Use entry points map proposed effects into that contract; explicit current-turn user intent can satisfy a matching Tier-1 effect, while hardline actions remain unconditionally blocked. Feishu, relay/web and CLI render the same structured request, with persona narration separated from deterministic safety facts.

**Tech Stack:** Python 3.11+, dataclasses, existing HoneyOS gateway adapters, Feishu Interactive Message Card JSON 1.0, vanilla HTML/CSS/JavaScript web assets, pytest.

## Global Constraints

- Judge the effect, not the API spelling.
- An explicit instruction is consent only for the matching action and target in the current turn.
- Runtime policy makes the decision; persona narration cannot widen permission scope.
- HoneyOS internal credentials are never readable through the agent.
- Catastrophic hardline commands remain impossible in every approval mode.
- Technical detail is redacted and collapsed by default.
- Feishu uses option A: normal companion message followed by a compact permission card.
- The primary choices are `好，你继续` and `先别动`; scoped future permission is secondary.
- Existing memory, SOUL, IDENTITY, RELATIONSHIP, session keys and conversation history remain compatible.
- Do not reintroduce Hermes names or technical English approval copy in HoneyOS surfaces.

## File map

- Create `honeyos/tools/permission_policy.py`: structured effect, intent-grant and permission-request types plus pure matching/classification helpers.
- Modify `honeyos/tools/approval.py`: bridge legacy dangerous-command results into the structured contract; narrow interpreter and execute-code grants.
- Modify `honeyos/gateway/run.py`: attach trusted companion narration and deliver one structured request to adapters.
- Modify `honeyos/gateway/platforms/base.py`: friendly deterministic fallback rendering.
- Modify `honeyos/plugins/platforms/feishu/adapter.py`: option-A message plus compact card, collapsed details and resolved states.
- Modify `honeyos/gateway/relay/adapter.py`: structured prompt payload for the local web client.
- Modify `honeyos/companion/web_assets/index.html`: compact inline permission card and expanded detail state.
- Modify `honeyos/companion/projects.py`: path/effect helpers and scoped external-directory authorization.
- Modify `honeyos/model_tools.py`: bind current-turn explicit intent around the existing tool-dispatch scope.
- Modify `honeyos/tools/send_message_tool.py`: external-send effect gate.
- Modify `honeyos/tools/cronjob_tools.py`: future external-effect gate at job creation.
- Modify `honeyos/tools/computer_use/tool.py`: split reversible navigation from commit effects.
- Modify `honeyos/companion/config.py`: companion defaults and migration of broad legacy grants.
- Add focused tests under `tests/honeyos/` for every policy and renderer boundary.

---

### Task 1: Structured permission policy and explicit-intent grants

**Files:**
- Create: `honeyos/tools/permission_policy.py`
- Modify: `honeyos/model_tools.py:1450-1545`
- Test: `tests/honeyos/test_permission_policy.py`

**Interfaces:**
- Produces: `Effect`, `IntentGrant`, `PermissionRequest`, `PolicyDecision`, `RiskTier`, `set_turn_intent_grants()`, `reset_turn_intent_grants()`, `current_intent_grants()`, `decide_effect(effect)`.
- Consumes: the trusted current user message and session/turn identifiers already available in middleware context.

- [ ] **Step 1: Write failing pure-policy tests**

```python
from honeyos.tools.permission_policy import (
    Effect, IntentGrant, RiskTier, decide_effect, grants_from_user_task,
    set_turn_intent_grants, reset_turn_intent_grants,
)

def test_explicit_send_matches_only_same_recipient():
    grants = grants_from_user_task("帮我给小王发一句今晚见", turn_id="t1")
    token = set_turn_intent_grants(grants)
    try:
        assert decide_effect(Effect("send", target="小王")).tier is RiskTier.DIRECT
        assert decide_effect(Effect("send", target="小李")).tier is RiskTier.CONSENT
    finally:
        reset_turn_intent_grants(token)

def test_honeyos_secret_is_always_hard_blocked():
    decision = decide_effect(Effect("read_secret", target="~/.honeyos/.env", internal_secret=True))
    assert decision.tier is RiskTier.HARD_BLOCK

def test_project_write_is_direct():
    assert decide_effect(Effect("write_file", target="/Users/me/HoneyOS Projects/game/index.html", in_workspace=True)).tier is RiskTier.DIRECT
```

- [ ] **Step 2: Run the focused test to verify the module is missing**

Run: `pytest -q tests/honeyos/test_permission_policy.py`

Expected: collection fails with `ModuleNotFoundError: honeyos.tools.permission_policy`.

- [ ] **Step 3: Add the policy data model and exact-match grant logic**

```python
class RiskTier(str, Enum):
    HARD_BLOCK = "hard_block"
    CONSENT = "consent"
    DIRECT = "direct"

@dataclass(frozen=True)
class Effect:
    action_class: str
    target: str = ""
    in_workspace: bool = False
    internal_secret: bool = False
    destructive: bool = False
    external_commit: bool = False
    unattended: bool = False
    technical_detail: str = ""

@dataclass(frozen=True)
class IntentGrant:
    turn_id: str
    action_class: str
    target: str
    scope: str = "exact"

@dataclass(frozen=True)
class PolicyDecision:
    tier: RiskTier
    reason: str
    matched_grant: IntentGrant | None = None

@dataclass(frozen=True)
class PermissionRequest:
    request_id: str
    session_key: str
    turn_id: str
    action_class: str
    summary: str
    target: str
    boundaries: tuple[str, ...] = ()
    reversibility: str = "reversible"
    technical_detail: str = ""
    allow_scope: bool = False

def decide_effect(effect: Effect) -> PolicyDecision:
    if effect.internal_secret:
        return PolicyDecision(RiskTier.HARD_BLOCK, "HoneyOS internal credential access")
    matched = next((g for g in current_intent_grants() if grant_matches(g, effect)), None)
    if matched is not None:
        return PolicyDecision(RiskTier.DIRECT, "explicit current-turn instruction", matched)
    if effect.destructive or effect.external_commit or effect.unattended or not effect.in_workspace and effect.action_class in {"write_file", "directory"}:
        return PolicyDecision(RiskTier.CONSENT, "action crosses a user boundary")
    return PolicyDecision(RiskTier.DIRECT, "ordinary reversible action")
```

Implement `grants_from_user_task()` using anchored intent patterns. Reject questions first with `(?:吗|么|如何|怎么|能不能|可不可以|是否)[？?]?$`. Recognize only these explicit forms: `(?:帮我)?(?:给|向)(?P<target>[^，。,.\s]{1,32})(?:发|发送|回复|说)`, `(?:把|将)(?P<object>[^，。,.]{1,80})(?:上传|发布|删掉|删除)到?(?P<target>[^，。,.]{0,80})`, and `(?:每|每天|每周|明天|今晚|\d+[点时])(?P<schedule>[^，。,.]{0,80})(?:提醒|发送|运行)`. Normalize whitespace and platform prefixes but do not fuzzy-match people or paths. The function reads only the `user_task` argument passed by `handle_function_call()`.

- [ ] **Step 4: Bind grants around the existing tool-dispatch scope**

In `model_tools.handle_function_call()`, next to the existing approval observability context, bind the trusted `user_task` already supplied by the agent loop and reset it in the same `finally` block:

```python
intent_token = set_turn_intent_grants(
    grants_from_user_task(user_task or "", turn_id=turn_id or "")
)
try:
    result = _dispatch(function_args)
finally:
    reset_turn_intent_grants(intent_token)
```

Do not derive the grant from `function_args`, assistant text or tool results. Pass `user_task` into the `execute_code` registry dispatch too so nested audited proxies retain the same exact-turn grant.

- [ ] **Step 5: Run policy and middleware tests**

Run: `pytest -q tests/honeyos/test_permission_policy.py tests/honeyos/test_projects.py`

Expected: all tests pass.

- [ ] **Step 6: Commit the policy core**

```bash
git add honeyos/tools/permission_policy.py honeyos/model_tools.py tests/honeyos/test_permission_policy.py
git commit -m "feat: add effect-based companion permission policy"
```

### Task 2: Correct terminal, filesystem and execute-code policy

**Files:**
- Modify: `honeyos/tools/approval.py:694-960,3421-3530,4240-4535`
- Modify: `honeyos/companion/projects.py:70-180`
- Modify: `honeyos/tools/terminal_tool.py:2600-2710`
- Test: `tests/honeyos/test_approval_policy.py`
- Test: `tests/honeyos/test_execute_code_approval.py`
- Test: `tests/honeyos/test_projects.py`

**Interfaces:**
- Consumes: `Effect` and `decide_effect()` from Task 1.
- Produces: `effect_for_command(command, cwd)`, `authorize_external_directory(path, session_key)`, and structured approval payload fields on existing guard results.

- [ ] **Step 1: Add failing regression tests for current false prompts and missing guards**

```python
def test_project_config_yaml_is_not_security_config(project_env):
    result = check_all_command_guards("printf x > config.yaml", "local")
    assert result["approved"] is True

def test_safe_python_payload_is_not_flagged_only_for_dash_c(project_env):
    result = check_all_command_guards("python3 -c 'print(1 + 1)'", "local")
    assert result["approved"] is True

def test_terminal_read_of_honeyos_secret_is_hard_blocked(project_env):
    result = check_all_command_guards("cat ~/.honeyos/.env", "local")
    assert result["approved"] is False
    assert result["hardline"] is True

def test_arbitrary_host_python_never_offers_broad_permanent_grant(gateway_context):
    result = check_execute_code_guard("import os; print(os.getcwd())", "local")
    assert result["approval_pending"] is True
    assert result["allow_permanent"] is False
```

- [ ] **Step 2: Run the regressions and capture the expected failures**

Run: `pytest -q tests/honeyos/test_approval_policy.py tests/honeyos/test_execute_code_approval.py tests/honeyos/test_projects.py`

Expected: the new config, interpreter, secret-read and permanent-grant assertions fail.

- [ ] **Step 3: Classify command effects after retaining the hardline floor**

Add a path-aware bridge:

```python
def effect_for_command(command: str, cwd: str) -> Effect:
    normalized = _normalize_command_for_detection(command)
    if _reads_honeyos_internal_secret(normalized):
        return Effect("read_secret", target=_redacted_sensitive_target(normalized), internal_secret=True)
    if _is_external_upload(normalized):
        return Effect("upload", target=_external_host(normalized), external_commit=True, technical_detail=command)
    if _is_project_local_safe_script(normalized, cwd):
        return Effect("run_code", target=cwd, in_workspace=True, technical_detail=command)
    destructive = bool(_destructive_findings(normalized))
    return Effect("terminal", target=cwd, in_workspace=_cwd_in_managed_projects(cwd), destructive=destructive, technical_detail=command)
```

Run `detect_hardline_command()` and explicit user deny rules before this bridge. Convert Tier-1 decisions to the existing blocking approval queue with `action_class`, `target`, `boundaries`, `reversibility` and redacted `technical_detail` fields.

- [ ] **Step 4: Narrow false-positive patterns**

Remove generic project `config.yaml` from `_PROJECT_SENSITIVE_WRITE_TARGET`; retain `.env*` and the exact HoneyOS configuration paths. For interpreter flags, recursively inspect the payload and allow when no Tier-0/Tier-1 effect is found. Keep remote-script pipes, system mutation, destructive Git, service/container lifecycle and destructive SQL as Tier 1.

- [ ] **Step 5: Make execute-code permission one-shot or exact-scope only**

Set the approval request fields for direct host Python:

```python
approval_data.update({
    "action_class": "host_code",
    "target": active_managed_project_root_display(),
    "allow_permanent": False,
    "allow_session": False,
    "reversibility": "costly",
})
```

Keep `_is_honeyos_proxy_only_script()` direct. Keep sandbox backends direct. Preserve hardline checks within proxied terminal calls.

- [ ] **Step 6: Add scoped external-directory authorization**

Store canonical, symlink-resolved roots per session. Reject roots that contain or are parents of HoneyOS credential directories. `managed_project_boundary_error()` returns a Tier-1 request with `action_class="directory"` when a matching grant is absent; successful consent records only the exact canonical root for the current task or selected scope.

- [ ] **Step 7: Run the terminal, code and project suites**

Run: `pytest -q tests/honeyos/test_approval_policy.py tests/honeyos/test_execute_code_approval.py tests/honeyos/test_projects.py`

Expected: all tests pass and the original hardline tests remain green.

- [ ] **Step 8: Commit policy corrections**

```bash
git add honeyos/tools/approval.py honeyos/tools/terminal_tool.py honeyos/companion/projects.py tests/honeyos/test_approval_policy.py tests/honeyos/test_execute_code_approval.py tests/honeyos/test_projects.py
git commit -m "fix: classify command approvals by user-visible effect"
```

### Task 3: External messaging, schedules and Computer Use boundaries

**Files:**
- Modify: `honeyos/tools/send_message_tool.py:241-430`
- Modify: `honeyos/tools/cronjob_tools.py:710-1020`
- Modify: `honeyos/tools/computer_use/tool.py:80-110,430-570`
- Test: `tests/honeyos/test_permission_external_effects.py`
- Test: `tests/honeyos/test_computer_use_tool.py`

**Interfaces:**
- Consumes: `decide_effect()` and current-turn grants from Task 1; existing `request_tool_approval()` queue from `approval.py`.
- Produces: `gate_effect_or_error(effect, tool_name)` shared helper and effect metadata for messages, schedules and desktop commits.

- [ ] **Step 1: Write failing external-effect tests**

```python
def test_explicit_named_message_sends_without_second_prompt(intent_grant, fake_sender):
    with intent_grant("send", "feishu:小王"):
        assert send_message_tool({"action": "send", "target": "feishu:小王", "message": "今晚见"})["success"]
    assert fake_sender.approval_requests == []

def test_agent_initiated_message_requests_consent(fake_sender):
    result = send_message_tool({"action": "send", "target": "feishu:小王", "message": "今晚见"})
    assert result["status"] == "pending_approval"

def test_scroll_and_focus_are_reversible_without_prompt(fake_computer):
    assert computer_use({"action": "scroll", "direction": "down"})["ok"]
    assert computer_use({"action": "focus_app", "app": "Safari"})["ok"]
    assert fake_computer.approval_requests == []

def test_unrequested_submit_click_requests_consent(fake_computer):
    result = computer_use({"action": "click", "element": 7, "effect": "submit"})
    assert result["status"] == "pending_approval"
```

- [ ] **Step 2: Run the focused tests and verify the old behavior fails**

Run: `pytest -q tests/honeyos/test_permission_external_effects.py tests/honeyos/test_computer_use_tool.py`

Expected: send-message lacks a gate and reversible Computer Use still follows the old destructive-action approval path.

- [ ] **Step 3: Gate cross-channel sends by target-matched intent**

Before `_handle_send()` dispatches, construct:

```python
effect = Effect(
    "send",
    target=f"{platform_name}:{normalized_target}",
    external_commit=True,
    technical_detail=f"send message to {platform_name}:{normalized_target}",
)
blocked = gate_effect_or_error(effect, tool_name="send_message")
if blocked is not None:
    return blocked
```

Do not gate the assistant's ordinary reply in the active conversation; this applies only to the cross-channel `send_message` tool.

- [ ] **Step 4: Gate future side effects when a cron job is created**

Classify the job payload at `add`/`update`. Ordinary reminders remain direct. Jobs containing code execution or future `send_message` become `Effect("schedule", target=normalized_schedule_and_target, unattended=True)`. Consent happens at creation; execution records the stored grant and does not prompt on every run.

- [ ] **Step 5: Split Computer Use actions by effect**

Replace `_DESTRUCTIVE_ACTIONS` with:

```python
_REVERSIBLE_ACTIONS = frozenset({
    "capture", "wait", "list_apps", "list_windows", "scroll", "focus_app",
    "cua_browser_state", "cua_browser_prepare", "cua_browser_navigate", "cua_browser_pointer",
})
_COMMIT_EFFECTS = frozenset({"send", "submit", "publish", "purchase", "delete", "credential", "permission"})
```

Clicks and typing are direct during an explicitly requested desktop task unless the call declares or the driver identifies a commit effect. A commit effect enters the shared gate. Preserve `_BLOCKED_KEY_COMBOS` unchanged.

- [ ] **Step 6: Run external-effect tests**

Run: `pytest -q tests/honeyos/test_permission_external_effects.py tests/honeyos/test_computer_use_tool.py`

Expected: all tests pass.

- [ ] **Step 7: Commit external-effect gates**

```bash
git add honeyos/tools/send_message_tool.py honeyos/tools/cronjob_tools.py honeyos/tools/computer_use/tool.py tests/honeyos/test_permission_external_effects.py tests/honeyos/test_computer_use_tool.py
git commit -m "feat: gate only unrequested external companion effects"
```

### Task 4: Shared companion request rendering and Feishu option A

**Files:**
- Modify: `honeyos/gateway/run.py:5150-5260`
- Modify: `honeyos/gateway/platforms/base.py:3640-3690`
- Modify: `honeyos/plugins/platforms/feishu/adapter.py:2037-2205,2760-2935`
- Modify: `honeyos/gateway/relay/adapter.py:1702-1760,1880-1930`
- Modify: `honeyos/companion/web_assets/index.html`
- Test: `tests/honeyos/test_permission_rendering.py`
- Test: `tests/honeyos/test_feishu_adapter.py`

**Interfaces:**
- Consumes: structured request fields emitted by Tasks 1-3.
- Produces: `render_permission_narration(request, persona)`, Feishu collapsed panel JSON, relay `companion_permission` payload and shared resolution choices.

- [ ] **Step 1: Write failing rendering contract tests**

```python
def test_feishu_permission_uses_companion_copy_and_collapsed_detail(adapter):
    card = adapter._build_companion_permission_card(permission_fixture())
    rendered = json.dumps(card, ensure_ascii=False)
    assert "好，你继续" in rendered
    assert "先别动" in rendered
    assert "collapsible_panel" in rendered
    assert '"expanded": false' in rendered
    assert "Command Approval Required" not in rendered

def test_resolved_card_has_no_active_buttons(adapter):
    card = adapter._build_resolved_approval_card(choice="once", user_name="小酒")
    rendered = json.dumps(card, ensure_ascii=False)
    assert "我继续去做了" in rendered
    assert '"tag": "button"' not in rendered

def test_relay_emits_structured_companion_permission(relay):
    payload = relay._build_exec_approval_prompt(permission_fixture())
    assert payload["kind"] == "companion_permission"
    assert payload["summary"]
    assert payload["technical_detail"]
```

- [ ] **Step 2: Run rendering tests and verify technical-copy failures**

Run: `pytest -q tests/honeyos/test_permission_rendering.py tests/honeyos/test_feishu_adapter.py`

Expected: tests fail because current adapters render the yellow English command card.

- [ ] **Step 3: Normalize and redact the gateway request once**

In `gateway/run.py`, replace adapter-specific argument assembly with a request dictionary containing `request_id`, `action_class`, `summary`, `target`, `boundaries`, `reversibility`, `technical_detail`, `allow_scope`, `expires_at`, companion name and a validated persona narration. Redact before scheduling adapter delivery.

Use this deterministic fallback when narration is missing:

```python
"我需要直接操作一下你的电脑，才能把这件事继续做完。只会做下面写的这一步。让我继续吗？"
```

- [ ] **Step 4: Implement Feishu option A**

Send the narration through the normal message path, then send a compact interactive card. Its body contains the trusted summary, two primary buttons and:

```python
{
    "tag": "collapsible_panel",
    "expanded": False,
    "header": {"title": {"tag": "plain_text", "content": "查看具体会做什么"}},
    "elements": [{"tag": "markdown", "content": redacted_detail}],
}
```

Keep action values compatible with `resolve_gateway_approval()`. Put session/scope permission inside the collapsed region, never as a primary button. Update the same card to a compact resolved state.

- [ ] **Step 5: Implement the relay/web renderer**

Emit `kind="companion_permission"` with separate narration, summary and detail. In `index.html`, render the narration as an assistant bubble and the card as an inline component with `<details>`, two primary buttons and an in-place resolved state. Do not render raw Markdown fences as text.

- [ ] **Step 6: Replace the CLI fallback copy**

In the base renderer, show Chinese companion copy and the effect summary first. Keep the redacted technical detail behind the existing verbose/detail path. Preserve typed `/approve` and `/deny` compatibility.

- [ ] **Step 7: Run rendering and gateway tests**

Run: `pytest -q tests/honeyos/test_permission_rendering.py tests/honeyos/test_feishu_adapter.py tests/honeyos/test_continuity_gateway.py`

Expected: all tests pass.

- [ ] **Step 8: Commit shared rendering**

```bash
git add honeyos/gateway/run.py honeyos/gateway/platforms/base.py honeyos/plugins/platforms/feishu/adapter.py honeyos/gateway/relay/adapter.py honeyos/companion/web_assets/index.html tests/honeyos/test_permission_rendering.py tests/honeyos/test_feishu_adapter.py
git commit -m "feat: add companion-native permission cards"
```

### Task 5: Migration, compatibility and end-to-end verification

**Files:**
- Modify: `honeyos/companion/config.py:470-570`
- Modify: `honeyos/tools/approval.py:2600-2705`
- Modify: `honeyos/runtime/observability/relay_shared_metrics.py:420-455`
- Test: `tests/honeyos/test_permission_migration.py`
- Test: `tests/honeyos/test_companion_config.py`
- Test: `tests/honeyos/test_permission_end_to_end.py`

**Interfaces:**
- Consumes: structured policy, gates and renderers from Tasks 1-4.
- Produces: conservative migration of legacy approval keys and an end-to-end compatibility guarantee.

- [ ] **Step 1: Add failing migration and end-to-end tests**

```python
def test_broad_execute_code_allowlist_is_not_migrated_as_broad_grant(tmp_home):
    write_config(tmp_home, {"approvals": {"command_allowlist": ["execute_code"]}})
    migrated = migrate_companion_config(tmp_home)
    assert "execute_code" not in migrated["approvals"].get("effect_grants", [])

def test_existing_memory_and_identity_files_are_untouched(upgrade_fixture):
    before = upgrade_fixture.hashes("memory.db", "SOUL.md", "IDENTITY.md", "RELATIONSHIP.md")
    migrate_companion_config(upgrade_fixture.home)
    assert upgrade_fixture.hashes("memory.db", "SOUL.md", "IDENTITY.md", "RELATIONSHIP.md") == before

def test_feishu_permission_round_trip_resumes_same_tool_call(gateway_fixture):
    request = gateway_fixture.start_unrequested_external_send()
    gateway_fixture.click_feishu(request, "once")
    assert gateway_fixture.sent_messages == [("小王", "今晚见")]
    assert gateway_fixture.active_session_key == gateway_fixture.original_session_key

def test_permission_observer_never_records_raw_detail(observer_fixture):
    observer_fixture.record("requested", action_class="upload", technical_detail="Authorization: Bearer secret-value")
    event = observer_fixture.last_event()
    assert event["outcome"] == "requested"
    assert event["action_class"] == "upload"
    assert "secret-value" not in json.dumps(event)
```

- [ ] **Step 2: Run migration and end-to-end tests to verify failure**

Run: `pytest -q tests/honeyos/test_permission_migration.py tests/honeyos/test_companion_config.py tests/honeyos/test_permission_end_to_end.py`

Expected: the legacy broad key is still honored and the structured round trip is not implemented.

- [ ] **Step 3: Add conservative migration**

On companion initialization, retain narrow legacy pattern grants only when they map to an exact action class and target. Move broad `execute_code`, generic interpreter and wildcard grants into `approvals.legacy_audit` with a timestamp and do not activate them. Do not modify memory or persona files.

- [ ] **Step 4: Verify stale, timeout and owner-only behavior**

Add cases proving a stale request ID cannot resolve a newer prompt, a timeout fails closed, a different Feishu user cannot approve, secrets are redacted in card JSON and logs, and notification failure returns a final blocked result rather than retrying silently.

- [ ] **Step 5: Record redacted permission outcomes**

Extend the existing relay tool-call metric with `permission_action_class` and `permission_outcome`. Accept only `requested`, `explicit_grant`, `allowed`, `denied`, `expired`, `hard_blocked` and `not_required`. Store the policy rule key and redacted target; never store `technical_detail`, command bodies, message bodies or source excerpts.

- [ ] **Step 6: Run the full focused permission suite**

Run: `pytest -q tests/honeyos/test_permission_policy.py tests/honeyos/test_approval_policy.py tests/honeyos/test_execute_code_approval.py tests/honeyos/test_permission_external_effects.py tests/honeyos/test_computer_use_tool.py tests/honeyos/test_permission_rendering.py tests/honeyos/test_feishu_adapter.py tests/honeyos/test_permission_migration.py tests/honeyos/test_permission_end_to_end.py`

Expected: all tests pass.

- [ ] **Step 7: Run broader regression suites**

Run: `pytest -q tests/honeyos/test_projects.py tests/honeyos/test_execute_code_approval.py tests/honeyos/test_continuity_gateway.py tests/honeyos/test_config.py tests/honeyos/test_doctor.py tests/honeyos/test_companion_config.py`

Expected: all tests pass.

- [ ] **Step 8: Run product smoke tests**

Start the installed HoneyOS gateway and verify:

1. Create and run a small HTML game under HoneyOS Projects without a prompt.
2. Read a public API without a prompt.
3. Attempt an unrequested cross-chat message and resolve the companion card in Feishu.
4. Expand technical detail and confirm secrets are redacted.
5. Attempt a HoneyOS secret read and confirm no Continue button exists.
6. Restart the gateway and confirm memory plus the existing Feishu conversation remain intact.

- [ ] **Step 9: Commit migration and verification**

```bash
git add honeyos/companion/config.py honeyos/tools/approval.py honeyos/runtime/observability/relay_shared_metrics.py tests/honeyos/test_permission_migration.py tests/honeyos/test_companion_config.py tests/honeyos/test_permission_end_to_end.py
git commit -m "test: verify companion permission migration and flows"
```

- [ ] **Step 10: Review the final branch diff**

Run: `git status --short && git diff --check origin/main...HEAD && git log --oneline --decorate -8`

Expected: only intended source, tests and documentation changes; no whitespace errors; the five implementation commits are present.
