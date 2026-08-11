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
