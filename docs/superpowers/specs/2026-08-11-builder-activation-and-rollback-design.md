# Builder activation and rollback design

## Intent

HoneyOS lets a companion adapt a small, explicitly product-facing layer for a
user.  This is not a GitHub workflow.  The companion prepares a candidate,
explains it in its own voice, and waits for the user to say whether to turn it
on.

The confirmation prevents accidental replacement of the running product.  It
is intentionally the existing normal conversational confirmation, not a new
gateway authorisation system, owner token, callback secret, or special card.

## Mutable product layer

`builder_workspace.py` is the trusted, fixed boundary.  It copies source bytes
from a pinned Git revision into a partial workspace, never a complete source
checkout.  A candidate can contain only:

| Area | Mutable files |
| --- | --- |
| Interface | `honeyos/companion/web_assets/**` |
| Companion copy/activity | `activity.py`, `status_copy.py`, `topic_scout.py` |
| Extension surface | `extensions/**`, ordinary `companion_skills/**` |

The worktree contains no Git history and all non-listed paths are unavailable.
Memory persistence, deletion/migration, profile/configuration/channel routing,
service setup, authentication/pairing, approval, dependencies and Builder
itself remain protected.  Persona data remains in its normal `~/.honeyos`
files rather than becoming a code change.

## Activation state machine

```
partial workspace → review_ready → staged → awaiting_confirmation
                                          ↓ (user says yes)
                                      switching → healthy
                                          ↓
                                    rolling_back → rolled_back
```

Before confirmation, static preflight verifies complete slot metadata and
digests, the immutable source tree, required release artifacts, and AST syntax
of changed Python.  It does not import, execute, install, test, or network the
candidate.

`activate_confirmed()` only accepts an `awaiting_confirmation` record.  It
re-runs static checks, records the old pointer, atomically switches the current
slot pointer, restarts the trusted service, and polls its normal health status
for at most 30 seconds.  Failure atomically restores the old pointer and
restarts that service.  State transitions are durable CAS updates, so a
duplicate natural-language confirmation cannot activate the same record twice.

## Data continuity

Slots contain code only.  The service gets an active slot `PYTHONPATH`, but its
`HONEYOS_HOME` remains unchanged.  Builder activation neither reads nor writes
the memory database, model/config file, credentials, identity/relationship
files, channel pairing, or chat history.  A successful restart therefore uses
the same conversation and memory on the next message.

## Non-Builder operations

Ordinary Skills install and become usable without a runtime switch.  User
projects are edited directly inside HoneyOS Projects.  Personality, memory,
model and voice requests use the existing specialised data/configuration paths.
They must not stage product code or trigger Builder activation.

## Follow-up

This design intentionally leaves candidate dynamic smoke tests to a later,
post-confirmation trusted worker.  It also does not add a special Web/Feishu
confirmation callback; both channels use their ordinary chat confirmation
experience.
