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


def test_many_waiting_writes_are_rejected_without_starving_reads(monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls=[]
    def add(*args, **kwargs):
        calls.append(kwargs['user_id']);started.set();assert release.wait(5);return {'results': []}
    memory=SimpleNamespace(add=add,vector_store=SimpleNamespace(collection=SimpleNamespace(get=lambda **kw:{'ids':[],'metadatas':[]})))
    monkeypatch.setattr(main,'memory_instance',memory);monkeypatch.setenv('MEM0_BRIDGE_TOKEN','concurrency-fixture')
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test',headers={'X-Doorhandle-Memory-Token':'concurrency-fixture'}) as client:
            payload={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch','run_id':'session','content':'preference'}
            slow=asyncio.create_task(client.post('/memories/add',json=payload))
            try:
                assert await asyncio.to_thread(started.wait,1)
                replies=await asyncio.wait_for(asyncio.gather(*[client.post('/memories/add',json={**payload,'request_id':'other-'+str(i)}) for i in range(48)]),2)
                assert all(reply.status_code==503 and reply.headers.get('Retry-After')=='2' and 'not started' in reply.json()['detail'] for reply in replies)
                listing=await asyncio.wait_for(client.post('/memories/owned/list',json={'user_id':payload['user_id'],'app_id':'doorhandlecatch'}),1)
                assert listing.status_code==200 and calls==[payload['user_id']]
            finally:release.set();assert (await slow).status_code==200
            assert (await client.post('/memories/add',json=payload)).status_code==200
    asyncio.run(exercise())


def test_search_error_does_not_expose_provider_or_database_details(monkeypatch):
    def search(*args,**kwargs):raise RuntimeError('private-api-token and database path')
    monkeypatch.setattr(main,'memory_instance',SimpleNamespace(search=search));monkeypatch.setenv('MEM0_BRIDGE_TOKEN','fixture')
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test',headers={'X-Doorhandle-Memory-Token':'fixture'}) as client:
            response=await client.post('/memories/search',json={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch','run_id':'session','query':'preference'})
            assert response.status_code==503 and 'private-api-token' not in response.text and 'database path' not in response.text
    asyncio.run(exercise())
