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
state = HoneyOSRunState.reduce(state, {name:'assistant.completed', payload:{content:'找到了'}}, 1700);
process.stdout.write(JSON.stringify(state));
"""
    )

    assert state["phase"] == "completed"
    assert state["content"] == "找到了"
    assert state["activities"] == [
        {
            "activity_id": "a1",
            "kind": "checking",
            "state": "completed",
            "title": "找到了，我整理一下",
            "detail": "",
            "startedAt": 1100,
            "updatedAt": 1400,
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


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_completed_tool_does_not_claim_the_whole_turn_is_finished():
    summary = _run_state_script(
        """
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {name:'run.started', payload:{}}, 1000);
state = HoneyOSRunState.reduce(state, {name:'tool.started', payload:{activity:{activity_id:'a1',kind:'checking',state:'active',title:'正在认真核对',detail:'我在看几处相关内容'}}}, 1100);
state = HoneyOSRunState.reduce(state, {name:'tool.completed', payload:{activity:{activity_id:'a1',kind:'checking',state:'completed',title:'已经替你核对过了',detail:''}}}, 1400);
process.stdout.write(JSON.stringify(HoneyOSRunState.summarize(state)));
"""
    )

    assert summary == {
        "state": "active",
        "title": "我还在继续处理",
        "meta": "已完成 1 步，还在继续",
        "completed": 1,
        "total": 1,
    }


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_turn_summary_switches_to_finished_only_after_assistant_completion():
    summary = _run_state_script(
        """
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {name:'run.started', payload:{}}, 1000);
state = HoneyOSRunState.reduce(state, {name:'tool.started', payload:{activity:{activity_id:'a1',kind:'handling',state:'active',title:'正在替你处理',detail:'我还在这里，等我一下'}}}, 1100);
state = HoneyOSRunState.reduce(state, {name:'tool.completed', payload:{activity:{activity_id:'a1',kind:'handling',state:'completed',title:'已经替你处理好了',detail:''}}}, 1400);
state = HoneyOSRunState.reduce(state, {name:'assistant.completed', payload:{content:'弄好了'}}, 1700);
process.stdout.write(JSON.stringify(HoneyOSRunState.summarize(state)));
"""
    )

    assert summary == {
        "state": "completed",
        "title": "刚刚替你处理好了",
        "meta": "共 1 步，点开看过程",
        "completed": 1,
        "total": 1,
    }


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_activity_timeline_keeps_start_and_update_times():
    state = _run_state_script(
        """
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {name:'tool.started', payload:{activity:{activity_id:'a1',kind:'checking',state:'active',title:'正在认真核对',detail:''}}}, 1100);
state = HoneyOSRunState.reduce(state, {name:'tool.completed', payload:{activity:{activity_id:'a1',kind:'checking',state:'completed',title:'已经替你核对过了',detail:''}}}, 1400);
process.stdout.write(JSON.stringify(state));
"""
    )

    assert state["activities"][0]["startedAt"] == 1100
    assert state["activities"][0]["updatedAt"] == 1400


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_turn_state_exposes_waiting_permission_without_looking_stuck():
    state = _run_state_script(
        """
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {name:'run.started', payload:{}}, 1000);
state = HoneyOSRunState.reduce(state, {name:'approval.request', payload:{
  approval_id:'approval_1',
  narration:'我得借一下你电脑的能力，才能继续。',
  summary:'把一个文件发到 example.com',
  boundaries:['会把本机文件发到外部网站'],
  technical_detail:'curl -T photo.png https://example.com/upload',
  choices:['once','session','deny']
}}, 1200);
process.stdout.write(JSON.stringify(state));
"""
    )

    assert state["phase"] == "awaiting_permission"
    assert state["permission"]["summary"] == "把一个文件发到 example.com"
    assert state["permission"]["technical_detail"].startswith("curl")


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_permission_response_returns_turn_to_acting_state():
    state = _run_state_script(
        """
let state = HoneyOSRunState.create(1000);
state = HoneyOSRunState.reduce(state, {name:'approval.request', payload:{approval_id:'a1',summary:'运行脚本'}}, 1100);
state = HoneyOSRunState.reduce(state, {name:'approval.responded', payload:{choice:'once'}}, 1200);
process.stdout.write(JSON.stringify(state));
"""
    )

    assert state["phase"] == "acting"
    assert state["permission"] is None
