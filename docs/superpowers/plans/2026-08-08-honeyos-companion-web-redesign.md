# HoneyOS Companion Web Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build a polished private-companion web chat that immediately communicates presence, safely renders grouped tool activity, and never exposes raw reasoning or tool details.

**Architecture:** Keep the Python gateway and native browser assets. Extend the existing SSE projection with stable safe activity identifiers and a presence event, then replace the one-card DOM logic with a small turn-state controller and companion-specific components. Preserve the shared web/Feishu session and all loopback security boundaries.

**Tech Stack:** Python 3, aiohttp, pytest, native HTML/CSS/JavaScript, Server-Sent Events, optional Node.js for reducer tests.

## Global Constraints

- Do not install AI Elements, assistant-ui, CopilotKit, React, or a frontend build chain.
- Never send raw reasoning, commands, paths, tool arguments, credentials, or raw tool results to the companion renderer.
- Web and Feishu keep sharing agent:main:companion:dm:owner.
- Show safe presence feedback within 150ms unless assistant text has started.
- Skip transient process UI when direct text starts within 500ms.
- Use one grouped ActionTrail per assistant turn.
- Follow system light/dark preference and prefers-reduced-motion.
- Keep loopback-only serving, HttpOnly local cookie, current CSP, and no-account operation.

---

## File Structure

- Modify honeyos/companion/activity.py: safe presence and tool projections.
- Modify honeyos/gateway/platforms/api_server.py: projected SSE events, static routes, cache policy.
- Create honeyos/companion/web_assets/run-state.js: deterministic per-turn state transitions.
- Modify honeyos/companion/web_assets/app.js: browser I/O, DOM rendering, SSE, input.
- Modify honeyos/companion/web_assets/index.html: semantic companion chat structure.
- Modify honeyos/companion/web_assets/styles.css: responsive visual system.
- Modify honeyos/companion/web_assets/file-open.js: direct-file recovery.
- Modify tests/honeyos/test_companion_web.py: Python and asset contracts.
- Create tests/honeyos/test_companion_web_state.py: reducer tests via Node.js.

---

### Task 1: Safe Presence and Stable Activity Events

**Files:**
- Modify: honeyos/companion/activity.py
- Modify: honeyos/gateway/platforms/api_server.py:3925-3970
- Test: tests/honeyos/test_companion_web.py

**Interfaces:**
- Produces: project_presence(preview: str | None = None) -> dict[str, str]
- Produces: project_activity(event_type: str, tool_name: str | None, *, activity_id: str | None = None, preview: str | None = None, args: Any = None) -> dict[str, str]
- Preserves: non-companion SSE clients retain their existing raw fields.

- [ ] **Step 1: Write the failing projection tests**

~~~python
from honeyos.companion.activity import project_activity, project_presence

def test_presence_projection_never_contains_reasoning():
    presence = project_presence(preview="private chain of thought")
    assert presence == {
        "activity_id": "presence",
        "kind": "presence",
        "state": "active",
        "title": "我在想你刚才说的事",
        "detail": "",
    }
    assert "private" not in str(presence)

def test_activity_projection_keeps_only_opaque_identifier():
    activity = project_activity(
        "tool.started",
        "web_search",
        activity_id="activity_3",
        preview="curl https://secret.example",
        args={"api_key": "sk-secret"},
    )
    assert activity["activity_id"] == "activity_3"
    assert set(activity) == {"activity_id", "kind", "state", "title", "detail"}
    assert "web_search" not in str(activity)
    assert "secret" not in str(activity)
~~~

- [ ] **Step 2: Run tests and verify failure**

Run:

~~~bash
pytest tests/honeyos/test_companion_web.py -k "presence_projection or opaque_identifier" -v
~~~

Expected: import or assertion failure because project_presence and activity_id do not exist.

- [ ] **Step 3: Implement safe projections**

Add project_presence, discard its preview, add activity_id to project_activity, and preserve the existing kind-specific copy. Update __all__ to export both functions. The payload must contain only the five keys asserted above.

