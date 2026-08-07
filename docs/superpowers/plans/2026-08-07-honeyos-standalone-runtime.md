# HoneyOS Standalone Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the layered H2OS-over-Hermes checkout with one independently named, minimal HoneyOS runtime and a clean user ZIP that cannot start or modify an existing Hermes installation.

**Architecture:** Introduce a single `honeyos` package as the public and internal namespace, migrate `~/.h2os` transactionally into `~/.honeyos`, and register only HoneyOS-specific services. Move the runtime modules HoneyOS actually uses into that namespace, delete unrelated source trees, and enforce the result with forbidden-name, import-closure, distribution, migration, and coexistence tests.

**Tech Stack:** Python 3.11-3.13, pytest, uv, YAML, SQLite, macOS launchd, Linux systemd, POSIX shell.

## Global Constraints

- Product display name is `HoneyOS`; the only command is `honeyos`.
- Python distribution and top-level package are both `honeyos`.
- New data lives only in `~/.honeyos`.
- macOS service label is `ai.honeyos.gateway`; Linux unit is `honeyos-gateway.service`.
- Existing `~/.h2os` data migrates automatically and remains as a timestamped backup.
- Existing `~/.hermes`, `ai.hermes.*`, and `hermes-gateway*` are never read, stopped, started, or modified.
- The current Weixin, Feishu, companion prompt, continuity, memory, tool handback, web, files, sandbox, Computer Use, Skill, todo, and cron capabilities must remain.
- The words `hermes`, `h2os`, and `springbrand` may remain only in `LICENSE`, `NOTICE`, and the narrowly scoped legacy migration module/tests.

---

### Task 1: Lock the standalone product contract with failing tests

**Files:**
- Create: `tests/honeyos/test_product_contract.py`
- Create: `tests/honeyos/test_repository_surface.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: repository-level rules consumed by every later task.
- Produces: `honeyos.PRODUCT_NAME`, `honeyos.RUNTIME_ID`, and `honeyos.__version__`.

- [ ] **Step 1: Add a product-contract test that names every public identifier**

```python
from pathlib import Path

import honeyos


def test_public_identity_is_honeyos():
    assert honeyos.PRODUCT_NAME == "HoneyOS"
    assert honeyos.RUNTIME_ID.startswith("honeyos-companion-")
    assert Path(honeyos.default_home()).name == ".honeyos"
```

- [ ] **Step 2: Add repository and packaging assertions**

```python
import re
import tomllib
from pathlib import Path


def test_only_honeyos_console_script_is_exported():
    config = tomllib.loads(Path("pyproject.toml").read_text())
    assert config["project"]["name"] == "honeyos"
    assert config["project"]["scripts"] == {"honeyos": "honeyos.cli.main:main"}


def test_forbidden_runtime_names_are_absent():
    allowed = {Path("LICENSE"), Path("NOTICE"), Path("honeyos/migration/legacy_h2os.py")}
    offenders = []
    for path in Path(".").rglob("*"):
        if not path.is_file() or ".git" in path.parts or path in allowed:
            continue
        if any(part in {"tests", "docs"} for part in path.parts):
            continue
        if re.search(r"hermes|h2os|springbrand", str(path), re.I):
            offenders.append(str(path))
    assert offenders == []
```

- [ ] **Step 3: Run the tests and record the expected initial failure**

Run: `uv run pytest tests/honeyos/test_product_contract.py tests/honeyos/test_repository_surface.py -q`

Expected: FAIL because the `honeyos` package does not exist and `pyproject.toml` still exports Hermes/H2OS scripts.

- [ ] **Step 4: Create the minimal package identity and update packaging metadata**

```python
# honeyos/__init__.py
from pathlib import Path

PRODUCT_NAME = "HoneyOS"
RUNTIME_ID = "honeyos-companion-v0.3"
__version__ = "0.3.0"


def default_home() -> Path:
    return Path.home() / ".honeyos"
```

Set `[project].name = "honeyos"`, update the description, and make `[project.scripts]` contain only `honeyos = "honeyos.cli.main:main"`.

- [ ] **Step 5: Run the narrow identity test**

Run: `uv run pytest tests/honeyos/test_product_contract.py::test_public_identity_is_honeyos -q`

Expected: PASS. The repository-surface test remains failing until Tasks 4-5.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml honeyos/__init__.py tests/honeyos
git commit -m "feat: establish standalone HoneyOS identity"
```

