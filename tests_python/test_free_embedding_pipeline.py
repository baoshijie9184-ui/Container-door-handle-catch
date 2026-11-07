"""Private environment preparation; no process, model or production interaction."""
import fcntl
import importlib.util
import json
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "script/jenkins/verify-free-embedding.py"
spec = importlib.util.spec_from_file_location("free_embedding_pipeline", SOURCE)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


@pytest.fixture
def fixture(tmp_path):
    root, runtime = tmp_path / "ci", tmp_path / "runtime"
    root.mkdir(mode=0o700); (root / "state").mkdir(mode=0o700)
    runtime.mkdir(mode=0o700); (runtime / "deploy").mkdir(mode=0o700)
    environment = runtime / "deploy/cloud.env"
    original = b"# private fixture\nDB_URL=jdbc:mysql://original-server/business\nDASHSCOPE_API_KEY=fixture-llm\nEMBEDDING_API_KEY=fixture-old\nEMBEDDING_MODEL=old-model\nUNRELATED=unchanged\n"
    environment.write_bytes(original); environment.chmod(0o600)
    key = tmp_path / "embedding.key"
    key.write_text("sk-" + "x" * 30); key.chmod(0o600)
    return root, runtime, environment, key, original


def prepare(fixture, tag="ci-62-0123456789ab"):
    root, runtime, _, key, _ = fixture
    return pipeline.prepare_next_release_environment(runtime, root, tag, key)


def test_preparation_backs_up_original_and_only_changes_embedding_settings(fixture):
    _, runtime, environment, _, original = fixture
    receipt = prepare(fixture)
    assert (runtime / "deploy/embedding-backups/ci-62-0123456789ab.env").read_bytes() == original
    content = environment.read_text()
    assert "DB_URL=jdbc:mysql://original-server/business\nDASHSCOPE_API_KEY=fixture-llm\n" in content
    assert "UNRELATED=unchanged\n" in content and "EMBEDDING_MODEL=BAAI/bge-m3\n" in content
    assert content.count("EMBEDDING_API_KEY=") == 1 and environment.stat().st_mode & 0o777 == 0o600
    assert receipt["status"] == "PREPARED_FOR_NEXT_RELEASE" and receipt["liveActivationPerformed"] is False
    assert "sk-" not in json.dumps(receipt)


def test_duplicate_setting_is_refused_before_writing_any_configuration(fixture):
    _, runtime, environment, _, original = fixture
    damaged = original + b"export EMBEDDING_MODEL=second-model\n"
    environment.write_bytes(damaged)
    with pytest.raises(ValueError, match="Duplicate"): prepare(fixture)
    assert environment.read_bytes() == damaged and not (runtime / "deploy/embedding-backups").exists()


def test_public_configuration_permissions_are_refused(fixture):
    _, _, environment, _, original = fixture
    environment.chmod(0o644)
    with pytest.raises(ValueError, match="Private original"): prepare(fixture)
    assert environment.read_bytes() == original


def test_a_live_deployment_lock_prevents_configuration_preparation(fixture):
    root, _, environment, _, original = fixture
    with (root / "state/deploy.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError): prepare(fixture)
    assert environment.read_bytes() == original


def test_atomic_replace_failure_preserves_original_backup_and_removes_pending_file(fixture, monkeypatch):
    _, runtime, environment, _, original = fixture
    def fail(*_): raise OSError("fixture replace interruption")
    monkeypatch.setattr(pipeline.os, "replace", fail)
    with pytest.raises(OSError): prepare(fixture)
    assert environment.read_bytes() == original
    assert (runtime / "deploy/embedding-backups/ci-62-0123456789ab.env").read_bytes() == original
    assert not list(environment.parent.glob("*.pending"))


def test_an_existing_build_backup_is_never_replaced(fixture):
    _, runtime, environment, _, _ = fixture
    prepare(fixture)
    updated = environment.read_bytes()
    backup = runtime / "deploy/embedding-backups/ci-62-0123456789ab.env"
    first = backup.read_bytes()
    with pytest.raises(FileExistsError): prepare(fixture)
    assert environment.read_bytes() == updated and backup.read_bytes() == first


def test_redirected_private_environment_is_refused(fixture):
    _, runtime, environment, _, original = fixture
    target = runtime / "deploy/original.env"
    environment.rename(target); environment.symlink_to(target)
    with pytest.raises(ValueError, match="Private original"): prepare(fixture)
    assert target.read_bytes() == original


def test_redirected_original_runtime_is_refused(fixture, tmp_path):
    root, runtime, environment, key, original = fixture
    alias = tmp_path / "runtime-alias"
    alias.symlink_to(runtime, target_is_directory=True)
    with pytest.raises(ValueError, match="Canonical"):
        pipeline.prepare_next_release_environment(alias, root, "ci-62-0123456789ab", key)
    assert environment.read_bytes() == original
