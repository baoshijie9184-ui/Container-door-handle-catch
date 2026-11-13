"""Qdrant target contracts with a stateful REST substitute; not real BGE/provider proof.

Old Chroma is read-only source evidence. These fixtures execute only on ECS.
"""
import copy
import json
import math
import struct
from types import SimpleNamespace

import pytest

from memory_service import embedding_config as embedding
from tests_python import test_legacy_store_migration as legacy
from script.memory import qdrant_migration as qdrant
from memory_service.qdrant_store import point_id, vector_identity


migration = legacy.migration
IDENTITY = {"instanceId": "fixture-instance", "machineId": "fixture-machine"}


class FakeRemote(qdrant.Remote):
    """Exercise the real admit/import/readback algorithm, substituting only REST I/O."""
    def __init__(self, base="http://fixture-qdrant"):
        self.base, self.collections, self.calls = base, {}, []
        self.import_calls = 0

    def import_records(self, collection, records, **kwargs):
        self.import_calls += 1
        return super().import_records(collection, records, **kwargs)

    def request(self, method, route, body=None):
        self.calls.append((method, route, copy.deepcopy(body)))
        if route == "/collections":
            assert method == "GET"
            return {"collections": [{"name": name} for name in sorted(self.collections)]}
        parts = route.split("?", 1)[0].split("/")
        assert parts[:2] == ["", "collections"] and len(parts) >= 3
        name = parts[2]
        if len(parts) == 3:
            if method == "PUT":
                assert name not in self.collections
                self.collections[name] = {"config": {"params": {"vectors": copy.deepcopy(body["vectors"]), "sparse_vectors": None},
                                                       "metadata": copy.deepcopy(body["metadata"])}, "points": {}}
                return True
            assert method == "GET"
            return {"config": copy.deepcopy(self.collections[name]["config"])}
        if parts[3] == "index":
            assert method == "PUT"
            return {"status": "completed"}
        points = self.collections[name]["points"]
        if len(parts) == 4:
            assert method == "PUT"
            for row in body["points"]:
                norm = math.sqrt(sum(float(value) ** 2 for value in row["vector"]))
                assert norm > 0
                normalized = list(struct.unpack("<1024f", struct.pack("<1024f", *(float(value) / norm for value in row["vector"]))))
                points[row["id"]] = {"id": row["id"], "payload": copy.deepcopy(row["payload"]), "vector": normalized}
            return {"status": "completed"}
        assert method == "POST"
        if parts[4] == "scroll":
            selected = [row for key, row in sorted(points.items()) if body.get("offset") is None or key > body["offset"]]
            page = selected[:body["limit"]]
            return {"points": copy.deepcopy(page), "next_page_offset": page[-1]["id"] if len(selected) > len(page) else None}
        assert parts[4] == "query"
        conditions = body.get("filter", {}).get("must", [])
        selected = [row for row in points.values() if all(row["payload"].get(item["key"]) == item["match"]["value"] for item in conditions)]
        norm = math.sqrt(sum(float(value) ** 2 for value in body["query"]))
        hits = [{"id": row["id"], "payload": copy.deepcopy(row["payload"]),
                 "score": sum(float(a) / norm * float(b) for a, b in zip(body["query"], row["vector"]))} for row in selected]
        return {"points": sorted(hits, key=lambda item: item["score"], reverse=True)[:body["limit"]]}


def prepared(bundle, mapping):
    result = legacy.embedding_output(bundle, mapping)
    result.update(dimensions=1024, targetModel=embedding.MODEL, targetCollection=embedding.COLLECTION,
                  embeddingProfile=embedding.FREE_PROFILE)
    for index, row in enumerate(result["records"]):
        vector = [0.0] * 1024; vector[index] = 3.0; vector[index + 2] = 4.0
        row.update(embedding=vector, targetVectorSha256=migration.sha(migration.vector_bytes(vector)))
    return result


