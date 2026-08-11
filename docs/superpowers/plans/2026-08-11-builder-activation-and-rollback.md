# HoneyOS Builder Activation and Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an owner approve a reviewed HoneyOS Builder candidate, switch the managed local runtime to an immutable version slot, restart automatically, and roll back code and data when health checks fail.

**Architecture:** Extend PR #25 with a trusted activation control plane that never imports candidate code. It stages reviewed source into private version slots, issues candidate-bound single-use confirmations, and hands service switching to a detached worker. Existing `HONEYOS_HOME` remains the data plane; service executables move between version slots and the legacy install.

**Tech Stack:** Python 3.11+, pathlib, JSON/JSONL state, SHA-256, `venv`/`uv`, existing HoneyOS gateway service managers, existing SQLite-safe backup helpers, pytest, Ruff.

## Global Constraints

- Self-improvement is enabled by default only for the canonical owner DM.
- Every core activation requires a fresh, candidate-specific confirmation; “always allow” is not supported.
- Normal Skill installation remains immediate and does not restart core HoneyOS.
- Candidate code never modifies the trusted Builder activation, approval, auth, backup, filesystem-safety, or service-switch control plane. Activation eligibility is controlled by a fixed, running-code-owned companion product allowlist; all host agent-loop, gateway, runtime, tool-dispatch, CLI, core, provider, and plugin paths are protected. Before activation, the trusted control plane never imports or executes candidate code.
- Same-user OS state is not a sandbox. The task manifest and trusted-policy record bind/restrict a requested change for audit and UX, but cannot expand the static activation surface even if both are altered.
- Candidate code is untrusted until the owner confirms one exact digest. That
  confirmation promotes it to the trusted local application, which necessarily
  runs with HoneyOS's data/tool capabilities. The controls here prevent
  accidental boundary edits and deployment failure; they do not claim to
  sandbox intentionally malicious same-user code after activation.
- Credential/channel binding, profile redaction, permission and model-control
  routing, delivery routing, bundled Skill instructions, and prompt templates
  remain protected in release 1.
- Host Runtime, gateway/IM adapters, agent loop, tool dispatch, CLI, provider,
  plugin, migration, and service code are developer-release changes in release
  1 and cannot be locally self-activated.
- Candidate dependency/build changes (`pyproject.toml`, `uv.lock`, installers, release scripts) are blocked in this release.
- `SOUL.md`, identity, relationship, memories, `state.db`, credentials, channel bindings, Skills, cron jobs, UI overlays, and projects remain under the existing `HONEYOS_HOME` and are never overlaid by a slot.
- No GitHub account, push, branch merge, or PR is part of local activation.
- Automatic rollback restores the pre-switch SQLite-safe snapshot; later manual rollback never silently restores an old snapshot over newer conversations.
- All manifests, tokens, pointers, receipts, and journals are atomic and mode `0600`; directories are mode `0700`.
- No candidate activation may run from a group lane, background job, stale confirmation, changed digest, or mismatched live base revision.

---

## File and interface map

- Create `honeyos/companion/builder_activation.py`: trusted slot, digest, confirmation, state-machine, and receipt store.
- Create `honeyos/runtime/builder_activation_worker.py`: detached switch, health, rollback, and recovery logic.
- Create `honeyos/tools/companion_builder_tool.py`: owner-DM model interface for inspect/stage/request/confirm/status; no raw install command.
- Modify `honeyos/companion/builder_workspace.py`: protect activation and dependency surfaces; bind reviews to candidate digests.
- Modify `honeyos/runtime/builder_cmd.py`: trusted operator status/recovery commands only; no model-callable activation entrypoint.
- Modify `honeyos/runtime/main.py`: register internal Builder activation commands.
- Modify `honeyos/companion/config.py`: include the dedicated toolset and managed Skill contract.
- Modify `honeyos/companion/companion_skills/honeyos-builder/SKILL.md`: route candidate completion through staging and owner confirmation.
- Modify `honeyos/companion/activity.py`: companion-language staging, switching, success, and rollback states.
- Modify `honeyos/gateway/platforms/api_server.py` and `honeyos/companion/web_assets/app.js`: structured Web confirmation/result card.
- Add focused tests under `tests/honeyos/test_builder_activation*.py`, then extend Builder, gateway, config, and distribution tests.

