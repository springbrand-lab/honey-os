# Task 2 report — private complete version slots

## RED

Command:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py
```

Output before implementation:

```text
11 failed in 1.39s
ModuleNotFoundError: No module named 'honeyos.companion.builder_activation'
```

## Implementation

- Added a private `ActivationStore` below `HONEYOS_HOME/runtime`, with `0700`
  directories and atomic `0600` JSON records.
- Staging verifies the trusted policy, immutable manifest mirror, saved review,
  pinned source-repository `HEAD`, current candidate diff, and reviewed digest.
- The slot is a complete `git archive` of the pinned source revision.  Only the
  reviewed changed/deleted regular files overlay that baseline; links,
  traversal, ignored content, executable candidate files, and `.git` are never
  staged.
- Each slot records the reviewed-diff/candidate digest and a deterministic full
  source-tree digest. `verify_staged()` rechecks both before later promotion.
- Added durable compare-and-swap transitions.  This task does not start/stop a
  service, issue confirmations, alter the active pointer, or read/copy user
  data outside its private runtime control directory.

## GREEN

Commands and outputs:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py
12 passed in 2.08s

.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_activation.py
70 passed in 8.73s

.venv/bin/ruff check honeyos/companion/builder_activation.py tests/honeyos/test_builder_activation.py
All checks passed!

git diff --check
(no output)
```

## Self-review

- Complete baseline: covered by slot tests for package, lockfile, tests, and no
  `.git` directory.
- Pinned source and post-review tampering: covered by changed-`HEAD`, metadata,
  candidate-byte, symlink, executable, and full-slot digest tests.
- Import resolution: `resolve_candidate_module()` only returns a file under the
  staged slot and never imports candidate code; a separate isolated Python
  process proves `honeyos.runtime.main` resolves from the slot rather than the
  live checkout.
- State and privacy: covered by transition/CAS and permissions tests.
- Deferred intentionally: preflight venv, owner confirmation, service switch,
  data snapshots, and rollback belong to later tasks.

## Fix after independent review

### RED

Added tests for disposable Builder workspace cleanup, unrelated live source,
symlinked manifest/policy/review files, read-only source, crashes immediately
before and after slot publication, and importing without POSIX `fcntl`.

Before the fix these cases failed because verification reopened the disposable
workspace, `bundled_root` was unused, published slots and records had no staging
journal, metadata reads followed symlinks, source stayed writable, and the
module imported `fcntl` unconditionally.

### GREEN

- The live bundled Git root must be the reviewed source at the pinned commit.
- Staging copies private manifest/policy/review/path evidence into the slot;
  later verification depends only on that evidence and the full source digest.
- A durable, fsynced staging journal makes crashes before/after slot publication
  recover deterministically on the next store initialization.
- Candidate metadata uses no-follow regular/private-file reads with inode checks.
- The source tree is frozen read-only after its digest is computed; later byte
  changes are still detected.
- File locking selects `fcntl` or `msvcrt` at runtime without a POSIX-only
  module import.
- Extraction/copy happens only inside a private temporary root and uses
  no-follow/inode checks where portable. The documented same-user threat model
  remains explicit; this does not claim a hostile same-user filesystem sandbox.

Verification:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py
21 passed

.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py tests/honeyos/test_builder_activation.py
81 passed in 10.18s

.venv/bin/ruff check honeyos/companion/builder_activation.py tests/honeyos/test_builder_activation.py
All checks passed!

git diff --check
(no output)
```