def test_new_model_merge_keeps_original_collection_vectors_and_native_history(tmp_path, monkeypatch):
    bundle = legacy.legacy_bundle(); mapping = legacy.owner_map(bundle)
    path = legacy.candidate(tmp_path / "candidate", bundle)
    old = legacy.collection_at(path)
    old.add(ids=["original-cloud"], embeddings=[[0.1, 0.2, 0.3]], metadatas=[{"data": "existing", "user_id": "doorhandlecatch:user:1"}])
    baseline = migration.read_collection(old)
    result = prepared(bundle, mapping)
    remote = FakeRemote()
    monkeypatch.setattr(migration, "target_connection", lambda *_: remote)
    first = migration.merge_candidate(bundle, mapping, result, path, path / "receipt.json", IDENTITY)
    writes = [call for call in remote.calls if call[0] == "PUT"]
    with pytest.raises(migration.MigrationError, match="prior target write receipt"):
        migration.merge_candidate(bundle, mapping, result, path, path / "receipt.json", IDENTITY)
    assert [call for call in remote.calls if call[0] == "PUT"] == writes
    assert first["activeRecords"] == 2 and first["status"] == "MERGED_PENDING_INDEPENDENT_RECOVERY"
    assert first["productionPromotionAllowed"] is False
    assert migration.read_collection(old) == baseline
    records = remote.records(qdrant.COLLECTIONS["mem0"])
    assert len(records) == 2
    assert records["legacy-memory-0"]["payload"]["user_id"] == "doorhandlecatch:user:1"
    assert records["legacy-memory-1"]["payload"]["user_id"] == "doorhandlecatch:user:18"
    assert "legacy-memory-2" not in records
    receipt = json.loads((path / "receipt.json").read_text())
    assert receipt["targetCollection"] == embedding.COLLECTION and receipt["targetBackend"] == "qdrant"
    assert receipt["historyMode"] == "single-writer-sqlite"
    assert json.loads((path / "vector-space.json").read_text())["identity"] == vector_identity({"EMBEDDING_PROFILE": embedding.FREE_PROFILE})
    with migration.open_ro(path / "history.db") as db:
        history = migration.history_snapshot(db)
    assert len(history["history"]) == 2 and len(history["messages"]) == 2
    for logical, row in records.items():
        assert row["physicalId"] == point_id(embedding.COLLECTION, logical)
        assert row["physicalId"][14] == "8"
        evidence = receipt["storedVectors"][logical]
        assert evidence["cosineNormalizationVerified"] is True
        assert evidence["rawVectorSha256"] != evidence["storedVectorSha256"]


def test_existing_remote_payload_is_never_rebound_or_overwritten(tmp_path, monkeypatch):
    bundle = legacy.legacy_bundle(); mapping = legacy.owner_map(bundle); output = prepared(bundle, mapping)
    path = legacy.candidate(tmp_path / "candidate", bundle); remote = FakeRemote()
    projected = migration.prepared_records(bundle, mapping, output)
    remote.import_records(embedding.COLLECTION, projected["records"])
    before = remote.catalog(embedding.COLLECTION)
    projected["records"][0]["metadata"]["user_id"] = "doorhandlecatch:user:99"
    with pytest.raises(ValueError, match="conflicts"):
        remote.import_records(embedding.COLLECTION, projected["records"])
    assert remote.catalog(embedding.COLLECTION) == before
    monkeypatch.setattr(migration, "target_connection", lambda *_: remote)
    report = migration.merge_candidate(bundle, mapping, output, path, path / "receipt.json", IDENTITY)
    assert report["productionPromotionAllowed"] is False
    assert remote.catalog(embedding.COLLECTION) == before


def test_snapshot_recovery_requires_independent_empty_remote_before_any_snapshot_call(tmp_path):
    remote = FakeRemote(); same = FakeRemote(remote.base)
    with pytest.raises(ValueError, match="independent"):
        remote.snapshot_recovery(same, tmp_path / "snapshot")
    other = FakeRemote("http://independent-qdrant")
    other.admit(embedding.COLLECTION, create=True)
    with pytest.raises(ValueError, match="not empty"):
        remote.snapshot_recovery(other, tmp_path / "snapshot")
    assert not any("snapshot" in route for _, route, _ in remote.calls + other.calls)


@pytest.mark.parametrize("damage", ["wrong-direction", "wrong-norm", "nonfinite"])
def test_stored_cosine_evidence_cannot_be_an_arbitrary_1024_dimension_hash(damage):
    raw = [3.0, 4.0] + [0.0] * 1022
    stored = [0.6, 0.8] + [0.0] * 1022
    qdrant.normalized_agreement(raw, stored)
    if damage == "wrong-direction": stored[0], stored[1] = -0.6, -0.8
    elif damage == "wrong-norm": stored[0], stored[1] = 0.3, 0.4
    else: stored[0] = float("nan")
    with pytest.raises(ValueError): qdrant.normalized_agreement(raw, stored)


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
