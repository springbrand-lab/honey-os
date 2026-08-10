# HoneyOS Claude-style Component Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rough HoneyOS companion web presentation with a cohesive Claude-inspired component system while preserving every existing chat, memory, topic, permission, and profile API.

**Architecture:** Use a compatibility-first migration inside the packaged static web client: keep the existing API/SSE controller, introduce semantic component markup and small rendering helpers, then replace the legacy style cascade with a tokenized component stylesheet. This produces the approved UI immediately without adding Node.js to end-user installation; the resulting component boundaries remain suitable for a later React build if the product needs it.

**Tech Stack:** Semantic HTML, modular browser JavaScript, CSS custom properties, existing Python gateway and pytest asset-contract tests.

## Global Constraints

- Keep all HoneyOS user data, memory, personality, model, and channel configuration unchanged.
- Keep the existing warm-neutral palette and use one restrained orange accent.
- Default to deterministic letter avatars; do not generate random human faces.
- Keep current HTTP, SSE, memory, permission, topic-pool, and file-opening APIs unchanged.
- Ship static assets inside the Python package so users do not need Node.js.
- Cover desktop, tablet, and mobile layouts and reduced-motion preferences.

---

### Task 1: Lock the visual component contract with tests

**Files:**
- Modify: `tests/honeyos/test_companion_web_assets.py`

**Interfaces:**
- Consumes: packaged assets from `honeyos/companion/web_assets/`.
- Produces: assertions for semantic avatar fallbacks, icon assets, component classes, tool disclosure, and composer controls.

- [ ] **Step 1: Add failing asset-contract tests**

