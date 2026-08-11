# Task 4 brief — simplified Builder activation

Builder is a default product capability, not a GitHub or specialised gateway
approval flow.  It exposes only a partial mutable companion layer, creates an
immutable complete slot, runs static preflight, waits for the companion to
receive the user's ordinary affirmative reply, then atomically switches and
restarts the local service.  A failed health check restores the previous slot.

User data in `~/.honeyos`, including memory, configuration and credentials,
must remain byte-for-byte untouched.  Ordinary Skill installation, project
coding, and persona/configuration changes do not use Builder.
