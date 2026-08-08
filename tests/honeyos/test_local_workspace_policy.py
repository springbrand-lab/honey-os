from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]


def _run_case(tmp_path: Path, code: str) -> dict:
    environment = os.environ.copy()
    environment.update(
        {
            "HONEYOS_HOME": str(tmp_path / ".honeyos"),
            "HONEYOS_PROJECTS_HOME": str(tmp_path / "HoneyOS Projects"),
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_companion_file_writes_are_blocked_outside_managed_projects(tmp_path):
    outside = tmp_path / "Desktop" / "surprise.txt"
    payload = _run_case(
        tmp_path,
        f"""
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.tools.file_tools import write_file_tool
home = Path({str(tmp_path / '.honeyos')!r})
initialize_home(home)
print(write_file_tool({str(outside)!r}, 'must not escape'))
""",
    )

    assert "error" in payload
    assert "HoneyOS Projects" in payload["error"]
    assert not outside.exists()


def test_companion_terminal_rejects_an_explicit_workdir_outside_projects(tmp_path):
    outside = tmp_path / "Desktop"
    outside.mkdir()
    payload = _run_case(
        tmp_path,
        f"""
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.tools.terminal_tool import terminal_tool
home = Path({str(tmp_path / '.honeyos')!r})
initialize_home(home)
print(terminal_tool('pwd', workdir={str(outside)!r}))
""",
    )

    assert payload["status"] == "blocked"
    assert "HoneyOS Projects" in payload["error"]


def test_companion_terminal_and_file_writes_work_inside_projects(tmp_path):
    projects = tmp_path / "HoneyOS Projects"
    payload = _run_case(
        tmp_path,
        f"""
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.tools.file_tools import write_file_tool
from honeyos.tools.terminal_tool import terminal_tool
home = Path({str(tmp_path / '.honeyos')!r})
initialize_home(home)
write_result = json.loads(write_file_tool('game/index.html', '<h1>game</h1>'))
terminal_result = json.loads(terminal_tool('test -f game/index.html'))
print(json.dumps({{'write': write_result, 'terminal': terminal_result}}))
""",
    )

    assert "error" not in payload["write"]
    assert payload["terminal"]["exit_code"] == 0
    assert (projects / "game" / "index.html").read_text(encoding="utf-8") == "<h1>game</h1>"


def test_agent_dispatch_can_write_files_without_optional_acp_adapter(tmp_path):
    projects = tmp_path / "HoneyOS Projects"
    payload = _run_case(
        tmp_path,
        f"""
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.model_tools import handle_function_call
home = Path({str(tmp_path / '.honeyos')!r})
initialize_home(home)
result = handle_function_call(
    'write_file',
    {{'path': 'game/index.html', 'content': '<h1>visible</h1>'}},
    task_id='local-project-test',
)
print(result)
""",
    )

    assert "error" not in payload
    assert (projects / "game" / "index.html").read_text(encoding="utf-8") == (
        "<h1>visible</h1>"
    )


def test_companion_terminal_blocks_absolute_redirect_outside_projects(tmp_path):
    outside = tmp_path / "Desktop" / "escape.html"
    outside.parent.mkdir()
    payload = _run_case(
        tmp_path,
        f"""
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.tools.terminal_tool import terminal_tool
home = Path({str(tmp_path / '.honeyos')!r})
initialize_home(home)
print(terminal_tool({f'printf safe > {outside}'!r}, task_id='redirect-test'))
""",
    )

    assert payload["status"] == "blocked"
    assert "HoneyOS Projects" in payload["error"]
    assert not outside.exists()


def test_companion_terminal_allows_relative_redirect_inside_projects(tmp_path):
    projects = tmp_path / "HoneyOS Projects"
    payload = _run_case(
        tmp_path,
        """
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.tools.terminal_tool import terminal_tool
home = Path(__import__('os').environ['HONEYOS_HOME'])
initialize_home(home)
print(terminal_tool("mkdir -p game && printf safe > game/index.html", task_id='redirect-test'))
""",
    )

    assert payload["exit_code"] == 0
    assert (projects / "game" / "index.html").read_text(encoding="utf-8") == "safe"


def test_companion_terminal_allows_stderr_to_dev_null(tmp_path):
    projects = tmp_path / "HoneyOS Projects"
    payload = _run_case(
        tmp_path,
        """
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.tools.terminal_tool import terminal_tool
home = Path(__import__('os').environ['HONEYOS_HOME'])
initialize_home(home)
print(terminal_tool(
    "mkdir -p game && printf safe > game/index.html 2>/dev/null",
    task_id='dev-null-test',
))
""",
    )

    assert payload["exit_code"] == 0
    assert (projects / "game" / "index.html").read_text(encoding="utf-8") == "safe"


def test_companion_write_request_is_retargeted_before_execution_and_verification(
    tmp_path,
):
    projects = tmp_path / "HoneyOS Projects"
    desktop_target = tmp_path / "Desktop" / "打地鼠.html"
    payload = _run_case(
        tmp_path,
        f"""
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.runtime.middleware import apply_tool_request_middleware
home = Path({str(tmp_path / '.honeyos')!r})
initialize_home(home)
result = apply_tool_request_middleware(
    'write_file',
    {{'path': {str(desktop_target)!r}, 'content': '<h1>game</h1>'}},
    task_id='retarget-test',
)
print(json.dumps({{
    'payload': result.payload,
    'changed': result.changed,
    'trace': result.trace,
}}, ensure_ascii=False))
""",
    )

    assert payload["changed"] is True
    assert payload["payload"]["path"] == str(projects / "打地鼠.html")
    assert payload["payload"]["content"] == "<h1>game</h1>"
    assert payload["trace"] == [{"source": "honeyos_project_workspace"}]


def test_agent_dispatch_retargets_desktop_write_in_one_call(tmp_path):
    projects = tmp_path / "HoneyOS Projects"
    desktop_target = tmp_path / "Desktop" / "打地鼠.html"
    payload = _run_case(
        tmp_path,
        f"""
import json
from pathlib import Path
from honeyos.companion.config import initialize_home
from honeyos.model_tools import handle_function_call
home = Path({str(tmp_path / '.honeyos')!r})
initialize_home(home)
print(handle_function_call(
    'write_file',
    {{'path': {str(desktop_target)!r}, 'content': '<h1>game</h1>'}},
    task_id='retarget-dispatch-test',
))
""",
    )

    assert "error" not in payload
    assert payload["resolved_path"] == str(projects / "打地鼠.html")
    assert not desktop_target.exists()
    assert (projects / "打地鼠.html").read_text(encoding="utf-8") == "<h1>game</h1>"
