"""Real OpenAI/Mem0 serialization against an in-process transport, on ECS only."""
import json
from types import SimpleNamespace

import httpx
from openai import OpenAI, RateLimitError
import pytest

from memory_service import embedding_config as embedding
from memory_service import main


def settings(**changes):
    return {"EMBEDDING_API_KEY": "fixture-not-real", **changes}


def native_client(handler):
    from mem0.utils.factory import EmbedderFactory
    native = EmbedderFactory.create("openai", embedding.embedder_config(settings()), None)
    native.client.close()
    native.client = OpenAI(api_key="fixture-not-real", base_url=embedding.BASE_URL, max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return native


def response(request, *, damage=None):
    body = json.loads(request.content)
    vectors = [{"object": "embedding", "index": i, "embedding": [1.0] + [0.0] * 1023}
               for i, _ in enumerate(body["input"])]
    if damage == "dimension": vectors[0]["embedding"].pop()
    if damage == "duplicate": vectors.append(vectors[0])
    if damage == "missing": vectors = []
    if damage == "index": vectors[0]["index"] = 10
    if damage == "zero": vectors[0]["embedding"] = [0.0] * 1024
    return httpx.Response(200, json={"object": "list", "model": "different-model" if damage == "model" else embedding.MODEL,
        "data": list(reversed(vectors)), "usage": {"prompt_tokens": 1, "total_tokens": 1}})


def test_free_default_uses_exact_provider_and_model_with_an_independent_vector_space(monkeypatch):
    for key in ("EMBEDDING_PROFILE", "EMBEDDING_MODEL", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY_FILE",
                "DOORHANDLE_RUNTIME_ACCEPTANCE", "DOORHANDLE_RUNTIME_PROJECT", "MEM0_RUNTIME_TEST_COLLECTION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-llm")
    monkeypatch.setenv("EMBEDDING_API_KEY", "fixture-embedding")
    config = main.get_memory_config()
    assert config["embedder"]["config"] == {"model": embedding.MODEL, "openai_base_url": embedding.BASE_URL,
        "api_key": "fixture-embedding", "embedding_dims": 1024}
    assert config["vector_store"]["provider"] == "qdrant"
    assert config["vector_store"]["config"]["embedding_model_dims"] == 1024
    assert config["vector_store"]["config"]["collection_name"] == embedding.COLLECTION
    assert config["llm"]["config"]["api_key"] == "fixture-llm"


@pytest.mark.parametrize("changes", [
    {"EMBEDDING_MODEL": "Pro/BAAI/bge-m3"}, {"EMBEDDING_MODEL": "text-embedding-v4"},
    {"EMBEDDING_BASE_URL": "https://api.siliconflow.cn.evil.invalid/v1"},
    {"EMBEDDING_BASE_URL": "http://api.siliconflow.cn/v1"},
    {"EMBEDDING_BASE_URL": "https://api.siliconflow.cn/v1?key=x"}, {"EMBEDDING_PROFILE": "unknown"},
])
def test_paid_variants_other_providers_and_unknown_profiles_fail_before_client_creation(changes):
    with pytest.raises(ValueError): embedding.embedder_config(settings(**changes))


def test_custom_fixture_transport_requires_an_explicit_profile():
    values = settings(EMBEDDING_PROFILE=embedding.CUSTOM_PROFILE, EMBEDDING_MODEL="fixture-model",
                      EMBEDDING_BASE_URL="http://owned-fixture:8099/v1")
    assert embedding.embedder_config(values) == {"model": "fixture-model", "api_key": "fixture-not-real",
                                                "openai_base_url": "http://owned-fixture:8099/v1", "embedding_dims": 1024}
    assert main.memory_collection_name(values) == "doorhandle_memories_explicit_test"


def test_native_sdk_sends_fixed_model_float_input_and_no_unsupported_dimension_parameter():
    calls = []
    def handler(request):
        calls.append((str(request.url), json.loads(request.content)))
        return response(request)
    native = native_client(handler)
    try:
        subject = embedding.FreeBgeEmbedder(native, settings=settings())
        assert len(subject.embed("门把手\n涂层检验", "search")) == 1024
        assert len(subject.embed_batch(["第一条", "第二条"], "add")) == 2
        assert calls[0] == (embedding.BASE_URL + "/embeddings", {
            "model": "BAAI/bge-m3", "input": ["门把手 涂层检验"], "encoding_format": "float"})
        assert all("dimensions" not in body for _, body in calls)
        assert native.config.embedding_dims == 1024
    finally: native.client.close()


@pytest.mark.parametrize("damage", ["dimension", "duplicate", "missing", "index", "zero", "model"])
def test_malformed_or_foreign_provider_vectors_never_reach_storage(damage):
    native = native_client(lambda request: response(request, damage=damage))
    try:
        with pytest.raises(ValueError): embedding.FreeBgeEmbedder(native, settings=settings()).embed("检验")
    finally: native.client.close()


@pytest.mark.parametrize("texts", [[""], ["  "], ["好" * 2667], ["valid", None], [], ["x"] * 65])
def test_empty_oversized_or_invalid_batch_fails_without_any_provider_request(texts):
    native = native_client(lambda _: pytest.fail("invalid input must not reach a provider"))
    try:
        with pytest.raises(ValueError): embedding.FreeBgeEmbedder(native, settings=settings()).embed_batch(texts)
    finally: native.client.close()


def test_rate_limit_rejects_without_sleeping_and_recovers_after_the_window():
    calls, clock = [], [0.0]
    def handler(request): calls.append(request); return response(request)
    native = native_client(handler)
    try:
        subject = embedding.FreeBgeEmbedder(native, settings=settings(EMBEDDING_REQUESTS_PER_MINUTE="1"), clock=lambda: clock[0])
        subject.embed("检验")
        with pytest.raises(RuntimeError, match="rate limit"): subject.embed("检验")
        assert len(calls) == 1
        clock[0] = 60
        subject.embed("检验")
        assert len(calls) == 2
    finally: native.client.close()


def test_provider_error_is_not_retried_and_cannot_select_a_paid_model():
    calls = []
    def handler(request): calls.append(json.loads(request.content)); return httpx.Response(429, json={"error": {"message": "fixture", "type": "limit"}})
    native = native_client(handler)
    try:
        subject = embedding.FreeBgeEmbedder(native, settings=settings())
        with pytest.raises(RateLimitError): subject.embed("检验")
        assert len(calls) == 1 and calls[0]["model"] == embedding.MODEL
    finally: native.client.close()


@pytest.mark.parametrize("count,metadata", [(1, {}), (0, {"doorhandle_embedding_model": "old-model"}),
    (1, {**embedding.SPACE_METADATA, "doorhandle_embedding_provider": "other-provider"})])
def test_same_dimension_does_not_admit_unproven_or_foreign_collections(count, metadata):
    collection = SimpleNamespace(metadata=metadata, count=lambda: count,
                                 modify=lambda **_: pytest.fail("foreign collection cannot be modified"))
    with pytest.raises(ValueError): embedding.bind_collection(collection)


def test_real_chroma_marker_survives_reopening_and_preserves_other_metadata(tmp_path):
    import chromadb
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collection = client.create_collection(embedding.COLLECTION, metadata={"purpose": "fixture"}, embedding_function=None)
    embedding.bind_collection(collection)
    collection.add(ids=["one"], embeddings=[[1.0] + [0.0] * 1023], metadatas=[{"user_id": "fixture-owner"}])
    reopened = client.get_collection(embedding.COLLECTION, embedding_function=None)
    embedding.bind_collection(reopened)
    assert reopened.count() == 1 and reopened.metadata == {"purpose": "fixture", **embedding.SPACE_METADATA}
    assert reopened.get(ids=["one"])["metadatas"] == [{"user_id": "fixture-owner"}]


def test_embedding_secret_file_is_private_and_separate_from_llm_credentials(tmp_path):
    key = tmp_path / "embedding.key"
    key.write_text("fixture-embedding-secret\n")
    key.chmod(0o600)
    config = embedding.embedder_config({"EMBEDDING_API_KEY_FILE": str(key), "DASHSCOPE_API_KEY": "fixture-llm"})
    assert config["api_key"] == "fixture-embedding-secret"
    with pytest.raises(ValueError, match="exactly one"):
        embedding.embedder_config({"EMBEDDING_API_KEY_FILE": str(key), "EMBEDDING_API_KEY": "another"})
    key.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        embedding.embedder_config({"EMBEDDING_API_KEY_FILE": str(key)})
