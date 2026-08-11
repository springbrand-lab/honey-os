# Controlled HoneyOS Self-Builder

## Status

Builder is available by default for product-level companion improvements.  It
uses a partial candidate workspace, a normal conversational confirmation, and
an atomic slot switch with automatic rollback.

## Product routing

| User intent | Product path |
| --- | --- |
| Name, tone, relationship, or remembered fact | Profile and memory data interfaces |
| Independent capability | Normal Skill/tool/MCP; installed Skill is usable immediately |
| User's own files or game/app | Direct work in HoneyOS Projects |
| Companion web UI, activity/copy, bundled companion Skill, extension | Controlled Builder |
| Credentials, approvals, service/update code, gateways, database migrations | Not self-modifiable |

## Candidate boundary

Builder copies only a fixed mutable layer into `HoneyOS Projects/HoneyOS
Builder`.  It does not clone the repository or expose `.git`.  The layer is
limited to companion web assets, `activity.py`, `status_copy.py`,
`topic_scout.py`, `extensions/**`, and ordinary `companion_skills/**`.

Memory persistence and distillation, profile/config/channel routing, persona
templates, credentials, service code, installer/updater, approval/security
policy, Builder control code, dependencies, and all user data are deny-by-
default.  The fixed allowlist is in the currently running Builder code rather
than candidate metadata.

## User flow

Honey prepares and reviews a candidate, explains the result in character, and
asks: “我改好了，现在换上吗？”.  Only after the user gives an ordinary affirmative
reply does Honey run `honeyos builder activate <change-id>`.

Activation materializes a complete immutable code slot, verifies its static
evidence and changed Python syntax without executing candidate code, preserves
the prior slot pointer, then atomically switches the current pointer and
restarts the trusted service.  The normal health check gets up to 30 seconds.
If it fails, HoneyOS restores the old pointer and restarts the old service.

No GitHub login, pull request, bespoke approval token, callback secret, or
channel-specific confirmation card is required for this local user flow.

## Data continuity

The active slot only changes code selection.  `~/.honeyos` remains the same
data home before and after switching: memory, conversations, identity,
relationship, model configuration, voice settings and credentials are neither
copied nor modified by Builder.  The next user message continues in the same
runtime data context.

## Current limit

Before confirmation Builder performs only static checks.  Dynamic smoke tests
for candidate code belong to a later post-confirmation worker task.
