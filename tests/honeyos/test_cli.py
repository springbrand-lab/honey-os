from __future__ import annotations

import json
import os

from honeyos.cli.main import main


def test_init_command_activates_requested_home(tmp_path, capsys):
    assert main(["--home", str(tmp_path), "init"]) == 0

    output = capsys.readouterr().out
    assert os.environ["HONEYOS_HOME"] == str(tmp_path.resolve())
    assert (tmp_path / "runtime.json").exists()
    assert "HoneyOS" in output
    assert "Hermes" not in output
    assert str(tmp_path.resolve()) in output


def test_init_runtime_metadata_points_at_requested_home(tmp_path):
    main(["--home", str(tmp_path), "init"])

    payload = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))
    assert payload["data_directory"] == str(tmp_path.resolve())


def test_cli_rejects_unknown_command_without_traceback(capsys):
    assert main(["unknown"]) == 2

    captured = capsys.readouterr()
    assert "unknown" in captured.err
    assert "Traceback" not in captured.err


def test_setup_command_routes_to_guided_setup(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.companion.setup.run_setup",
        lambda home, **_kwargs: observed.append(home) or 0,
    )

    assert main(["--home", str(tmp_path), "setup"]) == 0
    assert observed == [tmp_path.resolve()]


def test_channel_setup_weixin_routes_through_honeyos(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.companion.channels.setup_weixin",
        lambda home: observed.append(home) or 0,
    )

    assert main(["--home", str(tmp_path), "channel", "setup", "weixin"]) == 0
    assert observed == [tmp_path.resolve()]


def test_channel_setup_feishu_routes_through_honeyos(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.companion.channels.setup_feishu",
        lambda home: observed.append(home) or 0,
    )

    assert main(["--home", str(tmp_path), "channel", "setup", "feishu"]) == 0
    assert observed == [tmp_path.resolve()]


def test_pairing_approve_stays_inside_honeyos_home(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.cli.main._run_embedded",
        lambda arguments, home: observed.append((arguments, home)) or 0,
    )

    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "pairing",
                "approve",
                "weixin",
                "ABC123",
            ]
        )
        == 0
    )
    assert observed == [
        (["pairing", "approve", "weixin", "ABC123"], tmp_path.resolve())
    ]


def test_pairing_approve_accepts_feishu(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.cli.main._run_embedded",
        lambda arguments, home: observed.append((arguments, home)) or 0,
    )

    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "pairing",
                "approve",
                "feishu",
                "ABC123",
            ]
        )
        == 0
    )
    assert observed == [
        (["pairing", "approve", "feishu", "ABC123"], tmp_path.resolve())
    ]


def test_skills_command_routes_to_full_honeyos_runtime(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.cli.main._run_embedded",
        lambda arguments, home: observed.append((arguments, home)) or 0,
    )

    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "skills",
                "search",
                "relationship",
                "--limit",
                "5",
            ]
        )
        == 0
    )
    assert observed == [
        (
            ["skills", "search", "relationship", "--limit", "5"],
            tmp_path.resolve(),
        )
    ]


def test_runtime_capability_commands_route_through_honeyos(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.cli.main._run_embedded",
        lambda arguments, home: observed.append((arguments, home)) or 0,
    )

    for arguments in (
        ["model", "list"],
        ["tools"],
        ["computer-use", "doctor", "--json"],
        ["mcp", "login", "example"],
    ):
        assert main(["--home", str(tmp_path), *arguments]) == 0

    assert observed == [
        (["model", "list"], tmp_path.resolve()),
        (["tools"], tmp_path.resolve()),
        (["computer-use", "doctor", "--json"], tmp_path.resolve()),
        (["mcp", "login", "example"], tmp_path.resolve()),
    ]


def test_runtime_capability_command_forwards_direct_help(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.cli.main._run_embedded",
        lambda arguments, home: observed.append((arguments, home)) or 0,
    )

    assert main(["--home", str(tmp_path), "model", "--help"]) == 0

    assert observed == [(["model", "--help"], tmp_path.resolve())]


def test_runtime_capability_command_forwards_direct_options(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.cli.main._run_embedded",
        lambda arguments, home: observed.append((arguments, home)) or 0,
    )

    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "model",
                "--portal-url",
                "https://portal.example.test",
                "--refresh",
            ]
        )
        == 0
    )

    assert observed == [
        (
            [
                "model",
                "--portal-url",
                "https://portal.example.test",
                "--refresh",
            ],
            tmp_path.resolve(),
        )
    ]


def test_runtime_environment_clears_previous_product_homes(monkeypatch, tmp_path):
    from honeyos.cli.main import _runtime_environment

    monkeypatch.setenv("HERMES_HOME", "/tmp/hermes-home")
    monkeypatch.setenv("H2OS_HOME", "/tmp/h2os-home")

    environment = _runtime_environment(tmp_path)

    assert "HERMES_HOME" not in environment
    assert "H2OS_HOME" not in environment
    assert environment["HONEYOS_HOME"] == str(tmp_path)


def test_start_installs_then_starts_honeyos_service(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(
        "honeyos.cli.main.install_service",
        lambda identity: observed.append(("install", identity.data_home)) or 0,
    )
    monkeypatch.setattr(
        "honeyos.cli.main.start_service",
        lambda identity: observed.append(("start", identity.data_home)) or 0,
    )

    assert main(["--home", str(tmp_path), "start"]) == 0
    assert observed == [
        ("install", tmp_path.resolve()),
        ("start", tmp_path.resolve()),
    ]


def test_start_does_not_continue_when_service_install_fails(monkeypatch, tmp_path):
    observed = []

    def fake_install(identity):
        observed.append(("install", identity.data_home))
        return 7

    monkeypatch.setattr("honeyos.cli.main.install_service", fake_install)
    monkeypatch.setattr(
        "honeyos.cli.main.start_service",
        lambda identity: observed.append(("start", identity.data_home)) or 0,
    )

    assert main(["--home", str(tmp_path), "start"]) == 7
    assert [command for command, _home in observed] == ["install"]


def test_web_fails_without_opening_browser_when_service_is_not_ready(
    monkeypatch, tmp_path, capsys
):
    opened = []
    monkeypatch.setattr("honeyos.cli.main._initialize_embedded", lambda _home: None)
    monkeypatch.setattr("honeyos.cli.main.install_service", lambda _identity: 0)
    monkeypatch.setattr("honeyos.cli.main.start_service", lambda _identity: 0)
    monkeypatch.setattr(
        "honeyos.companion.web.wait_for_companion_web", lambda: False
    )
    monkeypatch.setattr(
        "honeyos.companion.web.open_companion_web",
        lambda: opened.append(True) or True,
    )

    assert main(["--home", str(tmp_path), "web"]) == 1
    assert opened == []
    assert "gateway.error.log" in capsys.readouterr().err