---

### Task 1: Freeze the trusted boundary and bind reviews to candidate bytes

**Files:**
- Modify: `honeyos/companion/builder_workspace.py`
- Modify: `honeyos/runtime/builder_cmd.py`
- Test: `tests/honeyos/test_builder_workspace.py`
- Test: `tests/honeyos/test_builder_cli.py`

**Interfaces:**
- Produces: `BuilderReviewReport.candidate_digest: str`
- Produces: `inspect_builder_change(change_root) -> BuilderReviewReport` whose private report includes `source_commit`, `candidate_digest`, and `reviewed_at`.
- Protects: activation modules, runtime command registration, dependency manifests, install/update scripts, service management, backup/restore, approval delivery, and all non-static host execution/agent-loop paths. Dynamic task scope is a narrowing record, not the security boundary.

- [ ] **Step 1: Write failing protected-path and digest tests**

```python
def test_inspect_binds_review_to_candidate_digest(tmp_path):
    prepared = _prepared_change(tmp_path)
    feature = prepared.workspace / "honeyos" / "companion" / "feature.py"
    feature.write_text("VALUE = 'candidate'\n", encoding="utf-8")

    first = inspect_builder_change(prepared.change_root)
    feature.write_text("VALUE = 'changed-after-review'\n", encoding="utf-8")
    second = inspect_builder_change(prepared.change_root)

    assert first.candidate_digest
    assert second.candidate_digest != first.candidate_digest
    assert json.loads(first.report_path.read_text())["source_commit"]


@pytest.mark.parametrize(
    "path",
    (
        "honeyos/companion/builder_activation.py",
        "honeyos/runtime/builder_activation_worker.py",
        "honeyos/tools/companion_builder_tool.py",
        "honeyos/runtime/gateway.py",
        "honeyos/runtime/backup.py",
        "pyproject.toml",
        "uv.lock",
        "install.sh",
    ),
)
def test_builder_blocks_activation_and_dependency_surfaces(tmp_path, path):
    prepared = _prepared_change(tmp_path, allowed_paths=("**",))
    target = prepared.workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n", encoding="utf-8")
    report = inspect_builder_change(prepared.change_root)
    assert report.status == "blocked"
    assert path in report.protected_changes
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py`

Expected: FAIL because `candidate_digest` is absent and the new paths are not protected.

- [ ] **Step 3: Implement deterministic reviewed-tree hashing**

Add a helper that hashes the source commit plus each changed path, status, mode,
and bytes in sorted order; reject symlinks and unreadable paths. Add the new
protected globs and persist the digest in `review.json`.

```python
@dataclass(frozen=True)
class BuilderReviewReport:
    status: str
    allowed_changes: tuple[str, ...]
    protected_changes: tuple[str, ...]
    out_of_scope_changes: tuple[str, ...]
    installable: bool
    report_path: Path
    candidate_digest: str = ""


def candidate_digest(workspace: Path, source_commit: str, paths: Iterable[str]) -> str:
    digest = hashlib.sha256(source_commit.encode("utf-8"))
    for relative in sorted(paths):
        path = workspace / relative
        if path.is_symlink():
            raise ValueError(f"candidate path is a symlink: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"<deleted>")
    return digest.hexdigest()
```

- [ ] **Step 4: Run focused tests and Ruff**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py`

Expected: PASS.

Run: `.venv/bin/ruff check honeyos/companion/builder_workspace.py honeyos/runtime/builder_cmd.py tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py`

Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add honeyos/companion/builder_workspace.py honeyos/runtime/builder_cmd.py tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
git commit -m "fix(companion): bind builder reviews to trusted candidate bytes"
```

---

### Task 2: Add private version slots and atomic activation state

**Files:**
- Create: `honeyos/companion/builder_activation.py`
- Create: `tests/honeyos/test_builder_activation.py`

**Interfaces:**
- Produces: `ActivationStore(home: Path, bundled_root: Path)`
- Produces: `stage(change_root: Path) -> StagedActivation`
- Produces: `issue_confirmation(activation_id: str, lane_key: str, channel: str, now: datetime | None = None) -> ActivationConfirmation`
- Produces: `consume_confirmation(activation_id: str, token: str, lane_key: str, now: datetime | None = None) -> ActivationRecord`
- Produces: `transition(activation_id: str, expected: str, target: str, detail: str = "") -> ActivationRecord`

