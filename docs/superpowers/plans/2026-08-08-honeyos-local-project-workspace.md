# HoneyOS Local Project Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace HoneyOS's mandatory Docker coding backend with a real, user-visible local project workspace while preserving all companion data and recovering prior container projects.

**Architecture:** A focused `honeyos.companion.projects` module owns project-root resolution, creation, and one-time legacy workspace recovery. Companion configuration points the existing local terminal/code runtime at that root and re-enables dangerous-command approvals; doctor and prompt layers describe and verify the new contract without changing memory storage.

**Tech Stack:** Python 3.11+, pathlib/shutil, YAML configuration, existing HoneyOS local terminal and approval runtime, pytest.

## Global Constraints

- Default project root is exactly `~/HoneyOS Projects` unless `HONEYOS_PROJECTS_HOME` is explicitly set.
- Normal project commands run without confirmation; dangerous commands use `approvals.mode: manual` and hardline commands remain blocked.
- No file under `~/.honeyos/memories`, `sessions`, `skills`, or channel/model configuration may be removed or overwritten by project migration.
- Legacy recovery copies data and never deletes the source under `~/.honeyos/sandboxes/docker`.
- Docker remains an optional upstream backend but is not required by the HoneyOS companion profile.
- No new third-party dependency is introduced.

---

### Task 1: Project root and local companion configuration

**Files:**
- Create: `honeyos/companion/projects.py`
- Modify: `honeyos/companion/config.py`
- Test: `tests/honeyos/test_projects.py`
- Test: `tests/honeyos/test_config.py`

**Interfaces:**
- Produces: `project_root() -> Path` and `ensure_project_root() -> Path`.
- Consumed by: companion initialization, upgrades, doctor, prompt tests, and Task 2 recovery.

- [ ] **Step 1: Write failing tests**

Add tests which set `HONEYOS_PROJECTS_HOME` to a temporary path and assert initialization creates it, writes `terminal.backend == "local"`, writes the absolute `terminal.cwd`, preserves an empty passthrough list, and sets `approvals.mode == "manual"`. Extend the upgrade test to snapshot `SOUL.md`, `memories`, provider and IM fields and assert they remain byte-for-byte unchanged.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_projects.py tests/honeyos/test_config.py`

Expected: failures showing the projects module is missing and the current backend is `docker`.

- [ ] **Step 3: Implement the minimum project module and config switch**

Implement:

```python
PROJECTS_ENV = "HONEYOS_PROJECTS_HOME"
DEFAULT_PROJECTS_DIR = "HoneyOS Projects"

def project_root() -> Path:
    configured = os.environ.get(PROJECTS_ENV, "").strip()
    return Path(configured).expanduser().resolve() if configured else Path.home() / DEFAULT_PROJECTS_DIR

def ensure_project_root() -> Path:
    root = project_root()
    root.mkdir(parents=True, exist_ok=True)
    return root
```

Call it from `initialize_home` and `upgrade_companion_capabilities`; configure local backend/cwd, empty secret passthrough, and manual dangerous approval.

- [ ] **Step 4: Run focused tests and commit**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_projects.py tests/honeyos/test_config.py`

Expected: all selected tests pass.

Commit: `feat: run HoneyOS projects in a local workspace`

### Task 2: Recover old Docker project files without touching memory

**Files:**
- Modify: `honeyos/companion/projects.py`
- Modify: `honeyos/companion/config.py`
- Test: `tests/honeyos/test_projects.py`

**Interfaces:**
- Produces: `RecoveryResult` and `recover_legacy_projects(home: Path, destination: Path | None = None) -> RecoveryResult`.
- Consumes: `project_root()` from Task 1.

- [ ] **Step 1: Write failing recovery tests**

Build temporary `sandboxes/docker/default/workspace/game/index.html` and `home/notes.txt`, plus hidden cache data. Assert recovery copies visible content into `从旧版本恢复/default`, leaves source files untouched, skips hidden home entries, never enters `memories`, refuses to overwrite a destination collision, and returns no copies on a second call.

- [ ] **Step 2: Run recovery tests to verify failure**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_projects.py -k recovery`

Expected: failures because `recover_legacy_projects` does not exist.

- [ ] **Step 3: Implement idempotent copy-only recovery**

Use `Path.iterdir`, `shutil.copytree(..., dirs_exist_ok=False)` and `shutil.copy2`; copy workspace entries plus non-hidden home entries. Record a JSON marker under `~/.honeyos/.local-project-recovery-v1.json` only after each source task succeeds. Catch per-entry filesystem errors into `RecoveryResult.errors` and do not delete or rename source paths.

- [ ] **Step 4: Integrate recovery and commit**

Call recovery during `upgrade_companion_capabilities` after project-root creation. Recovery diagnostics must not abort configuration or startup.

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_projects.py tests/honeyos/test_config.py`

Expected: all selected tests pass.

Commit: `feat: recover legacy container projects`

### Task 3: Prompt, doctor, and startup contract

**Files:**
- Modify: `honeyos/agent/prompt_builder.py`
- Modify: `honeyos/companion/doctor.py`
- Modify: `honeyos/companion/health.py`
- Test: `tests/honeyos/test_companion_prompt.py`
- Test: `tests/honeyos/test_doctor.py`
- Test: relevant health tests located by `rg -n "Docker.*隔离代码" tests/honeyos`

**Interfaces:**
- Consumes: `project_root()` and config fields created in Task 1.
- Produces: user-facing environment guidance and diagnostics for local coding.

- [ ] **Step 1: Write failing contract tests**

Assert the companion prompt says commands run on the user's computer inside the HoneyOS project workspace, requires deliverables to be stored there, and no longer claims an isolated container. Assert doctor accepts only `local` plus the expected writable project cwd and rejects `approvals.mode: off`. Assert health no longer marks missing Docker as loss of code execution.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_companion_prompt.py tests/honeyos/test_doctor.py`

Expected: current container wording and sandbox-backend check fail.

- [ ] **Step 3: Update prompt and diagnostics**

Replace `COMPANION_ENVIRONMENT_GUIDANCE` with local-project wording. Rename doctor check `sandbox-backend` to `project-workspace`, validate resolved cwd equals the managed root and is writable, then add an `execution-approval` check requiring `manual` or `smart`. Change Docker health output to an optional advanced-isolation note only.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_companion_prompt.py tests/honeyos/test_doctor.py`

Expected: all selected tests pass.

Commit: `fix: describe and diagnose local project execution`

### Task 4: User documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `tests/install/test_honeyos_zip.sh` only if release assertions require the project-workspace contract.

**Interfaces:**
- Consumes: final behavior from Tasks 1–3.
- Produces: installation and upgrade guidance for users.

- [ ] **Step 1: Update README**

Describe `~/HoneyOS Projects`, real host coding, project-local dependencies, optional Docker, old-project recovery, and the guarantee that `~/.honeyos` memory is preserved.

- [ ] **Step 2: Run focused and full verification**

Run:

```bash
git diff --check
sh -n scripts/install_honeyos.sh tests/install/test_honeyos_zip.sh
.venv/bin/python -m pytest -q tests/honeyos
```

Expected: no whitespace/shell errors and zero pytest failures.

- [ ] **Step 3: Verify real local execution**

With temporary HOME and `HONEYOS_PROJECTS_HOME`, initialize HoneyOS, execute a terminal command that writes `demo/index.html`, and assert the host process can read that exact file. Run a known hardline command through the approval detector and assert it remains blocked; do not execute the destructive command.

- [ ] **Step 4: Commit**

Commit: `docs: explain visible HoneyOS project workspace`
