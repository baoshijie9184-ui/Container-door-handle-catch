"""New vector runtime contract; run only in the unified ECS test stage."""
from contextlib import contextmanager
import json
from types import SimpleNamespace
import uuid
import pytest
from fastapi.testclient import TestClient
from memory_service import main
from memory_service.qdrant_store import (point_id, vector_identity, admit_collection, LogicalQdrantStore,
                                         dense_vector, vector_fingerprint, ID_PROTOCOL)
from tests_python.qdrant_fixture import ecs_memory_qdrant


def test_public_ids_map_deterministically_to_namespaced_uuid8_without_renaming():
    one = point_id("doorhandle_memories_bge_m3_v1", "legacy-memory_1")
    assert one == point_id("doorhandle_memories_bge_m3_v1", "legacy-memory_1")
    assert uuid.UUID(one).version == 8
    assert one != point_id("another_collection", "legacy-memory_1")
    assert ID_PROTOCOL == "doorhandle-vector-sha256-v8-v1"
    for invalid in ("", "\0", "x" * 513):
        with pytest.raises(ValueError):
            point_id("owned", invalid)


def test_same_dimensions_cannot_admit_unknown_model_or_storage_generation():
    identity = vector_identity({})
    config = {"collection_name": "owned"}
    for damage in ({}, {**identity, "doorhandle_model": "foreign"}, {**identity, "doorhandle_storage_generation": "old"}):
        info = SimpleNamespace(config=SimpleNamespace(metadata=damage,
            params=SimpleNamespace(vectors=SimpleNamespace(size=1024, distance="Cosine"), sparse_vectors=None)))
        client = SimpleNamespace(collection_exists=lambda _: True, get_collection=lambda _: info)
        with pytest.raises(ValueError, match="identity"):
            admit_collection(config, {}, client=client)
    with pytest.raises(ValueError, match="generation"):
        vector_identity({"MEM0_STORAGE_GENERATION": "old"})


class Trace:
    @contextmanager
    def span(self, *args, **kwargs):
        yield SimpleNamespace(set_outcome=lambda _: None)


def test_shared_embedding_endpoint_is_private_bounded_and_uses_the_same_model_object(monkeypatch):
    calls = []
    embedder = SimpleNamespace(embed_batch=lambda texts: calls.append(texts) or [[2.] + [0.] * 1023 for _ in texts])
    monkeypatch.setattr(main, "memory_instance", SimpleNamespace(embedding_model=embedder))
    monkeypatch.setattr(main, "telemetry", Trace())
    monkeypatch.setenv("MEM0_BRIDGE_TOKEN", "fixture-private-token")
    monkeypatch.setenv("EMBEDDING_PROFILE", "siliconflow-bge-m3-v1")
    monkeypatch.setenv("MEM0_STORAGE_GENERATION", "qdrant-bge-m3-v1")
    client = TestClient(main.app)
    request = {"app_id": "doorhandlecatch", "purpose": "KNOWLEDGE", "user_id": "doorhandlecatch:user:42",
               "request_id": "fixture-request-id", "texts": ["门把手\n检验"]}
    assert client.post("/internal/embeddings", json=request).status_code == 401
    headers = {"x-doorhandle-memory-token": "fixture-private-token"}
    result = client.post("/internal/embeddings", json=request, headers=headers)
    assert result.status_code == 200
    assert calls == [["门把手 检验"]]
    assert result.json()["profile"] == "siliconflow-bge-m3-v1"
    assert result.json()["model"] == "BAAI/bge-m3" and result.json()["dimensions"] == 1024
    for changes in ({"texts": ["", "second"]}, {"texts": ["好" * 2667]}, {"texts": ["x"] * 65}, {"app_id": "foreign-app"}):
        assert client.post("/internal/embeddings", json={**request, **changes}, headers=headers).status_code == 422
    assert len(calls) == 1


def test_real_native_qdrant_keeps_public_id_vector_direction_and_account_filters(ecs_memory_qdrant):
    from mem0.vector_stores.qdrant import Qdrant
    config, client = ecs_memory_qdrant
    store = LogicalQdrantStore(Qdrant(**config))
    source = [2.] + [0.] * 31
    store.insert([source, source], [{"user_id": "doorhandlecatch:user:42", "agent_id": "doorhandlecatch", "data": "legacy"},
        {"user_id": "doorhandlecatch:user:43", "agent_id": "doorhandlecatch", "data": "foreign"}], ["legacy-id", "other-id"])
    assert store.get("legacy-id").id == "legacy-id"
    assert store.get("missing-id") is None
    first = store.get_with_vector("legacy-id")
    assert dense_vector(first) == [1.] + [0.] * 31
    assert vector_fingerprint(source) != vector_fingerprint(dense_vector(first))
    assert [row.id for row in store.owned_page("doorhandlecatch:user:42", "doorhandlecatch", 5, 0)] == ["legacy-id"]
    assert [row.id for row in store.search("query", source, filters={"user_id": "doorhandlecatch:user:42", "agent_id": "doorhandlecatch"})] == ["legacy-id"]
    store.update("legacy-id", vector=source, payload={"user_id": "doorhandlecatch:user:42", "agent_id": "doorhandlecatch", "data": "updated"})
    assert store.get("legacy-id").payload["data"] == "updated"
    store.delete("legacy-id")
    assert store.get("legacy-id") is None
