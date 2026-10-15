import asyncio
import pytest
from pydantic import ValidationError

from memory_service import main


class FakeMemory:
    def __init__(self):
        self.add_call = None
        self.search_call = None

    def add(self, content, **kwargs):
        self.add_call = (content, kwargs)
        return {"results": []}

    def search(self, query, **kwargs):
        self.search_call = (query, kwargs)
        return {"results": []}


def test_add_and_search_scope_memories_by_user_app_and_run(monkeypatch):
    fake = FakeMemory()
    monkeypatch.setattr(main, "memory_instance", fake)
    scope = {
        "user_id": "doorhandlecatch:user:42",
        "app_id": "doorhandlecatch",
        "run_id": "sess_abc",
    }

    asyncio.run(main.add_memory(main.AddMemoryRequest(content="hello", **scope)))
    asyncio.run(main.search_memories(main.SearchMemoryRequest(query="hello", top_k=3, **scope)))

    assert fake.add_call[1]["user_id"] == scope["user_id"]
    assert fake.add_call[1]["agent_id"] == scope["app_id"]
    assert fake.add_call[1]["run_id"] == scope["run_id"]
    assert fake.search_call[1]["filters"] == {
        "user_id": scope["user_id"],
        "agent_id": scope["app_id"],
        "run_id": scope["run_id"],
    }


def test_memory_config_keeps_dashscope_model_and_credentials_separate_from_main_agent(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-dashscope-key")
    monkeypatch.setenv("DASHSCOPE_MODEL", "kimi-k3")
    monkeypatch.setenv("AGENTSCOPE_AI_MODEL", "openai-official:gpt-6.1-sol")
    monkeypatch.setenv("EMBEDDING_API_KEY", "fixture-embedding-key")
    monkeypatch.delenv("MEM0_LLM_MODEL", raising=False)
    config = main.get_memory_config()
    assert config["llm"]["config"]["model"] == "kimi-k3"
    assert config["llm"]["config"]["api_key"] == "fixture-dashscope-key"
    assert config["embedder"]["config"]["api_key"] == "fixture-embedding-key"


def test_memory_config_supports_an_explicit_memory_model(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-dashscope-key")
    monkeypatch.setenv("EMBEDDING_API_KEY", "fixture-embedding-key")
    monkeypatch.setenv("MEM0_LLM_MODEL", "qwen-plus")
    assert main.get_memory_config()["llm"]["config"]["model"] == "qwen-plus"


def test_account_memory_spans_sessions_but_always_filters_user_and_application(monkeypatch):
    fake = FakeMemory()
    monkeypatch.setattr(main, "memory_instance", fake)
    for user in ("doorhandlecatch:user:42", "doorhandlecatch:user:43"):
        for session in ("sess_one", "sess_two"):
            asyncio.run(main.search_memories(main.SearchMemoryRequest(
                user_id=user, app_id="doorhandlecatch", run_id=session,
                query="报告习惯", scope="ACCOUNT", top_k=5)))
            assert fake.search_call[1]["filters"] == {"user_id": user, "agent_id": "doorhandlecatch"}


def test_account_scope_cannot_be_global_or_missing_identity():
    for overrides in ({"scope": "GLOBAL"}, {"user_id": ""}, {"app_id": ""}, {"top_k": 1000}):
        request = dict(user_id="doorhandlecatch:user:42", app_id="doorhandlecatch", run_id="sess_one", query="报告", scope="ACCOUNT")
        request.update(overrides)
        with pytest.raises(ValidationError):
            main.SearchMemoryRequest(**request)
