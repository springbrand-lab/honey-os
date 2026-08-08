from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


NODE = shutil.which("node")
ASSET = (
    Path(__file__).parents[2]
    / "honeyos"
    / "companion"
    / "web_assets"
    / "message-format.js"
)


def _parse_message(message: str) -> list[dict]:
    script = f"""
global.window = global;
require({json.dumps(str(ASSET))});
process.stdout.write(JSON.stringify(HoneyOSMessageFormat.parse({json.dumps(message)})));
"""
    result = subprocess.run(
        [NODE, "-e", script],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_companion_message_format_parses_markdown_without_raw_markers():
    blocks = _parse_message(
        "看了一下。\n\n---\n\n**relationship-continuity** → 延续我们的关系。"
    )

    assert [block["type"] for block in blocks] == ["paragraph", "hr", "paragraph"]
    assert blocks[2]["inline"][0] == {
        "type": "strong",
        "value": "relationship-continuity",
    }
    assert "**" not in json.dumps(blocks, ensure_ascii=False)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_companion_message_format_treats_html_as_text():
    blocks = _parse_message('<img src=x onerror="alert(1)">')

    assert blocks == [
        {
            "type": "paragraph",
            "inline": [
                {"type": "text", "value": '<img src=x onerror="alert(1)">'},
            ],
        }
    ]
