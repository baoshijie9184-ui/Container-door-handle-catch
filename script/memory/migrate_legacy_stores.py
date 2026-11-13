#!/usr/bin/env python3
"""Preserve legacy stores and migrate only to an offline, admitted ECS candidate.

Never loads a workstation Mem0 process or overwrites a live cloud volume. Original
vectors, text and history stay in private exports and byte-identical snapshots.
Mem0 and RAG use the fixed verified BGE-M3 provider and remote Qdrant targets.
Old hashing vectors and Chroma files are preserved only as import evidence.
Adapted from this repository's prepared migrate_legacy_mem0.py (2026-11-05).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
from functools import wraps
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import subprocess
import sys
import tarfile
from types import SimpleNamespace
import urllib.request
import urllib.error
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

FORMAT = 1
COLLECTION = "doorhandle_memories"
OWNER = re.compile(r"doorhandlecatch:user:[1-9][0-9]*\Z")
RAG_COLLECTION = "door_handle_assistant_knowledge"
JAVA_EMBEDDER = "doorhandle-module-app/src/main/java/com/ruanzhu/doorhandle/module/app/service/LocalTextEmbeddingService.java"
HISTORY_COLUMNS = ("id", "memory_id", "old_memory", "new_memory", "event", "created_at", "updated_at", "is_deleted", "actor_id", "role")
MESSAGE_COLUMNS = ("id", "session_scope", "role", "content", "name", "created_at")
PRESERVATION_LEGACY_PROFILE = "legacy-stores-v1"
PRESERVATION_COMBINED_PROFILE = "legacy-stores-with-windows-mcp-v1"
PRESERVATION_KAFKA_PROFILE = "legacy-stores-with-windows-mcp-and-kafka-v1"
PRESERVATION_MAX_FILES = 8192
PRESERVATION_MAX_BYTES = 512 * 1024 ** 2
PRESERVATION_KAFKA_MAX_LOGICAL_BYTES = 2 * 1024 ** 3
PRESERVATION_MAX_MANIFEST = 16 * 1024 ** 2
# Digests cover sorted [portable member name, byte size, raw SHA256] tuples from
# the independently inventoried originals. These are byte-preservation profiles,
# never executable/import profiles or authorization to include other directories.
LEGACY_MEMBER_INVENTORY_SHA256 = "ed490983e42cb1a175af444b427de19e1a6095d008ac61b1302a1fae57d9d89a"
WINDOWS_MCP_MEMBER_INVENTORY_SHA256 = "d2d7ce9705eb37a420991d7b6db8c7e4ae79597803377ea231f9545a15a95b43"
LEGACY_KAFKA_MEMBER_INVENTORY_SHA256 = "85ae732b214d2ed49ab3baf641774e333e6efc6a9594ca6157b25c7ced326929"
LEGACY_KAFKA_FILE_COUNT = 309
PRESERVATION_SOURCE_ROOTS = {
    "personal_chroma": "D:/AI/lunwen1/DoorHandleCatch/memory_service/chroma_db",
    "legacy_history": "C:/Users/19771/.mem0",
    "rag_chroma": "D:/AI/lunwen1/DoorHandleCatch/work/middlewares/chroma",
    "windows_mcp": "D:/AI/lunwen1/DoorHandleCatch/.agentscope/workspace/users/18/mcp",
    "legacy_kafka": "D:/AI/lunwen1/DoorHandleCatch/work/middlewares/kafka-data",
}


class MigrationError(Exception):
    """A safe error whose message contains no memory or credential content."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MigrationError("Verification endpoint redirected; refusing to forward private data")


def require(condition, message):
    if not condition:
        raise MigrationError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_path(path, *, exists=True):
    p = Path(path).absolute()
    require(".." not in p.parts, "Parent path traversal is not supported")
    require(not any(x.is_symlink() or getattr(x, "is_junction", lambda: False)() for x in (p, *p.parents)), "Linked paths are not supported")
    require(not exists or p.exists(), "Required file or directory is missing")
    return p


def read_json(path):
    return json.loads(safe_path(path).read_text(encoding="utf-8-sig"))


def private_json(path, value, *, replace=False):
    p = safe_path(path, exists=False)
    require(replace or not p.exists(), "Output already exists")
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = p.with_name(p.name + "." + uuid.uuid4().hex + ".tmp")
    with os.fdopen(os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, p)


def vector_bytes(vector):
    values = [float(x) for x in vector]
    require(bool(values) and all(math.isfinite(x) for x in values), "Invalid embedding vector")
    return struct.pack("<" + "f" * len(values), *values)


