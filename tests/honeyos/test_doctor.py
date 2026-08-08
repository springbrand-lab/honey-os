from __future__ import annotations

from honeyos.cli.bootstrap import activate_home
from honeyos.companion.config import initialize_home
from honeyos.companion.doctor import run_doctor
from honeyos.companion.runtime import write_runtime_identity


def _home(tmp_path):
    home = activate_home(tmp_path)
    initialize_home(home)
    write_runtime_identity(home)
    return home


def test_doctor_reports_companion_contract_without_secrets(tmp_path):
    home = _home(tmp_path)
    (home / ".env").write_text(
        "OPENAI_API_KEY=top-secret\nWEIXIN_TOKEN=other-secret\n",
        encoding="utf-8",
    )

    report = run_doctor(home)
    rendered = report.render()

    assert "top-secret" not in rendered
    assert "other-secret" not in rendered
    assert report.by_name("data-home").ok
    assert report.by_name("runtime-isolated").ok
    assert report.by_name("companion-mode").ok
    assert report.by_name("bundled-skills-disabled").ok
    assert report.by_name("tool-allowlist").ok
    assert report.by_name("project-workspace").ok
    assert report.by_name("execution-approval").ok
    assert report.by_name("storage-writable").ok
    assert report.by_name("absolute-runtime-dispatch").ok


def test_doctor_fails_modified_tool_allowlist(tmp_path):
    home = _home(tmp_path)
    (home / "config.yaml").write_text(
        "agent:\n  mode: companion\n"
        "platform_toolsets:\n  weixin: [memory, session_search, delegation]\n",
        encoding="utf-8",
    )

    report = run_doctor(home)

    assert report.by_name("tool-allowlist").ok is False
    assert "delegation" in report.by_name("tool-allowlist").detail


def test_doctor_fails_non_local_terminal_backend(tmp_path):
    home = _home(tmp_path)
    config = __import__("yaml").safe_load((home / "config.yaml").read_text())
    config["terminal"]["backend"] = "docker"
    (home / "config.yaml").write_text(
        __import__("yaml").safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    report = run_doctor(home)

    assert report.by_name("project-workspace").ok is False
    assert "docker" in report.by_name("project-workspace").detail


def test_doctor_rejects_disabled_dangerous_command_approval(tmp_path):
    home = _home(tmp_path)
    config = __import__("yaml").safe_load((home / "config.yaml").read_text())
    config["approvals"]["mode"] = "off"
    (home / "config.yaml").write_text(
        __import__("yaml").safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    report = run_doctor(home)

    assert report.by_name("execution-approval").ok is False
    assert "off" in report.by_name("execution-approval").detail


def test_doctor_reports_missing_runtime_identity(tmp_path):
    home = activate_home(tmp_path)
    initialize_home(home)

    report = run_doctor(home)

    assert report.by_name("runtime-isolated").ok is False
