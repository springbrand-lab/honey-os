# HoneyOS Builder Activation and Rollback

## Status

Proposed design for the user-approved continuation of PR #25. The controlled
Builder already prepares and inspects an isolated candidate. This design adds
the missing owner-confirmed activation path without requiring GitHub.

## Product decision

Self-improvement is available by default to the owner of every HoneyOS
companion. A product-level candidate never becomes live merely because the
model finished editing it. Each core-version activation requires one explicit,
candidate-specific confirmation from an owner DM.

The end-user flow is:

```text
ordinary-language request
→ isolated candidate
→ tests and activation preflight
→ “new version is ready” confirmation
→ staged version slot
→ atomic service switch and restart
→ health check
→ success receipt, or automatic rollback
```

The user does not need a GitHub account, a repository, or a terminal. Pull
requests remain a developer workflow for product-wide releases and are not part
of local activation.

## Scope boundaries

| User intent | Product path | Activation behavior |
| --- | --- | --- |
| Change name, tone, relationship, or remembered content | Typed profile and memory interfaces | Immediate |
| Add an independent capability | Normal Skill, tool, MCP, or workflow | Install and continue the task; no core restart |
| Change safe visual presentation tokens, copy, or avatar | Companion UI overlay | Apply after the explicit request; reversible without a core restart |
| Change memory logic, sessions, structural Web UI, IM adapters, routing, or Runtime | Controlled Builder | Candidate-specific owner confirmation, version switch, restart, health check |
| Change credentials, approval policy, authentication, Builder safeguards, activation safeguards, or filesystem boundaries | Hard blocked | Never self-activated |

The first activation release also blocks dependency and build-system changes
(`pyproject.toml`, lockfiles, installer scripts, CI/release scripts). Allowing a
candidate to introduce and execute new supply-chain code requires a separate
reviewed design. Candidates in this release may change existing HoneyOS Python,
Web assets, adapters, prompts, Skills, and tests within the manifest's explicit
allowed paths.

Candidate code is untrusted until the owner confirms one exact digest. That
confirmation promotes it to the trusted local HoneyOS application. The active
application must read memories, render the Web UI, and perform companion work,
so it runs with HoneyOS's local capabilities. This design protects against
scope drift, candidate tampering before confirmation, startup/data failure, and
irreversible deployment; it does not claim a same-user sandbox against
intentionally malicious Python or JavaScript after activation. Credentials and
channel binding, profile redaction, permission/model-control routing, message
delivery routing, bundled Skill instructions, and prompt templates stay outside
the release-1 activatable surface.

## User experience

### Candidate preparation

Honey remains in character and says it is working on a safe copy. Raw terminal,
patch, and test commands remain behind the product activity layer. The current
chat and current HoneyOS version stay available while the candidate is built.

### Confirmation

After inspection and staging succeed, Honey sends one durable confirmation:

> 我把这次改动准备好了。它会改善「跨渠道记忆」，不会动你的记忆、人格、API Key 和飞书配置。启用时我会短暂重启一下；如果起不来，我会自己退回现在这版。要现在启用吗？

The Web channel renders the existing confirmation card. Feishu and Weixin use
the gateway's channel-native confirmation path or a bound natural-language
confirmation. The confirmation displays:

- the user-visible goal;
- changed product areas;
- tests and preflight status;
- protected data that remains untouched;
- expected brief restart;
- automatic rollback promise.

“Confirm” is bound to one immutable candidate digest, one owner session, and a
short expiry. A stale confirmation cannot activate a changed candidate.

### Restart and return

The confirmation turn first acknowledges the switch in relationship language.
A detached trusted activation worker performs the switch so stopping the old
gateway cannot kill the operation. After startup, Honey delivers a durable
result receipt to the owner's most recently used channel:

- success: the new version is active and the relationship continues;
- rollback: the new version failed its health check, the old version and data
  were restored, and a concise reason is shown;
- indeterminate: the old version remains selected and the user receives a
  recovery instruction rather than a false success.

The next user message uses the same canonical owner session and existing
memory. No new conversation is created.

## Architecture

### 1. Trusted activation control plane

The activation implementation is trusted code in the currently stable
HoneyOS, not code imported from the candidate. It owns:

- staging and validating immutable version slots;
- issuing and consuming confirmation tokens;
- creating data snapshots;
- changing the service executable;
- health checks and rollback;
- activation audit records.

All activation modules, CLI commands, manifests, service-switch helpers, and
confirmation handlers are added to `DEFAULT_PROTECTED_PATHS`. A candidate may
not modify or widen this control plane.  Release 1 additionally uses a
running-code-owned `DEFAULT_ACTIVATABLE_PATHS` allowlist: only explicit
companion product behavior, persona/memory, browser presentation, ordinary
companion skills, tests, and documentation can be eligible for activation.
The host agent loop, gateway, runtime, tool dispatch, CLI, core, and provider
trees are protected wholesale. Classification is protected-first, then the
static allowlist, then the task's requested scope.

