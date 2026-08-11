# Builder activation and rollback plan

**Goal:** Let Honey prepare a narrowly scoped product improvement, ask the user
in ordinary conversation whether to enable it, and safely switch the local
runtime while preserving all user data.

## Product decision

Builder is enabled for every HoneyOS user.  It is a product-flow confirmation,
not a separate security or approval system: Honey says “我改好了，现在换上吗？”.
When the user answers yes, Honey runs the normal Builder activation command.

The following never enter Builder:

- installing an ordinary Skill (it is usable immediately);
- writing or running a user project in HoneyOS Projects;
- changing identity, relationship, memory entries, model, or voice (their
  established data/configuration paths own those changes).

## Scope boundary

Builder creates a **partial** workspace rather than a clone.  The only mutable
source paths are:

- `honeyos/companion/activity.py`
- `honeyos/companion/status_copy.py`
- `honeyos/companion/topic_scout.py`
- `honeyos/companion/web_assets/**`
- `honeyos/companion/extensions/**`
- `honeyos/companion/companion_skills/**`, except the protected Builder and
  self-extension Skills

Everything else is deny-by-default.  In particular `continuity.py`,
`distillation.py`, `memory_policy.py`, `persistent_memory.py`, `profile.py`,
`topic_pool.py`, `topic_delivery.py`, templates, gateway/pairing, services,
install/update code, approvals, credentials, configuration, database
migrations, and the Builder/activation code itself never appear in the
workspace.

## Flow

1. `honeyos builder prepare` copies only the requested allowed files into
   `HoneyOS Projects/HoneyOS Builder/...`; it never includes `.git` history or
   live user data.
2. Honey edits the partial workspace and runs `honeyos builder inspect`.
3. A reviewed candidate is staged as a complete immutable slot.  Static checks
   verify the source tree, release artifacts, digests, and changed Python
   syntax; they never execute candidate code before confirmation.
4. Honey asks the user in normal language to enable it.  No GitHub account,
   PR, opaque callback, or special owner token is part of the user flow.
5. On an explicit yes, `honeyos builder activate <change-id>` revalidates the
   candidate, writes the old pointer as `previous-slot.json`, atomically writes
   `current-slot.json`, writes a durable handoff journal, restarts the trusted
   service, and waits up to 30 seconds for a real local gateway health response
   and matching source-slot attestation.
6. A healthy service marks the slot `healthy`.  If restart or health fails, it
   restores the previous pointer (or removes a first-install pointer), restarts
   the old service, and marks the record `rolled_back`.

`~/.honeyos` remains the single data home.  Its memory database, configuration,
credentials, persona files, and conversations are never copied, deleted, or
modified by Builder activation.  The restarted service reads the active slot
through its generated service environment while retaining that same data home.

## Verification

- The candidate workspace contains only the listed mutable paths and no `.git`.
- Protected edits are absent from the workspace and rejected by inspection.
- Static preflight is required before `awaiting_confirmation`.
- A successful switch updates the runtime pointer, restarts the service, and
  preserves memory/configuration/credentials byte-for-byte.
- A failing health check restores the previous pointer and restarts it.
- Service definitions on macOS/systemd load the complete active slot through
  `PYTHONPATH` without changing the HoneyOS data home; Linux regenerates and
  daemon-reloads its unit before every switch and rollback.

Dynamic smoke checks are deliberately post-confirmation work for a later task;
this release only performs static candidate validation before a user chooses to
switch.
