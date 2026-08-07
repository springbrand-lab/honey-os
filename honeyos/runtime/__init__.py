"""
HoneyOS CLI - Unified command-line interface for HoneyOS.

Provides subcommands for:
- honeyos chat          - Interactive chat (same as ./honeyos)
- honeyos gateway       - Run gateway in foreground
- honeyos gateway start - Start gateway service
- honeyos gateway stop  - Stop gateway service
- honeyos setup         - Interactive setup wizard
- honeyos status        - Show status of all components
- honeyos cron          - Manage cron jobs
"""

import os
import sys

__version__ = "0.20.0"
__release_date__ = "2026.8.3"


def _ensure_utf8():
    """Force UTF-8 stdout/stderr to prevent UnicodeEncodeError crashes.

    Several environments select a legacy, non-UTF-8 encoding for the standard
    streams:

    - Windows services and terminals default to cp1252.
    - Linux hosts with a latin-1 / C / POSIX locale (common on minimal Debian
      installs and Raspberry Pi) select latin-1 or ASCII.

    The CLI prints box-drawing characters (┌│├└─) and the ⚕ glyph in the setup
    wizard, doctor, and status banners. Encoding those under a non-UTF-8 codec
    raises an unhandled UnicodeEncodeError that crashes the command before it
    can even start — e.g. `honeyos setup` on a fresh Pi.

    This runs at import time so it protects every CLI subcommand, on any
    platform. It re-wraps stdout/stderr as UTF-8 when their encoding is not
    already UTF-8, preferring TextIOWrapper.reconfigure() so the existing
    stream object is fixed in place (cached `sys.stdout` references keep
    working) and falling back to reopening the file descriptor with
    closefd=False (the CPython-recommended safe variant).

    No-op when the streams are already UTF-8: a healthy UTF-8 system sees no
    stream change and no environment mutation.

    Note: this is intentionally the earliest, platform-agnostic guard.
    honeyos.runtime/stdio.py::configure_windows_stdio() runs later from the entry
    points and layers on the Windows-only extras (console code-page flip,
    EDITOR default, PATH augmentation); its stream reconfiguration is a
    harmless idempotent no-op once we have already repaired the streams here.
    """
    repaired = False

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
            if encoding == "utf8":
                continue

            # Preferred: reconfigure the existing TextIOWrapper in place. This
            # preserves object identity so any code already holding a reference
            # to the old sys.stdout benefits from the repair too.
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")
                repaired = True
                continue

            # Fallback: reopen the underlying file descriptor as UTF-8. Used
            # for streams that don't expose reconfigure() (e.g. some wrapped
            # or replaced streams). closefd=False keeps the original fd open.
            new_stream = open(
                stream.fileno(), "w", encoding="utf-8",
                errors="replace", buffering=1, closefd=False,
            )
            setattr(sys, stream_name, new_stream)
            repaired = True
        except (AttributeError, OSError, ValueError):
            pass

    # Only nudge child processes toward UTF-8 when we actually detected a
    # non-UTF-8 locale. On a healthy UTF-8 host children inherit UTF-8 from the
    # locale already, so leave the environment untouched (minimal footprint).
    if repaired:
        os.environ.setdefault("PYTHONUTF8", "1")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")


_ensure_utf8()
