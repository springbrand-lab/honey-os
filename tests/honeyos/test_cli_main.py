from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _main_module():
    try:
        spec = importlib.util.find_spec("honeyos.cli.main")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "the public HoneyOS CLI must exist"
    return importlib.import_module("honeyos.cli.main")


def test_init_creates_only_honeyos_home(tmp_path: Path) -> None:
    main = _main_module()
    home = tmp_path / ".honeyos"

    assert main.main(["--home", str(home), "init"]) == 0

    assert home.is_dir()
    assert not (tmp_path / ".h2os").exists()
    assert not (tmp_path / ".hermes").exists()


def test_help_exposes_only_honeyos_commands(capsys) -> None:
    main = _main_module()

    assert main.main(["--help"]) == 0

    output = capsys.readouterr().out.lower()
    assert "honeyos" in output
    assert "honey-os" not in output
    assert "h2os" not in output
    assert "hermes" not in output


def test_installers_invoke_only_honeyos() -> None:
    command = ROOT / "Install-HoneyOS.command"
    opener = ROOT / "Open-HoneyOS.command"
    installer = ROOT / "scripts" / "install_honeyos.sh"

    assert command.is_file()
    assert opener.is_file()
    assert installer.is_file()
    for path in (command, opener, installer):
        content = path.read_text(encoding="utf-8").lower()
        assert "honeyos" in content
        assert "honey-os" not in content
        assert "h2os" not in content
        assert "hermes" not in content
    opener_text = opener.read_text(encoding="utf-8")
    assert ".venv/bin/honeyos" in opener_text
    assert opener_text.rstrip().endswith('honeyos" web')
