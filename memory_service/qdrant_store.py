"""Dense-only remote Qdrant admission and Mem0's stable logical-ID compatibility.

Uses the pinned native Mem0 Qdrant adapter; never loads local Qdrant or an old
Chroma collection as a runtime fallback. SQLite history remains single-writer.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import uuid

try:
    from .embedding_config import FREE_PROFILE, CUSTOM_PROFILE, MODEL, DIMENSIONS, profile
except ImportError:
    from embedding_config import FREE_PROFILE, CUSTOM_PROFILE, MODEL, DIMENSIONS, profile

GENERATION = "qdrant-bge-m3-v1"
PREPROCESSING = "utf8-newline-space-v1"
ID_PROTOCOL = "doorhandle-vector-sha256-v8-v1"
LOGICAL_ID = "doorhandle_logical_id"


def point_id(collection, logical):
    if not isinstance(logical, str) or not logical.strip() or len(logical) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in logical):
        raise ValueError("Invalid vector logical identity")
    raw = bytearray(hashlib.sha256((ID_PROTOCOL + "\0" + collection + "\0" + logical).encode()).digest()[:16])
    raw[6], raw[8] = raw[6] & 15 | 128, raw[8] & 63 | 128
    return str(uuid.UUID(bytes=bytes(raw)))


def vector_identity(settings=None):
    settings = os.environ if settings is None else settings
    selected = profile(settings)
    dimensions = DIMENSIONS if selected == FREE_PROFILE else int(settings.get("EMBEDDING_DIMENSIONS", "1024"))
    if not 32 <= dimensions <= 8192:
        raise ValueError("Invalid explicit embedding dimensions")
    generation = GENERATION if selected == FREE_PROFILE else "qdrant-explicit-test-v1"
    if settings.get("MEM0_STORAGE_GENERATION", generation) != generation:
        raise ValueError("Memory storage generation differs from its explicit embedding profile")
    return {"doorhandle_profile": selected,
            "doorhandle_model": MODEL if selected == FREE_PROFILE else settings.get("EMBEDDING_MODEL", MODEL),
            "doorhandle_dimensions": dimensions, "doorhandle_preprocessing": PREPROCESSING,
            "doorhandle_storage_generation": generation,
            "doorhandle_metric": "Cosine", "doorhandle_id_protocol": ID_PROTOCOL}


def qdrant_config(collection, settings=None):
    settings = os.environ if settings is None else settings
    if settings.get("MEM0_VECTOR_BACKEND", "qdrant") != "qdrant":
        raise ValueError("Runtime vector backend must be Qdrant; legacy Chroma is an import source only")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", collection):
        raise ValueError("Invalid memory vector collection")
    host, port = settings.get("QDRANT_HOST", "qdrant"), settings.get("QDRANT_PORT", "6333")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,253}", host) or not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Invalid remote Qdrant transport")
    result = {"collection_name": collection, "host": host, "port": int(port),
              "https": settings.get("QDRANT_TLS", "false") == "true", "on_disk": True,
              "embedding_model_dims": vector_identity(settings)["doorhandle_dimensions"]}
    filename = settings.get("QDRANT_API_KEY_FILE", "")
    if filename:
        path = Path(filename)
        if not path.is_absolute() or path.resolve(strict=True) != path or path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            raise ValueError("Invalid private Qdrant credential file")
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise ValueError("Qdrant credential requires private access")
        key = path.read_text().strip()
        if not key or any(c.isspace() for c in key):
            raise ValueError("Invalid Qdrant credential")
        result["api_key"] = key
    return result


def admit_collection(config, settings=None, *, client=None):
    """Create only a new named dense collection; reject every unmarked/different existing space."""
    from qdrant_client import QdrantClient, models
    owned = client is None
    if owned:
        client = QdrantClient(host=config["host"], port=config["port"], https=config["https"],
                              api_key=config.get("api_key"), timeout=10)
    name, identity = config["collection_name"], vector_identity(settings)
    try:
        if not client.collection_exists(name):
            client.create_collection(name, vectors_config=models.VectorParams(
                size=identity["doorhandle_dimensions"], distance=models.Distance.COSINE, on_disk=True), metadata=identity)
            for field in ("user_id", "agent_id", "run_id", LOGICAL_ID):
                client.create_payload_index(name, field, field_schema=models.PayloadSchemaType.KEYWORD, wait=True)
        info = client.get_collection(name)
        params = info.config.params.vectors
        metadata = info.config.metadata or {}
        if isinstance(params, dict) or params.size != identity["doorhandle_dimensions"] or params.distance != models.Distance.COSINE \
                or any(metadata.get(key) != value for key, value in identity.items()) or info.config.params.sparse_vectors:
            raise ValueError("Qdrant embedding identity differs; use an explicit new target collection")
        return identity
    finally:
        if owned:
            client.close()


def persist_storage_floor(directory, collection, identity):
    """Rollback floor is independent from the history/protocol floor and never authorizes a cutover."""
    path = Path(directory) / "vector-space.json"
    value = {"schemaVersion": 1, "backend": "qdrant", "collection": collection, "identity": identity,
             "historyMode": "single-writer-sqlite"}
    if path.exists():
        if path.is_symlink() or json.loads(path.read_text()) != value:
            raise ValueError("Stored vector generation differs; explicit migration required")
        return
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":")); stream.flush(); os.fsync(stream.fileno())


class LogicalQdrantStore:
    """Native Mem0 methods plus public-ID mapping and bounded native read operations."""
    def __init__(self, native):
        self.delegate, self.client, self.collection_name = native, native.client, native.collection_name
        if getattr(native, "is_local", True) or getattr(native, "_has_bm25_slot", False):
            raise ValueError("Only admitted dense remote Qdrant is supported")

    def __getattr__(self, name):
        if name in ("collection", "reset", "delete_col"):
            raise AttributeError("Runtime collection reset and legacy collection access are not exposed")
        return getattr(self.delegate, name)

    def _physical(self, logical):
        if not isinstance(logical, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", logical):
            raise ValueError("Invalid public memory identity")
        return point_id(self.collection_name, logical)

    def _payload(self, logical, payload):
        payload = dict(payload or {})
        if LOGICAL_ID in payload and payload[LOGICAL_ID] != logical:
            raise ValueError("Logical memory ID cannot be rebound")
        payload[LOGICAL_ID] = logical
        return payload

    def _logical(self, row):
        if row is None:
            return None
        logical = (row.payload or {}).get(LOGICAL_ID)
        if not isinstance(logical, str) or self._physical(logical) != str(row.id):
            raise ValueError("Memory physical/logical identity mismatch")
        return row.model_copy(update={"id": logical})

    def insert(self, vectors, payloads=None, ids=None):
        if ids is None or len(vectors) != len(ids) or payloads is None or len(payloads) != len(ids):
            raise ValueError("Complete memory point identities are required")
        return self.delegate.insert(vectors=vectors, payloads=[self._payload(i, p) for i, p in zip(ids, payloads)],
                                    ids=[self._physical(i) for i in ids])

    def update(self, vector_id, vector=None, payload=None):
        if self.get(vector_id) is None:
            raise ValueError("Memory update target does not exist")
        return self.delegate.update(self._physical(vector_id), vector=vector,
                                    payload=None if payload is None else self._payload(vector_id, payload))

    def get(self, vector_id):
        return self._logical(self.delegate.get(self._physical(vector_id)))

    def delete(self, vector_id):
        return self.delegate.delete(self._physical(vector_id))

    def search(self, *args, **kwargs):
        return [self._logical(row) for row in self.delegate.search(*args, **kwargs)]

    def search_batch(self, *args, **kwargs):
        return [[self._logical(row) for row in rows] for rows in self.delegate.search_batch(*args, **kwargs)]

    def keyword_search(self, *args, **kwargs):
        # Dense-only by design: no hidden FastEmbed/model download or fake sparse PASS.
        return None

    def list(self, filters=None, top_k=100):
        rows, offset = self.delegate.list(filters=filters, top_k=top_k)
        return [self._logical(row) for row in rows], offset

    def owned_page(self, user, app, limit, offset):
        if not 1 <= limit <= 101 or not 0 <= offset <= 10000:
            raise ValueError("Invalid memory page bound")
        query_filter = self.delegate._create_filter({"user_id": user, "agent_id": app})
        cursor, skipped, result = None, 0, []
        while len(result) < limit:
            rows, cursor = self.client.scroll(self.collection_name, scroll_filter=query_filter,
                offset=cursor, limit=min(256, offset - skipped + limit - len(result)), with_payload=True, with_vectors=False)
            for row in rows:
                if skipped < offset:
                    skipped += 1
                else:
                    result.append(self._logical(row))
            if cursor is None:
                break
        return result

    def get_with_vector(self, logical):
        rows = self.client.retrieve(self.collection_name, ids=[self._physical(logical)], with_payload=True, with_vectors=True)
        return self._logical(rows[0]) if rows else None

    def search_with_vectors(self, vector, user, app, limit):
        found = self.client.query_points(self.collection_name, query=vector,
            query_filter=self.delegate._create_filter({"user_id": user, "agent_id": app}), limit=limit,
            with_payload=True, with_vectors=True)
        return [self._logical(row) for row in found.points]


def dense_vector(row):
    vector = row.vector
    if isinstance(vector, dict):
        vector = vector.get("")
    if not isinstance(vector, list) or not vector or any(type(v) not in (float, int) or not math.isfinite(v) for v in vector):
        raise ValueError("Dense memory vector is unavailable")
    return vector


def vector_fingerprint(vector):
    """Explicit integrity evidence for raw-provider and first-stored vectors, never an ordinary file read."""
    return hashlib.sha256(struct.pack("<" + "f" * len(vector), *vector)).hexdigest()
