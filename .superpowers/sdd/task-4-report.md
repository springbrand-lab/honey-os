# Task 4 report — simplified Builder activation

## RED

- `test_builder_activate_stages_static_checks_then_uses_plain_confirmation`
  failed because `activate` did not exist and preparation still reported
  `review_only`.
- `test_public_honeyos_command_exposes_builder` failed because the installed
  `honeyos` command did not expose Builder.

## GREEN

- `honeyos builder activate <change-id>` now stages, performs static preflight,
  records `awaiting_confirmation`, then switches/restarts with rollback on an
  unhealthy service.  It is called only after Honey has interpreted the user's
  ordinary affirmative reply.
- Builder workspaces contain only the fixed mutable companion allowlist and no
  Git checkout.  Memory persistence, delivery/routing and user-data files are
  outside the workspace.
- The public CLI exposes Builder, the service loads an active complete slot via
  `PYTHONPATH`, and activation tests prove successful switching and rollback
  without modifying memory/configuration/credentials.
- Linux rewrites and reloads its user unit for the current slot before every
  restart.  Health requires the local gateway `/health` response and the live
  gateway's source-slot attestation, not merely a service-manager process
  state.  An interrupted switch journal restores the prior pointer when the
  Store next opens.

## Verification

- Builder/activation/service/skill/config/distribution/Web combined run:
  **194 passed**.
- Ruff on all changed Python files: **passed**.
- `uv lock --check`: **passed**.
- staged and unstaged whitespace diff checks: **passed**.
