from __future__ import annotations

import os
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest


def test_honeyos_runtime_extra_declares_pytest_for_candidate_preflight():
    root = Path(__file__).resolve().parents[2]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    lockfile = (root / "uv.lock").read_text(encoding="utf-8")

    runtime_extra = tomllib.loads(pyproject)["project"]["optional-dependencies"]["honeyos"]

    assert "pytest==9.1.1" in runtime_extra
    assert 'marker = "extra == \'honeyos\'", specifier = "==9.1.1"' in lockfile


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "trusted-source"
    (source / "honeyos" / "companion").mkdir(parents=True)
    (source / "honeyos" / "runtime").mkdir(parents=True)
    (source / "tests" / "honeyos").mkdir(parents=True)
    (source / "honeyos" / "__init__.py").write_text("\n", encoding="utf-8")
    (source / "honeyos" / "runtime" / "__init__.py").write_text("\n", encoding="utf-8")
    (source / "honeyos" / "runtime" / "main.py").write_text(
        "def main():\n    return 0\n", encoding="utf-8"
    )
    (source / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "MEMORY = 'base'\n", encoding="utf-8"
    )
    (source / "tests" / "honeyos" / "test_builder_workspace.py").write_text(
        "def test_boundary():\n    assert True\n", encoding="utf-8"
    )
    (source / "tests" / "honeyos" / "test_candidate.py").write_text(
        "def test_candidate():\n    assert True\n", encoding="utf-8"
    )
    (source / "pyproject.toml").write_text(
        """[build-system]\nrequires = [\"setuptools\"]\nbuild-backend = \"setuptools.build_meta\"\n\n[project]\nname = \"honeyos-preflight-test\"\nversion = \"0.0.1\"\n\n[project.optional-dependencies]\ndev = [\"pytest\"]\n\n[tool.setuptools.packages.find]\ninclude = [\"honeyos\", \"honeyos.*\"]\n""",
        encoding="utf-8",
    )
    (source / "uv.lock").write_text("version = 1\npytest = true\n", encoding="utf-8")
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "builder-test@example.com")
    _git(source, "config", "user.name", "Builder Test")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "initial")
    return source


def _staged_activation(tmp_path: Path):
    from honeyos.companion.builder_activation import ActivationStore
    from honeyos.companion.builder_workspace import (
        inspect_builder_change,
        prepare_builder_change,
    )

    source = _source_repo(tmp_path)
    prepared = prepare_builder_change(
        source_repo=source,
        goal="改善记忆",
        allowed_paths=("honeyos/companion/**", "tests/honeyos/**"),
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="candidate-preflight-001",
    )
    (prepared.workspace / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "MEMORY = 'candidate'\n", encoding="utf-8"
    )
    (prepared.workspace / "tests" / "honeyos" / "test_candidate.py").write_text(
        "def test_candidate():\n    assert True\n", encoding="utf-8"
    )
    assert inspect_builder_change(prepared.change_root).status == "review_ready"
    store = ActivationStore(tmp_path / "home", bundled_root=source)
    return store, store.stage(prepared.change_root), source


class RecordingRunner:
    def __init__(self, *, fail_at: int | None = None, timeout_at: int | None = None, import_paths: tuple[Path, Path] | None = None):
        self.commands = []
        self.fail_at = fail_at
        self.timeout_at = timeout_at
        self.import_paths = import_paths

    def run(self, command):
        from honeyos.companion.builder_activation import ProcessResult

        self.commands.append(command)
        index = len(self.commands)
        if command.argv[1:3] == ("-m", "venv"):
            venv = Path(command.argv[-1])
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("synthetic", encoding="utf-8")
        if self.timeout_at == index:
            return ProcessResult(returncode=None, stdout="api_key=sk-private-token", stderr="", timed_out=True)
        if self.fail_at == index:
            return ProcessResult(returncode=1, stdout="api_key=sk-private-token", stderr="failed")
        if "import honeyos" in " ".join(command.argv):
            assert self.import_paths is not None
            return ProcessResult(
                returncode=0,
                stdout=f"{self.import_paths[0]}\n{self.import_paths[1]}\n",
                stderr="",
            )
        return ProcessResult(returncode=0, stdout="ok", stderr="")


def _runner_for(staged):
    source = staged.slot_root / "source"
    return RecordingRunner(
        import_paths=(source / "honeyos" / "__init__.py", source / "honeyos" / "runtime" / "main.py")
    )


