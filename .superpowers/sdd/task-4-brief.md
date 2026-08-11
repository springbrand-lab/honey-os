# Task 4 Brief: Owner confirmation for Builder activation

## Objective

Let the model stage and request activation, but reserve authorization for one
authenticated owner callback bound to an exact static-preflight digest.

## Non-negotiable boundary

- Model actions are `stage`, `request_activation`, and `status` only.
- Callback IDs are opaque routing handles; model output and cards never include
  a confirmation secret.
- The control plane persists only a hash of a server-derived callback secret,
  binds owner lane/channel/digest/TTL, and consumes the callback once.
- `always` is exactly one confirmation, not a saved grant.
- Confirmation enters `authorized` only. Dynamic execution and switching begin
  in Task 5 after this durable CAS.

## Verification

Run focused confirmation, Task 1–4 combined, Ruff, lock, and diff checks.
