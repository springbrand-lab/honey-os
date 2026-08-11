# Task 3 Brief: Non-executing candidate preflight

## Objective

Statically validate a staged slot without executing any candidate code. A
failed or forged receipt cannot become confirmable.

## Required reading

- Design and implementation plan, Task 3
- `.superpowers/sdd/activation-plan-feasibility-report.md`, B1, S2
- `.superpowers/sdd/task-2-report.md`
- `honeyos/companion/builder_activation.py`

## Files

- Modify `honeyos/companion/builder_activation.py`
- Modify `tests/honeyos/test_builder_activation.py`
- Create `tests/honeyos/test_builder_preflight.py`
- Append `.superpowers/sdd/task-3-report.md`

## Required behavior

1. Add `preflight(activation_id) -> PreflightReceipt` using trusted static checks only.
2. Receipt is private/atomic and binds candidate digest plus full slot-tree
   digest. It includes success, fixed ordered checks, source root, and bounded errors.
3. Revalidate evidence and full slot bytes, required release artifacts, path
   types/modes/sizes, and Python syntax using `ast.parse` only.
4. Never import candidate modules, run candidate tests/CLI, start a candidate
   subprocess, or access real data/network/providers before confirmation.
5. Recompute all static checks before entering `awaiting_confirmation`; do not
   trust a same-user-writable receipt's success bit.
7. Only a successful receipt permits transition/request to
   `awaiting_confirmation`. Failure records state/detail but does not issue or
   expose confirmation material.
8. Do not start/stop/install gateway services, call providers, use real data,
   or implement owner confirmation in this task.

## Required TDD cases

- malicious candidate code that writes outside the slot is never executed;
- invalid Python syntax fails closed;
- preflight failure blocks awaiting-confirmation;
- missing release artifacts and slot mutation fail closed;
- forged/incomplete receipts are rejected;
- a real distribution archive without exported tests still passes;
- no candidate subprocess/provider/network/channel call occurs.

## Verification

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py tests/honeyos/test_builder_preflight.py
.venv/bin/ruff check honeyos/companion/builder_activation.py tests/honeyos/test_builder_preflight.py
git diff --check
```

Record RED/GREEN evidence and self-review, then commit the Task 3 files,
distribution dependency declaration/lock, updated transition test, and report.