- Materialization contract: require the trusted `source_repo` HEAD to equal the
  recorded `source_commit`; create a complete no-`.git` baseline from a trusted
  `git archive source_commit`; overlay only reviewed changed/deleted paths with
  a no-symlink copier; store both the reviewed-diff digest and a full slot-tree
  digest.

- [ ] **Step 1: Write failing slot/state tests**

```python
OWNER = "agent:main:companion:dm:owner"


def test_stage_materializes_complete_reviewed_source_into_private_slot(tmp_path):
    prepared, review = _review_ready_change(tmp_path)
    store = ActivationStore(tmp_path / "home", bundled_root=tmp_path / "live")

    staged = store.stage(prepared.change_root)

    assert staged.state == "staged"
    assert staged.candidate_digest == review.candidate_digest
    assert staged.slot_root.is_relative_to(tmp_path / "home" / "runtime" / "slots")
    assert not (staged.slot_root / "source" / ".git").exists()
    assert (staged.slot_root / "source" / "pyproject.toml").is_file()
    assert staged.slot_tree_digest
    assert staged.manifest_path.stat().st_mode & 0o777 == 0o600


def test_changed_candidate_cannot_be_staged_from_old_review(tmp_path):
    prepared, _review = _review_ready_change(tmp_path)
    (prepared.workspace / "honeyos" / "companion" / "feature.py").write_text(
        "tampered\n", encoding="utf-8"
    )
    with pytest.raises(ActivationError, match="changed after review"):
        ActivationStore(tmp_path / "home", tmp_path / "live").stage(
            prepared.change_root
        )


def test_stage_rejects_changed_live_source_head(tmp_path):
    prepared, _review = _review_ready_change(tmp_path)
    _commit_unexpected_change(prepared.source_repo)
    with pytest.raises(ActivationError, match="source revision"):
        ActivationStore(tmp_path / "home", tmp_path / "live").stage(
            prepared.change_root
        )


def test_candidate_import_resolves_from_slot_source(tmp_path):
    store, staged = _staged_activation(tmp_path)
    resolved = store.resolve_candidate_module(staged.activation_id, "honeyos.runtime.main")
    assert resolved.is_relative_to(staged.slot_root / "source")


def test_activation_transitions_are_compare_and_swap_and_private(tmp_path):
    store, staged = _staged_activation(tmp_path)
    switched = store.transition(staged.activation_id, "staged", "awaiting_confirmation")
    assert switched.state == "awaiting_confirmation"
    with pytest.raises(ActivationConflict):
        store.transition(staged.activation_id, "staged", "switching")
    assert (store.activations / f"{staged.activation_id}.json").stat().st_mode & 0o777 == 0o600
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py`

Expected: FAIL with `ModuleNotFoundError: honeyos.companion.builder_activation`.

- [ ] **Step 3: Implement the store, safe copier, and state machine**

Use trusted `git archive`, `Path.resolve()`, `os.lstat()`, `shutil.copy2`,
temporary sibling directories, `os.replace`, and the existing
`MemoryStore()._file_lock` pattern. Never use an editable install or copy `.git`.
The baseline includes unchanged trusted packaging/test artifacts; only reviewed
paths may differ from the pinned base. Recompute the reviewed-diff digest before
overlay and the full slot-tree digest after materialization.
The only legal transitions are:

```python
_TRANSITIONS = {
    "staged": {"awaiting_confirmation", "invalidated"},
    "awaiting_confirmation": {"switching", "denied", "expired", "invalidated"},
    "switching": {"healthy", "rolling_back", "recovery_required"},
    "rolling_back": {"rolled_back", "recovery_required"},
}
```

Write JSON with a private atomic helper:

```python
def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
```

- [ ] **Step 4: Run focused tests and Ruff**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py`

Expected: PASS.

Run: `.venv/bin/ruff check honeyos/companion/builder_activation.py tests/honeyos/test_builder_activation.py`

Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add honeyos/companion/builder_activation.py tests/honeyos/test_builder_activation.py
git commit -m "feat(companion): add private builder version slots"
```

