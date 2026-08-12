from __future__ import annotations

import os
import subprocess
from pathlib import Path

import honeyos


ROOT = Path(__file__).parents[2]
INSTALLER = ROOT / "scripts" / "install_honeyos.sh"
BOOTSTRAP = ROOT / "install.sh"


def _run_installer(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    uv_log = tmp_path / "uv.log"
    fake_uv = uv_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo \"uv 0.11.21\"; exit 0; fi\n"
        "printf '%s\\n' \"$*\" >> \"$UV_LOG\"\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment.pop("HONEYOS_HOME", None)
    environment.pop("H2OS_HOME", None)
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": "/usr/bin:/bin",
            "UV_INSTALL_DIR": str(uv_bin),
            "UV_LOG": str(uv_log),
        }
    )
    completed = subprocess.run(
        ["/bin/sh", str(INSTALLER)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = uv_log.read_text(encoding="utf-8").splitlines()
    return completed, calls


def test_installer_runs_setup_for_a_new_user(tmp_path):
    completed, calls = _run_installer(tmp_path)

    assert completed.returncode == 0
    assert calls == ["sync --locked --quiet --extra honeyos", "run honeyos setup"]
    assert "发现已有的 HoneyOS" not in completed.stdout


def test_installer_upgrades_an_existing_user_without_repeating_setup(tmp_path):
    home = tmp_path / "home" / ".honeyos"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("agent:\n  mode: companion\n", encoding="utf-8")

    completed, calls = _run_installer(tmp_path)

    assert completed.returncode == 0
    assert calls[-1] == "run honeyos web"
    assert all(call != "run honeyos setup" for call in calls)
    assert "发现已有的 HoneyOS 和伴侣数据" in completed.stdout
    assert "人设、关系记忆与历史聊天会保留" in completed.stdout


def test_release_version_is_0_3_1_and_consistent():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")

    assert honeyos.__version__ == "0.3.1"
    assert 'version = "0.3.1"' in pyproject
    assert "`v0.3.1`" in readme
    assert "VERSION=0.3.1" in bootstrap
    assert "refs/heads/main.tar.gz" in bootstrap