Add assertions that the page provides stable avatar labels and icon hooks, the script updates all avatar surfaces through one helper, and the stylesheet defines the new message, tool-card, composer, focus, responsive, dark-mode, and reduced-motion states.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest -q tests/honeyos/test_companion_web_assets.py`

Expected: failures for the new component hooks before implementation.

- [ ] **Step 3: Commit the contract test**

Run: `git add tests/honeyos/test_companion_web_assets.py && git commit -m "test(companion): define polished web component contract"`

### Task 2: Replace placeholder glyphs and unify avatar rendering

**Files:**
- Modify: `honeyos/companion/web_assets/index.html`
- Modify: `honeyos/companion/web_assets/app.js`
- Create: `honeyos/companion/web_assets/icons.svg`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `companion_name` and existing profile bootstrap data.
- Produces: `setAvatarLabel(name)` and semantic `<svg><use href="./icons.svg#..."></use></svg>` icon surfaces.

- [ ] **Step 1: Add a packaged SVG symbol sheet**

Create a same-origin icon sheet containing the required navigation, chat action, composer, topic, status, and disclosure symbols with a single stroke language.

- [ ] **Step 2: Replace text glyphs with accessible icon buttons**

Keep visible Chinese labels and `aria-label` values, but replace decorative characters such as `◌`, `◇`, `⌁`, `＋`, and `◖` with icon references.

- [ ] **Step 3: Centralize deterministic letter-avatar updates**

Implement `avatarLabel(name, fallback)` and `setAvatarLabel(name)` so header, message, status, and relationship surfaces always show the same stable character.

- [ ] **Step 4: Include nested/static SVG assets in the package**

Update package data only as needed for `icons.svg`; do not add a frontend runtime dependency.

- [ ] **Step 5: Run focused tests**

Run: `pytest -q tests/honeyos/test_companion_web_assets.py tests/honeyos/test_companion_web.py`

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run: `git add honeyos/companion/web_assets/index.html honeyos/companion/web_assets/app.js honeyos/companion/web_assets/icons.svg pyproject.toml && git commit -m "feat(companion): unify avatars and interface icons"`

### Task 3: Build the Claude-inspired message and tool components

**Files:**
- Modify: `honeyos/companion/web_assets/index.html`
- Modify: `honeyos/companion/web_assets/app.js`
- Modify: `honeyos/companion/web_assets/run-state.js`
- Modify: `honeyos/companion/web_assets/message-format.js`
- Modify: `tests/honeyos/test_companion_web_state.py`
- Modify: `tests/honeyos/test_companion_message_format.py`

**Interfaces:**
- Consumes: existing SSE events and `HoneyOSRunState` projections.
- Produces: one collapsible `.activity-card` per run, stable message action rows, and polished Markdown content.

- [ ] **Step 1: Add failing rendering/state tests**

Assert that repeated completed events receive distinct humanized labels, the activity summary exposes running/success/failure states, and rendered Markdown strips raw emphasis markers while preserving lists and code.

- [ ] **Step 2: Implement a single collapsible activity component**

Render the run summary as a native disclosure with a compact title, state icon, step count, and detailed step list. Keep permission content deterministic and separate inside the same activity region.

- [ ] **Step 3: Add message hover actions and semantic content wrappers**

Provide copy/retry/feedback buttons with hidden-by-default visual treatment and keyboard focus access. Do not expose internal chain-of-thought.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/honeyos/test_companion_web_state.py tests/honeyos/test_companion_message_format.py tests/honeyos/test_companion_web_assets.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run: `git add honeyos/companion/web_assets tests/honeyos/test_companion_web_state.py tests/honeyos/test_companion_message_format.py tests/honeyos/test_companion_web_assets.py && git commit -m "feat(companion): polish messages and activity cards"`

### Task 4: Replace the legacy visual cascade with a component stylesheet

**Files:**
- Modify: `honeyos/companion/web_assets/styles.css`

**Interfaces:**
- Consumes: semantic classes introduced in Tasks 2 and 3.
- Produces: tokenized shell, navigation, header, message, Markdown, activity, composer, drawer, memory, relationship, history, and settings components.

- [ ] **Step 1: Define page-level design tokens and geometry rules**

Define light/dark semantic variables for canvas, surfaces, lines, text, accent, user message, success, warning, and danger. Lock the radius scale and maximum reading widths.

- [ ] **Step 2: Implement the app shell and navigation components**

Use a compact 232px sidebar on desktop, a 72px collapsed rail on medium screens, and bottom navigation on mobile. Keep focus rings visible and icon strokes consistent.

- [ ] **Step 3: Implement message, Markdown, activity, and composer components**

Use unboxed assistant prose, compact right-aligned user bubbles, 30px avatars, a bordered disclosure for activity, and an auto-growing floating composer with attachment and send/stop controls.

- [ ] **Step 4: Apply the same design system to secondary pages**

Restyle memory cards, relationship form, history split view, settings rows, topic drawer, empty states, errors, and permission cards with the shared tokens and geometry.

- [ ] **Step 5: Add accessibility and responsive states**

Cover `:focus-visible`, hover-capable pointers, dark mode, `prefers-reduced-motion`, 1024px, 768px, and phone widths.

- [ ] **Step 6: Run focused tests**

Run: `pytest -q tests/honeyos/test_companion_web_assets.py tests/honeyos/test_companion_web.py`

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run: `git add honeyos/companion/web_assets/styles.css && git commit -m "feat(companion): ship cohesive Claude-style visual system"`

### Task 5: Verify, install locally, and perform browser acceptance

**Files:**
- Modify only if verification finds a concrete defect in the files above.

**Interfaces:**
- Consumes: complete packaged web assets.
- Produces: a locally running HoneyOS build at `http://127.0.0.1:8642/` ready for user acceptance.

- [ ] **Step 1: Run the full relevant test set**

Run: `pytest -q tests/honeyos/test_companion_web_assets.py tests/honeyos/test_companion_web_state.py tests/honeyos/test_companion_message_format.py tests/honeyos/test_companion_web.py tests/honeyos/test_persistent_memory_cards.py`

Expected: all tests pass.

- [ ] **Step 2: Run package and diff checks**

Run: `python -m build --wheel` when the build module is available, then inspect the wheel for all companion assets. Run `git diff --check` and confirm only intended files changed.

- [ ] **Step 3: Restart the local HoneyOS service**

Use the repository's existing install/service commands so the local profile and user data remain untouched.

- [ ] **Step 4: Visually inspect key states**

Verify empty chat, existing history, user and assistant messages, long Markdown, running and completed tool activity, permission card, memories, relationship, history, settings, topic drawer, dark mode, and mobile width.

- [ ] **Step 5: Run a final regression suite**

Run: `pytest -q tests/honeyos/test_companion_web_assets.py tests/honeyos/test_companion_web_state.py tests/honeyos/test_companion_message_format.py tests/honeyos/test_companion_web.py tests/honeyos/test_persistent_memory_cards.py`

Expected: all tests pass after local installation.

- [ ] **Step 6: Commit final fixes if any**

Commit only verified follow-up fixes with a scoped `fix(companion): ...` message.