### Task 2: Transactionally migrate `~/.h2os` to `~/.honeyos`

**Files:**
- Create: `honeyos/migration/__init__.py`
- Create: `honeyos/migration/legacy_h2os.py`
- Create: `tests/honeyos/test_legacy_migration.py`

**Interfaces:**
- Produces: `MigrationResult` and `migrate_legacy_home(new_home: Path, legacy_home: Path | None = None) -> MigrationResult`.
- Consumes: no gateway/runtime imports, so migration runs before service startup.

- [ ] **Step 1: Write failing migration tests**

```python
from pathlib import Path

from honeyos.migration.legacy_h2os import migrate_legacy_home


def test_migrates_legacy_home_and_keeps_backup(tmp_path: Path):
    old = tmp_path / ".h2os"
    new = tmp_path / ".honeyos"
    old.mkdir()
    (old / "config.yaml").write_text("agent:\n  mode: companion\n")
    (old / "memories").mkdir()
    (old / "memories" / "IDENTITY.md").write_text("温柔但有主见")

    result = migrate_legacy_home(new, old)

    assert result.migrated is True
    assert (new / "memories" / "IDENTITY.md").read_text() == "温柔但有主见"
    assert result.backup_home is not None and result.backup_home.exists()
    assert not old.exists()


def test_existing_new_home_wins_without_touching_legacy(tmp_path: Path):
    old = tmp_path / ".h2os"
    new = tmp_path / ".honeyos"
    old.mkdir()
    new.mkdir()
    result = migrate_legacy_home(new, old)
    assert result.migrated is False
    assert old.exists()
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `uv run pytest tests/honeyos/test_legacy_migration.py -q`

Expected: FAIL because the migration module is missing.

- [ ] **Step 3: Implement an atomic copy-validate-rename migration**

```python
@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    new_home: Path
    backup_home: Path | None


def migrate_legacy_home(new_home: Path, legacy_home: Path | None = None) -> MigrationResult:
    legacy = legacy_home or Path.home() / ".h2os"
    if new_home.exists() or not legacy.exists():
        return MigrationResult(False, new_home, None)
    staging = new_home.with_name(f".{new_home.name}.migrating")
    shutil.copytree(legacy, staging, symlinks=False)
    _rewrite_legacy_paths(staging, legacy, new_home)
    _validate_migrated_home(staging)
    staging.replace(new_home)
    backup = legacy.with_name(f".h2os.backup-{datetime.now():%Y%m%d%H%M%S}")
    legacy.replace(backup)
    return MigrationResult(True, new_home, backup)
```

The validator must parse `config.yaml`, open every discovered SQLite database read-only, and require the companion memory/session directories that existed in the source to exist in staging. On any exception, remove only staging and leave the legacy directory unchanged.

- [ ] **Step 4: Add failure rollback and `.hermes` non-interference tests**

```python
def test_failure_leaves_legacy_and_hermes_untouched(tmp_path, monkeypatch):
    old = tmp_path / ".h2os"
    hermes = tmp_path / ".hermes"
    new = tmp_path / ".honeyos"
    old.mkdir(); hermes.mkdir()
    (old / "config.yaml").write_text("[")
    marker = hermes / "marker"; marker.write_text("keep")
    with pytest.raises(MigrationError):
        migrate_legacy_home(new, old)
    assert old.exists() and not new.exists()
    assert marker.read_text() == "keep"