- [ ] **Step 4: Emit projected lifecycle events**

Inside _handle_session_chat_stream, add activity_seq and active_activity_ids: Dict[str, List[str]]. Allocate activity_N on tool.started and pop the matching per-tool FIFO on completed/failed. For companion requests:

~~~python
if event_type == "reasoning.available":
    _enqueue("presence.updated", {
        "message_id": message_id,
        "activity": project_presence(preview=preview),
    })
elif event_type in {"tool.started", "tool.completed", "tool.failed"}:
    payload["activity"] = project_activity(
        event_type,
        tool_name,
        activity_id=activity_id,
        preview=preview,
        args=args,
    )
~~~

Never place reasoning preview in the companion payload.

- [ ] **Step 5: Run companion gateway tests**

~~~bash
pytest tests/honeyos/test_companion_web.py -v
~~~

Expected: all tests pass.

- [ ] **Step 6: Commit**

~~~bash
git add honeyos/companion/activity.py honeyos/gateway/platforms/api_server.py tests/honeyos/test_companion_web.py
git commit -m "feat: stream safe companion activity states"
~~~

---

### Task 2: Deterministic Turn State Controller

**Files:**
- Create: honeyos/companion/web_assets/run-state.js
- Create: tests/honeyos/test_companion_web_state.py
- Modify: honeyos/gateway/platforms/api_server.py:2038-2170
- Modify: tests/honeyos/test_companion_web.py

**Interfaces:**
- Produces: HoneyOSRunState.create(now) -> TurnState
- Produces: HoneyOSRunState.reduce(state, event, now) -> TurnState
- TurnState.phase is idle, present, acting, responding, completed, or failed.

- [ ] **Step 1: Write a failing Node-backed reducer test**

~~~python
import json
import shutil
import subprocess
from pathlib import Path
import pytest

NODE = shutil.which("node")
ASSET = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets" / "run-state.js"

@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_turn_state_groups_presence_tools_and_response():
    script = f"""
global.window = global;
require({json.dumps(str(ASSET))});
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {{name:'run.started', payload:{{}}}}, 1000);
state = HoneyOSRunState.reduce(state, {{name:'tool.started', payload:{{activity:{{activity_id:'a1',kind:'checking',state:'active',title:'我去替你认真看看',detail:''}}}}}}, 1100);
state = HoneyOSRunState.reduce(state, {{name:'tool.completed', payload:{{activity:{{activity_id:'a1',kind:'checking',state:'completed',title:'找到了，我整理一下',detail:''}}}}}}, 1400);
state = HoneyOSRunState.reduce(state, {{name:'assistant.delta', payload:{{delta:'找'}}}}, 1600);
process.stdout.write(JSON.stringify(state));
"""
    result = subprocess.run([NODE, "-e", script], check=True, text=True, capture_output=True)
    state = json.loads(result.stdout)
    assert state["phase"] == "responding"
    assert state["activities"][0]["activity_id"] == "a1"
    assert state["activities"][0]["state"] == "completed"
~~~

- [ ] **Step 2: Run and verify failure**

~~~bash
pytest tests/honeyos/test_companion_web_state.py -v
~~~

Expected: FAIL because run-state.js is missing.

- [ ] **Step 3: Implement immutable transitions**