---

### Task 3: Build and preflight a candidate without touching live data

**Files:**
- Modify: `honeyos/companion/builder_activation.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tests/honeyos/test_builder_activation.py`
- Create: `tests/honeyos/test_builder_preflight.py`

**Interfaces:**
- Produces: `preflight(activation_id: str, runner: ProcessRunner | None = None) -> PreflightReceipt`
- `PreflightReceipt` includes `success`, `checks`, `candidate_digest`, `python_executable`, `source_root`, and redacted `error`.
- Consumes: existing approved dependency files from `bundled_root`; candidate changes to dependency files are already blocked. The normal `honeyos` runtime extra includes pinned pytest so every distribution install can execute the fixed Builder boundary tests.

- [ ] **Step 1: Write failing isolation and preflight tests**

```python
def test_preflight_uses_synthetic_home_and_never_copies_real_data(tmp_path):
    store, staged = _staged_activation(tmp_path)
    real_secret = store.home / "config.yaml"
    real_secret.write_text("api_key: sk-private\n", encoding="utf-8")
    runner = RecordingRunner(success=True)

    receipt = store.preflight(staged.activation_id, runner=runner)

    assert receipt.success is True
    assert all(str(store.home) not in command.env.get("HONEYOS_HOME", "") for command in runner.commands)
    assert all("sk-private" not in repr(command) for command in runner.commands)
    assert (staged.slot_root / "preflight.json").stat().st_mode & 0o777 == 0o600


def test_preflight_failure_never_issues_confirmation(tmp_path):
    store, staged = _staged_activation(tmp_path)
    receipt = store.preflight(staged.activation_id, runner=RecordingRunner(success=False))
    assert receipt.success is False
    with pytest.raises(ActivationConflict, match="preflight"):
        store.issue_confirmation(staged.activation_id, OWNER, "feishu")
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_preflight.py`

Expected: FAIL because `preflight` does not exist.

- [ ] **Step 3: Implement an injectable process runner and trusted checks**

Create a slot-local virtual environment using the current trusted interpreter.
Install the complete slot source using the unchanged, locked approved dependency
set and an explicit non-editable installation rooted at `slot/source`; fail
closed when required approved artifacts are unavailable. Build from a disposable
archive outside the read-only source; make only the current trusted runtime's
installed dependency set visible to the slot venv (not an editable running
checkout). Run every command with
`cwd=slot/source`, a temporary synthetic `HONEYOS_HOME`, `PYTHONPATH` cleared,
and `PYTHONPYCACHEPREFIX` pointing to a disposable directory outside the
read-only slot source:

```python
checks = (
    (slot_python, "-m", "compileall", "-q", str(source_root / "honeyos")),
    (slot_python, "-c", "import honeyos; import honeyos.runtime.main"),
    (slot_python, "-m", "honeyos.runtime.main", "--help"),
    (slot_python, "-m", "pytest", "-q", "tests/honeyos/test_builder_workspace.py"),
)
```

Record bounded duration, return code, and redacted last output for every check.
Do not inherit credential environment variables; allow only PATH, locale,
temporary HOME, synthetic HONEYOS_HOME, and the slot's virtual environment.
Explicitly clear `PYTHONPATH`, `VIRTUAL_ENV`, `PIP_*`, `UV_*`, proxy variables,
credential variables, and existing HoneyOS product variables. Assert the
imported `honeyos.__file__` is below `slot/source`.

