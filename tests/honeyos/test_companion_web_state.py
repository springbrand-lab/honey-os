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
    / "run-state.js"
)


def _run_state_script(body: str) -> dict:
    script = f"""
global.window = global;
require({json.dumps(str(ASSET))});
{body}
"""
    result = subprocess.run(
        [NODE, "-e", script],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_turn_state_groups_presence_tools_and_response():
    state = _run_state_script(
        """
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {name:'run.started', payload:{}}, 1000);
state = HoneyOSRunState.reduce(state, {name:'tool.started', payload:{activity:{activity_id:'a1',kind:'checking',state:'active',title:'我去替你认真看看',detail:''}}}, 1100);
state = HoneyOSRunState.reduce(state, {name:'tool.completed', payload:{activity:{activity_id:'a1',kind:'checking',state:'completed',title:'找到了，我整理一下',detail:''}}}, 1400);
state = HoneyOSRunState.reduce(state, {name:'assistant.delta', payload:{delta:'找'}}, 1600);
process.stdout.write(JSON.stringify(state));
"""
    )

    assert state["phase"] == "responding"
    assert state["content"] == "找"
    assert state["activities"] == [
        {
            "activity_id": "a1",
            "kind": "checking",
            "state": "completed",
            "title": "找到了，我整理一下",
            "detail": "",
        }
    ]


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_turn_state_keeps_multiple_tools_in_one_ordered_trail():
    state = _run_state_script(
        """
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {name:'run.started', payload:{}}, 1000);
state = HoneyOSRunState.reduce(state, {name:'presence.updated', payload:{activity:{activity_id:'presence',kind:'presence',state:'active',title:'我在想你刚才说的事',detail:''}}}, 1050);
state = HoneyOSRunState.reduce(state, {name:'tool.started', payload:{activity:{activity_id:'a1',kind:'checking',state:'active',title:'我去替你认真看看',detail:''}}}, 1100);
state = HoneyOSRunState.reduce(state, {name:'tool.started', payload:{activity:{activity_id:'a2',kind:'remembering',state:'active',title:'我替你记下来',detail:''}}}, 1200);
state = HoneyOSRunState.reduce(state, {name:'tool.failed', payload:{activity:{activity_id:'a2',kind:'remembering',state:'failed',title:'刚才没走通，我换个办法',detail:''}}}, 1300);
process.stdout.write(JSON.stringify(state));
"""
    )

    assert state["phase"] == "acting"
    assert [item["activity_id"] for item in state["activities"]] == ["a1", "a2"]
    assert state["activities"][1]["state"] == "failed"
    assert state["presence"]["title"] == "我在想你刚才说的事"

