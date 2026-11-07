"""BGE candidate migration with real Chroma and fixture HTTP, on ECS only."""
import copy
import json
from types import SimpleNamespace

import pytest

from memory_service import embedding_config as embedding
from tests_python import test_legacy_store_migration as legacy


migration = legacy.migration
IDENTITY = {"instanceId": "fixture-instance", "machineId": "fixture-machine"}


def prepared(bundle, mapping):
    result = legacy.embedding_output(bundle, mapping)
    result.update(dimensions=1024, targetModel=embedding.MODEL, targetCollection=embedding.COLLECTION,
                  embeddingProfile=embedding.FREE_PROFILE)
    for index, row in enumerate(result["records"]):
        vector = [0.0] * 1024; vector[index] = 1.0
        row.update(embedding=vector, targetVectorSha256=migration.sha(migration.vector_bytes(vector)))
    return result


def test_new_model_merge_keeps_original_collection_vectors_and_native_history(tmp_path):
    bundle = legacy.legacy_bundle(); mapping = legacy.owner_map(bundle)
    path = legacy.candidate(tmp_path / "candidate", bundle)
    old = legacy.collection_at(path)
    old.add(ids=["original-cloud"], embeddings=[[0.1, 0.2, 0.3]], metadatas=[{"data": "existing", "user_id": "doorhandlecatch:user:1"}])
    baseline = migration.read_collection(old)
    result = prepared(bundle, mapping)
    first = migration.merge_candidate(bundle, mapping, result, path, path / "receipt.json", IDENTITY)
    second = migration.merge_candidate(bundle, mapping, result, path, path / "receipt.json", IDENTITY)
    assert first["activeRecords"] == second["activeRecords"] == 2
    assert migration.read_collection(old) == baseline
    import chromadb
    client = chromadb.PersistentClient(path=str(path / "chroma"))
    target = client.get_collection(embedding.COLLECTION, embedding_function=None)
    assert target.count() == 2 and target.metadata == embedding.SPACE_METADATA
    records = migration.read_collection(target)
    assert records["legacy-memory-0"]["metadata"]["user_id"] == "doorhandlecatch:user:1"
    assert records["legacy-memory-1"]["metadata"]["user_id"] == "doorhandlecatch:user:18"
    assert "legacy-memory-2" not in records
    receipt = json.loads((path / "receipt.json").read_text())
    assert receipt["targetCollection"] == embedding.COLLECTION


@pytest.mark.parametrize("changes", [{"targetCollection": "arbitrary"}, {"dimensions": 256},
    {"targetModel": "Pro/BAAI/bge-m3"}, {"embeddingProfile": "unproven"}, {"targetCollection": "doorhandle_memories"}])
def test_unbound_models_dimensions_and_collection_reuse_are_rejected_before_merge(tmp_path, changes):
    bundle = legacy.legacy_bundle(); mapping = legacy.owner_map(bundle)
    path = legacy.candidate(tmp_path / "candidate", bundle)
    result = prepared(bundle, mapping); result.update(changes)
    with pytest.raises(migration.MigrationError):
        migration.merge_candidate(bundle, mapping, result, path, path / "receipt.json", IDENTITY)
    assert not (path / "history.db").exists()


def test_reembedding_uses_native_bge_dimensions_and_preserves_frozen_text(monkeypatch, tmp_path):
    bundle = legacy.legacy_bundle(); mapping = legacy.owner_map(bundle)
    frozen = copy.deepcopy(bundle)
    calls = []
    def create(**request):
        calls.append(request)
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0] + [0.0] * 1023)
            for i in range(len(request["input"]))], model=embedding.MODEL, usage=None)
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **_: SimpleNamespace(embeddings=SimpleNamespace(create=create)))
    config = {"embeddingProfile": embedding.FREE_PROFILE, "model": embedding.MODEL, "baseUrl": embedding.BASE_URL,
              "apiKey": "fixture-not-real", "dimensions": None, "verifiedTargetRuntime": True}
    report = migration.reembed(bundle, mapping, config, tmp_path / "prepared.json")
    assert report["reembeddedRecords"] == 2 and bundle == frozen
    assert len(calls) == 1 and "dimensions" not in calls[0] and calls[0]["model"] == embedding.MODEL
    output = json.loads((tmp_path / "prepared.json").read_text())
    assert output["targetCollection"] == embedding.COLLECTION and output["dimensions"] == 1024
    with pytest.raises(migration.MigrationError, match="exists"):
        migration.reembed(bundle, mapping, config, tmp_path / "prepared.json")
    assert len(calls) == 1
