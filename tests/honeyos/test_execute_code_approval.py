from __future__ import annotations

from unittest.mock import patch

from honeyos.tools.approval import check_execute_code_guard


def _gateway_guard(code: str) -> dict:
    with (
        patch("honeyos.tools.approval._is_gateway_approval_context", return_value=True),
        patch("honeyos.tools.approval._get_approval_mode", return_value="manual"),
        patch("honeyos.tools.approval.get_current_session_key", return_value="proxy-test"),
        patch("honeyos.tools.approval.is_approved", return_value=False),
    ):
        return check_execute_code_guard(code, "local")


def test_proxy_only_execute_code_does_not_require_outer_approval():
    code = """
from honeyos_tools import terminal

r1 = terminal('curl -s https://springbrand.ai/aifriend/night/bar')
print("=== AGENT DOC ===")
print(r1['output'])

r2 = terminal('curl -s -H "Authorization: Bearer token" https://springbrand.ai/task')
print("=== TASK ===")
print(r2['output'])
"""

    result = _gateway_guard(code)

    assert result["approved"] is True
    assert result["proxy_only"] is True


def test_direct_host_file_access_still_requires_approval():
    result = _gateway_guard("open('/tmp/escape.txt', 'w').write('unsafe')")

    assert result["approved"] is False
    assert result["approval_pending"] is True


def test_direct_process_access_still_requires_approval():
    result = _gateway_guard("import os\nos.system('echo unsafe')")

    assert result["approved"] is False
    assert result["approval_pending"] is True


def test_dunder_object_escape_still_requires_approval():
    result = _gateway_guard("print((1).__class__.__mro__)")

    assert result["approved"] is False
    assert result["approval_pending"] is True