```

- [ ] **Step 5: Run migration tests**

Run: `uv run pytest tests/honeyos/test_legacy_migration.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add honeyos/migration tests/honeyos/test_legacy_migration.py
git commit -m "feat: migrate legacy companion homes safely"
```

### Task 3: Replace public CLI and background service lifecycle

**Files:**
- Create: `honeyos/cli/main.py`
- Create: `honeyos/cli/service.py`
- Create: `honeyos/cli/bootstrap.py`
- Create: `tests/honeyos/test_service_identity.py`
- Create: `tests/honeyos/test_cli_bootstrap.py`
- Modify: `Install-Honey-OS.command` -> rename to `Install-HoneyOS.command`
- Modify: `scripts/install_honey_os.sh` -> rename to `scripts/install_honeyos.sh`

**Interfaces:**
- Produces: `activate_home(home: Path | None = None) -> Path`.
- Produces: `ServiceIdentity.macos_label == "ai.honeyos.gateway"` and `linux_unit == "honeyos-gateway"`.
- Consumes: `migrate_legacy_home` from Task 2.

- [ ] **Step 1: Write failing service and CLI bootstrap tests**

```python
def test_service_identity_has_no_legacy_aliases():
    identity = ServiceIdentity.default()
    assert identity.macos_label == "ai.honeyos.gateway"
    assert identity.linux_unit == "honeyos-gateway"
    assert identity.data_home.name == ".honeyos"


