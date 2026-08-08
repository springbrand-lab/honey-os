from honeyos.tools.approval import (
    check_all_command_guards,
    detect_dangerous_command,
    detect_hardline_command,
)
from honeyos.tools.permission_policy import (
    grants_from_user_task,
    reset_turn_intent_grants,
    set_turn_intent_grants,
)
from unittest.mock import patch


def test_project_config_yaml_is_not_treated_as_honeyos_security_config():
    dangerous, _key, _description = detect_dangerous_command(
        "printf 'theme: dark' > config.yaml"
    )

    assert dangerous is False


def test_simple_python_calculation_is_not_dangerous_only_because_it_uses_dash_c():
    dangerous, _key, _description = detect_dangerous_command(
        "python3 -c 'print(1 + 1)'"
    )

    assert dangerous is False


def test_python_inline_import_remains_gated():
    dangerous, _key, description = detect_dangerous_command(
        "python3 -c 'import os; print(os.getcwd())'"
    )

    assert dangerous is True
    assert description == "script execution via -e/-c flag"


def test_terminal_reference_to_honeyos_secret_is_hard_blocked():
    hardline, description = detect_hardline_command("cat ~/.honeyos/.env")

    assert hardline is True
    assert description == "access HoneyOS internal credential"


def test_curl_read_is_direct_but_local_file_upload_is_gated():
    read = detect_dangerous_command("curl -s https://example.com/data")
    upload = detect_dangerous_command(
        "curl -F 'file=@report.pdf' https://example.com/upload"
    )

    assert read[0] is False
    assert upload[0] is True
    assert upload[2] == "upload local file to external service"


def test_explicit_upload_to_same_host_suppresses_only_the_upload_prompt():
    token = set_turn_intent_grants(
        grants_from_user_task(
            "把 report.pdf 上传到 example.com",
            turn_id="turn-upload",
        )
    )
    try:
        with (
            patch("honeyos.tools.approval._is_gateway_approval_context", return_value=True),
            patch("honeyos.tools.approval._get_approval_mode", return_value="manual"),
            patch("honeyos.tools.approval.get_current_session_key", return_value="upload-test"),
            patch("honeyos.tools.approval.is_approved", return_value=False),
            patch("honeyos.tools.tirith_security.check_command_security", return_value={"action": "allow", "findings": [], "summary": ""}),
        ):
            result = check_all_command_guards(
                "curl -F 'file=@report.pdf' https://example.com/upload",
                "local",
            )
    finally:
        reset_turn_intent_grants(token)

    assert result["approved"] is True
