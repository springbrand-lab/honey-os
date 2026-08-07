from __future__ import annotations

import subprocess
import sys


def test_core_runtime_imports_from_honeyos_namespace_only() -> None:
    script = """
import sys
import honeyos.agent.conversation_loop
import honeyos.gateway.run
import honeyos.tools.skills_tool
assert not any(
    name == 'agent' or name.startswith('agent.')
    or name == 'gateway' or name.startswith('gateway.')
    or name == 'tools' or name.startswith('tools.')
    or name == 'hermes_cli' or name.startswith('hermes_cli.')
    or name == 'h2os_cli' or name.startswith('h2os_cli.')
    for name in sys.modules
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_gateway_process_command_is_honeyos() -> None:
    from honeyos.cli.service import ServiceIdentity

    argv = ServiceIdentity.default().command_argv()
    assert argv[1:] == ("-m", "honeyos", "gateway", "run")
