# Task 3 Brief: Isolated candidate preflight

## Objective

Build and test a staged slot with synthetic data only, proving that candidate
imports and checks come from the slot rather than the running checkout. A failed
preflight cannot become confirmable.

## Required reading

- Design and implementation plan, Task 3
- `.superpowers/sdd/activation-plan-feasibility-report.md`, B1, S2
- `.superpowers/sdd/task-2-report.md`
- `honeyos/companion/builder_activation.py`

## Files

- Modify `honeyos/companion/builder_activation.py`
- Modify `pyproject.toml`
- Modify `uv.lock`
- Modify `tests/honeyos/test_builder_activation.py`
- Create `tests/honeyos/test_builder_preflight.py`
- Append `.superpowers/sdd/task-3-report.md`

## Required behavior

1. Add injectable `ProcessRunner` and
   `preflight(activation_id, runner=None) -> PreflightReceipt`.
2. Receipt is private/atomic and binds candidate digest plus full slot-tree
   digest. It includes success, bounded duration, checks, slot interpreter,
   source root, and redacted bounded errors.
3. Create a slot-local venv from the trusted current interpreter. Install the
   complete slot source non-editably using the unchanged approved packaging and
   lock artifacts from the pinned baseline. The regular `honeyos` distribution
   extra must include pinned pytest so a normal desktop install provides the
   fixed boundary-test runner; make the slot venv see only that current trusted
   runtime dependency set, never an editable live checkout. Fail closed if
   approved artifacts or required test tooling are unavailable.
4. Every process uses `cwd=slot/source`, a fresh synthetic HOME and
   `HONEYOS_HOME`, cleared `PYTHONPATH`/`VIRTUAL_ENV`, no inherited `PIP_*`,
   `UV_*`, proxy, credential, provider, channel, or HoneyOS product variables.
   Set `PYTHONPYCACHEPREFIX` to a disposable synthetic cache outside the
   read-only `slot/source`; compile/import/tests must never write there.
   No real `HONEYOS_HOME` path/value/secret appears in argv/env/output.
5. Run syntax compile, slot-origin import assertion, CLI help/smoke, Task1
   boundary tests, and focused candidate-affected tests selected only from the
   reviewed test paths. Use bounded timeouts and output limits.
6. Revalidate candidate and full slot digest before and after preflight. A test
   or build step that mutates slot source fails closed.
7. Only a successful receipt permits transition/request to
   `awaiting_confirmation`. Failure records state/detail but does not issue or
   expose confirmation material.
8. Do not start/stop/install gateway services, call providers, use real data,
   or implement owner confirmation in this task.

## Required TDD cases

- runner observes only synthetic homes and sanitized env;
- imported `honeyos.__file__`/`honeyos.runtime.main` are below slot source;
- live checkout cannot make a broken candidate pass;
- preflight failure blocks awaiting-confirmation;
- missing approved packaging/test artifacts fails closed;
- command timeout and secret-looking output are bounded/redacted;
- slot mutation during checks invalidates receipt;
- successful private receipt includes both digests and correct interpreter;
- no provider/network/channel call is attempted.
- a normal `honeyos` runtime install declares the pinned preflight test runner;
- a real slot subprocess preflight succeeds with that runtime dependency and
  fails closed when it is unavailable.

## Verification

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py tests/honeyos/test_builder_preflight.py
.venv/bin/ruff check honeyos/companion/builder_activation.py tests/honeyos/test_builder_preflight.py
git diff --check
```

Record RED/GREEN evidence and self-review, then commit the Task 3 files,
distribution dependency declaration/lock, updated transition test, and report.
