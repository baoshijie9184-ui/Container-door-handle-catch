import base64
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from memory_service import main
from memory_service.model_config import LlmConfigurationStore
from memory_service.write_receipts import ReceiptError

KEY = bytes(32)
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def envelope(revision, *, key="fixture-new-key", url=URL, model="fixture-json", purpose="mem0-llm"):
    body = {"provider": "dashscope", "model": model, "api_key": key, "base_url": url}
    nonce = bytes(range(12))
    encrypted = AESGCM(KEY).encrypt(nonce, json.dumps(body).encode(), f"doorhandle:{purpose}:{revision}".encode())
    return "v1." + base64.b64encode(nonce).decode() + "." + base64.b64encode(encrypted).decode()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    secret = tmp_path / "master.key"
    secret.write_text(base64.b64encode(KEY).decode())
    calls = []

    class Llm:
        def __init__(self, name): self.name = name
        def generate_response(self, *args, **kwargs): calls.append(self.name); return self.name

    memory = SimpleNamespace(llm=Llm("environment"), embedding_model=object(), vector_store=object())
    lock = threading.Lock()
    factory = lambda data: Llm(data["model"])
    store = LlmConfigurationStore(tmp_path / "state", secret, {"dashscope": URL}, lambda: memory, lock, factory)
    store.guard_environment("fixture-environment-key")
    monkeypatch.setattr(main, "model_configuration", store)
    monkeypatch.setenv("MEM0_BRIDGE_TOKEN", "fixture-token")
    http = TestClient(main.app)
    headers = {"X-Doorhandle-Memory-Token": "fixture-token"}
    return SimpleNamespace(store=store, secret=secret, calls=calls, memory=memory, lock=lock, factory=factory, http=http, headers=headers)


def test_private_endpoints_require_auth_and_never_echo_credentials(fixture):
    f = fixture
    assert f.http.get("/internal/model-config/status").status_code == 401
    assert f.http.post("/internal/model-config/prepare", headers=f.headers, json={"revision": 1, "envelope": envelope(1)}).json() == {"status": "PREPARED", "revision": 1}
    assert f.http.post("/internal/model-config/apply", headers=f.headers, json={"revision": 1}).status_code == 200
    response = f.http.get("/internal/model-config/status", headers=f.headers)
    assert response.json() == {"revision": 1}
    assert "key" not in response.text and "envelope" not in response.text
    assert f.calls == []  # Preparing and applying are metadata-only.
    assert b"fixture-new-key" not in f.store.path.read_bytes()


def test_apply_preserves_embeddings_and_inflight_extraction(fixture):
    f = fixture
    embedding, vector = f.memory.embedding_model, f.memory.vector_store
    original = f.memory.llm
    f.store.prepare(1, envelope(1))
    with f.lock:
        with pytest.raises(ReceiptError, match="previous model"):
            f.store.apply(1)
        assert f.store.applied_revision() == 0
        assert f.memory.llm is original
        assert f.memory.llm.generate_response() == "environment"
    f.store.apply(1)
    assert f.memory.llm.generate_response() == "fixture-json"
    assert f.memory.embedding_model is embedding and f.memory.vector_store is vector
    f.store.apply(1)
    assert f.store.applied_revision() == 1


def test_prepare_is_immutable_and_apply_cannot_downgrade(fixture):
    f = fixture
    f.store.prepare(1, envelope(1)); f.store.prepare(1, envelope(1))
    with pytest.raises(ReceiptError, match="immutable"):
        f.store.prepare(1, envelope(1, model="different"))
    f.store.prepare(2, envelope(2)); f.store.apply(2)
    with pytest.raises(ReceiptError, match="older"):
        f.store.apply(1)
    with f.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM llm_config_event").fetchone()[0] == 3


@pytest.mark.parametrize("bad", [lambda: envelope(2), lambda: envelope(1, purpose="model-config"),
                                      lambda: envelope(1, url="https://arbitrary.invalid/v1"),
                                      lambda: envelope(1, model="../invalid model"),
                                      lambda: "v1.bad.bad"])
def test_invalid_envelopes_never_change_runtime(fixture, bad):
    f = fixture
    response = f.http.post("/internal/model-config/prepare", headers=f.headers, json={"revision": 1, "envelope": bad()})
    assert response.status_code in {400, 422}
    assert f.store.applied_revision() == 0 and f.calls == []


def test_revoke_is_durable_and_blocks_provider_calls_after_restart(fixture):
    f = fixture
    f.store.prepare(1, envelope(1)); f.store.apply(1)
    digest = hashlib.sha256(b"fixture-new-key").hexdigest()
    assert f.http.post("/internal/model-config/revoke", headers=f.headers, json={"fingerprint": digest}).status_code == 200
    f.store.revoke(digest)
    with pytest.raises(ReceiptError, match="revoked"):
        f.memory.llm.generate_response("must never reach the provider")
    restarted = LlmConfigurationStore(f.store.path.parent, f.secret, {"dashscope": URL}, lambda: f.memory, f.lock, f.factory)
    restarted.restore()
    with pytest.raises(ReceiptError, match="revoked"):
        f.memory.llm.generate_response()
    assert f.calls == []
    assert f.memory.embedding_model is not None and f.memory.vector_store is not None


def test_committed_apply_interruption_is_recovered_without_llm_write(fixture):
    f = fixture
    original = f.memory.llm
    f.store.prepare(1, envelope(1))

    class InterruptedMemory:
        @property
        def llm(self): return original
        @llm.setter
        def llm(self, value): raise RuntimeError("process interrupted after commit")

    f.store.memory = lambda: InterruptedMemory()
    with pytest.raises(RuntimeError, match="interrupted"):
        f.store.apply(1)
    assert f.store.applied_revision() == 1
    with pytest.raises(ReceiptError, match="runtime needs verification"):
        original.generate_response()
    restarted = LlmConfigurationStore(f.store.path.parent, f.secret, {"dashscope": URL}, lambda: f.memory, f.lock, f.factory)
    restarted.restore()
    assert f.calls == []
    assert f.memory.llm.generate_response() == "fixture-json"


def test_apply_audit_failure_keeps_old_client_and_revision(fixture):
    f = fixture
    f.store.prepare(1, envelope(1))
    with f.store.connect() as db:
        db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON llm_config_event BEGIN SELECT RAISE(ABORT,'fixture audit failed'); END")
    response = f.http.post("/internal/model-config/apply", headers=f.headers, json={"revision": 1})
    assert response.status_code == 503 and "fixture audit failed" not in response.text
    assert f.store.applied_revision() == 0
    assert f.memory.llm.generate_response() == "environment"
