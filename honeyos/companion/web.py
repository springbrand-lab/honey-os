"""Local-only HoneyOS companion web helpers."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8642
DEFAULT_COMPANION_NAME = "Honey"

_NAME_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:名字|姓名|名称|name)\s*[：:]\s*(.+?)\s*$",
    re.IGNORECASE,
)


def companion_web_url(*, port: int = DEFAULT_WEB_PORT) -> str:
    return f"http://{DEFAULT_WEB_HOST}:{int(port)}/"


def open_companion_web(*, port: int = DEFAULT_WEB_PORT, open_fn=None) -> bool:
    """Open the local companion page with an injectable browser launcher."""

    launcher = open_fn or webbrowser.open
    return bool(launcher(companion_web_url(port=port)))


def wait_for_companion_web(
    *,
    port: int = DEFAULT_WEB_PORT,
    probe_fn=None,
    sleep_fn=time.sleep,
    attempts: int = 40,
    delay: float = 0.125,
) -> bool:
    """Wait briefly for the background listener before opening a browser."""

    url = companion_web_url(port=port)

    def default_probe(target: str) -> bool:
        try:
            with urllib.request.urlopen(target, timeout=0.5) as response:
                return 200 <= int(response.status) < 400
        except (OSError, urllib.error.URLError):
            return False

    probe = probe_fn or default_probe
    for index in range(max(1, int(attempts))):
        if probe(url):
            return True
        if index + 1 < attempts:
            sleep_fn(max(0.0, float(delay)))
    return False


def companion_profile(home: Path) -> dict[str, str]:
    """Return the tiny public profile needed by the chat header."""

    from honeyos.companion.profile import load_companion_profile

    managed = load_companion_profile(home)
    if managed.companion_name:
        return {"name": managed.companion_name[:40], "status": "在这儿"}
    identity_path = Path(home).expanduser().resolve() / "memories" / "IDENTITY.md"
    name = ""
    try:
        for line in identity_path.read_text(encoding="utf-8").splitlines():
            match = _NAME_LINE.match(line)
            if match:
                name = match.group(1).strip().strip("`*_# ")[:40]
                break
    except OSError:
        pass
    return {"name": name or DEFAULT_COMPANION_NAME, "status": "在这儿"}


__all__ = [
    "DEFAULT_COMPANION_NAME",
    "DEFAULT_WEB_HOST",
    "DEFAULT_WEB_PORT",
    "companion_profile",
    "companion_web_url",
    "open_companion_web",
    "wait_for_companion_web",
]
