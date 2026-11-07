"""Pinned SiliconFlow BGE-M3 transport and persistent vector-space identity.

Reuse the installed OpenAI client and Mem0 adapter. BGE-M3 has fixed dimensions;
the OpenAI ``dimensions`` parameter must not be sent to this model.
"""
from collections import deque
import math
import os
from pathlib import Path
import stat
import threading
import time


FREE_PROFILE = "siliconflow-bge-m3-v1"
CUSTOM_PROFILE = "explicit-openai-compatible"
BASE_URL = "https://api.siliconflow.cn/v1"
MODEL = "BAAI/bge-m3"
DIMENSIONS = 1024
COLLECTION = "doorhandle_memories_bge_m3_v1"
SPACE_METADATA = {
    "doorhandle_embedding_profile": FREE_PROFILE,
    "doorhandle_embedding_provider": "siliconflow",
    "doorhandle_embedding_model": MODEL,
    "doorhandle_embedding_dimensions": DIMENSIONS,
}


def profile(settings=None):
    settings = os.environ if settings is None else settings
    value = settings.get("EMBEDDING_PROFILE", FREE_PROFILE)
    if value not in (FREE_PROFILE, CUSTOM_PROFILE):
        raise ValueError("Unknown explicit embedding profile")
    return value


def api_key(settings):
    """Allow a read-only ECS secret mount; never fall back to the LLM key."""
    value, filename = settings.get("EMBEDDING_API_KEY", ""), settings.get("EMBEDDING_API_KEY_FILE", "")
    if bool(value) == bool(filename):
        raise ValueError("Configure exactly one embedding credential source")
    if filename:
        path = Path(filename)
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError("Embedding secret must be a canonical absolute file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 4096 \
                    or os.name != "nt" and info.st_mode & 0o077:
                raise ValueError("Embedding secret requires private regular-file access")
            value = stream.read(4097).decode("utf-8").strip()
    if not isinstance(value, str) or not value or len(value) > 4096 or any(c.isspace() for c in value):
        raise ValueError("Invalid embedding credential")
    return value


def embedder_config(settings=None):
    settings = os.environ if settings is None else settings
    selected = profile(settings)
    base = settings.get("EMBEDDING_BASE_URL", BASE_URL).rstrip("/")
    model = settings.get("EMBEDDING_MODEL", MODEL)
    if selected == FREE_PROFILE and (base != BASE_URL or model != MODEL):
        raise ValueError("Free BGE-M3 profile requires its exact provider and model")
    result = {"model": model, "api_key": api_key(settings), "openai_base_url": base}
    if selected == FREE_PROFILE:
        result["embedding_dims"] = DIMENSIONS
    return result


def bind_collection(collection):
    """Never mix an unknown or another model's vectors, including equal dimensions."""
    before = dict(collection.metadata or {})
    present = {key: before[key] for key in SPACE_METADATA if key in before}
    if present and present != SPACE_METADATA:
        raise ValueError("Memory collection embedding identity differs; migrate to a new collection")
    if present != SPACE_METADATA:
        if collection.count() != 0:
            raise ValueError("Nonempty unmarked memory collection requires explicit vector migration")
        collection.modify(metadata={**before, **SPACE_METADATA})
    if any((collection.metadata or {}).get(key) != value for key, value in SPACE_METADATA.items()):
        raise ValueError("Memory collection embedding identity readback failed")


def integer_setting(settings, name, default, minimum, maximum):
    raw = settings.get(name, str(default))
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit():
        raise ValueError("Invalid embedding request bound")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ValueError("Invalid embedding request bound")
    return value


class FreeBgeEmbedder:
    """One request at a time, bounded input, zero SDK retries, no paid fallback."""
    def __init__(self, native, *, settings=None, clock=time.monotonic):
        settings = os.environ if settings is None else settings
        if native.config.model != MODEL or str(native.client.base_url).rstrip("/") != BASE_URL:
            raise ValueError("Embedding runtime differs from the fixed free profile")
        self.config, self.client = native.config, native.client
        self.config.embedding_dims = DIMENSIONS
        self.requests_per_minute = integer_setting(settings, "EMBEDDING_REQUESTS_PER_MINUTE", 60, 1, 120)
        self.max_input_bytes = integer_setting(settings, "EMBEDDING_MAX_INPUT_BYTES", 8000, 1, 8000)
        self.batch_size = integer_setting(settings, "EMBEDDING_BATCH_SIZE", 8, 1, 8)
        self._clock, self._calls = clock, deque()
        self._slot = threading.Lock()

    def _texts(self, texts):
        if not isinstance(texts, list) or not 1 <= len(texts) <= 64:
            raise ValueError("Embedding batch exceeds the request bound")
        result = []
        for text in texts:
            if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > self.max_input_bytes:
                raise ValueError("Embedding text is empty or exceeds its UTF-8 byte bound")
            result.append(text.replace("\n", " "))
        return result

    def _request(self, texts):
        if not self._slot.acquire(blocking=False):
            raise RuntimeError("Embedding request busy; retry a new read later")
        try:
            now = self._clock()
            while self._calls and now - self._calls[0] >= 60:
                self._calls.popleft()
            if len(self._calls) >= self.requests_per_minute:
                raise RuntimeError("Embedding request rate limit reached")
            # Failed calls also consume the local bound. No request is replayed here.
            self._calls.append(now)
            response = self.client.embeddings.create(model=MODEL, input=texts, encoding_format="float")
            if getattr(response, "model", MODEL) not in (None, MODEL, "bge-m3"):
                raise ValueError("Embedding response model differs")
            rows = sorted(response.data, key=lambda item: item.index)
            if [row.index for row in rows] != list(range(len(texts))):
                raise ValueError("Embedding response cardinality differs")
            vectors = []
            for row in rows:
                vector = row.embedding
                if len(vector) != DIMENSIONS or not all(type(v) in (float, int) and math.isfinite(v) for v in vector) \
                        or not any(vector):
                    raise ValueError("Embedding response vector is invalid")
                vectors.append(vector)
            return vectors
        finally:
            self._slot.release()

    def embed(self, text, memory_action=None):
        return self._request(self._texts([text]))[0]

    def embed_batch(self, texts, memory_action="add"):
        texts = self._texts(texts)  # Validate every input before the first provider request.
        result = []
        for offset in range(0, len(texts), self.batch_size):
            result.extend(self._request(texts[offset:offset + self.batch_size]))
        return result


def configure_runtime(memory, *, settings=None):
    if profile(settings) == FREE_PROFILE:
        memory.embedding_model = FreeBgeEmbedder(memory.embedding_model, settings=settings)
        bind_collection(memory.vector_store.collection)
