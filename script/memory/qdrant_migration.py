"""Bounded, remote-only Qdrant import and independent recovery evidence.

The original Chroma stores remain export sources. This module never opens a local
Qdrant database, changes an alias, or chooses a provider/model for an application.
Its first readback establishes stored FLOAT32 fingerprints because Cosine storage
normalizes provider vectors; later readbacks require those fingerprints exactly.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import urllib.error
import urllib.parse
import urllib.request

from memory_service.qdrant_store import ID_PROTOCOL, LOGICAL_ID, point_id, vector_identity

COLLECTIONS = {
    "rag": "doorhandle_rag_bge_m3_v1",
    "knowledge": "doorhandle_knowledge_bge_m3_v1",
    "experience": "doorhandle_experience_bge_m3_v1",
    "mem0": "doorhandle_memories_bge_m3_v1",
}
MAX_RECORDS = 2000
MAX_RESPONSE = 64 * 1024 ** 2


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def fingerprint(vector):
    values = [float(value) for value in vector]
    require(len(values) == 1024 and all(math.isfinite(value) for value in values), "Invalid BGE-M3 dense vector")
    return hashlib.sha256(struct.pack("<1024f", *values)).hexdigest()


def normalized_agreement(raw, stored):
    """Qdrant may round its norm/normalization in float32, not Python float64."""
    fingerprint(raw); fingerprint(stored)
    norm = math.sqrt(sum(float(value) ** 2 for value in raw))
    require(norm > 0, "Zero provider vector cannot establish a Cosine target")
    expected = [float(value) / norm for value in raw]
    stored_norm = math.sqrt(sum(float(value) ** 2 for value in stored))
    require(abs(stored_norm - 1) <= 2e-5
            and max(abs(left - float(right)) for left, right in zip(expected, stored)) <= 3e-6
            and sum(left * float(right) for left, right in zip(expected, stored)) >= 0.99998,
            "Qdrant stored vector does not agree with normalized provider output")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, *arguments):
        raise ValueError("Qdrant migration endpoint redirected")


class Remote:
    """Small REST transport for migration tools; runtime uses the mature SDK."""
    def __init__(self, base, key_file):
        parsed = urllib.parse.urlsplit(base)
        require(parsed.scheme in ("http", "https") and parsed.hostname
                and not parsed.username and not parsed.password and parsed.path in ("", "/")
                and not parsed.query and not parsed.fragment, "Invalid remote Qdrant endpoint")
        path = Path(key_file)
        require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file()
                and path.stat().st_size <= 4096 and (os.name == "nt" or path.stat().st_mode & 0o077 == 0),
                "Qdrant migration requires a private credential file")
        self.key = path.read_text().strip()
        require(self.key and not any(value.isspace() for value in self.key), "Invalid Qdrant migration credential")
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method, route, body=None):
        require(route.startswith("/") and ".." not in route, "Invalid Qdrant operation")
        request = urllib.request.Request(self.base + route, method=method,
            data=None if body is None else canonical(body),
            headers={"api-key": self.key, "Content-Type": "application/json"})
        with self.opener.open(request, timeout=120) as response:
            raw = response.read(MAX_RESPONSE + 1)
        require(len(raw) <= MAX_RESPONSE, "Qdrant migration response exceeded its bound")
        value = json.loads(raw)
        require(value.get("status") == "ok", "Qdrant operation did not succeed")
        return value["result"]

    def admit(self, collection, *, create=False):
        require(collection in COLLECTIONS.values(), "Unreviewed migration collection")
        names = {row["name"] for row in self.request("GET", "/collections")["collections"]}
        identity = vector_identity({"EMBEDDING_PROFILE": "siliconflow-bge-m3-v1"})
        route = "/collections/" + collection
        if collection not in names:
            require(create, "Required Qdrant collection is missing")
            self.request("PUT", route, {"vectors": {"size": 1024, "distance": "Cosine", "on_disk": True},
                "metadata": identity})
            for field in (LOGICAL_ID, "logical_id", "kind", "user_id", "agent_id", "generation"):
                self.request("PUT", route + "/index?wait=true", {"field_name": field, "field_schema": "keyword"})
        info = self.request("GET", route)
        params = info["config"]["params"]
        require(params["vectors"].get("size") == 1024 and params["vectors"].get("distance") == "Cosine"
                and params["vectors"].get("on_disk") is True and not params.get("sparse_vectors")
                and all(info["config"].get("metadata", {}).get(key) == value for key, value in identity.items()),
                "Existing Qdrant target has an incompatible model, generation or vector layout")
        return identity

    def records(self, collection):
        self.admit(collection)
        result, offset = {}, None
        for _ in range(MAX_RECORDS // 128 + 2):
            body = {"limit": 128, "with_payload": True, "with_vector": True}
            if offset is not None:
                body["offset"] = offset
            page = self.request("POST", "/collections/" + collection + "/points/scroll", body)
            for row in page["points"]:
                payload = row["payload"]
                logical = payload.get(LOGICAL_ID) if collection == COLLECTIONS["mem0"] else payload.get("logical_id")
                require(isinstance(logical, str) and row["id"] == point_id(collection, logical)
                        and logical not in result, "Qdrant physical/logical identity is inconsistent")
                fingerprint(row["vector"])
                result[logical] = {"physicalId": row["id"], "payload": payload,
                    "storedVectorSha256": fingerprint(row["vector"]), "vector": row["vector"]}
                require(len(result) <= MAX_RECORDS, "Qdrant target exceeds its reviewed record bound")
            offset = page.get("next_page_offset")
            if offset is None:
                return result
        raise ValueError("Qdrant target pagination did not terminate")

    def import_records(self, collection, records, *, kind=None, generation=None):
        self.admit(collection, create=True)
        before = self.records(collection)
        require(isinstance(records, list) and len(records) <= MAX_RECORDS
                and len({row["id"] for row in records}) == len(records), "Invalid duplicate migration records")
        prepared, provenance = [], {}
        for row in records:
            logical, vector = row["id"], row["embedding"]
            raw_sha = fingerprint(vector)
            metadata = dict(row["metadata"])
            if collection == COLLECTIONS["mem0"]:
                require(re.fullmatch(r"doorhandlecatch:user:[1-9][0-9]*", metadata.get("user_id", ""))
                        and metadata.get("agent_id") == "doorhandlecatch", "Unmapped personal memory scope")
                payload = {**metadata, LOGICAL_ID: logical}
            else:
                require(kind in ("SYSTEM_RAG", "KNOWLEDGE", "EXPERIENCE") and isinstance(generation, str) and generation,
                        "Semantic records need their kind and content generation")
                require(all(isinstance(key, str) and isinstance(value, str) for key, value in metadata.items()),
                        "Java semantic payload metadata must remain strings")
                payload = {**metadata, "logical_id": logical, "text": row["document"],
                    "kind": kind, "generation": generation}
                if kind == "SYSTEM_RAG":
                    payload.update(visibility="SYSTEM", lifecycle="ACTIVE")
            if logical in before:
                require(before[logical]["payload"] == payload, "Target logical ID conflicts; no overwrite is allowed")
                normalized_agreement(vector, before[logical]["vector"])
            else:
                prepared.append({"id": point_id(collection, logical), "vector": vector, "payload": payload})
            provenance[logical] = {"rawVectorSha256": raw_sha}
        for start in range(0, len(prepared), 64):
            self.request("PUT", "/collections/" + collection + "/points?wait=true", {"points": prepared[start:start + 64]})
        after = self.records(collection)
        require(set(after) == set(before) | {row["id"] for row in records}, "Qdrant target gained unexpected records")
        for logical, original in before.items():
            require(after[logical] == original, "Previously stored Qdrant vector changed")
        for row in records:
            logical = row["id"]
            normalized_agreement(row["embedding"], after[logical]["vector"])
            provenance[logical].update(storedVectorSha256=after[logical]["storedVectorSha256"], cosineNormalizationVerified=True)
            filters = [{"key": LOGICAL_ID if collection == COLLECTIONS["mem0"] else "logical_id", "match": {"value": logical}}]
            if collection == COLLECTIONS["mem0"]:
                filters += [{"key": key, "match": {"value": row["metadata"][key]}} for key in ("user_id", "agent_id")]
            else:
                filters += [{"key": "kind", "match": {"value": kind}}, {"key": "generation", "match": {"value": generation}}]
            hit = self.request("POST", "/collections/" + collection + "/points/query", {
                "query": row["embedding"], "filter": {"must": filters}, "limit": 1, "with_payload": True})["points"]
            require(len(hit) == 1 and hit[0]["id"] == point_id(collection, logical)
                    and hit[0]["score"] >= 0.99998, "Qdrant imported vector cannot retrieve its scoped source")
        return {"identity": self.admit(collection), "records": self.catalog(collection), "provenance": provenance,
                "inserted": len(prepared), "selfQueries": len(records)}

    def catalog(self, collection):
        return {key: {field: value for field, value in row.items() if field != "vector"}
                for key, row in self.records(collection).items()}

    def complete_catalog(self):
        names = {row["name"] for row in self.request("GET", "/collections")["collections"]}
        require(names == set(COLLECTIONS.values()), "Migration target must contain exactly its four owned collections")
        return {name: {"identity": self.admit(name), "records": self.catalog(name)} for name in sorted(names)}

    def snapshot_recovery(self, independent, snapshot_directory):
        """Restore actual Qdrant snapshots on a different empty remote server."""
        require(independent.base != self.base, "A snapshot must be restored on an independent Qdrant server")
        require(not independent.request("GET", "/collections")["collections"], "Independent recovery target is not empty")
        before = self.complete_catalog()
        snapshots = {}
        for collection in sorted(COLLECTIONS.values()):
            descriptor = self.request("POST", "/collections/" + collection + "/snapshots", {})
            name = descriptor["name"]
            require(re.fullmatch(r"[A-Za-z0-9_.-]+\.snapshot", name), "Unexpected Qdrant snapshot filename")
            # The new server has a readonly mount of the source snapshot root.
            location = "file://" + str(Path(snapshot_directory) / collection / name)
            recovery = {"location": location, "priority": "snapshot"}
            if descriptor.get('checksum') is not None:
                require(re.fullmatch(r'[a-f0-9]{64}', descriptor['checksum']), 'Invalid Qdrant snapshot checksum')
                recovery['checksum'] = descriptor['checksum']
            independent.request("PUT", "/collections/" + collection + "/snapshots/recover?wait=true", recovery)
            snapshots[collection] = {"name": name, "checksum": descriptor.get("checksum"), "size": descriptor["size"]}
        require(self.complete_catalog() == before and independent.complete_catalog() == before,
                "Independent Qdrant snapshot recovery changed stored vectors, payloads or IDs")
        return {"status": "RESTORED_VERIFIED", "backend": "qdrant", "snapshots": snapshots,
                "storedCatalogSha256": hashlib.sha256(canonical(before)).hexdigest(),
                "exactStoredFloat32Verified": True, "independentServer": True}


def admit_history_import(projected, data, migration):
    """Reject known schema/ID conflicts before the first remote vector write."""
    definitions = {'history': migration.HISTORY_COLUMNS, 'messages': migration.MESSAGE_COLUMNS}
    for table, columns in definitions.items():
        require(all(set(row) == set(columns) for row in projected[table]), 'Source native history schema differs')
    path = Path(data) / 'history.db'
    if not path.exists():
        return
    with contextlib.closing(migration.open_ro(path)) as db:
        before = migration.history_snapshot(db)
        for table, columns in definitions.items():
            existing = {row[1] for row in db.execute('PRAGMA table_info("' + table + '")')}
            require(not existing or existing == set(columns), 'Native history schema differs')
            require(all(row['id'] not in before[table] or before[table][row['id']] == row for row in projected[table]),
                    'Native history identity conflicts')


def merge_history(projected, data, migration):
    """Native history stays SQLite and single writer; Qdrant is not its history HA."""
    data = Path(data)
    import fcntl
    fence = data / "bridge_receipts/writer.lock"
    fence.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with fence.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with contextlib.closing(sqlite3.connect(data / "history.db")) as db:
            db.row_factory = sqlite3.Row
            before = migration.history_snapshot(db)
            definitions = {
                "history": (migration.HISTORY_COLUMNS, "id TEXT PRIMARY KEY,memory_id TEXT,old_memory TEXT,new_memory TEXT,event TEXT,created_at DATETIME,updated_at DATETIME,is_deleted INTEGER,actor_id TEXT,role TEXT"),
                "messages": (migration.MESSAGE_COLUMNS, "id TEXT PRIMARY KEY,session_scope TEXT,role TEXT,content TEXT,name TEXT,created_at DATETIME"),
            }
            db.execute("BEGIN IMMEDIATE")
            for table, (columns, definition) in definitions.items():
                existing = {row[1] for row in db.execute('PRAGMA table_info("' + table + '")')}
                require(not existing or existing == set(columns), "Native history schema differs")
                db.execute('CREATE TABLE IF NOT EXISTS "' + table + '" (' + definition + ')')
                for row in projected[table]:
                    require(set(row) == set(columns), "Source native history schema differs")
                    if row["id"] in before[table]:
                        require(before[table][row["id"]] == row, "Native history identity conflicts")
                    else:
                        db.execute('INSERT INTO "' + table + '" (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                                   tuple(row[key] for key in columns))
            db.commit()
            after = migration.history_snapshot(db)
            for table in definitions:
                require(all(after[table].get(key) == row for key, row in before[table].items())
                        and all(after[table].get(row["id"]) == row for row in projected[table])
                        and set(after[table]) == set(before[table]) | {row["id"] for row in projected[table]},
                        "Native history merge lost or introduced a record")
            return {"before": before, "after": after, "historyMode": "single-writer-sqlite"}


def admit_lifecycle_import(data, logical_ids, migration, *, accepted_existing_ids=()):
    """A missing/new vector cannot silently revive a governed/deleted identity."""
    journal = Path(data) / 'bridge_receipts/write-receipts.sqlite3'
    if not journal.exists():
        require(not (journal.parent / 'writer.lock').exists(), 'Existing writer fence has no verifiable receipt journal')
        return
    with contextlib.closing(migration.open_ro(journal)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require(bool({'memory_write_receipt', 'memory_lifecycle'} & tables), 'Unknown bridge journal cannot authorize vector import')
        if 'bridge_protocol_floor' in tables:
            rows = db.execute('SELECT required_version FROM bridge_protocol_floor WHERE id=1').fetchall()
            require(len(rows) == 1 and type(rows[0][0]) is int
                    and (rows[0][0] < 2 or 'memory_lifecycle' in tables), 'Incomplete governed bridge journal')
        if 'memory_lifecycle' in tables:
            governed = {row[0] for row in db.execute('SELECT DISTINCT memory_id FROM memory_lifecycle')}
            require(not governed.intersection(set(logical_ids) - set(accepted_existing_ids)),
                    'Source memory has target lifecycle history; explicit reconciliation is required')


def rag_manifest(commit, generation, prepared, imported):
    records = []
    for row in prepared:
        meta = {**row["metadata"], "kind": "SYSTEM_RAG", "generation": generation,
                "visibility": "SYSTEM", "lifecycle": "ACTIVE"}
        records.append({"id": row["id"], "text": row["document"], "metadata": meta, **imported["provenance"][row["id"]]})
    return {"schemaVersion": 2, "kind": "QDRANT_RAG_TARGET", "status": "VERIFIED", "commit": commit,
            "identity": {"backend": "qdrant", "collection": COLLECTIONS["rag"], "model": "BAAI/bge-m3",
                "profile": "siliconflow-bge-m3-v1", "dimensions": 1024, "preprocessing": "utf8-newline-space-v1",
                "storageGeneration": "qdrant-bge-m3-v1", "generation": generation, "idProtocol": ID_PROTOCOL},
            "records": records}
