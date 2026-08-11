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

## Second fix after review

### RED evidence

Added tests for a private authoritative policy record, mutable-manifest scope
and identity tampering, missing/tampered private policy, policy scope/digest in
the review report, and the gateway/approval/execution enforcement files. Then
ran:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py
```

Observed result: `18 failed, 23 passed in 4.13s`. The failures showed the
existing manifest was the only scope authority and that several actual
gateway/terminal/code-execution/computer-use approval boundaries remained
candidate-editable.

### Fix and GREEN evidence

- Added a `trusted-policy.json` record under the protected Builder state
  change root, outside the candidate `source` workspace. It is mode `0600` and
  records the goal, source identity/base revision, workspace identity, branch,
  and approved scope.
- Inspection loads that record first, validates it, and rejects any mismatch in
  the mutable candidate-visible manifest. The review report records the trusted
  allowed scope and policy digest; the candidate digest includes that policy
  digest as well as the reviewed bytes.
- Expanded the protected set to cover gateway ingress, pairing/auth, terminal,
  execute-code, computer-use permissions, and the discovered runtime approval
  subcommands. Ordinary `honeyos/**` business files remain reviewable when
  within the approved scope.
- Documented the trust assumption: model-driven Builder work can write only the
  isolated candidate `source` directory; HoneyOS state/control-plane storage is
  trusted. This is a filesystem boundary, not a user-facing secret.

Commands:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
.venv/bin/ruff check honeyos/companion/builder_workspace.py tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
git diff --check
```

Observed results: `46 passed in 4.88s`; `All checks passed!`; no whitespace
errors.

### Companion control-plane follow-up

Added RED cases for companion configuration, permission UI, distribution,
project workspace boundary, doctor/health, runtime identity, and setup files.
The focused run initially reported seven failures because those changes were
only out of scope rather than explicitly protected. Added them to the running
protected-path policy, then ran:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
.venv/bin/ruff check honeyos/companion/builder_workspace.py tests/honeyos/test_builder_workspace.py
git diff --check
```

Observed results: `60 passed in 6.75s`; `All checks passed!`; no whitespace
errors.

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

## Third fix after architecture review

### RED evidence

Added a regression matrix that broadens both the candidate-visible manifest
and the same-user `trusted-policy.json` to `**`, then changes
`honeyos/model_tools.py`, `honeyos/toolsets.py`,
`honeyos/agent/agent_runtime_helpers.py`, `honeyos/runtime/middleware.py`, or
`honeyos/tools/registry.py`. Ran:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py
```

Observed result: `5 failed, 45 passed`. Each host execution/control-plane path
was incorrectly marked `review_ready`, showing that task metadata could still
expand the security boundary.

### Fix and GREEN evidence

- Introduced running-code-owned `DEFAULT_ACTIVATABLE_PATHS`, an explicit
  release-1 product surface for companion behavior, persona/memory, browser
  presentation, ordinary companion skills, tests, and docs.
- Protected all agent, runtime, gateway, tools, CLI, core, provider, plugin,
  and migration trees plus root agent-loop/tool-dispatch files. Candidate
  classification is now protected-first, then static allowlist, then dynamic
  task relevance.
- Retained task policy/manifest metadata as an audit and narrowing record, but
  removed the false claim that it is inaccessible to a same-user terminal.
  The static allowlist remains effective when both records are broadened.
- Included exact changed paths with Git status alongside the candidate digest
  in `review.json`, so a later owner confirmation can display exactly what it
  binds.
- Updated the design and implementation plan to document that same-user OS
  state is not a sandbox and that the static activation surface is the security
  boundary.

Commands:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_workspace.py tests/honeyos/test_builder_cli.py
.venv/bin/ruff check honeyos/companion/builder_workspace.py tests/honeyos/test_builder_workspace.py
git diff --check
```

Observed results: `52 passed in 5.77s`; `All checks passed!`; no whitespace
errors.
