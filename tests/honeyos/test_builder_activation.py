from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "live-honeyos"
    (source / "honeyos" / "companion").mkdir(parents=True)
    (source / "honeyos" / "runtime").mkdir(parents=True)
    (source / "tests" / "honeyos").mkdir(parents=True)
    (source / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "MEMORY = 'live'\n", encoding="utf-8"
    )
    (source / "honeyos" / "runtime" / "main.py").write_text(
        "RUNTIME = 'live'\n", encoding="utf-8"
    )
    (source / "pyproject.toml").write_text("[project]\nname = 'honeyos-test'\n", encoding="utf-8")
    (source / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (source / "tests" / "honeyos" / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n", encoding="utf-8"
    )
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "builder-test@example.com")
    _git(source, "config", "user.name", "Builder Test")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "initial")
    return source


def _review_ready_change(tmp_path: Path):
    from honeyos.companion.builder_workspace import inspect_builder_change, prepare_builder_change

    source = _source_repo(tmp_path)
    prepared = prepare_builder_change(
        source_repo=source,
        goal="改善记忆",
        allowed_paths=("honeyos/companion/**",),
        builder_root=tmp_path / "HoneyOS Builder",
        change_id="candidate-slot-001",
    )
    (prepared.workspace / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "MEMORY = 'candidate'\n", encoding="utf-8"
    )
    review = inspect_builder_change(prepared.change_root)
    assert review.status == "review_ready"
    return source, prepared, review


def _staged_activation(tmp_path: Path):
    from honeyos.companion.builder_activation import ActivationStore

    source, prepared, review = _review_ready_change(tmp_path)
    store = ActivationStore(tmp_path / "home", bundled_root=source)
    return store, store.stage(prepared.change_root), prepared, review


def test_stage_materializes_complete_reviewed_source_into_private_slot(tmp_path):
    source, prepared, review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationStore

    home = tmp_path / "home"
    (home / "state.db").parent.mkdir(parents=True)
    (home / "state.db").write_text("must-not-copy", encoding="utf-8")
    store = ActivationStore(home, bundled_root=source)

    staged = store.stage(prepared.change_root)

    assert staged.state == "staged"
    assert staged.candidate_digest == review.candidate_digest
    assert staged.slot_root.is_relative_to(home / "runtime" / "slots")
    assert not (staged.slot_root / "source" / ".git").exists()
    assert (staged.slot_root / "source" / "pyproject.toml").is_file()
    assert (staged.slot_root / "source" / "uv.lock").is_file()
    assert (staged.slot_root / "source" / "tests" / "honeyos" / "test_smoke.py").is_file()
    assert (staged.slot_root / "source" / "honeyos" / "companion" / "persistent_memory.py").read_text(encoding="utf-8") == "MEMORY = 'candidate'\n"
    assert staged.slot_tree_digest
    assert staged.manifest_path.stat().st_mode & 0o777 == 0o600
    assert not any(path.name == "state.db" for path in staged.slot_root.rglob("*"))
    assert _git(source, "rev-parse", "HEAD") == staged.source_commit