~~~javascript
(function attachRunState(root) {
  function create(now) {
    return { phase: "idle", startedAt: now, content: "", activities: [], error: "" };
  }
  function upsertActivity(activities, next) {
    const index = activities.findIndex((item) => item.activity_id === next.activity_id);
    if (index < 0) return [...activities, next];
    return activities.map((item, i) => i === index ? next : item);
  }
  function reduce(state, event, now) {
    const payload = event.payload || {};
    if (event.name === "run.started") return { ...create(now), phase: "present" };
    if (event.name === "presence.updated" && state.phase !== "responding") {
      return { ...state, phase: "present", presence: payload.activity || null };
    }
    if (event.name.startsWith("tool.") && payload.activity) {
      return { ...state, phase: "acting", activities: upsertActivity(state.activities, payload.activity) };
    }
    if (event.name === "assistant.delta") {
      return { ...state, phase: "responding", content: state.content + (payload.delta || "") };
    }
    if (event.name === "assistant.completed") {
      return { ...state, phase: "completed", content: payload.content || state.content };
    }
    if (event.name === "error") return { ...state, phase: "failed", error: payload.message || "" };
    return state;
  }
  root.HoneyOSRunState = Object.freeze({ create, reduce });
})(typeof window === "undefined" ? globalThis : window);
~~~

- [ ] **Step 4: Serve and package the script**

Register GET /honeyos/run-state.js, add a handler through _handle_companion_asset, assert the route and file in test_companion_web.py, and change companion static asset caching to no-cache so a restarted installation cannot keep old CSS/JS.

- [ ] **Step 5: Run reducer and route tests**

~~~bash
pytest tests/honeyos/test_companion_web_state.py tests/honeyos/test_companion_web.py -v
~~~

Expected: all pass; reducer test skips only when Node.js is absent.

- [ ] **Step 6: Commit**

~~~bash
git add honeyos/companion/web_assets/run-state.js honeyos/gateway/platforms/api_server.py tests/honeyos/test_companion_web.py tests/honeyos/test_companion_web_state.py
git commit -m "feat: add companion turn state controller"
~~~

---

### Task 3: Companion Conversation Rendering

**Files:**
- Modify: honeyos/companion/web_assets/index.html
- Modify: honeyos/companion/web_assets/app.js
- Modify: tests/honeyos/test_companion_web.py

**Interfaces:**
- Consumes: HoneyOSRunState from Task 2.
- Consumes: projected payload.activity from Task 1.
- Produces: one presence line, one action trail, and one streaming assistant message per turn.

- [ ] **Step 1: Write failing semantic asset tests**

~~~python
def test_companion_assets_define_relationship_native_run_ui():
    assets = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets"
    index = (assets / "index.html").read_text(encoding="utf-8")
    app = (assets / "app.js").read_text(encoding="utf-8")
    assert 'src="./run-state.js"' in index
    assert 'id="presence-line"' in index
    assert 'id="action-trail"' in index
    assert "activityTimer" not in app
    assert "ACTIVITY_DELAY_MS" not in app
~~~

- [ ] **Step 2: Run and verify failure**

~~~bash
pytest tests/honeyos/test_companion_web.py::test_companion_assets_define_relationship_native_run_ui -v
~~~

Expected: FAIL because the new structure is absent and the old delay remains.

- [ ] **Step 3: Replace the semantic page structure**

Use relative assets and this hierarchy while preserving existing profile and composer IDs:

~~~html
<main class="companion-app" aria-label="HoneyOS 私人聊天">
  <section class="conversation" aria-live="polite">
    <header class="companion-header">
      <div class="avatar" id="avatar" aria-hidden="true">H</div>
      <div class="identity">
        <h1 id="companion-name">Honey</h1>
        <p id="companion-status">在这儿</p>
      </div>
    </header>
    <div class="messages" id="messages">
      <div class="empty-state" id="empty-state">
        <p>想说什么都可以。</p>
        <span>我在这儿听着。</span>
      </div>
    </div>
    <div class="turn-status" id="turn-status" hidden>
      <div class="presence-line" id="presence-line" hidden></div>
      <div class="action-trail" id="action-trail" hidden></div>
    </div>
    <form class="composer" id="composer">
      <label class="sr-only" for="message-input">消息</label>
      <textarea id="message-input" rows="1" maxlength="12000" placeholder="和我说句话"></textarea>
      <button class="send-button" id="send-button" type="submit">发送</button>
    </form>
  </section>
</main>
<script src="./run-state.js"></script>
<script src="./app.js" defer></script>
~~~

- [ ] **Step 4: Render the reducer state**

