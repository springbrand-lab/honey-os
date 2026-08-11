# Task 1 report: bind builder reviews to candidate bytes

## Files changed

- `honeyos/companion/builder_workspace.py`
- `honeyos/runtime/builder_cmd.py`
- `tests/honeyos/test_builder_workspace.py`
- `tests/honeyos/test_builder_cli.py`

## RED evidence

The worktree initially did not contain the prescribed `.venv`, so I created
the locked development environment with `uv sync --extra dev` before running
the required test command.

Command:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py
```

Observed result: `9 failed, 6 passed in 3.05s` (exit 1). The new digest test
failed with `AttributeError: 'BuilderReviewReport' object has no attribute
'candidate_digest'`; each new protected-path case was incorrectly classified
as `review_ready` instead of `blocked`.

## Implementation

- Added a candidate digest to `BuilderReviewReport` and the inspect CLI output.
- Added digesting of source commit, path, Git status, file mode, and bytes in
  sorted path order. Symlinks, unsafe paths, non-files, and unreadable paths
  are rejected; deletions use explicit mode/content markers.
- Made inspection enumerate untracked files individually and account for the
  source side of renames, so policy and digest inputs cover the reviewed tree.
- Persisted `source_commit`, `candidate_digest`, and `reviewed_at` to the
  private `review.json` report.
- Froze activation, runtime, dependency, install/update, service, and approval
  surfaces in the protected-path policy.

## GREEN evidence

Commands:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
.venv/bin/ruff check honeyos/companion/builder_workspace.py honeyos/runtime/builder_cmd.py tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
```

Observed result: `18 passed in 3.52s`; `All checks passed!`.

## Self-review

- `candidate_digest` changes when reviewed candidate bytes change and is stored
  alongside the originating commit and review timestamp.
- The listed activation and dependency paths are blocked even when `--allow
  **` is used.
- The CLI exposes the digest returned by inspection.
- `git diff --check` completed without whitespace errors.

## Commit

`HEAD` — `fix(companion): bind builder reviews to trusted candidate bytes`

## Concerns

No remaining implementation concerns. The development virtual environment had
to be created because it was absent from the fresh worktree; this did not
modify tracked project files.

## Fix after review

### RED evidence

Added regression tests for a committed workspace change, ignored non-cache
content, an explicitly ignored ephemeral cache, a stale policy manifest, an
ordinary Runtime business change, and the release zip script. Then ran:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py
```

Observed result: `6 failed, 17 passed`. The failures demonstrated that a
committed candidate was invisible to the review, ignored content was omitted,
the broad Runtime protection rejected an ordinary Runtime module, stale policy
data was trusted, and `scripts/build_release_zip.sh` was not protected.

### Fix and GREEN evidence

- Candidate inspection now requires workspace `HEAD` to exactly equal the
  manifest's trusted source commit.
- A versioned current policy is written to every new manifest; inspection
  rejects old or altered policy manifests and always classifies against the
  current immutable protected list.
- Ignored non-ephemeral paths are recorded in the reviewed digest and block the
  candidate. Only narrowly named local cache artifacts are ignored, and those
  are not candidate input.
- Runtime protection is precise: service/gateway/backup/activation control
  plane files are blocked while ordinary Runtime business modules remain
  reviewable.
- Release, installer, and updater script patterns now include
  `scripts/build_release_zip.sh`.

Commands:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
.venv/bin/ruff check honeyos/companion/builder_workspace.py tests/honeyos/test_builder_workspace.py
git diff --check
```

Observed results: `23 passed`; `25 passed`; `All checks passed!`; no whitespace
errors. Candidate ordinary code is not subject to an import ban: only the
trusted pre-activation control plane is prohibited from importing or executing
candidate code.