The Builder model can edit only its isolated candidate `source` workspace.
Its identity, goal, base revision, and requested scope are recorded in
`trusted-policy.json` outside that workspace. The candidate-visible manifest
is a mirror and is rejected when it differs, which keeps reviews coherent and
auditable. This metadata is not a sandbox or security boundary: a same-user
terminal may change local state. The static activation allowlist in the
currently running code is the security boundary; dynamic requested scope only
narrows the task and improves review UX.

### 2. Version slots

Candidate source is copied out of the user-editable Builder workspace into a
private immutable slot:

```text
~/.honeyos/runtime/
├── current.json
├── slots/
│   ├── legacy-<digest>/
│   │   └── runtime.json
│   └── <change-id>-<digest>/
│       ├── source/
│       ├── venv/
│       ├── runtime.json
│       └── preflight.json
└── activations/
    └── <activation-id>.json
```

`current.json` is a private atomic pointer containing the active slot, previous
slot, executable, source digest, and activation generation. The existing
installation is registered as the initial legacy slot without moving or
rewriting it.

Slot creation first materializes a complete baseline from a trusted
`git archive` of the recorded source commit, then overlays only reviewed
changed/deleted paths using a no-symlink copier. It rejects path traversal,
executable additions outside known script locations, changed source HEAD, and
candidate changes made after inspection. The complete slot-tree hash, manifest,
source commit, and reviewed-diff hash must match before confirmation and again
before switching. The slot contains no `.git` directory.

### 3. Staging and preflight

`honeyos builder stage <change-id>` performs only non-live work:

1. require the latest inspection status to be `review_ready`;
2. require the live source revision to equal the candidate's recorded base;
3. recompute and bind the candidate digest;
4. materialize the complete pinned source tree into a private slot without
   `.git`, credentials, real data, or the Builder workspace's environment;
5. create an isolated virtual environment from the already-approved dependency
   set;
6. run syntax/import checks, targeted tests, core Builder safety tests, and CLI
   startup smoke checks with synthetic temporary data;
7. write a private preflight receipt.

Staging does not change the running service and does not need activation
confirmation. A failed stage leaves the old HoneyOS untouched and produces no
activatable token.

### 4. Owner confirmation

The companion receives an `activation_ready` result from staging and asks via
a dedicated gateway-owned durable activation confirmation system. It does not
reuse the model's command-approval queue. The stored confirmation contains:

- activation ID and candidate digest;
- canonical `agent:main:companion:dm:owner` lane;
- originating and most-recent delivery channels;
- issued and expiry times;
- single-use state;
- redacted goal and changed-area summary.

Only an authenticated owner DM can resolve it. Web and IM surfaces receive a
compact opaque callback ID whose secret mapping stays server-side and never
appears in model context or assistant text. Group chats, background jobs,
tool-generated messages, replayed buttons, and model-issued shell commands are
rejected. Denial or expiry leaves the staged slot available for later restaging
but never live.

### 5. Detached switch worker

The trusted stable runtime launches a detached worker with a private activation
record and a sealed inherited capability/FD, not an activation shell command or
arbitrary model-provided arguments. The worker:

1. acquires a global activation lock;
2. rechecks confirmation, hashes, base version, available disk, and slot health;
3. records the exact old managed-service definition and current pointer;
4. creates an activation-specific SQLite-safe snapshot receipt containing the
   exact required file set, manifest digest, and database integrity results;
5. drains and stops the gateway;
6. updates the managed service to the new slot's interpreter and source;
7. atomically writes the new current pointer;
8. starts the gateway;
9. waits for bounded health checks;
10. commits success or performs rollback.

The worker never imports candidate Python. Candidate code first executes only
inside the isolated preflight process and then in the newly started gateway.
Service installation has a true no-load/no-start mode on launchd, systemd,
Windows, and s6; the worker starts the candidate only after durable checkpoints.

### 6. Health checks

Activation succeeds only when all required checks pass within a bounded window:

- managed service is registered and running;
- the local health endpoint responds;
- a new-process startup attestation reports the expected candidate digest,
  resolved data directory, PID/start identifier, and stable runtime ID;
- the canonical state database passes SQLite integrity checks;
- the owner session can be opened without resetting history;
- configured IM adapters complete startup or report the same explicitly
  tolerated offline state they had before activation.

No model call is required for the health decision. Provider outages cannot
cause a healthy runtime to be rolled back.

### 7. Automatic rollback

On failed startup or health validation, the detached worker:

1. stops the candidate service;
2. restores the exact old service definition and current pointer;
3. restores the pre-activation data snapshot if the candidate touched or
   migrated state;
4. starts the old gateway;
5. verifies every restored artifact, SQLite integrity, the old health endpoint,
   and the old-process attestation;
