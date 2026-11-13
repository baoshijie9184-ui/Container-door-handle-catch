"""Remote ECS Qdrant fixture; never starts an embedded/local fallback or downloads a model."""
import os
import uuid
import pytest


@pytest.fixture
def ecs_memory_qdrant():
    from qdrant_client import QdrantClient
    from memory_service.qdrant_store import qdrant_config, admit_collection
    host = os.getenv("DOORHANDLE_TEST_QDRANT_HOST", "")
    if not host:
        if os.getenv("DOORHANDLE_REQUIRE_QDRANT_TESTS") == "true":
            pytest.fail("Required ECS Qdrant fixture endpoint is not configured")
        pytest.skip("ECS-only Qdrant integration endpoint is not configured")
    name = "doorhandle_test_memory_" + uuid.uuid4().hex
    settings = {"EMBEDDING_PROFILE": "explicit-openai-compatible", "EMBEDDING_MODEL": "fixture-model",
        "EMBEDDING_DIMENSIONS": "32", "MEM0_STORAGE_GENERATION": "qdrant-explicit-test-v1",
        "QDRANT_HOST": host, "QDRANT_PORT": os.getenv("DOORHANDLE_TEST_QDRANT_PORT", "6333"),
        "QDRANT_API_KEY_FILE": os.getenv("DOORHANDLE_TEST_QDRANT_KEY_FILE", ""),
        "QDRANT_TLS": os.getenv("DOORHANDLE_TEST_QDRANT_TLS", "false")}
    config = qdrant_config(name, settings)
    client = QdrantClient(host=config["host"], port=config["port"], https=config["https"], api_key=config.get("api_key"), timeout=10)
    admit_collection(config, settings, client=client)
    try:
        yield config, client
    finally:
        # Only this exact random collection is owned by the fixture; no source/production cleanup.
        if not name.startswith("doorhandle_test_memory_") or len(name) != len("doorhandle_test_memory_") + 32:
            raise ValueError("Fixture collection ownership differs")
        client.delete_collection(name)
        client.close()
