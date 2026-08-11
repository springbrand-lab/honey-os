# Controlled HoneyOS Self-Builder

## Status

MVP implemented as a review-only candidate workflow. Automatic installation,
restart, migration, and rollback are intentionally out of scope.

## Product background

HoneyOS is a personal companion, so users naturally speak to it as the product
itself: “remember me better”, “make your Feishu replies feel alive”, or “improve
your web conversation page”. These requests are different from both changing a
persona and installing a standalone Skill. They ask HoneyOS to improve the
software that produces the relationship experience.

The previous product model had only two useful outcomes:

1. turn the request into a normal Skill, even when it actually requires changes
   to memory, sessions, channel adapters, or the web client; or
2. let a local agent edit source with the host user's filesystem permissions.

The first outcome is too weak. The second confuses user intent with safe runtime
authority: the same companion process could edit the checkout it is currently
running, touch permission code, or leave no reliable path back to a working
version.

## Product decision

“Change yourself” is split into four product capabilities:

| User intent | Product path |
| --- | --- |
| Change name, tone, relationship, or remembered content | Typed profile and memory interfaces |
| Add an independent capability | Normal Skill, tool, MCP, or workflow |
| Change HoneyOS memory, sessions, UI, IM adapter, or Runtime | Controlled Builder candidate |
| Change credentials, approvals, permission boundaries, or Builder safeguards | Hard blocked from self-modification |

The companion remains the conversational front door. A Builder workflow does
the code work in a separate candidate checkout. The MVP never installs that
candidate and therefore never replaces the running companion.

## User experience

The user can ask in ordinary language. HoneyOS should respond in character:

> 可以。我会在一个不会影响现在这个我的副本里调整记忆逻辑。现在的聊天和记忆不会丢，改好后我先把结果给你看。

User-facing progress describes outcomes rather than raw tool calls:

- understanding the current behavior;
- preparing a candidate version;
- checking that existing data and behavior remain safe;
- reporting that a candidate is ready for human review.

The result must distinguish “candidate ready” from “enabled”. It includes the
goal, changed scope, tests, blocked paths, and the fact that the live HoneyOS
version remains unchanged.

## MVP technical design

### Builder Skill

The bundled `honeyos-builder` Skill classifies product-level requests, keeps
updates in character, chooses a minimal allowed path scope, prepares the
candidate, runs tests, and inspects the final diff. The existing
`honeyos-self-extension` Skill routes product-level changes to this workflow.

The Skill is orchestration guidance. It is not the security boundary.

### Candidate workspace

`honeyos builder prepare` creates a clone under the managed project root:

```text
~/HoneyOS Projects/HoneyOS Builder/
└── changes/<change-id>/source/       # candidate Git checkout
```

The live checkout is only a clone source. All candidate edits happen on a new
`honeyos-builder/<change-id>` branch in the clone.

### Protected policy state

The manifest is stored outside the ordinary writable project workspace:

```text
~/.honeyos/builder/
└── changes/<change-id>/
    ├── manifest.json                 # mode 0600
    └── review.json                   # diff classification
```

The manifest records the source commit, candidate workspace, allowed globs,
protected paths, denied real-data access, and `review_only` installation mode.
This prevents ordinary candidate edits from silently rewriting their own scope.

### Review gate

`honeyos builder inspect <change-id>` reads Git status and classifies every
changed path in this order:

1. protected path;
2. allowed path;
3. out of scope.

Protected or out-of-scope changes produce `blocked`. An allowed-only diff
produces `review_ready`. Both states remain non-installable in the MVP.

Protected paths include Builder implementation, approval and permission policy,
filesystem safety, authentication, threat detection, project-boundary logic,
and environment files.

## Security properties

- The running checkout is never used as the candidate workspace.
- The candidate receives no real user memory, sessions, credentials, or tokens.
- An allowed glob cannot be absolute, traverse with `..`, or explicitly name a
  protected path.
- Protected paths take precedence over broad allowed globs.
- The Builder manifest is kept in HoneyOS internal state, not in the normal
  project workspace.
- There is no install, restart, push, merge, permission-grant, or rollback-bypass
  operation in this version.

## Known MVP boundary

The candidate still runs through HoneyOS's local execution backend. Path
classification and the absence of an install operation make the MVP suitable
for producing review artifacts, but this is not yet a general operating-system
sandbox. A production auto-install phase must first add a constrained execution
broker or container with an explicit read/write mount manifest, no credentials,
network off by default, and resource limits.

## Future phases

1. Product card and persistent Builder task status shared by Web and Feishu.
2. Sandboxed test runner with synthetic fixtures and network consent.
3. Human-reviewed PR handoff from a `review_ready` candidate.
4. Versioned release packaging, database migration rehearsal, health check,
   atomic activation, and automatic rollback.
5. One-click “enable new version” only after all earlier boundaries are enforced.
