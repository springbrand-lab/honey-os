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
