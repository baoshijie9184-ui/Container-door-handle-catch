"""Exercise one ASGI event loop while a real worker waits for a slow extraction."""
import asyncio
import threading
from types import SimpleNamespace
import httpx
from memory_service import main


def test_extraction_does_not_block_health_or_owned_listing(monkeypatch):
    started, release, completed = threading.Event(), threading.Event(), threading.Event()
    def add(*args, **kwargs):
        started.set()
        try:
            assert release.wait(3)
            return {"results": []}
        finally:
            completed.set()
    memory = SimpleNamespace(add=add, vector_store=SimpleNamespace(collection=SimpleNamespace(get=lambda **kw: {"ids": [], "metadatas": []})))
    monkeypatch.setattr(main, "memory_instance", memory)
    monkeypatch.setenv("MEM0_BRIDGE_TOKEN", "concurrency-fixture")
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test", headers={"X-Doorhandle-Memory-Token": "concurrency-fixture"}) as client:
            slow = asyncio.create_task(client.post("/memories/add", json={"user_id": "doorhandlecatch:user:42", "app_id": "doorhandlecatch", "run_id": "session", "content": "preference"}))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                assert not completed.is_set()
                health, listing = await asyncio.wait_for(asyncio.gather(client.get("/health"), client.post("/memories/owned/list", json={"user_id": "doorhandlecatch:user:42", "app_id": "doorhandlecatch"})), 1)
                assert health.status_code == listing.status_code == 200
                assert not completed.is_set(), "List must complete while extraction is still waiting"
            finally:
                release.set()
                assert (await slow).status_code == 200
    asyncio.run(exercise())