- [ ] **Step 4: Run tests and Ruff**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py tests/honeyos/test_builder_preflight.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add honeyos/companion/builder_activation.py pyproject.toml uv.lock tests/honeyos/test_builder_activation.py tests/honeyos/test_builder_preflight.py
git commit -m "feat(companion): preflight builder slots with synthetic data"
```

---

### Task 4: Add single-use owner confirmation and a dedicated Builder tool

**Files:**
- Create: `honeyos/tools/companion_builder_tool.py`
- Modify: `honeyos/companion/builder_activation.py`
- Modify: `honeyos/companion/config.py`
- Test: `tests/honeyos/test_companion_builder_tool.py`
- Test: `tests/honeyos/test_config.py`

**Interfaces:**
- Produces model tool actions: `stage`, `request_activation`, and `status`; the
  model may prepare and explain a candidate but cannot authorize switching.
- Produces a gateway-owned durable confirmation resolver bound to activation ID,
  digest, expiry, canonical owner lane, and authenticated inbound event.
- Web and IM cards carry only a compact opaque callback ID mapped server-side;
  no confirmation token appears in model/tool text or rendered event payloads.
- The exact current-user quote remains defense-in-depth UX evidence, not the
  authorization boundary.
- Successful confirmation launches only the trusted gateway-owned detached
  worker using a sealed inherited capability/FD and returns `switching`.

- [ ] **Step 1: Write failing authorization and replay tests**

```python
def test_activation_confirmation_requires_authenticated_owner_callback(tmp_path):
    callback = _ready_confirmation(tmp_path)
    denied = _resolve_callback(callback.id, session="other", quote="现在启用")
    assert denied.success is False


def test_confirmation_is_owner_dm_only_single_use_and_digest_bound(tmp_path):
    callback = _ready_confirmation(tmp_path)
    first = _resolve_owner_callback(callback)
    second = _resolve_owner_callback(callback)
    assert first["state"] == "switching"
    assert second["success"] is False
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_companion_builder_tool.py`

Expected: FAIL because the tool is not registered.

- [ ] **Step 3: Implement token hashing, TTL, and tool boundary**

Store only the hash of the server-side callback secret in the private record.
Generate 32 random bytes, expire after 10 minutes, pop/transition before
launching, and use `hmac.compare_digest`. Treat an `always` UI choice as a
one-time confirmation; never persist a bypass. Persist replay protection across
gateway restarts and authenticate Web owner-session mapping rather than trusting
an arbitrary session header.

```python
def _tool_scope() -> tuple[Path, str] | None:
    if not os.environ.get("HONEYOS_RUNTIME_ID", "").startswith("honeyos-companion-"):
        return None
    lane = get_current_session_key("").strip()
    if lane != "agent:main:companion:dm:owner":
        return None
    return Path(os.environ["HONEYOS_HOME"]).expanduser().resolve(), lane
```

Register `companion_builder` in `COMPANION_TOOLSETS`; do not add terminal-level
activation to the model schema. Reject activation worker, switch, and rollback
commands from model-facing terminal/code execution policy.

- [ ] **Step 4: Run focused tests and Ruff**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_companion_builder_tool.py tests/honeyos/test_config.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add honeyos/tools/companion_builder_tool.py honeyos/companion/builder_activation.py honeyos/companion/config.py tests/honeyos/test_companion_builder_tool.py tests/honeyos/test_config.py
git commit -m "feat(companion): require owner confirmation for builder activation"
```

---

### Task 5: Implement detached service switching and health-based rollback

**Files:**
- Create: `honeyos/runtime/builder_activation_worker.py`
- Modify: `honeyos/companion/builder_activation.py`
- Modify: `honeyos/runtime/builder_cmd.py`
- Modify: `honeyos/runtime/main.py`
- Create: `tests/honeyos/test_builder_activation_worker.py`
- Modify: `tests/honeyos/test_builder_cli.py`

**Interfaces:**
- Produces: `ActivationWorker(record_path: Path, service: ServiceController, health: HealthProbe, backup: BackupController)`.
- Produces: `run() -> int`, returning `0` only for `healthy` or a verified `rolled_back` state.
- Produces a gateway-owned detached launcher that hands the worker a sealed inherited capability/FD; activation is not exposed as a shell subcommand.
- Consumes: `run_gateway_command`, runtime identity, existing quick snapshot/SQLite integrity helpers, and platform service managers.
- Produces a testable `ManagedGatewayDefinition` abstraction that reads,
  installs, and restores the exact service definition with explicit
  `python`, `source_root`, `home`, `activation_digest`, and `start` arguments.
- Produces a startup attestation containing activation digest, resolved
  `HONEYOS_HOME`, PID/start identifier, and stable runtime ID.
- Produces an activation-specific backup receipt with exact captured files,
  manifest digest, DB integrity results, strict restore verification, and
  retention independent of ordinary quick snapshots.

- [ ] **Step 1: Write failing success, rollback, and crash-recovery tests**