def open_ro(path):
    db = sqlite3.connect(safe_path(path).as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Source SQLite integrity check failed")
    return db


def export_legacy(chroma_path, history_path):
    """Read a frozen copy. The complete add-only source queue must prove every vector."""
    sources = [{"name": "chroma.sqlite3", "sha256": file_sha(chroma_path)},
               {"name": "history.db", "sha256": file_sha(history_path)}]
    with contextlib.closing(open_ro(chroma_path)) as db:
        collections = db.execute("SELECT id, dimension FROM collections WHERE name=?", (COLLECTION,)).fetchall()
        require(len(collections) == 1, "Expected one legacy memory collection")
        collection, dimension = collections[0]
        require(type(dimension) is int and 1 <= dimension <= 8192, "Invalid source embedding dimension")
        segments = [r[0] for r in db.execute("SELECT id FROM segments WHERE collection=? AND scope='METADATA'", (collection,))]
        require(len(segments) == 1, "Expected one SQLite metadata segment")
        records = []
        for row in db.execute("SELECT id, embedding_id FROM embeddings WHERE segment_id=? ORDER BY embedding_id", (segments[0],)):
            metadata = {}
            for item in db.execute("SELECT key,string_value,int_value,float_value,bool_value FROM embedding_metadata WHERE id=?", (row[0],)):
                nonnull = [(k, item[k]) for k in ("string_value", "int_value", "float_value", "bool_value") if item[k] is not None]
                require(len(nonnull) == 1, "Unsupported legacy metadata value")
                key, value = nonnull[0]
                metadata[item["key"]] = bool(value) if key == "bool_value" else value
            require(isinstance(metadata.get("data"), str) and metadata["data"].strip(), "Source memory text is missing")
            require(isinstance(metadata.get("user_id"), str) and metadata["user_id"], "Source owner is missing")
            queued = db.execute("SELECT operation,vector,encoding,metadata FROM embeddings_queue WHERE id=? ORDER BY seq_id", (row[1],)).fetchall()
            require(len(queued) == 1 and queued[0][0] == 0 and queued[0][2] == "FLOAT32", "Source queue cannot independently prove the original vector")
            raw = queued[0][1]
            require(len(raw) == dimension * 4, "Source vector dimension mismatch")
            vector = list(struct.unpack("<" + "f" * dimension, raw))
            require(vector_bytes(vector) == raw, "Source vector is not finite FLOAT32")
            require(json.loads(queued[0][3]) == metadata, "Source metadata and queue disagree")
            records.append({"id": row[1], "metadata": metadata, "embedding": vector,
                            "originalVectorSha256": sha(raw), "textSha256": sha(metadata["data"].encode("utf8"))})
        require(len({r["id"] for r in records}) == len(records), "Duplicate source memory ID")
    with contextlib.closing(open_ro(history_path)) as db:
        history = [dict(x) for x in db.execute("SELECT * FROM history ORDER BY id")]
        messages = [dict(x) for x in db.execute("SELECT * FROM messages ORDER BY id")]
    require(file_sha(chroma_path) == sources[0]["sha256"] and file_sha(history_path) == sources[1]["sha256"], "Frozen source changed during export")
    return {"format": FORMAT, "kind": "legacy-mem0-private-export", "collection": COLLECTION,
            "dimension": dimension, "sources": sources, "records": records, "history": history, "messages": messages}


def project(bundle, mapping):
    require(bundle.get("format") == FORMAT and bundle.get("kind") == "legacy-mem0-private-export", "Unsupported source bundle")
    require(mapping.get("sourceBundleSha256") == sha(canonical(bundle)), "Owner mapping is not bound to this export")
    entries = mapping.get("owners", [])
    owners = {entry["sourceOwner"]: entry for entry in entries}
    require(len(owners) == len(entries), "Duplicate owner mapping")
    require(set(owners) == {r["metadata"]["user_id"] for r in bundle["records"]}, "Every source owner needs an explicit disposition")
    tenant = mapping.get("targetTenantId")
    require(tenant is None, "Monolith memory ownership has no tenant namespace")
    active, archived = [], []
    target_owners = {}
    for owner, entry in owners.items():
        require(entry.get("disposition") in ("import", "archive"), "Invalid owner disposition")
        require(isinstance(entry.get("reason"), str) and bool(entry["reason"]), "Owner disposition needs a reason")
        if entry["disposition"] == "import":
            require(type(entry.get("userId")) is int and entry["userId"] > 0, "Invalid target account")
            target_owners[owner] = "doorhandlecatch:user:" + str(entry["userId"])
    for record in bundle["records"]:
        source_owner = record["metadata"]["user_id"]
        if source_owner not in target_owners:
            archived.append(record["id"])
            continue
        metadata = dict(record["metadata"])
        require(metadata.get("agent_id") in (None, "doorhandlecatch"), "Imported memory belongs to another application")
        metadata.update(user_id=target_owners[source_owner], agent_id="doorhandlecatch")
        require(OWNER.fullmatch(metadata["user_id"]), "Invalid projected owner")
        active.append({**record, "metadata": metadata})
    active_ids = {r["id"] for r in active}
    history = [dict(r) for r in bundle["history"] if r["memory_id"] in active_ids]
    messages = []
    for row in bundle["messages"]:
        pieces = row["session_scope"].split("&")
        require(all("=" in s for s in pieces), "Invalid native session scope")
        scope = dict(s.split("=", 1) for s in pieces)
        require(len(scope) == len(pieces), "Duplicate native session scope field")
        old_owner = scope.get("user_id")
        if old_owner in target_owners:
            require(scope.get("agent_id") in (None, "doorhandlecatch"), "Imported message belongs to another application")
            scope.update(user_id=target_owners[old_owner], agent_id="doorhandlecatch")
            messages.append({**row, "session_scope": "&".join(f"{k}={v}" for k, v in sorted(scope.items()))})
    return {"records": active, "history": history, "messages": messages,
            "archivedMemoryIds": archived,
            "archivedHistoryRows": len(bundle["history"]) - len(history),
            "archivedMessageRows": len(bundle["messages"]) - len(messages)}


def verify_accounts(mapping, proof_path, identity=None):
    require(file_sha(proof_path) == mapping.get("currentAccountProofSha256"), "Current account proof differs from mapping")
    proof = read_json(proof_path)
    require(proof.get("verifiedOnEcs") is True, "Account identities were not verified on ECS")
    if identity is not None:
        require(proof.get("identity") == identity, "Account proof is for another ECS")
        verified = dt.datetime.fromisoformat(proof.get("verifiedAtUtc", ""))
        require(verified.tzinfo is not None and 0 <= (dt.datetime.now(dt.timezone.utc) - verified).total_seconds() <= 7200,
                "Account proof must be refreshed for this migration session")
    accounts = {r["userId"]: r for r in proof["accounts"]}
    for entry in mapping["owners"]:
        if entry["disposition"] != "import":
            continue
        row = accounts.get(entry["userId"])
        require(row is not None and row.get("username") == entry.get("username"), "Target account identity is not proven")


def ecs_identity(expected_instance, expected_machine):
    require(sys.platform == "linux", "Runtime migration actions execute only on ECS")
    machine = Path("/etc/machine-id").read_text().strip()
    require(machine == expected_machine, "ECS machine identity mismatch")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    base = "http://100.100.100.200/latest/"
    token = opener.open(urllib.request.Request(base + "api/token", data=b"", method="PUT",
        headers={"X-aliyun-ecs-metadata-token-ttl-seconds": "60"}), timeout=4).read().decode()
    instance = opener.open(urllib.request.Request(base + "meta-data/instance-id",
        headers={"X-aliyun-ecs-metadata-token": token}), timeout=4).read().decode().strip()
    require(instance == expected_instance, "ECS instance identity mismatch")
    return {"instanceId": instance, "machineId": machine}


def reembed(bundle, mapping, config, output, *, max_records=30):
    projected = project(bundle, mapping)
    rows = projected["records"]
    require(0 < len(rows) <= max_records <= 30, "Embedding record budget exceeded")
    require(isinstance(config.get("model"), str) and bool(config["model"]), "Target embedding model is missing")
    require(isinstance(config.get("baseUrl"), str) and config["baseUrl"].startswith("https://"), "Embedding provider must use HTTPS")
    require(config.get("apiKey") and config.get("verifiedTargetRuntime") is True, "Target embedding configuration is not verified")
    require("dimensions" in config and (config["dimensions"] is None or type(config["dimensions"]) is int and 1 <= config["dimensions"] <= 8192), "Target embedding dimension policy is missing")
    bge = config.get("embeddingProfile") == "siliconflow-bge-m3-v1"
    if bge:
        require(config["model"] == "BAAI/bge-m3" and config["baseUrl"] == "https://api.siliconflow.cn/v1"
                and config["dimensions"] is None, "Free BGE migration requires the exact model, provider and native fixed dimensions")
    fingerprint = sha(canonical({k: config[k] for k in ("model", "baseUrl", "dimensions")}))
    state = {"format": FORMAT, "sourceBundleSha256": sha(canonical(bundle)), "ownerMappingSha256": sha(canonical(mapping)),
             "targetModel": config["model"], "providerConfigSha256": fingerprint,
             "dimensions": config["dimensions"], "maximumRecords": max_records, "requests": [], "records": [], "status": "PREPARED"}
    if bge:
        state.update(embeddingProfile="siliconflow-bge-m3-v1", targetCollection="doorhandle_memories_bge_m3_v1")
    path = safe_path(output, exists=False)
    require(not path.exists(), "Embedding output exists; inspect it before another provider call")
    private_json(path, state)
    from openai import OpenAI
    client = OpenAI(api_key=config["apiKey"], base_url=config["baseUrl"], timeout=60, max_retries=0)
    for offset in range(0, len(rows), 8):
        batch = rows[offset:offset + 8]
        state["status"] = "REQUEST_IN_FLIGHT"
        state["requests"].append({"offset": offset, "records": len(batch), "status": "IN_FLIGHT"})
        private_json(path, state, replace=True)
        # Match the native Mem0 OpenAI embedder's input normalization. Stored text stays exact.
        request = {"model": config["model"], "input": [r["metadata"]["data"].replace("\n", " ") for r in batch], "encoding_format": "float"}
        if config["dimensions"] is not None:
            request["dimensions"] = config["dimensions"]
        response = client.embeddings.create(**request)
        result = sorted(response.data, key=lambda item: item.index)
        require([item.index for item in result] == list(range(len(batch))), "Provider embedding response cardinality mismatch")
        for row, item in zip(batch, result):
            if bge:
                require(len(item.embedding) == 1024, "Free BGE migration returned another vector dimension")
            if state["dimensions"] is None:
                state["dimensions"] = len(item.embedding)
            require(1 <= len(item.embedding) <= 8192 and len(item.embedding) == state["dimensions"], "Provider embedding dimension mismatch")
            raw = vector_bytes(item.embedding)
            state["records"].append({"id": row["id"], "textSha256": row["textSha256"],
                "originalVectorSha256": row["originalVectorSha256"], "embedding": list(struct.unpack("<" + "f" * state["dimensions"], raw)),
                "targetVectorSha256": sha(raw)})
        usage = getattr(response, "usage", None)
        state["requests"][-1].update(status="SUCCEEDED", promptTokens=getattr(usage, "prompt_tokens", None),
            totalTokens=getattr(usage, "total_tokens", None), responseModel=getattr(response, "model", None), requestId=getattr(response, "_request_id", None))
        state["status"] = "PARTIAL"
        private_json(path, state, replace=True)
    state["status"] = "COMPLETE"
    private_json(path, state, replace=True)
    return {"reembeddedRecords": len(state["records"]), "requests": len(state["requests"]),
            "model": state["targetModel"], "tokens": sum(r.get("totalTokens") or 0 for r in state["requests"]), "status": state["status"]}


def prepared_records(bundle, mapping, embeddings):
    projected = project(bundle, mapping)
    require(embeddings.get("status") == "COMPLETE" and embeddings.get("sourceBundleSha256") == sha(canonical(bundle)), "Embedding output is incomplete or belongs to another export")
    require(embeddings.get("ownerMappingSha256") == sha(canonical(mapping)), "Embedding output belongs to another owner mapping")
    vectors = {r["id"]: r for r in embeddings["records"]}
    require(len(vectors) == len(embeddings["records"]) and set(vectors) == {r["id"] for r in projected["records"]}, "Embedding output does not cover exactly the active memories")
    for row in projected["records"]:
        vector = vectors[row["id"]]
        require(vector["textSha256"] == row["textSha256"] and vector["originalVectorSha256"] == row["originalVectorSha256"], "Embedding provenance mismatch")
        require(sha(vector_bytes(vector["embedding"])) == vector["targetVectorSha256"], "Prepared embedding digest mismatch")
        row["embedding"] = vector["embedding"]
    return projected


def rag_bge_reembed(bundle, policy, config, output):
    """Re-embed source text, never reinterpret 256/old1024 vectors as BGE."""
    from memory_service.embedding_config import FreeBgeEmbedder
    from openai import OpenAI
    from types import SimpleNamespace
    require(policy.get('sourceBundleSha256') == sha(canonical(bundle))
            and policy.get('projectScopeVerified') is True and policy.get('verifiedTargetRuntime') is True
            and policy.get('collection') == 'doorhandle_rag_bge_m3_v1'
            and policy.get('targetEmbeddingName') == 'BAAI/bge-m3' and policy.get('targetDimension') == 1024
            and re.fullmatch(r'[a-f0-9]{40}', policy.get('applicationCommit', '')),
            'RAG BGE policy lacks a verified source, project and target identity')
    require(config.get('embeddingProfile') == 'siliconflow-bge-m3-v1' and config.get('model') == 'BAAI/bge-m3'
            and config.get('baseUrl') == 'https://api.siliconflow.cn/v1' and config.get('dimensions') is None
            and config.get('verifiedTargetRuntime') is True and bool(config.get('apiKey')),
            'RAG requires the fixed free BGE transport without dimension override')
    rows = bundle['records']
    require(0 < len(rows) <= 1000 and len(rows) == policy.get('expectedSourceRecords')
            and set(policy.get('dispositions', {})) == {row['id'] for row in rows}
            and all(value == 'import' for value in policy['dispositions'].values())
            and policy.get('targetIds') == {row['id']: row['id'] for row in rows},
            'Every RAG document needs an explicit stable-ID project disposition')
    for row in rows:
        require(sha(row['document'].encode()) == row['textSha256']
                and sha(vector_bytes(row['embedding'])) == row['originalVectorSha256']
                and 'user_id' not in row['metadata'] and row['metadata'].get('agent_id') in (None, 'doorhandlecatch'),
                'RAG source provenance or ownership differs')
    state = {'schemaVersion': 2, 'kind': 'rag-bge-prepared-embeddings', 'status': 'PREPARED',
             'sourceBundleSha256': sha(canonical(bundle)), 'policySha256': sha(canonical(policy)),
             'profile': 'siliconflow-bge-m3-v1', 'model': 'BAAI/bge-m3', 'dimensions': 1024,
             'preprocessing': 'utf8-newline-space-v1', 'paidModelCalls': 0, 'llmCalls': 0,
             'requests': [], 'records': []}
    path = safe_path(output, exists=False); require(not path.exists(), 'RAG BGE output already exists; no provider replay')
    private_json(path, state)
    client = OpenAI(api_key=config['apiKey'], base_url=config['baseUrl'], timeout=60, max_retries=0)
    embedder = FreeBgeEmbedder(SimpleNamespace(client=client, config=SimpleNamespace(model='BAAI/bge-m3')),
                               settings={'EMBEDDING_PROFILE': 'siliconflow-bge-m3-v1'})
    for offset in range(0, len(rows), 8):
        batch = rows[offset:offset + 8]
        state['status'] = 'REQUEST_IN_FLIGHT'; state['requests'].append({'offset': offset, 'records': len(batch), 'status': 'IN_FLIGHT'})
        private_json(path, state, replace=True)
        vectors = embedder.embed_batch([row['document'] for row in batch])
        for row, vector in zip(batch, vectors):
            raw = vector_bytes(vector)
            state['records'].append({'id': row['id'], 'textSha256': row['textSha256'],
                'originalVectorSha256': row['originalVectorSha256'], 'embedding': list(struct.unpack('<1024f', raw)),
                'rawVectorSha256': sha(raw)})
        state['requests'][-1]['status'] = 'SUCCEEDED'; state['status'] = 'PARTIAL'
        private_json(path, state, replace=True)
    state['status'] = 'COMPLETE'; private_json(path, state, replace=True)
    return {'status': 'COMPLETE', 'reembeddedRecords': len(rows), 'requests': len(state['requests']),
            'model': state['model'], 'dimensions': 1024, 'paidModelCalls': 0, 'llmCalls': 0}


def prepared_bge_rag_records(bundle, policy, embeddings):
    require(embeddings.get('status') == 'COMPLETE' and embeddings.get('kind') == 'rag-bge-prepared-embeddings'
            and embeddings.get('sourceBundleSha256') == sha(canonical(bundle))
            and embeddings.get('policySha256') == sha(canonical(policy))
            and embeddings.get('profile') == 'siliconflow-bge-m3-v1' and embeddings.get('model') == 'BAAI/bge-m3'
            and embeddings.get('dimensions') == 1024 and embeddings.get('preprocessing') == 'utf8-newline-space-v1'
            and all(row['status'] == 'SUCCEEDED' for row in embeddings.get('requests', [])),
            'Prepared BGE RAG output is incomplete or belongs to another source/model')
    vectors = {row['id']: row for row in embeddings['records']}
    require(len(vectors) == len(embeddings['records']) == len(bundle['records'])
            and set(vectors) == {row['id'] for row in bundle['records']}, 'BGE RAG vector IDs do not exactly cover the source')
    result = []
    for source in bundle['records']:
        row = vectors[source['id']]
        require(row['textSha256'] == source['textSha256'] and row['originalVectorSha256'] == source['originalVectorSha256']
                and len(row['embedding']) == 1024 and sha(vector_bytes(row['embedding'])) == row['rawVectorSha256'],
                'Prepared RAG vector/source provenance differs')
        result.append({**source, 'embedding': row['embedding']})
    return result


def read_collection(collection):
    result = {}
    count = collection.count()
    require(count <= 200000, "Candidate collection exceeds review limit")
    for offset in range(0, count, 500):
        page = collection.get(offset=offset, limit=500, include=["metadatas", "embeddings", "documents"])
        for index, ident in enumerate(page["ids"]):
            require(ident not in result, "Candidate returned duplicate IDs")
            result[ident] = {"metadata": page["metadatas"][index],
                "vectorSha256": sha(vector_bytes(page["embeddings"][index])),
                "document": page["documents"][index]}
    require(len(result) == count, "Candidate collection changed while reading")
    return result


def history_snapshot(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {name: {row["id"]: dict(row) for row in db.execute('SELECT * FROM "' + name + '" ORDER BY id')} if name in tables else {}
            for name in ("history", "messages")}


def target_connection(admission, root):
    filename = safe_path(admission.get('qdrantConfigFile', ''))
    require(filename.is_file() and root not in filename.parents and filename.stat().st_mode & 0o077 == 0,
            'Qdrant connection stays in a private file outside the preserved payload')
    config = read_json(filename)
    require(set(config) == {'backend', 'baseUrl', 'apiKeyFile'} and config['backend'] == 'qdrant',
            'An explicit remote Qdrant target is required')
    key = safe_path(config['apiKeyFile'])
    require(root not in key.parents, 'The Qdrant credential must remain outside the candidate data payload')
    from script.memory.qdrant_migration import Remote
    return Remote(config['baseUrl'], config['apiKeyFile'])


def migration_target_operation(function):
    """Keep the public migration error contract without leaking remote payloads."""
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValueError:
            raise MigrationError('Qdrant target validation failed; production remains gated') from None
    return guarded


@migration_target_operation
def merge_candidate(bundle, mapping, embeddings, candidate, receipt_path, identity):
    root = safe_path(candidate)
    admission = admit_candidate(root, 'mem0-offline-candidate', bundle, identity)
    output = safe_path(receipt_path, exists=False)
    require(not output.exists(), 'A prior target write receipt requires review; do not replay an unknown migration')
    require(embeddings.get('targetModel') == 'BAAI/bge-m3' and embeddings.get('targetCollection') == 'doorhandle_memories_bge_m3_v1'
            and embeddings.get('embeddingProfile') == 'siliconflow-bge-m3-v1' and embeddings.get('dimensions') == 1024,
            'Memory migration only writes the explicitly bound BGE/Qdrant target')
    from script.memory.qdrant_migration import COLLECTIONS, merge_history, admit_lifecycle_import, admit_history_import
    from memory_service.qdrant_store import persist_storage_floor, vector_identity
    projected = prepared_records(bundle, mapping, embeddings)
    admit_lifecycle_import(root, [row['id'] for row in projected['records']],
                           SimpleNamespace(open_ro=open_ro))
    history_adapter = SimpleNamespace(HISTORY_COLUMNS=HISTORY_COLUMNS, MESSAGE_COLUMNS=MESSAGE_COLUMNS,
                                      history_snapshot=history_snapshot, open_ro=open_ro)
    admit_history_import(projected, root, history_adapter)
    remote = target_connection(admission, root)
    remote.admit(COLLECTIONS['mem0'], create=True)
    before = remote.catalog(COLLECTIONS['mem0'])
    private_json(output, {'status': 'PREPARED', 'identity': identity, 'sourceBundleSha256': sha(canonical(bundle)),
                         'before': before, 'vectorBackend': 'qdrant'})
    imported = remote.import_records(COLLECTIONS['mem0'], projected['records'])
    history = merge_history(projected, root, history_adapter)
    persist_storage_floor(root, COLLECTIONS['mem0'], vector_identity({'EMBEDDING_PROFILE': 'siliconflow-bge-m3-v1'}))
    receipt = {'format': FORMAT, 'status': 'MERGED_PENDING_INDEPENDENT_RECOVERY', 'identity': identity,
        'sourceBundleSha256': sha(canonical(bundle)), 'ownerMappingSha256': sha(canonical(mapping)),
        'embeddingOutputSha256': sha(canonical(embeddings)), 'targetBackend': 'qdrant',
        'targetModel': 'BAAI/bge-m3', 'targetCollection': COLLECTIONS['mem0'],
        'before': before, 'storedVectors': imported['provenance'], 'after': imported['records'],
        'activeRecords': len(projected['records']), 'importedHistoryRows': len(projected['history']),
        'importedMessageRows': len(projected['messages']), 'archivedMemoryIds': projected['archivedMemoryIds'],
        'archivedHistoryRows': projected['archivedHistoryRows'], 'archivedMessageRows': projected['archivedMessageRows'],
        'historyMode': history['historyMode'], 'productionPromotionAllowed': False}
    private_json(output, receipt, replace=True)
    return {key: receipt[key] for key in ('status', 'activeRecords', 'importedHistoryRows', 'importedMessageRows',
                                         'archivedHistoryRows', 'archivedMessageRows', 'productionPromotionAllowed')}


def verify_bridge(bundle, mapping, bridge_config, receipt_path, identity):
    """Exercise the actual authenticated bridge after the candidate is activated."""
    projected = project(bundle, mapping)
    base = bridge_config.get("baseUrl", "").rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    require(parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment, "Invalid bridge base URL")
    if parsed.hostname != "localhost":
        require(ipaddress.ip_address(parsed.hostname).is_private, "Bridge verification must use the ECS internal interface")
    token = bridge_config.get("token")
    require(isinstance(token, str) and bool(token), "Bridge token is missing")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(route, body, *, authenticated=True):
        headers = {"Content-Type": "application/json", "X-Doorhandle-Memory-Protocol": "2"}
        if authenticated:
            headers["X-Doorhandle-Memory-Token"] = token
        if mapping.get("targetTenantId") is not None:
            headers["X-Doorhandle-Tenant-Id"] = str(mapping["targetTenantId"])
        req = urllib.request.Request(base + route, data=canonical(body), headers=headers, method="POST")
        try:
            with opener.open(req, timeout=15) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, None

    owners = sorted({r["metadata"]["user_id"] for r in projected["records"]})
    require(len(owners) >= 2, "Cross-owner verification requires two mapped principals")
    scope = {"app_id": "doorhandlecatch", "user_id": owners[0]}
    code, _ = request("/memories/owned/list", {**scope, "limit": 10, "offset": 0}, authenticated=False)
    require(code == 401, "Unauthenticated memory access was not denied")
    receipts = []
    for owner in owners:
        owned = [r for r in projected["records"] if r["metadata"]["user_id"] == owner]
        visible = set()
        offset = 0
        pages = 0
        for _ in range(1000):
            code, result = request("/memories/owned/list", {"user_id": owner, "app_id": "doorhandlecatch", "limit": 7, "offset": offset})
            require(code == 200 and result.get("code") == 200, "Authenticated owner pagination failed")
            page = result["data"]
            ids = {r["id"] for r in page["items"]}
            require(not visible.intersection(ids), "Owner pagination repeated a record")
            visible.update(ids)
            pages += 1
            if not page.get("hasMore"):
                break
            require(type(page.get("nextOffset")) is int and page["nextOffset"] > offset, "Owner pagination did not advance")
            offset = page["nextOffset"]
        else:
            raise MigrationError("Owner pagination exceeded its bounded limit")
        require({r["id"] for r in owned}.issubset(visible), "Imported memories are missing from their owner's page")
        foreign_ids = {r["id"] for r in projected["records"] if r["metadata"]["user_id"] != owner}
        require(not visible.intersection(foreign_ids | set(projected["archivedMemoryIds"])), "Owner page exposed another principal or archived test memory")
        for row in owned:
            body = {"user_id": owner, "app_id": "doorhandlecatch", "memory_id": row["id"]}
            code, result = request("/memories/owned/get", body)
            require(code == 200 and result.get("code") == 200, "Imported owner memory could not be read")
            item = result["data"]
            require(item.get("id") == row["id"] and sha(item.get("memory", "").encode("utf8")) == row["textSha256"], "Bridge memory text or ID differs from the source")
            require(item.get("createdAt") == row["metadata"].get("created_at") and item.get("updatedAt") == row["metadata"].get("updated_at")
                    and item.get("sourceSessionId") == row["metadata"].get("run_id"), "Bridge timestamps or session provenance changed")
            stranger = next(other for other in owners if other != owner)
            code, _ = request("/memories/owned/get", {**body, "user_id": stranger})
            require(code == 404, "Cross-owner memory read was not denied")
        for ident in projected["archivedMemoryIds"]:
            code, _ = request("/memories/owned/get", {"user_id": owner, "app_id": "doorhandlecatch", "memory_id": ident})
            require(code == 404, "Archived test memory became visible to a real account")
        receipts.append({"owner": owner, "importedRecordsVerified": len(owned), "paginationPages": pages,
                         "visibleRecords": len(visible), "crossOwnerReadsDenied": len(owned), "archivedReadsDenied": len(projected["archivedMemoryIds"])})
    receipt = {"status": "BRIDGE_VERIFIED", "identity": identity, "sourceBundleSha256": sha(canonical(bundle)),
               "ownerMappingSha256": sha(canonical(mapping)), "unauthenticatedReadStatus": 401, "owners": receipts,
               "memoryWritesPerformed": False, "modelCallsPerformed": False, "verifiedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat()}
    private_json(receipt_path, receipt)
    return receipt


def relative_name(value):
    """Accept portable archive members, never links or traversal paths."""
    require(isinstance(value, str) and value and "\\" not in value and ":" not in value,
            "Invalid archive member name")
    parts = value.split("/")
    require(all(part not in ("", ".", "..") for part in parts), "Unsafe archive member name")
    return value


def admit_candidate(root, scope, bundle, identity):
    require(root.is_dir() and root.stat().st_uid == os.getuid() and not root.stat().st_mode & 0o077,
            "Candidate must be an owner-only directory")
    require(not any(path == Path("/data") or path == Path("/var/lib/docker/volumes") for path in (root, *root.parents)),
            "A live runtime or Docker volume cannot be a migration candidate")
    marker = safe_path(root / "migration-candidate.json")
    require(marker.is_file() and marker.stat().st_uid == os.getuid() and not marker.stat().st_mode & 0o077,
            "Candidate marker must be private and owned by the executor")
    admission = read_json(marker)
    require(admission.get("scope") == scope and admission.get("instanceId") == identity["instanceId"]
            and admission.get("machineId") == identity["machineId"] and admission.get("sourceQuiesced") is True,
            "Offline candidate identity or quiescence is not admitted")
    require(admission.get("sourceBundleSha256") == sha(canonical(bundle)), "Candidate belongs to another source export")
    backup = safe_path(admission.get("sourceBackupPath", ""))
    require(backup.is_file() and root not in backup.parents and file_sha(backup) == admission.get("sourceBackupSha256"),
            "Current volume requires an intact backup outside the candidate")
    proof = read_json(admission.get("restoreProofPath", ""))
    require(proof.get("status") == "RESTORED_VERIFIED" and proof.get("archiveSha256") == admission.get("sourceBackupSha256")
            and proof.get("identity") == identity and proof.get("fullVolume") is True,
            "Current full-volume backup needs an ECS restore verification proof")
    return admission


def tree_files(root, *, maximum=4096):
    root = safe_path(root)
    require(root.is_dir(), "Snapshot source must be a directory")
    found = {}
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            safe_path(Path(folder) / name)
        for name in files:
            path = Path(folder) / name
            require(path.is_file(), "Unsupported source file type")
            found[relative_name(path.relative_to(root).as_posix())] = path
            require(len(found) <= maximum, "Snapshot file budget exceeded")
    return found


def permission_record(path):
    info = path.stat()
    result = {"mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid,
              "mtimeNs": info.st_mtime_ns, "atimeNs": info.st_atime_ns}
    if os.name == "nt":
        # Use the read-only Windows API, independent of installed PowerShell modules.
        import ctypes
        from ctypes import wintypes
        security = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        security.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID,
                                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        security.GetFileSecurityW.restype = wintypes.BOOL
        security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.DWORD)]
        security.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [wintypes.LPVOID]
        kernel.LocalFree.restype = wintypes.LPVOID
        length = wintypes.DWORD()
        flags = 0x00000001 | 0x00000002 | 0x00000004  # Owner, group and DACL; no privileged SACL request.
        security.GetFileSecurityW(str(path), flags, None, 0, ctypes.byref(length))
        require(length.value > 0 and ctypes.get_last_error() == 122, "Unable to size original Windows permissions")
        descriptor = ctypes.create_string_buffer(length.value)
        require(security.GetFileSecurityW(str(path), flags, descriptor, length, ctypes.byref(length)),
                "Unable to capture original Windows permissions")
        text = wintypes.LPWSTR()
        require(security.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, flags, ctypes.byref(text), None),
                "Unable to encode original Windows permissions")
        try:
            result["windowsSddl"] = text.value
        finally:
            kernel.LocalFree(ctypes.cast(text, wintypes.LPVOID))
        require(bool(result["windowsSddl"]), "Original Windows permissions are missing")
    return result