6. records and delivers a rollback receipt.

The failed slot and redacted logs remain available for diagnosis but cannot be
retried without a new confirmation.

Immediate automatic rollback is data-safe because it restores the snapshot
created immediately before the switch. A later user-requested rollback after
new conversations have occurred switches code only when data compatibility is
declared; it never silently restores an old data snapshot and loses newer
messages.

## Persistence and upgrade safety

Program versions and user data remain separate. Activation never overlays or
deletes:

- `SOUL.md`, `IDENTITY.md`, or `RELATIONSHIP.md`;
- `state.db`, structured memories, correction journals, or chat history;
- model credentials, API keys, or IM bindings;
- installed user Skills and projects;
- cron jobs, proactive-chat settings, or pending owner pairings.

The data snapshot reuses the existing SQLite-safe primitives but adds a strict
activation receipt: activation stops before service mutation unless every
required artifact is captured and verified, and rollback is not declared until
every artifact is restored and verified. In-flight activation snapshots have
independent retention from ordinary quick-snapshot pruning. Secrets are never
placed in the candidate slot or activation report.

Schema-changing candidates must declare a migration contract. In the first
activation release, a candidate that changes known schema or migration files is
blocked unless the trusted control plane recognizes a reversible migration and
successfully rehearses it against a sanitized snapshot. This prevents a code
rollback from leaving data readable only by the failed version.

## CLI and tool surface

The trusted CLI gains:

```text
honeyos builder stage <change-id>
honeyos builder activation-status <activation-id>
honeyos builder rollback <activation-id>   # operator recovery only
```

Activation itself is not exposed as an ordinary model-callable shell command.
It is consumed through a dedicated owner-confirmation handler using a private,
single-use server-side callback. Model-facing terminal/code execution policy
blocks activation worker, switch, and rollback routes. The Builder Skill may
prepare, inspect, and stage; it may only request activation confirmation, never
approve its own request.

## State machine

```text
prepared
→ review_ready
→ staged
→ awaiting_confirmation
→ switching
→ healthy

awaiting_confirmation → denied | expired
switching → rolling_back → rolled_back
switching → recovery_required
```

Every transition is append-audited with private `0600` files. Repeated channel
delivery or button clicks are idempotent. At most one activation may be in
`switching` or `rolling_back` state per HoneyOS home.

## Error handling

- Candidate changed after review: invalidate staging and ask Honey to prepare a
  fresh candidate.
- Live version changed before activation: reject the stale candidate; never
  three-way merge automatically.
- Insufficient disk or environment build failure: fail before confirmation.
- Confirmation replay or wrong channel/user: reject without state change.
- Gateway stop kills the originating turn: detached worker continues and the
  receipt is delivered after restart.
- New gateway unhealthy: automatic rollback.
- Old gateway also unhealthy after rollback: keep the old version pointer,
  preserve both slots and snapshots, mark `recovery_required`, and show one
  concrete recovery command.
- Power loss during switching: startup reconciliation reads the activation
  journal and finishes rollback or validates the selected slot; it never guesses
  from partially written files.

## Retention

Keep the active slot, previous healthy slot, and the three most recent other
healthy slots. Failed slots are retained for seven days unless disk pressure
requires earlier cleanup. Completed activation snapshots may join ordinary
backup retention only after the activation settles. In-flight snapshots and
active, previous, switching, or recovery-required assets are never pruned.

## Verification and acceptance criteria

Automated tests must prove:

1. PR #25's existing prepare/inspect boundaries remain intact.
2. A candidate cannot activate changes outside the running release's static
   companion product surface, including activation, approval, auth, Builder,
   dependency, filesystem-safety, host agent-loop, gateway, runtime, and tool
   dispatch code, even if same-user metadata is broadened.
3. Staging never reads or copies real user data or credentials.
4. Changed candidate bytes invalidate the confirmation.
5. Wrong-owner, group, expired, replayed, and model-forged confirmations fail.
6. Successful activation switches the service executable and preserves the
   same data directory and canonical owner session.
7. Process death between each switch step recovers to wholly old or wholly new,
   never a mixed state.
8. Failed health checks restore the old service and SQLite-safe snapshot.
9. Provider/network failure alone does not trigger rollback.
10. Web, Feishu, and Weixin receive one consistent confirmation/result state.
11. Ordinary Skill installation still completes without a core restart.
12. Existing user memories, persona, credentials, channel bindings, scheduled
    tasks, UI overlays, and projects survive both activation and rollback.

The first live acceptance test uses a synthetic HoneyOS home and a disposable
managed service. Real user data is not used to validate the installer.

## Non-goals for the first release

- installing arbitrary new dependencies from a candidate;
- changing Builder or activation safeguards through self-improvement;
- pushing to GitHub or creating a PR for the user;
- multi-user or group approval;
- remote/server fleet rollout;
- silently activating without a fresh owner confirmation.