```python
def test_worker_switches_service_and_preserves_data_home(tmp_path):
    worker, service, health, record = _worker(tmp_path, healthy=True)
    assert worker.run() == 0
    assert service.installed_python == record.new_python
    assert service.environment["HONEYOS_HOME"] == str(worker.home)
    assert health.expected_digest == record.candidate_digest
    assert worker.store.read(record.activation_id).state == "healthy"


def test_failed_new_health_restores_old_service_and_snapshot(tmp_path):
    worker, service, _health, record = _worker(tmp_path, healthy=False)
    assert worker.run() == 0
    assert service.installed_python == record.old_python
    assert service.restart_count == 2
    assert worker.store.read(record.activation_id).state == "rolled_back"
    assert worker.backup.restored_snapshot == record.snapshot_id


@pytest.mark.parametrize("crash_after", ("snapshot", "stop_old", "pointer", "start_new"))
def test_reconcile_never_leaves_a_mixed_runtime(tmp_path, crash_after):
    worker = _crashing_worker(tmp_path, crash_after)
    with pytest.raises(SimulatedPowerLoss):
        worker.run()
    recovered = ActivationWorker.reconcile(worker.record_path, worker.dependencies)
    assert recovered.state in {"healthy", "rolled_back", "recovery_required"}
    assert recovered.service_python in {recovered.old_python, recovered.new_python}
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation_worker.py`

Expected: FAIL because the worker module does not exist.

- [ ] **Step 3: Implement injected controllers and durable checkpoints**

The worker records a checkpoint before and after every side effect. Before the
first service mutation, create and verify an activation-specific snapshot; fail
closed if any required state/DB is missing or fails integrity checks. Preserve
the exact old service definition as the rollback artifact. Never
shell-interpolate paths.

Health requires service liveness, local `/health`, expected runtime identity,
SQLite integrity, and owner session open. The new service supplies trusted
`HONEYOS_ACTIVATION_DIGEST`; startup atomically attests digest, home, PID/start
identity, and runtime ID. Reject an old listener, stale attestation, wrong
digest/home/PID. Provider calls are explicitly absent. On failure, stop new,
restore pointer/exact service definition/data snapshot, start old, and verify
every restored artifact plus old health before declaring `rolled_back`.

The service-definition implementation must honor a true no-load/no-start install
on launchd, systemd, Windows, and s6. In particular, macOS must not bootstrap the
new plist during install, and systemd must disable start-on-login until the
worker deliberately starts the candidate.

- [ ] **Step 4: Run worker, CLI, gateway, and backup tests**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation_worker.py tests/honeyos/test_builder_cli.py tests/honeyos/test_lifecycle.py tests/honeyos/test_runtime.py tests/honeyos/test_gateway_service_switch.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add honeyos/runtime/builder_activation_worker.py honeyos/companion/builder_activation.py honeyos/runtime/builder_cmd.py honeyos/runtime/main.py tests/honeyos/test_builder_activation_worker.py tests/honeyos/test_builder_cli.py
git commit -m "feat(companion): switch builder slots with automatic rollback"
```

---

### Task 6: Resume after restart and deliver one durable result receipt

**Files:**
- Modify: `honeyos/runtime/builder_activation_worker.py`
- Modify: `honeyos/gateway/run.py`
- Modify: `honeyos/companion/activity.py`
- Create: `tests/honeyos/test_builder_activation_receipts.py`
- Modify: `tests/honeyos/test_companion_web.py`

**Interfaces:**
- Produces private receipt states `healthy`, `rolled_back`, `recovery_required`, with delivery state `pending|sent`.
- Startup reconciliation consumes pending receipts once and sends them to the most recently used owner channel.
- Consumes existing canonical owner session and home-channel routing; never creates a new session.

- [ ] **Step 1: Write failing receipt idempotency and continuity tests**

```python
def test_startup_delivers_activation_receipt_once_to_recent_owner_channel(tmp_path):
    receipt = _pending_receipt(tmp_path, channel="feishu", state="healthy")
    sender = RecordingSender()
    deliver_pending_activation_receipts(tmp_path, sender)
    deliver_pending_activation_receipts(tmp_path, sender)
    assert len(sender.messages) == 1
    assert sender.messages[0].session_key == "agent:main:companion:dm:owner"
    assert sender.messages[0].channel == "feishu"
    assert receipt.read()["delivery_state"] == "sent"