Remove activityTimer, pendingActivity, and activeActivity. Feed every parsed SSE event to HoneyOSRunState.reduce. renderTurnState must show PresenceLine in present, one grouped ActionTrail in acting, collapse process UI in responding/completed, and show a retryable inline error in failed. It must never read preview, args, tool_name, or raw reasoning fields.

- [ ] **Step 5: Add scroll ownership**

Auto-scroll only when the user is within 80px of the bottom or just sent a message. Show a scroll-to-latest button otherwise. Listen to the messages element, not window scroll.

- [ ] **Step 6: Run asset and reducer tests**

~~~bash
pytest tests/honeyos/test_companion_web.py tests/honeyos/test_companion_web_state.py -v
~~~

Expected: all pass.

- [ ] **Step 7: Commit**

~~~bash
git add honeyos/companion/web_assets/index.html honeyos/companion/web_assets/app.js tests/honeyos/test_companion_web.py
git commit -m "feat: render companion presence and action trail"
~~~

---

### Task 4: Private Chat Room Visual Redesign

**Files:**
- Modify: honeyos/companion/web_assets/styles.css
- Modify: honeyos/companion/web_assets/index.html
- Test: tests/honeyos/test_companion_web.py

**Interfaces:**
- Consumes: semantic classes from Task 3.
- Produces: full-window desktop chat, mobile fallback, light/dark tokens, reduced-motion fallback.

- [ ] **Step 1: Write a failing visual contract test**

