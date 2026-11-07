"""Migration integrity checks. Execute on ECS; Chroma is a required dependency."""
from pathlib import Path
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("legacy_store_migration", ROOT / "script/memory/migrate_legacy_stores.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def legacy_bundle():
    records = []
    for index, owner in enumerate(("admin", "doorhandlecatch:user:18", "integration-user")):
        vector = [0.1 + index, 0.2, 0.3]
        text = "private migration fixture " + str(index)
        records.append({"id": "legacy-memory-" + str(index),
                        "metadata": {"data": text, "user_id": owner, "created_at": "2026-05-28T06:40:37+00:00", "updated_at": "2026-05-28T06:40:37+00:00"},
                        "embedding": vector, "textSha256": migration.sha(text.encode()),
                        "originalVectorSha256": migration.sha(migration.vector_bytes(vector))})
    history = [{"id": "history-" + str(i), "memory_id": "legacy-memory-" + str(i), "old_memory": None,
                "new_memory": "private migration fixture " + str(i), "event": "ADD", "created_at": "2026-05-28T06:40:37+00:00",
                "updated_at": None, "is_deleted": 0, "actor_id": None, "role": None} for i in range(4)]
    messages = [{"id": "message-" + str(i), "session_scope": "user_id=" + owner, "role": "user",
                 "content": "private fixture input", "name": None, "created_at": "2026-05-28T06:40:37+00:00"}
                for i, owner in enumerate(("admin", "doorhandlecatch:user:18", "integration-user"))]
    return {"format": 1, "kind": "legacy-mem0-private-export", "collection": migration.COLLECTION,
            "dimension": 3, "sources": [], "records": records, "history": history, "messages": messages}


def owner_map(bundle):
    return {"sourceBundleSha256": migration.sha(migration.canonical(bundle)), "targetTenantId": None,
            "owners": [{"sourceOwner": "admin", "disposition": "import", "reason": "username from original server", "userId": 1, "username": "admin"},
                       {"sourceOwner": "doorhandlecatch:user:18", "disposition": "import", "reason": "numeric ID from original server", "userId": 18, "username": "inspector.demo"},
                       {"sourceOwner": "integration-user", "disposition": "archive", "reason": "test principal with no account"}]}


def embedding_output(bundle, mapping):
    rows = migration.project(bundle, mapping)["records"]
    result = {"status": "COMPLETE", "sourceBundleSha256": migration.sha(migration.canonical(bundle)),
              "ownerMappingSha256": migration.sha(migration.canonical(mapping)), "dimensions": 3,
              "targetModel": "fixture-embedding-model", "records": []}
    for row in rows:
        vector = [0.4, 0.5, 0.6]
        result["records"].append({"id": row["id"], "textSha256": row["textSha256"],
            "originalVectorSha256": row["originalVectorSha256"], "embedding": vector,
            "targetVectorSha256": migration.sha(migration.vector_bytes(vector))})
    return result


def candidate(path, bundle):
    path.mkdir(mode=0o700)
    backup = path.parent / (path.name + "-backup.tar")
    backup.write_bytes(b"fixture full-volume backup")
    proof = path.parent / (path.name + "-restore.json")
    migration.private_json(proof, {"status": "RESTORED_VERIFIED", "archiveSha256": migration.file_sha(backup),
        "identity": {"instanceId": "fixture-instance", "machineId": "fixture-machine"}, "fullVolume": True})
    migration.private_json(path / "migration-candidate.json", {"scope": "mem0-offline-candidate", "instanceId": "fixture-instance",
        "machineId": "fixture-machine", "sourceBundleSha256": migration.sha(migration.canonical(bundle)), "sourceQuiesced": True,
        "sourceBackupPath": str(backup), "sourceBackupSha256": migration.file_sha(backup), "restoreProofPath": str(proof)})
    return path


def collection_at(path):
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(path=str(path / "chroma"), settings=Settings(anonymized_telemetry=False))
    return client.get_or_create_collection(migration.COLLECTION, embedding_function=None)


class LegacyMem0MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="legacy-mem0-migration-")
        self.root = Path(self.temp.name)
        self.bundle = legacy_bundle()
        self.mapping = owner_map(self.bundle)

    def tearDown(self):
        self.temp.cleanup()

    def test_preserves_source_and_maps_only_proven_principals(self):
        original = migration.canonical(self.bundle)
        projected = migration.project(self.bundle, self.mapping)
        self.assertEqual([r["metadata"]["user_id"] for r in projected["records"]], ["doorhandlecatch:user:1", "doorhandlecatch:user:18"])
        self.assertEqual(projected["archivedMemoryIds"], ["legacy-memory-2"])
        self.assertEqual(projected["archivedHistoryRows"], 2)
        self.assertEqual(projected["archivedMessageRows"], 1)
        self.assertEqual(migration.canonical(self.bundle), original)
        self.assertEqual(projected["messages"][0]["session_scope"], "agent_id=doorhandlecatch&user_id=doorhandlecatch:user:1")

    def test_missing_owner_and_stale_export_are_rejected(self):
        self.mapping["owners"].pop()
        with self.assertRaises(migration.MigrationError):
            migration.project(self.bundle, self.mapping)
        self.mapping = owner_map(self.bundle)
        self.bundle["records"][0]["metadata"]["data"] = "changed"
        with self.assertRaises(migration.MigrationError):
            migration.project(self.bundle, self.mapping)

    def test_monolith_rejects_tenant_namespace_and_requires_account_proof(self):
        self.mapping["targetTenantId"] = 1
        with self.assertRaises(migration.MigrationError):
            migration.project(self.bundle, self.mapping)
        self.mapping["targetTenantId"] = None
        proof = self.root / "accounts.json"
        migration.private_json(proof, {"verifiedOnEcs": True, "accounts": [{"userId": 1, "username": "changed-owner"}, {"userId": 18, "username": "inspector.demo"}]})
        self.mapping["currentAccountProofSha256"] = migration.file_sha(proof)
        with self.assertRaises(migration.MigrationError):
            migration.verify_accounts(self.mapping, proof)

    def test_prepared_vectors_require_text_owner_and_complete_coverage(self):
        output = embedding_output(self.bundle, self.mapping)
        output["records"][0]["embedding"][0] = 0.9
        with self.assertRaises(migration.MigrationError):
            migration.prepared_records(self.bundle, self.mapping, output)
        output = embedding_output(self.bundle, self.mapping)
        self.mapping["targetTenantId"] = 1
        with self.assertRaises(migration.MigrationError):
            migration.prepared_records(self.bundle, self.mapping, output)

    def test_provider_calls_are_bounded_and_existing_receipt_prevents_replay(self):
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(data=[types.SimpleNamespace(index=i, embedding=[0.1, 0.2, 0.3]) for i in range(len(kwargs["input"]))],
                usage=types.SimpleNamespace(prompt_tokens=9, total_tokens=9), model="fixture-embedding-model", _request_id="fixture-request")
        fake = types.SimpleNamespace(OpenAI=lambda **kwargs: types.SimpleNamespace(embeddings=types.SimpleNamespace(create=create)))
        config = {"model": "fixture-embedding-model", "baseUrl": "https://example.invalid/v1", "apiKey": "fixture-key", "dimensions": 3, "verifiedTargetRuntime": True}
        path = self.root / "embeddings.json"
        with patch.dict(sys.modules, {"openai": fake}):
            result = migration.reembed(self.bundle, self.mapping, config, path)
            self.assertEqual(result["reembeddedRecords"], 2)
            with self.assertRaises(migration.MigrationError):
                migration.reembed(self.bundle, self.mapping, config, path)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["input"], [r["metadata"]["data"] for r in self.bundle["records"][:2]])

    def test_provider_default_dimension_and_native_newline_normalization(self):
        calls = []
        self.bundle["records"][0]["metadata"]["data"] = "first\nsecond"
        self.bundle["records"][0]["textSha256"] = migration.sha(b"first\nsecond")
        self.mapping = owner_map(self.bundle)
        def create(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(data=[types.SimpleNamespace(index=i, embedding=[0.1, 0.2, 0.3, 0.4]) for i in range(len(kwargs["input"]))], usage=None, model="fixture-default-model")
        fake = types.SimpleNamespace(OpenAI=lambda **kwargs: types.SimpleNamespace(embeddings=types.SimpleNamespace(create=create)))
        config = {"model": "fixture-default-model", "baseUrl": "https://example.invalid/v1", "apiKey": "fixture-key", "dimensions": None, "verifiedTargetRuntime": True}
        path = self.root / "default-dimension.json"
        with patch.dict(sys.modules, {"openai": fake}):
            migration.reembed(self.bundle, self.mapping, config, path)
        self.assertNotIn("dimensions", calls[0])
        self.assertEqual(calls[0]["input"][0], "first second")
        self.assertEqual(migration.read_json(path)["dimensions"], 4)
        self.assertEqual(self.bundle["records"][0]["metadata"]["data"], "first\nsecond")

    def test_real_chroma_merge_preserves_target_and_is_idempotent(self):
        path = candidate(self.root / "candidate", self.bundle)
        collection = collection_at(path)
        collection.add(ids=["existing-cloud-memory"], embeddings=[[0.8, 0.2, 0.1]], metadatas=[{"data": "current cloud content", "user_id": "doorhandlecatch:user:1", "agent_id": "doorhandlecatch"}])
        original = migration.read_collection(collection)
        with sqlite3.connect(path / "history.db") as db:
            db.execute("CREATE TABLE messages (id TEXT PRIMARY KEY,session_scope TEXT,role TEXT,content TEXT,name TEXT,created_at DATETIME)")
            db.execute("INSERT INTO messages VALUES ('existing-cloud-message','user_id=doorhandlecatch:user:1','user','existing cloud message',NULL,'2026-10-29T00:00:00+00:00')")
        args = (self.bundle, self.mapping, embedding_output(self.bundle, self.mapping), path, path / "receipt.json", {"instanceId": "fixture-instance", "machineId": "fixture-machine"})
        first = migration.merge_candidate(*args)
        second = migration.merge_candidate(*args)
        self.assertEqual(first["activeRecords"], 2)
        self.assertEqual(second["targetTotalRecords"], 3)
        self.assertEqual(second["preservedTargetRecords"], 1)
        self.assertEqual(migration.read_collection(collection)["existing-cloud-memory"], original["existing-cloud-memory"])
        self.assertNotIn("legacy-memory-2", migration.read_collection(collection))
        with sqlite3.connect(path / "history.db") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM history").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT content FROM messages WHERE id='existing-cloud-message'").fetchone()[0], "existing cloud message")

    def test_conflicting_memory_does_not_change_target_or_history(self):
        path = candidate(self.root / "conflict", self.bundle)
        collection = collection_at(path)
        collection.add(ids=["legacy-memory-0"], embeddings=[[0.8, 0.2, 0.1]], metadatas=[{"data": "different current content", "user_id": "doorhandlecatch:user:1", "agent_id": "doorhandlecatch"}])
        original = migration.read_collection(collection)
        with self.assertRaises(migration.MigrationError):
            migration.merge_candidate(self.bundle, self.mapping, embedding_output(self.bundle, self.mapping), path, path / "receipt.json", {"instanceId": "fixture-instance", "machineId": "fixture-machine"})
        self.assertEqual(migration.read_collection(collection), original)
        self.assertFalse((path / "history.db").exists())

    def test_lifecycle_tombstone_is_not_resurrected(self):
        path = candidate(self.root / "governed", self.bundle)
        (path / "bridge_receipts").mkdir()
        with sqlite3.connect(path / "bridge_receipts/write-receipts.sqlite3") as db:
            db.execute("CREATE TABLE memory_lifecycle (memory_id TEXT,state TEXT)")
            db.execute("INSERT INTO memory_lifecycle VALUES ('legacy-memory-0','EXCLUDED')")
        with self.assertRaises(migration.MigrationError):
            migration.merge_candidate(self.bundle, self.mapping, embedding_output(self.bundle, self.mapping), path, path / "receipt.json", {"instanceId": "fixture-instance", "machineId": "fixture-machine"})
        self.assertEqual(collection_at(path).count(), 0)


