# Task 4 Report: Owner confirmation and Builder tool

## RED

The focused confirmation test suite was added before the implementation. It
exercises owner authentication, wrong-channel rejection, one-time replay
protection, expiry, restart persistence, digest tampering, and the model tool's
inability to expose callback material or authorize a candidate.

## GREEN

`ActivationStore` now persists private callback records with an opaque id,
digest binding, expiry, canonical owner lane, exact delivery channel, and only
a hash of a server-derived secret. The authenticated resolver verifies all
facts, performs the activation state CAS first, then marks the callback used.
It reaches `authorized`, not `switching`.

`companion_builder` is a default companion toolset member. Its schema exposes
only stage/request/status; it cannot resolve confirmation or launch a worker.

## Deferred

Task 5 owns every post-confirmation dynamic check and the trusted
`authorized -> switching` handoff. No candidate code, provider, network, or
service process is started here.