def test_activation_does_not_reset_owner_session(tmp_path):
    before = _owner_session_history(tmp_path)
    _simulate_successful_activation(tmp_path)
    assert _owner_session_history(tmp_path) == before
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation_receipts.py`

Expected: FAIL because receipt delivery is absent.

- [ ] **Step 3: Implement receipt projection and startup delivery**

Project internal states into relationship-safe copy:

```python
def activation_receipt_copy(state: str, goal: str) -> tuple[str, str]:
    if state == "healthy":
        return "我回来了", f"刚才那次「{goal}」已经启用了，我们接着聊。"
    if state == "rolled_back":
        return "我已经退回原来的版本", "新版本没能稳定启动，但你的记忆和聊天都没有丢。"
    return "这次切换需要你帮我看一下", "我保留了原来的版本和恢复记录，没有冒险继续切换。"
```

Mark sent only after adapter delivery succeeds. Keep the receipt pending across
restarts and route through the latest owner channel metadata.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation_receipts.py tests/honeyos/test_companion_web.py tests/honeyos/test_continuity_gateway.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add honeyos/runtime/builder_activation_worker.py honeyos/gateway/run.py honeyos/companion/activity.py tests/honeyos/test_builder_activation_receipts.py tests/honeyos/test_companion_web.py
git commit -m "feat(companion): resume owner chat after builder activation"
```

---

### Task 7: Render Web confirmation/status cards and update the Builder Skill

**Files:**
- Modify: `honeyos/gateway/platforms/api_server.py`
- Modify: `honeyos/companion/web_assets/app.js`
- Modify: `honeyos/companion/web_assets/styles.css`
- Modify: `honeyos/companion/companion_skills/honeyos-builder/SKILL.md`
- Modify: `honeyos/companion/companion_skills/honeyos-self-extension/SKILL.md`
- Modify: `honeyos/companion/config.py`
- Modify: `tests/honeyos/test_companion_web.py`
- Modify: `tests/honeyos/test_companion_prompt.py`
- Modify: `tests/honeyos/test_config.py`

**Interfaces:**
- API event: `builder.activation_confirmation` with goal, areas, preflight summary, activation ID, and opaque token.
- API action: owner-authenticated confirm/deny endpoint that injects a canonical user confirmation message; it does not call the worker directly.
- Web card states: ready, switching, healthy, rolled_back, recovery_required.

- [ ] **Step 1: Write failing projection, endpoint, and Skill-contract tests**

```python
def test_builder_confirmation_event_hides_paths_commands_and_token():
    payload = _builder_confirmation_event_payload(_private_record())
    assert payload == {
        "kind": "builder_activation",
        "state": "ready",
        "title": "新版本已经准备好了",
        "goal": "改善跨渠道记忆",
        "restart_required": True,
    }
    assert "workspace" not in repr(payload)
    assert "token" not in repr(payload)


def test_builder_skill_never_claims_review_ready_means_enabled():
    text = _bundled_skill("honeyos-builder")
    assert "request_activation" in text
    assert "用户明确确认" in text
    assert "自动回滚" in text
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_companion_web.py tests/honeyos/test_companion_prompt.py tests/honeyos/test_config.py`

Expected: FAIL because the event/card and new managed contract are absent.

- [ ] **Step 3: Implement safe API projection and Web component**

Reuse the current Claude-style component tokens. The card shows only goal,
changed areas, test state, restart/rollback promise, and confirm/cancel actions.
No paths, raw commands, diffs, token, or reasoning are rendered. Disable the
button after one click and follow live status events.

Update the Skill procedure:

```text
inspect → stage → request_activation → wait for the user's fresh confirmation
→ confirm_activation → report that a restart is beginning
```

The Skill must not interpret `review_ready` or `staged` as enabled, and must not
use terminal commands to bypass the dedicated tool.