~~~python
def test_companion_styles_are_full_window_and_accessible():
    css = (Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets" / "styles.css").read_text(encoding="utf-8")
    assert ".companion-app" in css
    assert ".presence-line" in css
    assert ".action-trail" in css
    assert "prefers-color-scheme: dark" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "width: min(100%, 460px)" not in css
    assert "linear-gradient(145deg, var(--ambient-a), var(--ambient-b))" not in css
~~~

- [ ] **Step 2: Run and verify failure**

~~~bash
pytest tests/honeyos/test_companion_web.py::test_companion_styles_are_full_window_and_accessible -v
~~~

Expected: FAIL because old phone-card CSS remains.

- [ ] **Step 3: Implement the visual system**

Use semantic tokens for canvas, conversation surface, primary/muted text, border, muted berry accent, user message, action surface, error, and tinted shadow. Provide matching dark tokens. Do not use AI-purple, generic glass cards, or a large gradient backdrop.

- [ ] **Step 4: Implement responsive composition**

Desktop uses min-height: 100dvh and a roughly 760px readable conversation column without a floating phone frame. Assistant text is unboxed, user messages use compact tinted bubbles, and ActionTrail is quiet inline status. Below 700px collapse to one column with safe-area composer padding and 44px minimum touch targets.

- [ ] **Step 5: Add motivated motion and focus**

Animate only opacity and translateY for message arrival and state transitions. Use a subtle breathing state only while active. Disable automatic motion for prefers-reduced-motion. Add visible AA-contrast focus states.

- [ ] **Step 6: Run visual contract tests**

~~~bash
pytest tests/honeyos/test_companion_web.py -k "styles_are_full_window or assets_define" -v
~~~

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add honeyos/companion/web_assets/index.html honeyos/companion/web_assets/styles.css tests/honeyos/test_companion_web.py
git commit -m "feat: redesign companion web as a private chat room"
~~~

---

### Task 5: File-Open and Provider Recovery

**Files:**
- Modify: honeyos/companion/web_assets/file-open.js
- Modify: honeyos/companion/web_assets/app.js
- Modify: honeyos/companion/web_assets/index.html
- Test: tests/honeyos/test_companion_web.py

**Interfaces:**
- Produces: styled file-mode fallback and redirect to http://127.0.0.1:8642/.
- Produces: normalizeError(message) returning safe Chinese copy.

- [ ] **Step 1: Write failing recovery tests**

~~~python
def test_file_mode_and_provider_recovery_have_human_copy():
    assets = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets"
    index = (assets / "index.html").read_text(encoding="utf-8")
    app = (assets / "app.js").read_text(encoding="utf-8")
    assert 'id="file-mode-notice"' in index
    assert "打开 HoneyOS" in index
    assert "honeyos setup" in app
    assert "No LLM provider configured" not in index
~~~

- [ ] **Step 2: Run and verify failure**

~~~bash
pytest tests/honeyos/test_companion_web.py::test_file_mode_and_provider_recovery_have_human_copy -v
~~~

Expected: FAIL because recovery UI is absent.

- [ ] **Step 3: Add file-mode fallback**

Load styles.css, run-state.js, and app.js with relative URLs. Add a hidden notice saying “HoneyOS 还没有启动。启动后点这里打开聊天。” file-open.js attempts window.location.replace, then reveals the notice after 800ms if the page remains on file protocol.

- [ ] **Step 4: Normalize expected errors**

Map No LLM provider configured to “还差一步模型配置，配置好我们就能说话了。” plus “请在终端运行 honeyos setup”. Map provider authentication and retry exhaustion to short Chinese recovery copy. Unknown errors get a generic message and never render raw provider details.

- [ ] **Step 5: Run recovery and security tests**

~~~bash
pytest tests/honeyos/test_companion_web.py -v
~~~

Expected: all pass.

- [ ] **Step 6: Commit**

~~~bash
git add honeyos/companion/web_assets/file-open.js honeyos/companion/web_assets/app.js honeyos/companion/web_assets/index.html tests/honeyos/test_companion_web.py
git commit -m "fix: guide local companion setup failures"
~~~

---

### Task 6: Full Verification and Local Acceptance

**Files:**
- Modify only if verification finds a defect in files already listed.

**Interfaces:**
- Verifies Python contracts, JavaScript transitions, packaging, security, real SSE, shared history, both themes, and process rendering.

- [ ] **Step 1: Run focused tests**

~~~bash
pytest tests/honeyos/test_companion_web.py tests/honeyos/test_companion_web_state.py -v
~~~

Expected: all pass; Node tests skip only when Node.js is unavailable.

- [ ] **Step 2: Run the complete HoneyOS slice**

~~~bash
pytest tests/honeyos -q
~~~

Expected: all tests pass with no new failures.

- [ ] **Step 3: Run lint and diff checks**

~~~bash
ruff check honeyos/companion/activity.py honeyos/gateway/platforms/api_server.py tests/honeyos/test_companion_web.py tests/honeyos/test_companion_web_state.py
git diff --check
~~~

Expected: both commands exit 0.

- [ ] **Step 4: Restart local HoneyOS**

Run uv run honeyos start from the repository root. Confirm http://127.0.0.1:8642/health returns HTTP 200, then run uv run honeyos web to open the page.

- [ ] **Step 5: Verify a direct companion turn**

Send “你好，今天有点累”. Confirm immediate presence feedback, no tool trail, streamed companion response, and shared history after refresh.

- [ ] **Step 6: Verify a real tool turn**

Send “帮我查一下今天上海的天气，再提醒我晚上带伞”. Confirm one ActionTrail transitions through checking and remembering, raw tool names never appear, and the final reply stays in persona.

- [ ] **Step 7: Verify failure recovery**

Run pytest tests/honeyos/test_companion_web.py::test_file_mode_and_provider_recovery_have_human_copy -v and confirm it passes. Do not replace the user's working provider during live acceptance.

- [ ] **Step 8: Check themes and reduced motion**

Verify light, dark, and reduced-motion preferences. Confirm messages, placeholders, controls, errors, and process copy remain readable.

- [ ] **Step 9: Review final scope**

~~~bash
git status --short
git diff --stat
~~~

Expected: only planned companion web files changed. Commit any verification fix with:

~~~bash
git add honeyos/companion honeyos/gateway/platforms/api_server.py tests/honeyos
git commit -m "test: verify companion web experience"
~~~
