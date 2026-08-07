# Langfuse Observability Plugin

This plugin ships bundled with HoneyOS but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
honeyos tools  # → Langfuse Observability

# Manual
pip install langfuse
honeyos plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.honeyos/.env` (or via `honeyos tools`):

```bash
HONEYOS_LANGFUSE_PUBLIC_KEY=pk-lf-...
HONEYOS_LANGFUSE_SECRET_KEY=sk-lf-...
HONEYOS_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
honeyos plugins list                 # observability/langfuse should show "enabled"
honeyos chat -q "hello"              # then check Langfuse for a "HoneyOS turn" trace
```

## Optional tuning

```bash
HONEYOS_LANGFUSE_ENV=production       # environment tag
HONEYOS_LANGFUSE_RELEASE=v1.0.0       # release tag
HONEYOS_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
HONEYOS_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
HONEYOS_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
honeyos plugins disable observability/langfuse
```