def test_preflight_uses_only_synthetic_home_and_sanitized_environment(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)
    (store.home / "config.yaml").write_text("api_key: sk-real-secret", encoding="utf-8")
    runner = _runner_for(staged)

    receipt = store.preflight(staged.activation_id, runner=runner)

    assert receipt.success is True
    assert receipt.candidate_digest == staged.candidate_digest
    assert receipt.slot_tree_digest == staged.slot_tree_digest
    assert receipt.python_executable.is_relative_to(staged.slot_root / "preflight")
    assert receipt.source_root == staged.slot_root / "source"
    for command in runner.commands:
        assert command.cwd == staged.slot_root / "source"
        assert command.env["HOME"].startswith(str(staged.slot_root / "preflight"))
        assert command.env["HONEYOS_HOME"].startswith(str(staged.slot_root / "preflight"))
        assert command.env["PYTHONPYCACHEPREFIX"].startswith(str(staged.slot_root / "preflight"))
        assert command.env["PYTHONPATH"] == ""
        assert command.env["VIRTUAL_ENV"] == ""
        assert command.env["HONEYOS_HOME"] != str(store.home)
        assert "sk-real-secret" not in repr(command)
        assert not any("http" in part or "curl" in part for part in command.argv)
        assert not any(key.startswith(("PIP_", "UV_")) for key in command.env)
    assert (staged.slot_root / "preflight.json").stat().st_mode & 0o777 == 0o600


def test_preflight_rejects_live_checkout_import_even_when_runner_succeeds(tmp_path):
    store, staged, source = _staged_activation(tmp_path)
    runner = RecordingRunner(
        import_paths=(source / "honeyos" / "__init__.py", source / "honeyos" / "runtime" / "main.py")
    )

    receipt = store.preflight(staged.activation_id, runner=runner)

    assert receipt.success is False
    assert "slot" in receipt.error
    with pytest.raises(Exception, match="preflight"):
        store.transition(staged.activation_id, "staged", "awaiting_confirmation")


def test_failed_preflight_cannot_become_confirmable(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)
    runner = _runner_for(staged)
    runner.fail_at = 2

    receipt = store.preflight(staged.activation_id, runner=runner)

    assert receipt.success is False
    with pytest.raises(Exception, match="preflight"):
        store.transition(staged.activation_id, "staged", "awaiting_confirmation")


def test_preflight_missing_approved_artifact_fails_closed(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)
    source_root = staged.slot_root / "source"
    source_root.chmod(0o700)
    lock = source_root / "uv.lock"
    lock.chmod(stat.S_IWUSR | stat.S_IRUSR)
    lock.unlink()

    receipt = store.preflight(staged.activation_id, runner=_runner_for(staged))

    assert receipt.success is False
    assert "approved" in receipt.error


def test_timeout_output_is_bounded_and_redacted(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)
    runner = _runner_for(staged)
    runner.timeout_at = 1

    receipt = store.preflight(staged.activation_id, runner=runner)

    assert receipt.success is False
    assert "sk-private-token" not in receipt.error
    assert len(receipt.error) <= 512
    assert receipt.checks[0].timed_out is True


def test_slot_mutation_during_preflight_invalidates_receipt(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)

    class MutatingRunner(RecordingRunner):
        def run(self, command):
            result = super().run(command)
            if len(self.commands) == 2:
                target = staged.slot_root / "source" / "honeyos" / "companion" / "persistent_memory.py"
                target.chmod(target.stat().st_mode | stat.S_IWUSR)
                target.write_text("MUTATED = True\n", encoding="utf-8")
            return result

    runner = MutatingRunner(
        import_paths=(
            staged.slot_root / "source" / "honeyos" / "__init__.py",
            staged.slot_root / "source" / "honeyos" / "runtime" / "main.py",
        )
    )

    receipt = store.preflight(staged.activation_id, runner=runner)

    assert receipt.success is False
    assert "digest" in receipt.error


def test_successful_preflight_allows_awaiting_confirmation(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)

    receipt = store.preflight(staged.activation_id, runner=_runner_for(staged))
    transitioned = store.transition(staged.activation_id, "staged", "awaiting_confirmation")

    assert receipt.success is True
    assert transitioned.state == "awaiting_confirmation"


def test_real_preflight_executes_slot_code_with_runtime_test_dependency(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)

    receipt = store.preflight(staged.activation_id)

    assert receipt.success is True, receipt.error
    origins = next(check for check in receipt.checks if check.name == "slot_origin")
    assert all(
        Path(line).resolve().is_relative_to(staged.slot_root / "source")
        for line in origins.output.splitlines()
    )
    assert (staged.slot_root / "preflight" / "pycache").exists()
    assert not any((staged.slot_root / "source").rglob("__pycache__"))


def test_preflight_fails_closed_when_runtime_test_dependency_is_unavailable(tmp_path, monkeypatch):
    import honeyos.companion.builder_activation as activation

    store, staged, _source = _staged_activation(tmp_path)
    monkeypatch.setattr(activation.site, "getsitepackages", lambda: [])

    receipt = store.preflight(staged.activation_id)

    assert receipt.success is False
    assert receipt.error == "approved preflight test tooling is unavailable"