- [ ] **Step 4: Run Python and JavaScript checks**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_companion_web.py tests/honeyos/test_companion_prompt.py tests/honeyos/test_config.py`

Expected: PASS.

Run: `node --check honeyos/companion/web_assets/app.js`

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add honeyos/gateway/platforms/api_server.py honeyos/companion/web_assets/app.js honeyos/companion/web_assets/styles.css honeyos/companion/companion_skills/honeyos-builder/SKILL.md honeyos/companion/companion_skills/honeyos-self-extension/SKILL.md honeyos/companion/config.py tests/honeyos/test_companion_web.py tests/honeyos/test_companion_prompt.py tests/honeyos/test_config.py
git commit -m "feat(companion): present builder activation in companion channels"
```

---

### Task 8: Add retention, upgrade preservation, distribution docs, and end-to-end verification

**Files:**
- Modify: `honeyos/companion/builder_activation.py`
- Modify: `honeyos/companion/config.py`
- Modify: `README.md`
- Create: `tests/honeyos/test_builder_activation_e2e.py`
- Modify: `tests/honeyos/test_config.py`
- Modify: `tests/honeyos/test_distribution_contract.py`

**Interfaces:**
- Produces: `prune_slots(now: datetime | None = None) -> tuple[str, ...]` retaining active, previous, three recent healthy, and seven-day failed slots.
- Reinitialization and package update preserve runtime slots, activation state, snapshots, and user data.

- [ ] **Step 1: Write failing retention, reinstall, and end-to-end tests**

```python
def test_pruning_never_removes_active_previous_or_inflight_slots(tmp_path):
    store = _store_with_many_slots(tmp_path)
    removed = store.prune_slots(now=NOW)
    protected = {store.current_id, store.previous_id, store.switching_id}
    assert protected.isdisjoint(removed)
    assert len(store.other_healthy_slots()) <= 3


def test_reinitialize_preserves_activation_and_companion_data(tmp_path):
    before = _seed_user_data_and_activation(tmp_path)
    initialize_home(tmp_path)
    assert _read_preserved_state(tmp_path) == before


def test_owner_confirmed_candidate_activates_and_failed_candidate_rolls_back(tmp_path):
    harness = DisposableManagedHoneyOS(tmp_path)
    successful = harness.prepare_stage_confirm(healthy_candidate=True)
    assert successful.final_state == "healthy"
    assert harness.owner_history_preserved()
    failed = harness.prepare_stage_confirm(healthy_candidate=False)
    assert failed.final_state == "rolled_back"
    assert harness.active_digest == successful.candidate_digest
    assert harness.user_data_preserved()
```

- [ ] **Step 2: Run and verify RED**

Run: `.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation_e2e.py tests/honeyos/test_config.py tests/honeyos/test_distribution_contract.py`

Expected: FAIL because retention and end-to-end activation are incomplete.

- [ ] **Step 3: Implement pruning and document the user flow**

Prune only while holding the activation lock. Never follow symlinks. Document
the natural-language flow, default availability, one-time confirmation,
automatic restart/rollback, preserved data, and the distinction from normal
Skill installation. Do not mention GitHub as a user prerequisite.

- [ ] **Step 4: Run complete verification**

Run: `.venv/bin/ruff check honeyos tests/honeyos`

Expected: `All checks passed!`

Run: `node --check honeyos/companion/web_assets/app.js`

Expected: exit 0.

Run: `.venv/bin/python -m pytest -q tests/honeyos`

Expected: all tests pass.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add honeyos/companion/builder_activation.py honeyos/companion/config.py README.md tests/honeyos/test_builder_activation_e2e.py tests/honeyos/test_config.py tests/honeyos/test_distribution_contract.py
git commit -m "docs(companion): ship safe local builder activation"
```

---

## Final review gate

- [ ] Re-read `docs/superpowers/specs/2026-08-11-builder-activation-and-rollback-design.md` and map every acceptance criterion to a passing test.
- [ ] Confirm the live checkout and real `~/.honeyos` were never used by tests.
- [ ] Confirm the model-facing schema has no raw activation-worker or service-switch action.
- [ ] Confirm protected paths take precedence over broad allowed globs.
- [ ] Confirm provider availability is absent from health decisions.
- [ ] Confirm confirmation replay, group lane, stale digest, stale base, power loss, failed new health, and failed rollback all have deterministic outcomes.
- [ ] Run the complete test suite once more after the final commit and record the exact pass count.