def test_stage_applies_reviewed_deletion_only(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationStore
    from honeyos.companion.builder_workspace import inspect_builder_change

    (prepared.workspace / "honeyos" / "companion" / "persistent_memory.py").unlink()
    review = inspect_builder_change(prepared.change_root)
    staged = ActivationStore(tmp_path / "home", source).stage(prepared.change_root)

    assert review.status == "review_ready"
    assert not (staged.slot_root / "source" / "honeyos" / "companion" / "persistent_memory.py").exists()
    assert (source / "honeyos" / "companion" / "persistent_memory.py").is_file()


def test_changed_candidate_cannot_be_staged_from_old_review(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationError, ActivationStore

    (prepared.workspace / "honeyos" / "companion" / "persistent_memory.py").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(ActivationError, match="changed after review"):
        ActivationStore(tmp_path / "home", source).stage(prepared.change_root)


def test_stage_rejects_changed_live_source_head(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationError, ActivationStore

    (source / "README.md").write_text("changed base\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "unexpected base change")

    with pytest.raises(ActivationError, match="source revision"):
        ActivationStore(tmp_path / "home", source).stage(prepared.change_root)


@pytest.mark.parametrize("mutation", ("manifest", "review"))
def test_stage_rejects_tampered_metadata(tmp_path, mutation):
    source, prepared, review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationError, ActivationStore

    path = prepared.manifest_path if mutation == "manifest" else review.report_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_commit"] = "0" * 40
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ActivationError, match="metadata|review"):
        ActivationStore(tmp_path / "home", source).stage(prepared.change_root)


def test_stage_rejects_candidate_symlink(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationError, ActivationStore
    from honeyos.companion.builder_workspace import inspect_builder_change

    target = tmp_path / "outside.py"
    target.write_text("outside\n", encoding="utf-8")
    candidate = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    candidate.unlink()
    candidate.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        inspect_builder_change(prepared.change_root)
    with pytest.raises(ActivationError, match="changed after review"):
        ActivationStore(tmp_path / "home", source).stage(prepared.change_root)


def test_candidate_import_resolves_from_slot_source(tmp_path):
    store, staged, _prepared, _review = _staged_activation(tmp_path)

    resolved = store.resolve_candidate_module(staged.activation_id, "honeyos.runtime.main")

    assert resolved.is_relative_to(staged.slot_root / "source")
    assert resolved.read_text(encoding="utf-8") == "RUNTIME = 'live'\n"


def test_candidate_python_import_cannot_fall_back_to_live_checkout(tmp_path):
    store, staged, _prepared, _review = _staged_activation(tmp_path)
    isolated_cwd = tmp_path / "isolated"
    isolated_cwd.mkdir()
    environment = os.environ | {"PYTHONPATH": str(staged.slot_root / "source")}

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import honeyos.runtime.main as main; print(main.__file__)",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=isolated_cwd,
        env=environment,
    )

    assert Path(completed.stdout.strip()).resolve().is_relative_to(staged.slot_root / "source")


def test_verify_rechecks_slot_tree_without_revisiting_disposable_builder_workspace(tmp_path):
    store, staged, prepared, _review = _staged_activation(tmp_path)
    from honeyos.companion.builder_activation import ActivationError

    tampered = staged.slot_root / "source" / "honeyos" / "runtime" / "main.py"
    tampered.chmod(tampered.stat().st_mode | stat.S_IWUSR)
    tampered.write_text(
        "tampered slot\n", encoding="utf-8"
    )
    with pytest.raises(ActivationError, match="slot tree digest"):
        store.verify_staged(staged.activation_id)

    # Once staged, later verification must depend exclusively on staged metadata.
    store2, staged2, prepared2, _review2 = _staged_activation(tmp_path / "second")
    shutil.rmtree(prepared2.change_root)
    assert store2.verify_staged(staged2.activation_id) == staged2


def test_activation_transitions_are_compare_and_swap_and_private(tmp_path):
    store, staged, _prepared, _review = _staged_activation(tmp_path)
    from honeyos.companion.builder_activation import ActivationConflict

    switched = store.transition(staged.activation_id, "staged", "awaiting_confirmation")

    assert switched.state == "awaiting_confirmation"
    with pytest.raises(ActivationConflict):
        store.transition(staged.activation_id, "staged", "switching")
    assert (store.activations / f"{staged.activation_id}.json").stat().st_mode & 0o777 == 0o600
    assert store.runtime_root.stat().st_mode & 0o777 == 0o700
    assert store.slots.stat().st_mode & 0o777 == 0o700
    assert store.activations.stat().st_mode & 0o777 == 0o700


def test_stage_rejects_executable_candidate_file(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationError, ActivationStore
    from honeyos.companion.builder_workspace import inspect_builder_change

    candidate = prepared.workspace / "honeyos" / "companion" / "persistent_memory.py"
    candidate.chmod(candidate.stat().st_mode | os.X_OK)
    inspect_builder_change(prepared.change_root)

    with pytest.raises(ActivationError, match="executable"):
        ActivationStore(tmp_path / "home", source).stage(prepared.change_root)


def test_stage_requires_the_live_bundled_root_to_be_the_reviewed_source(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationError, ActivationStore

    unrelated = _source_repo(tmp_path / "unrelated")

    with pytest.raises(ActivationError, match="bundled runtime"):
        ActivationStore(tmp_path / "home", unrelated).stage(prepared.change_root)


@pytest.mark.parametrize("metadata_name", ("manifest.json", "trusted-policy.json", "review.json"))
def test_stage_rejects_symlinked_private_candidate_metadata(tmp_path, metadata_name):
    source, prepared, review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationError, ActivationStore

    original = prepared.change_root / metadata_name
    if metadata_name == "review.json":
        original = review.report_path
    outside = tmp_path / f"outside-{metadata_name}"
    outside.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(outside)

    with pytest.raises(ActivationError, match="metadata|review"):
        ActivationStore(tmp_path / "home", source).stage(prepared.change_root)


def test_stage_snapshots_metadata_and_verifies_after_builder_files_are_deleted(tmp_path):
    store, staged, prepared, _review = _staged_activation(tmp_path)

    trusted = staged.slot_root / "trusted"
    assert {path.name for path in trusted.iterdir()} == {
        "manifest.json",
        "trusted-policy.json",
        "review.json",
        "changed-paths.json",
    }
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in trusted.iterdir())
    shutil.rmtree(prepared.change_root)

    verified = store.verify_staged(staged.activation_id)

    assert verified.candidate_digest == staged.candidate_digest
    assert verified.slot_tree_digest == staged.slot_tree_digest


def test_staged_source_is_read_only_and_tampering_is_detected(tmp_path):
    store, staged, _prepared, _review = _staged_activation(tmp_path)
    from honeyos.companion.builder_activation import ActivationError

    source_file = staged.slot_root / "source" / "honeyos" / "runtime" / "main.py"
    assert not (source_file.stat().st_mode & stat.S_IWUSR)
    source_file.chmod(source_file.stat().st_mode | stat.S_IWUSR)
    source_file.write_text("tampered slot\n", encoding="utf-8")

    with pytest.raises(ActivationError, match="slot tree digest"):
        store.verify_staged(staged.activation_id)


def test_stage_rejects_workspace_bytes_changed_during_reviewed_overlay(
    tmp_path, monkeypatch
):
    source, prepared, _review = _review_ready_change(tmp_path)
    import honeyos.companion.builder_activation as activation

    original_copy = activation._copy_reviewed_file
    changed_once = False

    def mutate_then_copy(workspace, source_root, changed):
        nonlocal changed_once
        if not changed_once:
            changed_once = True
            (workspace / changed.relative).write_text(
                "MEMORY = 'changed-during-copy'\n", encoding="utf-8"
            )
        return original_copy(workspace, source_root, changed)

    monkeypatch.setattr(activation, "_copy_reviewed_file", mutate_then_copy)

    with pytest.raises(activation.ActivationError, match="materialized candidate"):
        activation.ActivationStore(tmp_path / "home", source).stage(
            prepared.change_root
        )


def test_reconcile_completes_a_slot_published_before_the_final_record(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationConflict, ActivationStore

    def crash_after_publish(point: str) -> None:
        if point == "after_slot_publish":
            raise SystemExit("simulated crash")

    crashed = ActivationStore(tmp_path / "home", source, crash_hook=crash_after_publish)
    with pytest.raises(SystemExit, match="simulated crash"):
        crashed.stage(prepared.change_root)

    recovered = ActivationStore(tmp_path / "home", source)
    with pytest.raises(ActivationConflict, match="already been staged"):
        recovered.stage(prepared.change_root)
    activation_id = next(recovered.activations.glob("*.json")).stem
    assert recovered.verify_staged(activation_id).state == "staged"


def test_reconcile_discards_a_journal_left_before_slot_publication(tmp_path):
    source, prepared, _review = _review_ready_change(tmp_path)
    from honeyos.companion.builder_activation import ActivationStore

    def crash_before_publish(point: str) -> None:
        if point == "before_slot_publish":
            raise SystemExit("simulated crash")

    crashed = ActivationStore(tmp_path / "home", source, crash_hook=crash_before_publish)
    with pytest.raises(SystemExit, match="simulated crash"):
        crashed.stage(prepared.change_root)

    recovered = ActivationStore(tmp_path / "home", source)
    staged = recovered.stage(prepared.change_root)
    assert recovered.verify_staged(staged.activation_id).state == "staged"


def test_builder_activation_module_imports_without_posix_lock_module(tmp_path, monkeypatch):
    import importlib

    import honeyos.companion.builder_activation as activation

    monkeypatch.setitem(sys.modules, "fcntl", None)
    reloaded = importlib.reload(activation)

    assert reloaded.ActivationStore.__name__ == "ActivationStore"
