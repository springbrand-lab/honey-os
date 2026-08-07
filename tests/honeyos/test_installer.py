from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_installer_bootstraps_uv_then_runs_setup(tmp_path):
    repo = Path(__file__).parents[2]
    fake_bin = tmp_path / "bin"
    uv_bin = tmp_path / "uv-bin"
    fake_bin.mkdir()
    log = tmp_path / "uv.log"

    curl = fake_bin / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '#!/bin/sh' "
        "'printf \"%s\\n\" \"$*\" >> \"$HONEYOS_TEST_UV_LOG\"' "
        "> \"$UV_INSTALL_DIR/uv\"\n"
        "chmod +x \"$UV_INSTALL_DIR/uv\"\n"
        "printf ':\\n'\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "UV_INSTALL_DIR": str(uv_bin),
            "HONEYOS_TEST_UV_LOG": str(log),
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
        "sync --quiet --extra honeyos",
        "run honeyos setup",
    ]