def inventory_for(root, names):
    files = []
    for name in names:
        path = root / name
        files.append({"relativePath": name, "bytes": path.stat().st_size,
                      "sha256": migration.file_sha(path), "mtimeNs": path.stat().st_mtime_ns})
    return {"sources": {"rag_chroma": {"files": files}}}


def rag_bundle(count=3):
    rows = []
    for index in range(count):
        text = "质检 knowledge document " + str(index)
        vector = [0.2, 0.3, 0.4]
        rows.append({"id": "old-rag-" + str(index), "document": text,
                     "metadata": {"source": "legacy-source-" + str(index), "title": "title " + str(index)},
                     "embedding": vector, "textSha256": migration.sha(text.encode("utf8")),
                     "originalVectorSha256": migration.sha(migration.vector_bytes(vector))})
    return {"format": 1, "kind": "legacy-rag-private-export", "collection": migration.RAG_COLLECTION,
            "dimension": 3, "records": rows}


def rag_policy(bundle):
    return {"sourceBundleSha256": migration.sha(migration.canonical(bundle)), "collection": migration.RAG_COLLECTION,
            "projectScopeVerified": True, "scopeEvidence": "synthetic project-owned fixture", "expectedSourceRecords": len(bundle["records"]),
            "dispositions": {row["id"]: "import" for row in bundle["records"]},
            "targetIds": {row["id"]: row["id"] for row in bundle["records"]}, "targetDimension": 32,
            "javaSourceSha256": migration.file_sha(ROOT / migration.JAVA_EMBEDDER), "verifiedTargetRuntime": True,
            "targetEmbeddingName": "local-hashing-32", "applicationCommit": "a" * 40}


