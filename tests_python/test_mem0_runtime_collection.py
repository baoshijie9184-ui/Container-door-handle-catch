"""Configuration-only ECS regressions: no SDK creation, database or provider calls."""
import copy

import pytest

from memory_service import main


TOKEN = "0123456789ab"
PROJECT = "doorhandle-rehearsal-" + TOKEN
COLLECTION = "doorhandle_runtime_test_" + TOKEN
KEYS = ("DOORHANDLE_RUNTIME_ACCEPTANCE", "DOORHANDLE_RUNTIME_PROJECT", "MEM0_RUNTIME_TEST_COLLECTION")


def controlled():
    return dict(zip(KEYS, ("true", PROJECT, COLLECTION)))


def test_production_default_remains_the_original_collection():
    assert main.memory_collection_name({}) == "doorhandle_memories"
    assert main.memory_collection_name({"UNRELATED_SETTING": "true"}) == "doorhandle_memories"


def test_only_the_matching_controlled_project_can_select_its_independent_collection():
    settings = controlled()
    before = settings.copy()
    assert main.memory_collection_name(settings) == COLLECTION
    assert settings == before


@pytest.mark.parametrize("key,value", [
    (KEYS[0], None), (KEYS[0], "false"), (KEYS[0], "TRUE"), (KEYS[0], ""),
    (KEYS[1], None), (KEYS[1], "doorhandlecatch-monolith"),
    (KEYS[1], "doorhandle-rehearsal-0123456789AB"), (KEYS[1], "doorhandle-rehearsal-0123456789a"),
    (KEYS[1], "doorhandle-rehearsal-0123456789ab00"), (KEYS[1], "doorhandle-rehearsal-fedcba987654"),
    (KEYS[2], None), (KEYS[2], "doorhandle_memories"), (KEYS[2], "arbitrary_collection"),
    (KEYS[2], "doorhandle_runtime_test_fedcba987654"),
    (KEYS[2], "doorhandle_runtime_test_0123456789AB"),
    (KEYS[2], "doorhandle_runtime_test_0123456789ab/../doorhandle_memories"),
])
def test_partial_mismatched_or_uncontrolled_overrides_are_rejected(key, value):
    settings = controlled()
    if value is None:
        settings.pop(key)
    else:
        settings[key] = value
    with pytest.raises(ValueError, match="Invalid controlled memory acceptance collection"):
        main.memory_collection_name(settings)


@pytest.mark.parametrize("key", KEYS)
def test_a_lone_control_setting_cannot_change_the_production_namespace(key):
    with pytest.raises(ValueError, match="controlled memory acceptance collection"):
        main.memory_collection_name({key: controlled()[key]})


@pytest.fixture
def builder_environment(monkeypatch, tmp_path):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("MEM0_MODEL_GATEWAY_BASE_URL", raising=False)
    for key, value in {
        "DASHSCOPE_API_KEY": "fixture-not-real", "EMBEDDING_API_KEY": "fixture-not-real",
        "MEM0_LLM_MODEL": "fixture-llm", "EMBEDDING_MODEL": "fixture-embedding",
        "DASHSCOPE_BASE_URL": "https://llm-fixture.invalid/v1", "EMBEDDING_BASE_URL": "https://embed-fixture.invalid/v1",
        "MEM0_DATA_DIR": str(tmp_path / "candidate-memory"),
    }.items():
        monkeypatch.setenv(key, value)
    return tmp_path / "candidate-memory"


def test_actual_builder_changes_only_collection_and_retains_provider_dimension_and_history_config(builder_environment, monkeypatch):
    instance = main.memory_instance
    original = main.get_memory_config()
    assert original["vector_store"]["config"]["collection_name"] == "doorhandle_memories"
    for key, value in controlled().items():
        monkeypatch.setenv(key, value)
    candidate = main.get_memory_config()
    expected = copy.deepcopy(original)
    expected["vector_store"]["config"]["collection_name"] = COLLECTION
    assert candidate == expected
    assert "embedding_dims" not in candidate["embedder"]["config"]
    assert candidate["history_db_path"] == str(builder_environment / "history.db")
    assert main.memory_instance is instance


def test_invalid_builder_configuration_fails_before_credentials_or_storage_access(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MEM0_RUNTIME_TEST_COLLECTION", COLLECTION)
    monkeypatch.setattr(main, "required_env", lambda *_: pytest.fail("credentials must not be read for an invalid namespace"))
    with pytest.raises(ValueError, match="controlled memory acceptance collection"):
        main.get_memory_config()


def test_request_fields_cannot_override_the_deployment_collection(builder_environment):
    request = main.SearchMemoryRequest.model_validate({"user_id": "doorhandlecatch:user:1", "app_id": "doorhandlecatch",
        "run_id": "fixture-run", "query": "fixture text", "collection_name": COLLECTION, "MEM0_RUNTIME_TEST_COLLECTION": COLLECTION})
    assert "collection_name" not in request.model_dump()
    assert "MEM0_RUNTIME_TEST_COLLECTION" not in request.model_dump()
    assert main.get_memory_config()["vector_store"]["config"]["collection_name"] == "doorhandle_memories"
