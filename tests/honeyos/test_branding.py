from __future__ import annotations

from pathlib import Path

from honeyos.gateway import run as gateway_run
from honeyos.gateway import slash_commands
from honeyos.gateway.platforms import weixin
from honeyos.companion import PRODUCT_NAME
from honeyos.companion.health import FirstStartReport
from honeyos.cli.main import main


ROOT = Path(__file__).parents[2]


def test_public_cli_uses_honey_os_brand(capsys):
    assert PRODUCT_NAME == "HoneyOS"
    assert main(["--help"]) == 0

    output = capsys.readouterr().out
    assert "HoneyOS" in output
    assert "H2OS" not in output
    assert "Hermes" not in output


def test_first_start_report_uses_honey_os_brand():
    output = FirstStartReport(()).render()

    assert output == "HoneyOS 首次启动检查"


def test_public_readme_and_installer_use_honey_os_brand():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installer = (ROOT / "scripts" / "install_honeyos.sh").read_text(
        encoding="utf-8"
    )

    assert readme.startswith("# 🍯 HoneyOS")
    assert "H2OS" not in readme
    assert "Hermes" not in readme
    assert "uv run honeyos" in readme
    assert "uv run h2os" not in readme
    assert "HoneyOS" in installer
    assert 'echo "H2OS' not in installer
    assert (ROOT / "Install-HoneyOS.command").is_file()
    assert not (ROOT / "Install-H2OS.command").exists()


def test_package_exposes_only_honeyos_command():
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"] == {
        "honeyos": "honeyos.cli.main:main"
    }


def test_companion_identity_names_honey_os_without_upstream_brand(tmp_path):
    from honeyos.companion.config import initialize_home

    initialize_home(tmp_path)
    soul = (tmp_path / "SOUL.md").read_text(encoding="utf-8")

    assert "HoneyOS" in soul
    assert "H2OS" not in soul
    assert "Hermes" not in soul
    assert (tmp_path / "skills" / "honeyos-self-extension").is_dir()
    assert not (tmp_path / "skills" / "h2os-self-extension").exists()


def test_honey_os_gateway_does_not_append_upstream_tips(monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")

    tip = getattr(slash_commands, "_reset_tip_line", lambda: "missing")()

    assert tip == ""


def test_honey_os_pairing_instruction_uses_public_command(monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")

    prefix = getattr(gateway_run, "_pairing_cli_prefix", lambda: "missing")()

    assert prefix == "honeyos"


def test_weixin_egress_preserves_honeyos_product_name(monkeypatch):
    monkeypatch.setenv("HONEYOS_RUNTIME_ID", "honeyos-companion-v0.3")
    helper = getattr(weixin, "_productize_outbound_text", lambda text: text)

    output = helper("HoneyOS is HoneyOS. Run `honeyos gateway restart` when needed.")

    assert output == (
        "HoneyOS is HoneyOS. Run `honeyos gateway restart` when needed."
    )
