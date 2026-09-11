import asyncio

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
    assert fake.add_call[1]["app_id"] == scope["app_id"]
    assert fake.add_call[1]["run_id"] == scope["run_id"]
    assert fake.search_call[1]["filters"] == {
        "AND": [
            {"user_id": scope["user_id"]},
            {"app_id": scope["app_id"]},
            {"run_id": scope["run_id"]},
        ]
    }
