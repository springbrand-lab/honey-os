from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from honeyos.companion.runtime import (
    SOURCE_REVISION,
    gateway_argv,
    resolve_repository_root,
    write_runtime_identity,
)


def test_gateway_argv_uses_current_python_not_path_hermes():
    argv = gateway_argv("status")

    assert argv[:3] == [sys.executable, "-m", "honeyos.runtime.main"]
    assert argv[3:] == ["gateway", "status"]
    assert "hermes" not in argv


def test_write_runtime_identity_contains_no_secrets(tmp_path):
    identity = write_runtime_identity(tmp_path)
    payload = json.loads((tmp_path / "runtime.json").read_text(encoding="utf-8"))

    assert identity.source_revision == SOURCE_REVISION
    assert payload["python_executable"] == sys.executable
    assert payload["data_directory"] == str(tmp_path.resolve())
    assert payload["source_revision"] == SOURCE_REVISION
    assert "api_key" not in json.dumps(payload).lower()
    assert "token" not in json.dumps(payload).lower()


def test_resolve_repository_root_accepts_a_package_directory_inside_checkout(tmp_path):
    repository = tmp_path / "checkout"
    package = repository / "honeyos" / "companion"
    package.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repository)], check=True, capture_output=True)

    assert resolve_repository_root(package) == repository.resolve()


def test_write_runtime_identity_separates_package_and_repository_roots(
    monkeypatch, tmp_path
):
    import honeyos.companion.runtime as runtime_module

    repository = tmp_path / "checkout"
    package = repository / "honeyos"
    companion = package / "companion"
    companion.mkdir(parents=True)
    runtime_file = companion / "runtime.py"
    runtime_file.write_text("# test location\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(repository)], check=True, capture_output=True)
    monkeypatch.setattr(runtime_module, "__file__", str(runtime_file))

    write_runtime_identity(tmp_path / "home")
    payload = json.loads((tmp_path / "home" / "runtime.json").read_text(encoding="utf-8"))

    assert payload["package_root"] == str(package.resolve())
    assert payload["repository_root"] == str(repository.resolve())
