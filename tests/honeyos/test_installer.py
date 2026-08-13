from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path


def test_installer_uses_private_uv_when_path_contains_old_uv(tmp_path):
    repo = Path(__file__).parents[2]
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    uv_bin = home / ".local" / "share" / "honeyos" / "runtime"
    fake_bin.mkdir()
    log = tmp_path / "uv.log"
    system_uv_log = tmp_path / "system-uv.log"

    system_uv = fake_bin / "uv"
    system_uv.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$HONEYOS_TEST_SYSTEM_UV_LOG\"\n"
        "exit 2\n",
        encoding="utf-8",
    )
    system_uv.chmod(0o755)

    curl = fake_bin / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '#!/bin/sh' "
        "'if [ \"$1\" = \"--version\" ]; then echo \"uv 0.11.21\"; exit 0; fi' "
        "'printf \"%s\\n\" \"$*\" >> \"$HONEYOS_TEST_UV_LOG\"' "
        "> \"$UV_INSTALL_DIR/uv\"\n"
        "chmod +x \"$UV_INSTALL_DIR/uv\"\n"
        "printf ':\\n'\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    env = os.environ.copy()
    env.pop("HONEYOS_HOME", None)
    env.pop("H2OS_HOME", None)
    env.pop("UV_INSTALL_DIR", None)
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HONEYOS_TEST_UV_LOG": str(log),
            "HONEYOS_TEST_SYSTEM_UV_LOG": str(system_uv_log),
        }
    )
    result = subprocess.run(
        ["/bin/sh", str(repo / "scripts" / "install_honeyos.sh")],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8").splitlines() == [
        "sync --locked --quiet --extra honeyos --extra mcp",
        "run honeyos setup",
    ]
    assert not system_uv_log.exists()


def test_github_bootstrap_installs_to_stable_user_path(tmp_path):
    repo = Path(__file__).parents[2]
    fixture = tmp_path / "fixture" / "test_ai_0806-0.3.1"
    scripts = fixture / "scripts"
    scripts.mkdir(parents=True)
    (fixture / "pyproject.toml").write_text("[project]\nname = 'honeyos'\n", encoding="utf-8")
    (scripts / "install_honeyos.sh").write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "REPO_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")/..\" && pwd)\n"
        "mkdir -p \"$REPO_DIR/.venv/bin\"\n"
        "printf '#!/bin/sh\\n' > \"$REPO_DIR/.venv/bin/honeyos\"\n"
        "chmod +x \"$REPO_DIR/.venv/bin/honeyos\"\n"
        "printf 'installed\\n' > \"$HONEYOS_TEST_INSTALL_LOG\"\n",
        encoding="utf-8",
    )

    archive = tmp_path / "honeyos.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(fixture, arcname=fixture.name)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text('#!/bin/sh\ncp "$HONEYOS_TEST_ARCHIVE" "$4"\n', encoding="utf-8")
    curl.chmod(0o755)

    home = tmp_path / "home"
    log = tmp_path / "install.log"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HONEYOS_TEST_ARCHIVE": str(archive),
            "HONEYOS_TEST_INSTALL_LOG": str(log),
        }
    )
    result = subprocess.run(
        ["/bin/sh"],
        cwd=repo,
        env=env,
        input=(repo / "install.sh").read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )

    app = home / ".local" / "share" / "honeyos" / "app"
    launcher = home / ".local" / "bin" / "honeyos"
    assert result.returncode == 0, result.stderr
    assert (app / "pyproject.toml").is_file()
    assert launcher.is_symlink()
    assert launcher.resolve() == app / ".venv" / "bin" / "honeyos"
    assert log.read_text(encoding="utf-8") == "installed\n"