def rag_embeddings(bundle, policy):
    output = {"kind": "rag-prepared-local-embeddings", "status": "COMPLETE", "sourceBundleSha256": migration.sha(migration.canonical(bundle)),
              "policySha256": migration.sha(migration.canonical(policy)), "javaSourceSha256": policy["javaSourceSha256"], "dimensions": 32, "records": []}
    for index, row in enumerate(migration.project_rag(bundle, policy)["records"]):
        vector = [0.0] * 32
        vector[index % 32] = 1.0
        output["records"].append({"id": row["id"], "oldId": row["oldId"], "textSha256": row["textSha256"],
                                  "originalVectorSha256": row["originalVectorSha256"], "embedding": vector,
                                  "targetVectorSha256": migration.sha(migration.vector_bytes(vector))})
    return output


class LegacyStorePreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="legacy-stores-")
        self.root = Path(self.temp.name)
        self.identity = {"instanceId": "fixture-instance", "machineId": "fixture-machine"}

    def tearDown(self):
        self.temp.cleanup()

    def test_byte_snapshot_restores_hashes_times_and_records_original_permissions(self):
        source = self.root / "source"
        (source / "index").mkdir(parents=True)
        (source / "chroma.sqlite3").write_bytes(b"opaque SQLite bytes, never opened")
        (source / "index/hnsw.bin").write_bytes(bytes(range(255)))
        os.utime(source / "index/hnsw.bin", ns=(1700000000000000001, 1700000000000000002))
        inventory = inventory_for(source, ["chroma.sqlite3", "index/hnsw.bin"])
        history = self.root / "global-history"
        history.mkdir()
        (history / "history.db").write_bytes(b"opaque native history")
        (history / "config.json").write_bytes(b"private provider configuration fixture")
        inventory["sources"]["legacy_history"] = {"files": [{"relativePath": "history.db", "bytes": (history / "history.db").stat().st_size,
            "sha256": migration.file_sha(history / "history.db"), "mtimeNs": (history / "history.db").stat().st_mtime_ns}]}
        roots = {"rag_chroma": str(source), "legacy_history": str(history)}
        snapshot = self.root / "snapshot"
        migration.preserve_sources(inventory, roots, snapshot)
        restored = self.root / "restored"
        receipt = migration.verify_preservation(snapshot, restored)
        self.assertEqual(receipt["files"], 3)
        for row in inventory["sources"]["rag_chroma"]["files"]:
            path = restored / "rag_chroma" / row["relativePath"]
            self.assertEqual(migration.file_sha(path), row["sha256"])
            self.assertEqual(path.stat().st_mtime_ns, row["mtimeNs"])
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        manifest = migration.read_json(snapshot / "snapshot.json")
        self.assertIn("mode", manifest["files"][0]["permissions"])
        self.assertIn("uid", manifest["files"][0]["permissions"])
        self.assertEqual([row["path"] for row in manifest["excludedFiles"]], ["legacy_history/config.json"])
        self.assertEqual(manifest["excludedFiles"][0]["sha256"], migration.file_sha(history / "config.json"))
        self.assertFalse((restored / "legacy_history/config.json").exists())
        self.assertEqual(migration.file_sha(restored / "legacy_history/history.db"), migration.file_sha(history / "history.db"))
        for name in ("history.db-wal", "history.db-shm", "other.json"):
            (history / name).write_bytes(b"unadmitted file")
            with self.assertRaises(migration.MigrationError):
                migration.preserve_sources(inventory, roots, self.root / (name + "-refused"))
            (history / name).unlink()
        with self.assertRaises(migration.MigrationError):
            migration.verify_preservation(snapshot, restored)

    def test_snapshot_rejects_changed_inventory_and_traversal_archive(self):
        source = self.root / "source"
        source.mkdir()
        (source / "chroma.sqlite3").write_bytes(b"original")
        inventory = inventory_for(source, ["chroma.sqlite3"])
        (source / "chroma.sqlite3").write_bytes(b"changed")
        with self.assertRaises(migration.MigrationError):
            migration.preserve_sources(inventory, {"rag_chroma": str(source)}, self.root / "refused")
        snapshot = self.root / "malicious"
        snapshot.mkdir()
        with migration.tarfile.open(snapshot / "originals.tar", "w") as archive:
            member = migration.tarfile.TarInfo("../escaped")
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
        migration.private_json(snapshot / "snapshot.json", {"kind": "legacy-stores-byte-preservation", "status": "COMPLETE",
            "archiveSha256": migration.file_sha(snapshot / "originals.tar"), "files": []})
        with self.assertRaises(migration.MigrationError):
            migration.verify_preservation(snapshot, self.root / "malicious-restore")
        self.assertFalse((self.root / "escaped").exists())

    def test_sqlite_export_retains_all_32_memories_33_history_26_messages(self):
        chroma_path, history_path = self.root / "legacy-chroma.sqlite3", self.root / "legacy-history.db"
        with sqlite3.connect(chroma_path) as db:
            db.executescript("CREATE TABLE collections(id TEXT,name TEXT,dimension INTEGER);"
                "CREATE TABLE segments(id TEXT,collection TEXT,scope TEXT);"
                "CREATE TABLE embeddings(id INTEGER,embedding_id TEXT,segment_id TEXT);"
                "CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT,int_value INTEGER,float_value REAL,bool_value INTEGER);"
                "CREATE TABLE embeddings_queue(seq_id INTEGER,id TEXT,operation INTEGER,vector BLOB,encoding TEXT,metadata TEXT);")
            db.execute("INSERT INTO collections VALUES ('collection',?,3)", (migration.COLLECTION,))
            db.execute("INSERT INTO segments VALUES ('segment','collection','METADATA')")
            for index in range(32):
                owner = "admin" if index < 23 else "doorhandlecatch:user:18" if index < 30 else "integration-user"
                metadata = {"data": "original text " + str(index), "user_id": owner, "created_at": "2026-05-28T06:40:37+00:00"}
                db.execute("INSERT INTO embeddings VALUES (?,?, 'segment')", (index, "memory-" + str(index)))
                for key, value in metadata.items():
                    db.execute("INSERT INTO embedding_metadata VALUES (?,?,?,NULL,NULL,NULL)", (index, key, value))
                db.execute("INSERT INTO embeddings_queue VALUES (?,?,0,?,'FLOAT32',?)", (index, "memory-" + str(index), migration.vector_bytes([0.1, 0.2, 0.3]), json.dumps(metadata)))
        with sqlite3.connect(history_path) as db:
            db.execute("CREATE TABLE history (id TEXT,memory_id TEXT)")
            db.execute("CREATE TABLE messages (id TEXT,session_scope TEXT)")
            db.executemany("INSERT INTO history VALUES (?,?)", [("history-" + str(i), "memory-" + str(i)) for i in range(33)])
            db.executemany("INSERT INTO messages VALUES (?,?)", [("message-" + str(i), "user_id=" + ("admin" if i < 10 else "doorhandlecatch:user:18" if i < 25 else "integration-user")) for i in range(26)])
        hashes = [migration.file_sha(path) for path in (chroma_path, history_path)]
        bundle = migration.export_legacy(chroma_path, history_path)
        self.assertEqual((len(bundle["records"]), len(bundle["history"]), len(bundle["messages"])), (32, 33, 26))
        projected = migration.project(bundle, owner_map(bundle))
        self.assertEqual((len(projected["records"]), len(projected["history"]), len(projected["messages"])), (30, 30, 25))
        self.assertEqual((len(projected["archivedMemoryIds"]), projected["archivedHistoryRows"], projected["archivedMessageRows"]), (2, 3, 1))
        self.assertEqual([migration.file_sha(path) for path in (chroma_path, history_path)], hashes)

    def test_rag_export_covers_83_original_vectors_from_disposable_restore(self):
        from chromadb import PersistentClient
        from chromadb.config import Settings
        from chromadb.api.shared_system_client import SharedSystemClient
        source = self.root / "rag-source"
        client = PersistentClient(path=str(source), settings=Settings(anonymized_telemetry=False))
        collection = client.get_or_create_collection(migration.RAG_COLLECTION, embedding_function=None)
        bundle = rag_bundle(83)
        collection.add(ids=[row["id"] for row in bundle["records"]], embeddings=[row["embedding"] for row in bundle["records"]],
                       documents=[row["document"] for row in bundle["records"]], metadatas=[row["metadata"] for row in bundle["records"]])
        client._system.stop()
        SharedSystemClient.clear_system_cache()
        names = sorted(migration.tree_files(source))
        inventory = inventory_for(source, names)
        snapshot = self.root / "snapshot"
        migration.preserve_sources(inventory, {"rag_chroma": str(source)}, snapshot)
        archive_sha = migration.file_sha(snapshot / "originals.tar")
        restored = self.root / "restored"
        migration.verify_preservation(snapshot, restored)
        result = migration.rag_export(restored, 83)
        self.assertEqual(len(result["records"]), 83)
        self.assertEqual({row["id"]: row["originalVectorSha256"] for row in result["records"]},
                         {row["id"]: row["originalVectorSha256"] for row in bundle["records"]})
        self.assertEqual(migration.file_sha(snapshot / "originals.tar"), archive_sha)

    def test_rag_requires_scope_complete_dispositions_and_preserves_old_id_map(self):
        bundle = rag_bundle(83)
        policy = rag_policy(bundle)
        policy["dispositions"]["old-rag-82"] = "archive"
        policy["targetIds"].pop("old-rag-82")
        policy["targetIds"]["old-rag-0"] = "reviewed-legacy-rag-0"
        projected = migration.project_rag(bundle, policy)
        self.assertEqual(len(projected["records"]), 82)
        self.assertEqual(projected["archivedIds"], ["old-rag-82"])
        self.assertEqual(projected["records"][0]["oldId"], "old-rag-0")
        self.assertEqual(projected["records"][0]["id"], "reviewed-legacy-rag-0")
        policy["projectScopeVerified"] = False
        with self.assertRaises(migration.MigrationError):
            migration.project_rag(bundle, policy)

    def test_actual_java_rag_hashing_reembeds_unicode_without_model_calls(self):
        bundle = rag_bundle()
        bundle["records"][0]["document"] = "İ质检Ａ\n\t𝄞 e\u0301"
        bundle["records"][0]["textSha256"] = migration.sha(bundle["records"][0]["document"].encode("utf8"))
        policy = rag_policy(bundle)
        java = os.environ.get("DOORHANDLE_MIGRATION_JAVA") or shutil.which("java")
        self.assertTrue(java, "ECS verification requires its existing JDK source-file launcher")
        path = self.root / "rag-embeddings.json"
        report = migration.rag_reembed(bundle, policy, ROOT / migration.JAVA_EMBEDDER, java, self.root / "java-work", path)
        self.assertFalse(report["modelCallsPerformed"])
        self.assertEqual(report["reembeddedRecords"], 3)
        prepared = migration.read_json(path)
        self.assertEqual(len(migration.prepared_rag_records(bundle, policy, prepared)["records"]), 3)
        self.assertTrue(all(len(row["embedding"]) == 32 and any(row["embedding"]) for row in prepared["records"]))
        with self.assertRaises(migration.MigrationError):
            migration.rag_reembed(bundle, policy, ROOT / migration.JAVA_EMBEDDER, java, self.root / "java-work2", path)

    def test_rag_merge_preserves_current_docs_and_refuses_unreviewed_conflicts(self):
        from chromadb import PersistentClient
        from chromadb.config import Settings
        bundle, policy = rag_bundle(), rag_policy(rag_bundle())
        path = candidate(self.root / "rag-candidate", bundle)
        marker = migration.read_json(path / "migration-candidate.json")
        marker["scope"] = "rag-offline-candidate"
        migration.private_json(path / "migration-candidate.json", marker, replace=True)
        client = PersistentClient(path=str(path / "chroma"), settings=Settings(anonymized_telemetry=False))
        collection = client.get_or_create_collection(migration.RAG_COLLECTION, embedding_function=None)
        collection.add(ids=["current-cloud"], embeddings=[[0.3] * 32], documents=["cloud knowledge"], metadatas=[{"source": "current", "title": "current"}])
        original = migration.read_collection(collection)
        embeddings = rag_embeddings(bundle, policy)
        arguments = (bundle, policy, embeddings, path, path / "rag-receipt.json", self.identity)
        self.assertEqual(migration.rag_candidate_merge(*arguments)["activeRecords"], 3)
        self.assertEqual(migration.rag_candidate_merge(*arguments)["preservedTargetRecords"], 1)
        self.assertEqual(migration.read_collection(collection)["current-cloud"], original["current-cloud"])
        policy["targetIds"]["old-rag-0"] = "current-cloud"
        with self.assertRaises(migration.MigrationError):
            migration.rag_candidate_merge(bundle, policy, rag_embeddings(bundle, policy), path, path / "conflict-receipt.json", self.identity)
        self.assertEqual(migration.read_collection(collection)["current-cloud"], original["current-cloud"])

    def test_candidate_guard_rejects_wrong_machine_and_unrestorable_backup(self):
        bundle = rag_bundle()
        path = candidate(self.root / "candidate", bundle)
        with self.assertRaises(migration.MigrationError):
            migration.admit_candidate(path, "mem0-offline-candidate", bundle, {**self.identity, "machineId": "other-machine"})
        marker = migration.read_json(path / "migration-candidate.json")
        Path(marker["sourceBackupPath"]).write_bytes(b"modified backup")
        with self.assertRaises(migration.MigrationError):
            migration.admit_candidate(path, "mem0-offline-candidate", bundle, self.identity)


if __name__ == "__main__":
    unittest.main()