def preservation_member_inventory(files):
    return sha(canonical(sorted([[row["path"], row["bytes"], row["sha256"]] for row in files])))


def validate_preservation_plan(manifest):
    """Closed, byte-only CI admission; accepts the original minimal snapshot too."""
    require(isinstance(manifest, dict) and manifest.get("format") == FORMAT
            and manifest.get("kind") == "legacy-stores-byte-preservation"
            and manifest.get("status") == "COMPLETE", "Expected a completed source byte snapshot")
    profile = manifest.get("profile", PRESERVATION_LEGACY_PROFILE)
    require(profile in (PRESERVATION_LEGACY_PROFILE, PRESERVATION_COMBINED_PROFILE, PRESERVATION_KAFKA_PROFILE),
            "Unknown source preservation profile")
    kafka_profile = profile == PRESERVATION_KAFKA_PROFILE
    logical_limit = PRESERVATION_KAFKA_MAX_LOGICAL_BYTES if kafka_profile else PRESERVATION_MAX_BYTES
    required = {"format", "kind", "status", "inventorySha256", "files", "directories", "originalBytes", "excludedFiles", "permissionPolicy"}
    if kafka_profile:
        required.add("archiveEncoding")
        require(manifest.get("archiveEncoding") == "TAR_GZIP", "Kafka preservation requires explicit TAR_GZIP encoding")
    require(required <= set(manifest) <= required | {"archiveSha256", "profile", "memberInventorySha256"}
            and re.fullmatch(r"[a-f0-9]{64}", manifest.get("inventorySha256", "")),
            "Unexpected preservation metadata or missing inventory binding")
    files = manifest.get("files")
    require(isinstance(files, list) and 0 < len(files) <= PRESERVATION_MAX_FILES, "Preservation member count exceeds its bound")
    labels = {"personal_chroma", "legacy_history", "rag_chroma"}
    if profile in (PRESERVATION_COMBINED_PROFILE, PRESERVATION_KAFKA_PROFILE):
        labels.add("windows_mcp")
    if kafka_profile:
        labels.add("legacy_kafka")
    def permissions(value):
        fields = {"mode", "uid", "gid", "atimeNs", "mtimeNs"}
        require(isinstance(value, dict) and fields <= set(value) <= fields | {"windowsSddl"}
                and all(type(value[key]) is int and value[key] >= 0 for key in fields)
                and value["mode"] <= 0o7777
                and ("windowsSddl" not in value or isinstance(value["windowsSddl"], str)
                     and 0 < len(value["windowsSddl"]) <= 16384), "Unexpected original permission metadata")
    seen, groups, total = set(), {label: [] for label in labels}, 0
    for row in files:
        require(isinstance(row, dict) and set(row) == {"path", "sourcePath", "bytes", "sha256", "permissions"}
                and isinstance(row.get("path"), str), "Invalid preservation member metadata")
        name = relative_name(row["path"])
        permissions(row["permissions"])
        require(len(name) <= 512 and name not in seen and "/" in name, "Repeated or oversized preservation member")
        seen.add(name)
        label, relative = name.split("/", 1)
        require(label in labels and type(row.get("bytes")) is int and 0 <= row["bytes"] <= logical_limit
                and isinstance(row.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", row["sha256"]),
                "Member escaped the closed preservation roots or byte budget")
        raw_source = row.get("sourcePath")
        require(isinstance(raw_source, str) and not any(part in (".", "..") for part in raw_source.replace("\\", "/").split("/")),
                "Source path is not a frozen original root")
        normalized = re.sub(r"/+", "/", raw_source.replace("\\", "/"))
        expected = PRESERVATION_SOURCE_ROOTS[label] + "/" + relative
        require(normalized.casefold() == expected.casefold(), "Preservation source is outside the reviewed original roots")
        groups[label].append(row); total += row["bytes"]
    require(total == manifest.get("originalBytes") and total <= logical_limit,
            "Preservation total differs or exceeds the original-byte bound")
    directories = manifest["directories"]
    require(isinstance(directories, list) and len(directories) <= PRESERVATION_MAX_FILES
            and all(isinstance(row, dict) and set(row) == {"path", "permissions"}
                    and relative_name(row["path"]).split("/", 1)[0] in labels for row in directories),
            "Preservation directory metadata escaped its closed source roots")
    for row in directories:
        permissions(row["permissions"])
    excluded = manifest["excludedFiles"]
    require(isinstance(excluded, list) and len(excluded) <= 1
            and all(set(row) == {"path", "bytes", "sha256", "reason"} and row["path"] == "legacy_history/config.json"
                    and type(row["bytes"]) is int and row["bytes"] >= 0
                    and re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                    and row["reason"] == "global Mem0 provider configuration outside business-data inventory; raw hash only, no decoding or archive member"
                    for row in excluded), "Only the named unarchived global provider configuration may be described")
    require(manifest["permissionPolicy"] == "original modes/ownership/NTFS SDDL retained privately; ECS access stays owner-only",
            "Unexpected preservation permissions policy")
    business = [row for label in ("personal_chroma", "legacy_history", "rag_chroma") for row in groups[label]]
    require(preservation_member_inventory(business) == LEGACY_MEMBER_INVENTORY_SHA256,
            "Original legacy store names, bytes or hashes changed")
    windows = groups.get("windows_mcp", [])
    if profile in (PRESERVATION_COMBINED_PROFILE, PRESERVATION_KAFKA_PROFILE):
        require(preservation_member_inventory(windows) == WINDOWS_MCP_MEMBER_INVENTORY_SHA256,
                "Windows MCP members differ from the independently reviewed frozen inventory")
    kafka = groups.get("legacy_kafka", [])
    if kafka_profile:
        require(len(kafka) == LEGACY_KAFKA_FILE_COUNT
                and preservation_member_inventory(kafka) == LEGACY_KAFKA_MEMBER_INVENTORY_SHA256,
                "Kafka members differ from the complete independently frozen inventory")
    require("memberInventorySha256" not in manifest or manifest["memberInventorySha256"] == preservation_member_inventory(files),
            "Preservation member inventory digest changed")
    return {"profile": profile, "files": len(files), "bytes": total,
            "memberInventorySha256": preservation_member_inventory(files),
            "businessFiles": len(business), "windowsMcpFiles": len(windows),
            "businessBytes": sum(row["bytes"] for row in business), "windowsMcpBytes": sum(row["bytes"] for row in windows),
            "kafkaFiles": len(kafka), "kafkaBytes": sum(row["bytes"] for row in kafka),
            "archiveEncoding": "TAR_GZIP" if kafka_profile else "TAR",
            "logicalByteLimit": logical_limit, "transportByteLimit": PRESERVATION_MAX_BYTES}


def preserve_sources(inventory, roots, destination):
    """Byte-only preservation; never opens SQLite/Chroma, even on a workstation.

    roots maps the three inventory source names to ORIGINAL, unchanged trees.
    The resulting private directory is the unit to transfer and retain on ECS.
    """
    require(set(roots) == set(inventory.get("sources", {})), "Every inventory source needs an explicit root")
    kafka_profile = inventory.get("profile") == PRESERVATION_KAFKA_PROFILE
    logical_limit = PRESERVATION_KAFKA_MAX_LOGICAL_BYTES if kafka_profile else PRESERVATION_MAX_BYTES
    output = safe_path(destination, exists=False)
    require(not output.exists(), "Preservation output must be new")
    planned, directories, excluded = [], [], []
    total = 0
    for label, source in inventory["sources"].items():
        require(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", label), "Invalid source label")
        root = safe_path(roots[label])
        require(output != root and root not in output.parents, "Output cannot be inside a source")
        actual = tree_files(root, maximum=PRESERVATION_MAX_FILES
                            if inventory.get("profile") in (PRESERVATION_COMBINED_PROFILE, PRESERVATION_KAFKA_PROFILE)
                            and label == "windows_mcp" else 4096)
        expected = {relative_name(row["relativePath"]): row for row in source["files"]}
        extras = set(actual) - set(expected)
        # A global Mem0 directory can include credentials unrelated to this DB.
        # This single named exclusion never admits WAL/SHM or other missing data.
        allowed_extras = {"config.json"} if label == "legacy_history" and set(expected) == {"history.db"} else set()
        require(len(expected) == len(source["files"]) and not set(expected) - set(actual)
                and extras <= allowed_extras, "Source inventory file set changed")
        excluded.extend({"path": label + "/" + name, "bytes": actual[name].stat().st_size,
                         "sha256": file_sha(actual[name]),
                         "reason": "global Mem0 provider configuration outside business-data inventory; raw hash only, no decoding or archive member"}
                        for name in sorted(extras))
        for directory, names, _ in os.walk(root, followlinks=False):
            directories.append({"path": label + ("/" + Path(directory).relative_to(root).as_posix() if Path(directory) != root else ""),
                                "permissions": permission_record(Path(directory))})
        for name in sorted(expected):
            path, expected_file = actual[name], expected[name]
            original = permission_record(path)
            require(path.stat().st_size == expected_file["bytes"] and file_sha(path) == expected_file["sha256"], "Source bytes changed since inventory")
            require(original["mtimeNs"] == expected_file["mtimeNs"], "Source modification time changed since inventory")
            planned.append({"path": label + "/" + name, "sourcePath": str(path), "bytes": expected_file["bytes"],
                            "sha256": expected_file["sha256"], "permissions": original})
            total += expected_file["bytes"]
    require(total <= logical_limit and len(planned) <= PRESERVATION_MAX_FILES, "Preservation byte/member budget exceeded")
    output.mkdir(mode=0o700)
    archive = output / "originals.tar"
    manifest = {"format": FORMAT, "kind": "legacy-stores-byte-preservation", "inventorySha256": sha(canonical(inventory)),
                "files": planned, "directories": directories, "originalBytes": total, "excludedFiles": excluded,
                "permissionPolicy": "original modes/ownership/NTFS SDDL retained privately; ECS access stays owner-only"}
    if "profile" in inventory:
        manifest.update(profile=inventory["profile"], memberInventorySha256=preservation_member_inventory(planned))
        if kafka_profile:
            manifest["archiveEncoding"] = "TAR_GZIP"
        validate_preservation_plan({**manifest, "status": "COMPLETE"})
    require(len(canonical(manifest)) <= PRESERVATION_MAX_MANIFEST, "Preservation manifest exceeds its private metadata bound")
    # A partial archive is never labelled COMPLETE and is retained for inspection.
    private_json(output / "snapshot.json", {**manifest, "status": "PREPARED"})
    with os.fdopen(os.open(archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz" if kafka_profile else "w", format=tarfile.PAX_FORMAT,
                          dereference=True, **({"compresslevel": 6} if kafka_profile else {})) as tar:
            for entry in planned:
                path = Path(entry["sourcePath"])
                info = tar.gettarinfo(str(path), arcname=entry["path"])
                require(info.isfile(), "Source changed into a non-regular file")
                with path.open("rb") as content:
                    tar.addfile(info, content)
                require(file_sha(path) == entry["sha256"] and path.stat().st_mtime_ns == entry["permissions"]["mtimeNs"], "Source changed while preserving")
        stream.flush()
        os.fsync(stream.fileno())
    require(archive.stat().st_size <= PRESERVATION_MAX_BYTES, "Preservation archive exceeds its retained byte bound")
    manifest.update(status="COMPLETE", archiveSha256=file_sha(archive))
    private_json(output / "snapshot.json", manifest, replace=True)
    verify_preservation(output)
    return {"status": "PRESERVED", "files": len(planned), "bytes": total, "archiveSha256": manifest["archiveSha256"]}


def verify_preservation(snapshot, restore=None):
    """Verify every archive byte; optionally recover into a NEW private ECS tree."""
    root = safe_path(snapshot)
    require((root / "snapshot.json").stat().st_size <= PRESERVATION_MAX_MANIFEST, "Private preservation manifest exceeds its bound")
    manifest = read_json(root / "snapshot.json")
    require(manifest.get("kind") == "legacy-stores-byte-preservation" and manifest.get("status") == "COMPLETE", "Preservation snapshot is incomplete")
    archive = safe_path(root / "originals.tar")
    require(archive.stat().st_size <= PRESERVATION_MAX_BYTES and len(manifest.get("files", [])) <= PRESERVATION_MAX_FILES,
            "Preservation archive/member budget exceeded")
    if "profile" in manifest:
        validate_preservation_plan(manifest)
    kafka_profile = manifest.get("profile") == PRESERVATION_KAFKA_PROFILE
    logical_limit = PRESERVATION_KAFKA_MAX_LOGICAL_BYTES if kafka_profile else PRESERVATION_MAX_BYTES
    require(kafka_profile or "archiveEncoding" not in manifest, "Only the closed Kafka profile admits encoded archives")
    require(file_sha(archive) == manifest.get("archiveSha256"), "Preservation archive digest mismatch")
    with archive.open("rb") as stream:
        require((stream.read(2) == b"\x1f\x8b") == kafka_profile, "Archive encoding differs from its closed preservation profile")
    expected = {relative_name(row["path"]): row for row in manifest["files"]}
    require(len(expected) == len(manifest["files"]), "Duplicate preservation member")
    require(all(type(row.get("bytes")) is int and row["bytes"] >= 0 for row in expected.values())
            and sum(row["bytes"] for row in expected.values()) == manifest.get("originalBytes")
            and sum(row["bytes"] for row in expected.values()) <= logical_limit,
            "Preservation logical byte budget exceeded")
    output = safe_path(restore, exists=False) if restore is not None else None
    if output is not None:
        require(not output.exists() and output != root and root not in output.parents, "Restore requires a new, separate directory")
        output.mkdir(parents=True, mode=0o700)
    seen, copied_total = set(), 0
    zero_block = bytes(1024 * 1024)
    tar_options = {}
    if kafka_profile:
        expanded_limit = logical_limit + PRESERVATION_MAX_FILES * 8192

        class BoundedPreservationTarInfo(tarfile.TarInfo):
            def _proc_gnusparse_00(self, *args):
                raise MigrationError("Compressed preservation cannot contain foreign GNU sparse metadata")

            _proc_gnusparse_01 = _proc_gnusparse_00
            _proc_gnusparse_10 = _proc_gnusparse_00

            @staticmethod
            def checked_header(info):
                require(info.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.XHDTYPE, tarfile.XGLTYPE)
                        and 0 <= info.size <= (logical_limit if info.isfile() else 65536),
                        "Compressed preservation header exceeds its closed metadata bound")
                return info

            @classmethod
            def frombuf(cls, buf, encoding, errors):
                return cls.checked_header(super().frombuf(buf, encoding, errors))

            def _proc_member(self, archive):
                # New tarfile parsers use _frombuf directly. This dispatch runs
                # for every raw header before PAX reads or sparse processing.
                self.checked_header(self)
                require(archive.fileobj.tell() + self._block(self.size) <= expanded_limit,
                        "Compressed preservation expanded byte bound exceeded")
                info = super()._proc_member(archive)
                require(info.offset_data + info.size <= expanded_limit,
                        "Compressed preservation expanded byte bound exceeded")
                return info

            @classmethod
            def fromtarfile(cls, archive):
                require(archive.fileobj.tell() <= expanded_limit, "Compressed preservation expanded byte bound exceeded")
                info = super().fromtarfile(archive)
                require(info.offset_data + info.size <= expanded_limit, "Compressed preservation expanded byte bound exceeded")
                return info

        tar_options["tarinfo"] = BoundedPreservationTarInfo
    with tarfile.open(archive, mode="r:gz" if kafka_profile else "r:", **tar_options) as tar:
        for member in tar:
            name = relative_name(member.name)
            require(member.isfile() and name in expected and name not in seen, "Unexpected archive member or link")
            row = expected[name]
            require(member.size == row["bytes"], "Archive member size mismatch")
            digest = hashlib.sha256()
            copied = 0
            with contextlib.closing(tar.extractfile(member)) as content:
                target = output / name if output is not None else None
                if target is not None:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with contextlib.ExitStack() as stack:
                    stream = stack.enter_context(os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb")) if target else None
                    for chunk in iter(lambda: content.read(1024 * 1024), b""):
                        copied += len(chunk); copied_total += len(chunk)
                        require(copied <= row["bytes"] and copied_total <= logical_limit, "Archive expanded beyond its logical byte budget")
                        digest.update(chunk)
                        if stream:
                            if chunk == zero_block[:len(chunk)]:
                                stream.seek(len(chunk), os.SEEK_CUR)
                            else:
                                stream.write(chunk)
                    if stream:
                        # Seeking a final all-zero chunk does not extend a file.
                        stream.truncate(row["bytes"])
                        stream.flush()
                        os.fsync(stream.fileno())
            require(copied == row["bytes"] and digest.hexdigest() == row["sha256"], "Archive member digest mismatch")
            if target is not None:
                # NTFS/foreign ownership is retained in the manifest, not granted to Linux users.
                os.utime(target, ns=(row["permissions"]["atimeNs"], row["permissions"]["mtimeNs"]))
                require(file_sha(target) == row["sha256"], "Recovered file digest mismatch")
            seen.add(name)
    require(seen == set(expected), "Preservation archive is missing files")
    receipt = {"status": "RESTORED_VERIFIED" if output else "SNAPSHOT_VERIFIED", "archiveSha256": manifest["archiveSha256"],
               "snapshotManifestSha256": file_sha(root / "snapshot.json"), "files": len(seen), "bytes": sum(row["bytes"] for row in expected.values())}
    if output:
        private_json(output / "original-manifest.json", manifest)
        private_json(output / "restore-receipt.json", receipt)
    return receipt


def rag_export(snapshot, expected_count):
    """Read a disposable restored COPY; Chroma may upgrade its own SQLite schema.

    The original archive is never opened by Chroma; only a verified restore is.
    HNSW/queue/pickle bytes remain intact in the preservation archive. No unpickle.
    """
    require(type(expected_count) is int and 0 < expected_count <= 1000, "Invalid RAG export count")
    source = safe_path(snapshot)
    require((source / "restore-receipt.json").is_file(), "RAG export requires a verified disposable restore")
    original = {name: file_sha(path) for name, path in tree_files(source / "rag_chroma").items()}
    manifest = read_json(source / "original-manifest.json")
    receipt = read_json(source / "restore-receipt.json")
    require(receipt.get("status") == "RESTORED_VERIFIED" and receipt.get("snapshotManifestSha256") == sha(canonical(manifest)), "RAG restore provenance differs")
    expected = {row["path"][len("rag_chroma/"):]: row["sha256"] for row in manifest["files"] if row["path"].startswith("rag_chroma/")}
    require(original == expected, "Disposable RAG restore differs from the preserved original")
    from chromadb import PersistentClient
    from chromadb.config import Settings
    client = PersistentClient(path=str(source / "rag_chroma"), settings=Settings(anonymized_telemetry=False))
    collection = client.get_collection(RAG_COLLECTION, embedding_function=None)
    before = read_collection(collection)
    require(len(before) == expected_count, "RAG export does not match the admitted count")
    page = collection.get(limit=expected_count, include=["embeddings", "metadatas", "documents"])
    rows = []
    for index, ident in enumerate(page["ids"]):
        text, metadata, vector = page["documents"][index], page["metadatas"][index], page["embeddings"][index]
        require(isinstance(text, str) and text.strip() and isinstance(metadata, dict), "RAG document or metadata is missing")
        require(all(isinstance(metadata.get(key), str) and metadata[key] for key in ("source", "title")), "RAG source/title is missing")
        raw = vector_bytes(vector)
        rows.append({"id": ident, "document": text, "metadata": metadata, "embedding": list(struct.unpack("<" + "f" * len(vector), raw)),
                     "textSha256": sha(text.encode("utf8")), "originalVectorSha256": sha(raw)})
    require(len({r["id"] for r in rows}) == expected_count and read_collection(collection) == before, "RAG read changed during export")
    dimensions = {len(row["embedding"]) for row in rows}
    require(len(dimensions) == 1, "Original RAG vectors have mixed dimensions")
    return {"format": FORMAT, "kind": "legacy-rag-private-export", "collection": RAG_COLLECTION, "dimension": dimensions.pop(),
            "restoredSnapshotReceiptSha256": file_sha(source / "restore-receipt.json"), "originalFilesSha256": original,
            "sourceArchiveSha256": receipt["archiveSha256"], "sourceManifestSha256": receipt["snapshotManifestSha256"],
            "records": sorted(rows, key=lambda row: row["id"])}


def project_rag(bundle, policy):
    require(bundle.get("format") == FORMAT and bundle.get("kind") == "legacy-rag-private-export"
            and bundle.get("collection") == RAG_COLLECTION, "Unsupported RAG export")
    require(policy.get("sourceBundleSha256") == sha(canonical(bundle)), "RAG policy is not bound to this export")
    bge = policy.get("collection") == "doorhandle_rag_bge_m3_v1"
    require(policy.get("collection") in (RAG_COLLECTION, "doorhandle_rag_bge_m3_v1") and policy.get("projectScopeVerified") is True
            and isinstance(policy.get("scopeEvidence"), str) and policy["scopeEvidence"], "RAG project scope requires explicit evidence")
    require(policy.get("verifiedTargetRuntime") is True
            and (policy.get("targetEmbeddingName") == "BAAI/bge-m3" and policy.get("targetDimension") == 1024 if bge
                 else policy.get("targetEmbeddingName") == "local-hashing-" + str(policy.get("targetDimension")))
            and re.fullmatch(r"[a-f0-9]{40}", policy.get("applicationCommit", "")), "RAG target hashing configuration and commit need runtime verification")
    rows = bundle["records"]
    require(len(rows) == policy.get("expectedSourceRecords") and 0 < len(rows) <= 1000, "RAG source count differs from policy")
    dispositions = policy.get("dispositions", {})
    require(set(dispositions) == {row["id"] for row in rows} and len(dispositions) == len(rows), "Every RAG document needs an explicit disposition")
    require(all(value in ("import", "archive") for value in dispositions.values()), "Invalid RAG disposition")
    target_ids = policy.get("targetIds", {})
    require(set(target_ids) == {ident for ident, disposition in dispositions.items() if disposition == "import"}, "Every admitted RAG ID needs an explicit target ID")
    require(len(set(target_ids.values())) == len(target_ids) and all(isinstance(value, str) and value for value in target_ids.values()), "Invalid RAG target ID mapping")
    active = []
    for row in rows:
        require(sha(row["document"].encode("utf8")) == row["textSha256"] and sha(vector_bytes(row["embedding"])) == row["originalVectorSha256"], "RAG export provenance mismatch")
        if dispositions[row["id"]] == "import":
            require(row["metadata"].get("agent_id") in (None, "doorhandlecatch") and "user_id" not in row["metadata"],
                    "User-owned or foreign-application RAG records need separate ownership reconciliation")
            active.append({**row, "oldId": row["id"], "id": target_ids[row["id"]]})
    return {"records": active, "archivedIds": [row["id"] for row in rows if dispositions[row["id"]] == "archive"]}


def java_embedder_source(source):
    """Wrap the actual checked-in class instead of approximating Java float/Unicode."""
    require(source.count("public class LocalTextEmbeddingService {") == 1, "Java embedder source shape changed")
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("package ") or stripped.startswith("import ") and not stripped.startswith("import java."):
            continue
        if stripped in ("@Service", "@RequiredArgsConstructor"):
            continue
        lines.append(line)
    body = "\n".join(lines).replace("public class LocalTextEmbeddingService {", "class LocalTextEmbeddingService {\n"
        "    LocalTextEmbeddingService(ChatAssistantProperties properties) { this.properties = properties; }")
    return "import java.io.*;\nimport java.nio.*;\nimport java.util.Base64;\n" + body + '''
class ChatAssistantProperties {
    private final Integer dimension;
    ChatAssistantProperties(Integer value) { dimension = value; }
    Integer getChromaEmbeddingDimension() { return dimension; }
}
class StringUtils { static boolean hasText(String value) { return value != null && !value.isBlank(); } }
class DoorhandleRagEmbeddingBridge {
    public static void main(String[] args) throws Exception {
        var embedder = new LocalTextEmbeddingService(new ChatAssistantProperties(Integer.valueOf(args[0])));
        var input = new BufferedReader(new InputStreamReader(System.in, java.nio.charset.StandardCharsets.UTF_8));
        for (String line; (line = input.readLine()) != null;) {
            String text = new String(Base64.getDecoder().decode(line), java.nio.charset.StandardCharsets.UTF_8);
            float[] vector = embedder.embed(text);
            ByteBuffer bytes = ByteBuffer.allocate(vector.length * 4).order(ByteOrder.LITTLE_ENDIAN);
            for (float value : vector) { bytes.putFloat(value); }
            System.out.println(Base64.getEncoder().encodeToString(bytes.array()));
        }
    }
}
'''


def rag_reembed(bundle, policy, source_path, java_path, workdir, output):
    projected = project_rag(bundle, policy)
    rows = projected["records"]
    dimension = policy.get("targetDimension")
    require(type(dimension) is int and 32 <= dimension <= 8192 and rows, "Invalid RAG target dimension or empty admission")
    source = safe_path(source_path)
    require(source.as_posix().endswith(JAVA_EMBEDDER), "RAG must reuse the application Java embedder")
    require(file_sha(source) == policy.get("javaSourceSha256"), "RAG Java source digest differs from policy")
    java = safe_path(Path(java_path).resolve(strict=True))
    require(java.is_file() and os.access(java, os.X_OK), "Existing Java executable is required")
    directory = safe_path(workdir, exists=False)
    require(not directory.exists() and not safe_path(output, exists=False).exists(), "RAG embedding work/output must be new")
    directory.mkdir(parents=True, mode=0o700)
    generated = directory / "DoorhandleRagEmbeddingBridge.java"
    with os.fdopen(os.open(generated, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf8") as stream:
        stream.write(java_embedder_source(source.read_text(encoding="utf-8-sig")))
    state = {"format": FORMAT, "kind": "rag-prepared-local-embeddings", "status": "PREPARED",
             "sourceBundleSha256": sha(canonical(bundle)), "policySha256": sha(canonical(policy)), "javaSourceSha256": file_sha(source),
             "generatedSourceSha256": file_sha(generated), "dimensions": dimension, "modelCallsPerformed": False, "records": []}
    private_json(output, state)
    request = b"".join(base64.b64encode(row["document"].encode("utf8")) + b"\n" for row in rows)
    # Source-file launcher selects the FIRST top-level class. Put the main entry first.
    generated_text = generated.read_text(encoding="utf8")
    marker = "class DoorhandleRagEmbeddingBridge {"
    start = generated_text.index(marker)
    entry = generated_text[start:]
    remainder = generated_text[:start]
    imports_end = remainder.index("class LocalTextEmbeddingService {")
    generated.write_text(remainder[:imports_end] + entry + "\n" + remainder[imports_end:], encoding="utf8")
    state["generatedSourceSha256"] = file_sha(generated)
    private_json(output, state, replace=True)
    result = subprocess.run([str(java), str(generated), str(dimension)], input=request,
                            capture_output=True, timeout=120, check=False, cwd=directory)
    require(result.returncode == 0, "Existing Java could not execute the exact RAG embedder; private candidate retained")
    vectors = result.stdout.splitlines()
    require(len(vectors) == len(rows), "Java RAG embedder returned an unexpected number of vectors")
    for row, encoded in zip(rows, vectors):
        raw = base64.b64decode(encoded, validate=True)
        require(len(raw) == dimension * 4, "Java RAG vector dimension mismatch")
        values = list(struct.unpack("<" + "f" * dimension, raw))
        require(vector_bytes(values) == raw, "Java RAG vector is not finite FLOAT32")
        state["records"].append({"id": row["id"], "oldId": row["oldId"], "textSha256": row["textSha256"],
                                 "originalVectorSha256": row["originalVectorSha256"], "targetVectorSha256": sha(raw), "embedding": values})
    require(file_sha(source) == state["javaSourceSha256"], "Java RAG source changed during embedding")
    state["status"] = "COMPLETE"
    private_json(output, state, replace=True)
    return {"status": "COMPLETE", "reembeddedRecords": len(rows), "dimensions": dimension, "modelCallsPerformed": False}


def prepared_rag_records(bundle, policy, embeddings):
    projected = project_rag(bundle, policy)
    require(embeddings.get("kind") == "rag-prepared-local-embeddings" and embeddings.get("status") == "COMPLETE"
            and embeddings.get("sourceBundleSha256") == sha(canonical(bundle)) and embeddings.get("policySha256") == sha(canonical(policy))
            and embeddings.get("javaSourceSha256") == policy.get("javaSourceSha256")
            and embeddings.get("dimensions") == policy.get("targetDimension"), "RAG prepared vectors do not match the admitted source/policy")
    vectors = {row["id"]: row for row in embeddings["records"]}
    require(len(vectors) == len(embeddings["records"]) and set(vectors) == {row["id"] for row in projected["records"]}, "RAG prepared vectors do not cover all admitted documents")
    for row in projected["records"]:
        vector = vectors[row["id"]]
        require(vector.get("oldId") == row["oldId"] and vector.get("textSha256") == row["textSha256"]
                and vector.get("originalVectorSha256") == row["originalVectorSha256"], "RAG old-ID/text/vector provenance mismatch")
        require(len(vector["embedding"]) == embeddings["dimensions"] and sha(vector_bytes(vector["embedding"])) == vector["targetVectorSha256"], "RAG prepared vector digest/dimension mismatch")
        row["embedding"] = vector["embedding"]
    return projected


@migration_target_operation
def rag_candidate_merge(bundle, policy, embeddings, candidate, receipt_path, identity):
    root = safe_path(candidate)
    admission = admit_candidate(root, 'rag-offline-candidate', bundle, identity)
    rows = prepared_bge_rag_records(bundle, policy, embeddings)
    remote = target_connection(admission, root)
    from script.memory.qdrant_migration import COLLECTIONS, rag_manifest
    generation = 'legacy-' + sha(canonical(bundle))[:24]
    require(not safe_path(receipt_path, exists=False).exists(), 'Prior RAG target receipt requires review, not replay')
    private_json(receipt_path, {'status': 'PREPARED', 'identity': identity, 'sourceBundleSha256': sha(canonical(bundle))})
    result = remote.import_records(COLLECTIONS['rag'], rows, kind='SYSTEM_RAG', generation=generation)
    manifest = rag_manifest(policy['applicationCommit'], generation, rows, result)
    private_json(root / 'rag-preservation-manifest.json', manifest)
    receipt = {'status': 'MERGED_PENDING_INDEPENDENT_RECOVERY', 'identity': identity, 'targetBackend': 'qdrant',
        'sourceBundleSha256': sha(canonical(bundle)), 'policySha256': sha(canonical(policy)),
        'embeddingOutputSha256': sha(canonical(embeddings)), 'targetRecords': len(rows),
        'storedVectors': result['provenance'], 'productionPromotionAllowed': False}
    private_json(receipt_path, receipt, replace=True)
    return {'status': receipt['status'], 'targetRecords': len(rows), 'productionPromotionAllowed': False}


@migration_target_operation
def rag_verify_http(bundle, policy, embeddings, config, receipt_path, identity):
    from script.memory.qdrant_migration import Remote, COLLECTIONS, normalized_agreement
    require(set(config) == {'backend', 'baseUrl', 'apiKeyFile', 'storedCatalogueFile'} and config['backend'] == 'qdrant',
            'RAG verification requires explicit Qdrant transport and its first stored catalogue')
    remote = Remote(config['baseUrl'], config['apiKeyFile'])
    rows = prepared_bge_rag_records(bundle, policy, embeddings)
    actual = remote.records(COLLECTIONS['rag'])
    baseline = read_json(config['storedCatalogueFile'])
    require(remote.catalog(COLLECTIONS['rag']) == baseline, 'Stored Qdrant fingerprints changed since first normalization proof')
    for row in rows:
        stored = actual.get(row['id'])
        require(stored is not None and stored['payload'].get('text') == row['document']
                and all(stored['payload'].get(key) == value for key, value in row['metadata'].items()),
                'Qdrant RAG readback lost source text or metadata')
        normalized_agreement(row['embedding'], stored['vector'])
    receipt = {'status': 'QDRANT_HTTP_READBACK_VERIFIED', 'identity': identity, 'verifiedDocuments': len(rows),
        'firstStoredFloat32FingerprintsVerified': True, 'sourceBundleSha256': sha(canonical(bundle)),
        'paidModelCalls': 0, 'llmCalls': 0, 'writesPerformed': False, 'productionPromotionAllowed': False}
    private_json(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    preserve = sub.add_parser("snapshot", help="Byte-only preservation; no database process is started")
    preserve.add_argument("--inventory", required=True)
    preserve.add_argument("--roots", required=True, help="Private JSON mapping inventory source names to original directories")
    preserve.add_argument("--output", required=True)
    check = sub.add_parser("snapshot-verify")
    check.add_argument("--snapshot", required=True)
    check.add_argument("--restore")
    check.add_argument("--expected-instance-id")
    check.add_argument("--expected-machine-id")
    export = sub.add_parser("export")
    export.add_argument("--chroma-db", required=True)
    export.add_argument("--history-db", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--expected-instance-id", required=True)
    export.add_argument("--expected-machine-id", required=True)
    rag_source = sub.add_parser("rag-export")
    rag_source.add_argument("--restored-snapshot", required=True)
    rag_source.add_argument("--expected-count", type=int, required=True)
    rag_source.add_argument("--output", required=True)
    rag_source.add_argument("--expected-instance-id", required=True)
    rag_source.add_argument("--expected-machine-id", required=True)
    for name in ("rag-plan", "rag-reembed", "rag-merge", "rag-verify-http"):
        p = sub.add_parser(name)
        p.add_argument("--bundle", required=True)
        p.add_argument("--policy", required=True)
        if name != "rag-plan":
            p.add_argument("--expected-instance-id", required=True)
            p.add_argument("--expected-machine-id", required=True)
        if name == "rag-reembed":
            p.add_argument("--provider-config", required=True)
            p.add_argument("--output", required=True)
        if name in ("rag-merge", "rag-verify-http"):
            p.add_argument("--embeddings", required=True)
            p.add_argument("--receipt", required=True)
        if name == "rag-merge":
            p.add_argument("--candidate", required=True)
        if name == "rag-verify-http":
            p.add_argument("--qdrant-config", required=True)
    for name in ("plan", "reembed", "merge", "verify-bridge"):
        p = sub.add_parser(name)
        p.add_argument("--bundle", required=True)
        p.add_argument("--mapping", required=True)
        if name != "plan":
            p.add_argument("--account-proof", required=True)
            p.add_argument("--expected-instance-id", required=True)
            p.add_argument("--expected-machine-id", required=True)
        if name == "reembed":
            p.add_argument("--provider-config", required=True)
            p.add_argument("--output", required=True)
        if name == "merge":
            p.add_argument("--embeddings", required=True)
            p.add_argument("--candidate", required=True)
            p.add_argument("--receipt", required=True)
        if name == "verify-bridge":
            p.add_argument("--bridge-config", required=True)
            p.add_argument("--receipt", required=True)
    args = parser.parse_args()
    if args.action == "snapshot":
        report = preserve_sources(read_json(args.inventory), read_json(args.roots), args.output)
    elif args.action == "snapshot-verify":
        if args.restore:
            require(args.expected_instance_id and args.expected_machine_id, "Restoring original stores requires ECS identity arguments")
            ecs_identity(args.expected_instance_id, args.expected_machine_id)
        report = verify_preservation(args.snapshot, args.restore)
    elif args.action == "export":
        ecs_identity(args.expected_instance_id, args.expected_machine_id)
        result = export_legacy(args.chroma_db, args.history_db)
        private_json(args.output, result)
        report = {"records": len(result["records"]), "historyRows": len(result["history"]), "messageRows": len(result["messages"]), "sha256": sha(canonical(result))}
    elif args.action == "rag-export":
        ecs_identity(args.expected_instance_id, args.expected_machine_id)
        result = rag_export(args.restored_snapshot, args.expected_count)
        private_json(args.output, result)
        report = {"records": len(result["records"]), "dimension": result["dimension"], "sha256": sha(canonical(result))}
    elif args.action.startswith("rag-"):
        bundle, policy = read_json(args.bundle), read_json(args.policy)
        projected = project_rag(bundle, policy)
        if args.action == "rag-plan":
            report = {"activeRecords": len(projected["records"]), "archivedRecords": len(projected["archivedIds"])}
        else:
            identity = ecs_identity(args.expected_instance_id, args.expected_machine_id)
            if args.action == "rag-reembed":
                report = rag_bge_reembed(bundle, policy, read_json(args.provider_config), args.output)
            elif args.action == "rag-merge":
                report = rag_candidate_merge(bundle, policy, read_json(args.embeddings), args.candidate, args.receipt, identity)
            else:
                report = rag_verify_http(bundle, policy, read_json(args.embeddings), read_json(args.qdrant_config), args.receipt, identity)
    else:
        bundle, mapping = read_json(args.bundle), read_json(args.mapping)
        projected = project(bundle, mapping)
        if args.action == "plan":
            report = {"activeRecords": len(projected["records"]), "archivedRecords": len(projected["archivedMemoryIds"]), "activeHistoryRows": len(projected["history"]), "activeMessageRows": len(projected["messages"])}
        else:
            identity = ecs_identity(args.expected_instance_id, args.expected_machine_id)
            verify_accounts(mapping, args.account_proof, identity)
            if args.action == "reembed":
                report = reembed(bundle, mapping, read_json(args.provider_config), args.output)
            elif args.action == "verify-bridge":
                report = verify_bridge(bundle, mapping, read_json(args.bridge_config), args.receipt, identity)
            else:
                report = merge_candidate(bundle, mapping, read_json(args.embeddings), args.candidate, args.receipt, identity)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        # Provider/SQLite exception details can include memory text or a credential-bearing request.
        print("Migration stopped: " + type(exc).__name__ + "; private outputs retained for inspection", file=sys.stderr)
        raise SystemExit(3)
