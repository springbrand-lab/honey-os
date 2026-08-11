from __future__ import annotations

import json
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest


STATIC_CHECKS = (
    "slot_evidence",
    "release_artifacts",
    "source_tree",
    "candidate_python_syntax",
)


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
    (source / "honeyos" / "__init__.py").write_text("\n", encoding="utf-8")
    (source / "honeyos" / "runtime" / "__init__.py").write_text("\n", encoding="utf-8")
    (source / "honeyos" / "runtime" / "main.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    (source / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "MEMORY = 'base'\n", encoding="utf-8"
    )
    (source / "pyproject.toml").write_text(
        "[project]\nname = 'honeyos-preflight-test'\nversion = '0.0.1'\n",
        encoding="utf-8",
    )
    (source / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "builder-test@example.com")
    _git(source, "config", "user.name", "Builder Test")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "initial")
    return source


def _staged_activation(tmp_path: Path, *, candidate: str = "MEMORY = 'candidate'\n"):
    from honeyos.companion.builder_activation import ActivationStore
    from honeyos.companion.builder_workspace import (
        inspect_builder_change,
        prepare_builder_change,
    )

    source = _source_repo(tmp_path)
    prepared = prepare_builder_change(
        source_repo=source,
        goal="改善记忆",
        allowed_paths=("honeyos/companion/**",),
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="candidate-preflight-001",
    )
    candidate_path = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    candidate_path.write_text(candidate, encoding="utf-8")
    assert inspect_builder_change(prepared.change_root).status == "review_ready"
    store = ActivationStore(tmp_path / "home", bundled_root=source)
    return store, store.stage(prepared.change_root), source


def test_static_preflight_succeeds_without_tests_or_candidate_subprocesses(tmp_path):
    marker = tmp_path / "candidate-executed"
    candidate = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
    store, staged, _source = _staged_activation(tmp_path, candidate=candidate)

    receipt = store.preflight(staged.activation_id)

    assert receipt.success is True, receipt.error
    assert tuple(check.name for check in receipt.checks) == STATIC_CHECKS
    assert all(check.returncode == 0 and not check.timed_out for check in receipt.checks)
    assert receipt.candidate_digest == staged.candidate_digest
    assert receipt.slot_tree_digest == staged.slot_tree_digest
    assert not marker.exists()
    assert not (staged.slot_root / "preflight").exists()
    assert (staged.slot_root / "preflight.json").stat().st_mode & 0o777 == 0o600


def test_static_preflight_rejects_candidate_python_syntax_without_executing_it(tmp_path):
    marker = tmp_path / "candidate-executed"
    candidate = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\nif True print('bad')\n"
    store, staged, _source = _staged_activation(tmp_path, candidate=candidate)

    receipt = store.preflight(staged.activation_id)

    assert receipt.success is False
    assert receipt.error == "candidate_python_syntax failed"
    assert not marker.exists()


def test_transition_recomputes_static_checks_and_rejects_forged_receipt(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)
    receipt_path = staged.slot_root / "preflight.json"
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "activation_id": staged.activation_id,
                "success": True,
                "candidate_digest": staged.candidate_digest,
                "slot_tree_digest": staged.slot_tree_digest,
                "source_root": str(staged.slot_root / "source"),
                "checks": [],
                "error": "",
            }
        ),
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)

    from honeyos.companion.builder_activation import ActivationError

    with pytest.raises(ActivationError, match="preflight"):
        store.transition(staged.activation_id, "staged", "awaiting_confirmation")


def test_slot_source_mutation_invalidates_static_receipt_and_confirmation(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)
    assert store.preflight(staged.activation_id).success is True
    changed = staged.slot_root / "source" / "honeyos" / "companion" / "persistent_memory.py"
    changed.chmod(changed.stat().st_mode | stat.S_IWUSR)
    changed.write_text("MEMORY = 'tampered'\n", encoding="utf-8")

    from honeyos.companion.builder_activation import ActivationError

    with pytest.raises(ActivationError, match="slot tree digest"):
        store.transition(staged.activation_id, "staged", "awaiting_confirmation")


def test_real_distribution_archive_excludes_tests_but_static_preflight_does_not_require_them(tmp_path):
    root = Path(__file__).resolve().parents[2]
    assert "tests export-ignore" in (root / ".gitattributes").read_text(encoding="utf-8")
    archive = tmp_path / "release.tar"
    with archive.open("wb") as handle:
        subprocess.run(
            ["git", "-C", str(root), "archive", "--format=tar", "HEAD"],
            check=True,
            stdout=handle,
        )
    with tarfile.open(archive, "r:") as stream:
        assert not any(member.name.startswith("tests/") for member in stream.getmembers())

    store, staged, _source = _staged_activation(tmp_path / "static")
    assert not (staged.slot_root / "source" / "tests").exists()
    assert store.preflight(staged.activation_id).success is True


def test_static_preflight_fails_closed_when_required_release_artifact_is_missing(tmp_path):
    store, staged, _source = _staged_activation(tmp_path)
    source_root = staged.slot_root / "source"
    source_root.chmod(0o700)
    lock = source_root / "uv.lock"
    lock.chmod(stat.S_IWUSR | stat.S_IRUSR)
    lock.unlink()

    receipt = store.preflight(staged.activation_id)

    assert receipt.success is False
    assert receipt.error.endswith(" failed")
