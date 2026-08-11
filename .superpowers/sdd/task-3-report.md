# Task 3 report — non-executing candidate preflight

## Review correction

The first implementation created an isolated-looking environment but executed
candidate imports, CLI code, and tests before owner confirmation. A real review
proved that synthetic environment variables are not an OS sandbox: candidate
code could still read and write arbitrary same-user paths. The real release
archive also excludes `tests/`, so requiring pytest tests made production
preflight fail even though the synthetic fixture passed.

## Final behavior

- Confirmation-time preflight performs only trusted static operations.
- It revalidates staged metadata and the full slot digest, required release
  artifacts, file types/modes/sizes, and parses changed Python with `ast.parse`.
- Candidate Python, tests, CLI, imports, subprocesses, providers, channels, and
  network are never executed before the owner confirms the exact digest.
- The private receipt has a fixed ordered check set and binds both digests.
  Transition to `awaiting_confirmation` validates its structure and recomputes
  every static check, so a forged success bit is not authoritative.
- The flow works with the real release archive where `tests export-ignore` is
  active. Dynamic smoke and health checks are deferred until after owner
  confirmation in the activation worker task.
- The temporary pytest runtime dependency and `.pth` dependency bridge were
  removed; ordinary users do not need developer dependencies for static review.

## Verification

Focused Task 3 plus activation tests passed (`28 passed`). Full Task 1–3 and
lint verification is recorded in the follow-up commit that closes this review.