def test_bootstrap_migrates_before_runtime_import(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / ".h2os"; legacy.mkdir()
    (legacy / "config.yaml").write_text("agent:\n  mode: companion\n")
    assert activate_home() == tmp_path / ".honeyos"
```

- [ ] **Step 2: Run and verify failure**

Run: `uv run pytest tests/honeyos/test_service_identity.py tests/honeyos/test_cli_bootstrap.py -q`

Expected: FAIL because the standalone service layer is missing.

- [ ] **Step 3: Implement exact-label lifecycle operations**

`honeyos/cli/service.py` must generate launchd/systemd definitions whose program arguments are the current absolute interpreter, `-m`, `honeyos`, `gateway`, `run`. Start/stop/status operations address only the exact HoneyOS label/unit and never scan generic gateway processes.

- [ ] **Step 4: Replace the installer entrypoint**

```sh
cd "$REPO_DIR"
uv sync --quiet
exec uv run honeyos setup
```

The installer must reject unsupported systems, install `uv` locally when absent, and print only HoneyOS names.

- [ ] **Step 5: Run CLI/service tests**

Run: `uv run pytest tests/honeyos/test_service_identity.py tests/honeyos/test_cli_bootstrap.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add honeyos/cli tests/honeyos Install-HoneyOS.command scripts/install_honeyos.sh pyproject.toml
git rm Install-Honey-OS.command scripts/install_honey_os.sh
git commit -m "feat: isolate HoneyOS command and services"
```

### Task 4: Move the required runtime into the `honeyos` namespace

**Files:**
- Create/move: `honeyos/agent/**`
- Create/move: `honeyos/gateway/**`
- Create/move: `honeyos/tools/**`
- Create/move: `honeyos/scheduler/**`
- Create/move: `honeyos/platforms/weixin.py`
- Create/move: `honeyos/platforms/feishu.py`
- Create/move: `honeyos/companion/**`
- Test: `tests/honeyos/test_runtime_import_closure.py`
- Test: migrate relevant current `tests/h2os/**` into `tests/honeyos/**`

**Interfaces:**
- Produces: `python -m honeyos gateway run` as the only gateway process.
- Produces: the same companion tool definitions and prompt/memory hooks as current main.

- [ ] **Step 1: Add an import-closure test**

```python
def test_runtime_imports_only_honeyos_modules():
    completed = subprocess.run(
        [sys.executable, "-c", "import honeyos; import honeyos.gateway.run; import honeyos.agent.conversation_loop"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "hermes_cli" not in completed.stderr
```

- [ ] **Step 2: Move one subsystem at a time with mechanical import rewrites**

Order: companion/config first, then agent, tools, scheduler, gateway, Weixin, Feishu. For each move, replace imports with absolute `honeyos.*` imports and run that subsystem's existing tests before moving the next subsystem.

- [ ] **Step 3: Replace environment and path constants**

All runtime state lookups use `HONEYOS_HOME` or an explicit `Path`; remove `HERMES_HOME`, `H2OS_HOME`, `H2OS_RUNTIME_ID`, and `H2OS_PRODUCT_NAME` except from migration fixtures that verify they are removed from copied config/service files.

- [ ] **Step 4: Run retained feature tests**

Run: `uv run pytest tests/honeyos -q`

Expected: PASS for model setup, Weixin/Feishu, continuity, distillation, memory policy, tool handback, skill management, todo, cron, service lifecycle, and runtime imports.

- [ ] **Step 5: Verify tool surface exactly**

Run: `uv run python -m honeyos doctor --distribution`

Expected: PASS with required tools `companion_memory`, `memory`, `session_search`, `browser_navigate`, `skills_list`, `skill_manage`, `todo`, and `cronjob`; forbidden work tools remain absent.

- [ ] **Step 6: Commit**

```bash
git add honeyos tests/honeyos pyproject.toml
git commit -m "refactor: migrate agent runtime into HoneyOS"
```

### Task 5: Delete unrelated source and enforce the minimal repository

**Files:**
- Delete after migration: `h2os_cli/`, `hermes_cli/`, `agent/`, `gateway/`, `tools/`, `cron/`
- Delete unused product trees: `apps/`, `web/`, `website/`, `ui-tui/`, `tui_gateway/`, `assets/`, `datagen-config-examples/`, `mcp-research-data/`, `optional-mcps/`, `optional-skills/`, `nix/`, `tests-js/`, `acp_adapter/`
- Delete unused delivery trees: `docker/`, upstream installers, upstream README translations, demos and unrelated docs.
- Modify: `.gitignore`, `README.md`, `pyproject.toml`, `uv.lock`
- Create: `NOTICE`

**Interfaces:**
- Consumes: the import closure proven in Task 4.
- Produces: a repository whose installable runtime is entirely under `honeyos/`.

- [ ] **Step 1: Generate and review the retained-file manifest**

The manifest must include only root packaging/install files, `honeyos/**`, `tests/honeyos/**`, the HoneyOS README/PRDs, license/notice, and necessary CI metadata.

- [ ] **Step 2: Delete directories outside the manifest**

Use exact tracked paths, never a workspace-root recursive deletion. After each group, run the import-closure and relevant feature tests so missing dynamic imports are discovered at the group that removed them.

- [ ] **Step 3: Minimize dependencies and regenerate the lock**

Remove dependencies and extras not imported by the retained runtime. Run `uv lock` followed by `uv sync --locked`.

- [ ] **Step 4: Run forbidden-name and full retained tests**

Run: `uv run pytest tests/honeyos/test_repository_surface.py tests/honeyos -q`

Expected: PASS; only legal notice and legacy migration code/tests contain old names.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: prune repository to HoneyOS runtime"
```

### Task 6: Build the user ZIP and prove clean install/coexistence

**Files:**
- Create: `scripts/build_release_zip.sh`
- Create: `tests/install/test_honeyos_zip.sh`
- Create: `tests/honeyos/test_runtime_coexistence.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `dist/honeyos-0.3.0.zip`.
- Consumes: the minimal tracked-file manifest from Task 5.

- [ ] **Step 1: Add a deterministic archive builder**

The script exports only tracked files from `HEAD`, names the root directory `honeyos-<version>`, excludes `.git`, caches, local environments, logs, credentials, and all user homes, and writes a SHA-256 checksum next to the ZIP.

- [ ] **Step 2: Add clean-install verification**

The install test extracts the ZIP into a temporary directory with a temporary `HOME`, runs dependency sync, invokes `honeyos init`, and asserts that only `.honeyos` and the HoneyOS service definition are created.

- [ ] **Step 3: Add coexistence verification**

Create sentinel files and fake exact-label service states for both HoneyOS and Hermes. Run HoneyOS install/start/restart/stop/migration operations and assert byte-for-byte unchanged Hermes sentinels and unchanged Hermes service calls.

- [ ] **Step 4: Run final acceptance**

Run:

```bash
uv sync --locked
uv run pytest tests/honeyos -q
/bin/sh tests/install/test_honeyos_zip.sh
/bin/sh scripts/build_release_zip.sh
unzip -l dist/honeyos-0.3.0.zip
```

Expected: all tests pass; archive contains one HoneyOS root, no ignored/private files, and no unused upstream product trees.

- [ ] **Step 5: Commit and open PR**

```bash
git add README.md scripts tests dist/*.sha256
git commit -m "build: ship standalone HoneyOS user archive"
git push -u origin agent/honeyos-standalone-runtime
gh pr create --repo Nicole202504/test_ai_0806 --base main --head agent/honeyos-standalone-runtime
```

The PR body must link the design and this plan, enumerate deleted top-level trees, report retained test counts, show the ZIP file count/size/checksum, and include the Hermes coexistence result.
