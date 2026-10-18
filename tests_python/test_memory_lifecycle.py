import copy
import json
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from memory_service import main
from memory_service.lifecycle import GovernedVectorStore
from memory_service.write_receipts import CST, MemoryWriter
from tests_python.test_memory_governance import FakeMemory

USER, APP = "doorhandlecatch:user:42", "doorhandlecatch"


def setup(monkeypatch):
    fake = FakeMemory()
    monkeypatch.setattr(main, "memory_instance", fake)
    monkeypatch.setenv("MEM0_BRIDGE_TOKEN", "fixture")
    return TestClient(main.app), fake, {"X-Doorhandle-Memory-Token": "fixture"}


def policy(fake, **changes):
    return {"user_id": USER, "app_id": APP, "memory_id": "mine", "expected_digest": main.memory_digest(fake.rows["mine"]),
            "expected_revision": 0, "state": "EXCLUDED", "auto_delete": False, **changes}


def expired(writer, fake, *, auto_delete=True, memory_id="mine"):
    store = writer.lifecycle
    date = (datetime.now(CST) - timedelta(seconds=1)).isoformat(timespec="microseconds")
    store.change(USER, APP, memory_id, 0, main.memory_digest(fake.rows[memory_id]), "ACTIVE", date, auto_delete)


def test_owned_policy_is_versioned_durable_and_does_not_change_memory_text(monkeypatch, isolate_memory_receipts):
    http, fake, headers = setup(monkeypatch)
    original = copy.deepcopy(fake.rows["mine"])
    response = http.post('/memories/owned/lifecycle', json=policy(fake), headers=headers)
    assert response.status_code == 200 and response.json()['data']['revision'] == 1
    assert fake.rows['mine'] == original
    assert not isolate_memory_receipts.lifecycle.allowed(USER, APP, 'mine')
    listed = http.post('/memories/owned/list', json={'user_id': USER, 'app_id': APP}, headers=headers)
    assert listed.json()['data']['items'][0]['lifecycle']['state'] == 'EXCLUDED'
    assert http.post('/memories/owned/lifecycle', json=policy(fake), headers=headers).status_code == 409
    assert http.post('/memories/owned/lifecycle', json=policy(fake, state='ACTIVE', expected_revision=1), headers=headers).status_code == 200
    assert isolate_memory_receipts.lifecycle.allowed(USER, APP, 'mine')
    with isolate_memory_receipts.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM memory_cleanup_event').fetchone()[0] == 2
    assert '本人报告偏好'.encode() not in isolate_memory_receipts.store.path.read_bytes()


@pytest.mark.parametrize('override', [
    {'state': 'DELETE_ALL'}, {'expected_revision': -1}, {'expires_at': '2030-01-01T00:00:00'},
    {'expires_at': '2020-01-01T00:00:00+08:00'}, {'auto_delete': True}, {'app_id': 'other'},
])
def test_invalid_controls_never_reach_native_mutations(monkeypatch, override):
    http, fake, headers = setup(monkeypatch)
    assert http.post('/memories/owned/lifecycle', json=policy(fake, **override), headers=headers).status_code == 422
    assert not fake.deleted and not fake.updated


def test_other_accounts_apps_and_stale_content_cannot_change_controls(monkeypatch):
    http, fake, headers = setup(monkeypatch)
    for id in ['other', 'other-app', 'missing']:
        assert http.post('/memories/owned/lifecycle', json=policy(fake, memory_id=id), headers=headers).status_code == 404
    assert http.post('/memories/owned/lifecycle', json=policy(fake, expected_digest='a'*64), headers=headers).status_code == 409
    assert http.post('/memories/owned/lifecycle', json=policy(fake)).status_code == 401


def test_filtered_retrieval_and_native_context_never_contain_excluded_or_expired_records(monkeypatch, isolate_memory_receipts):
    http, fake, headers = setup(monkeypatch)
    store = isolate_memory_receipts.lifecycle
    store.change(USER, APP, 'mine', 0, main.memory_digest(fake.rows['mine']), 'EXCLUDED', None, False)
    fake.search = lambda *args, **kwargs: {'results': [{'id': 'mine', 'memory': '不应送入模型的正文'}]}
    payload = {'user_id': USER, 'app_id': APP, 'run_id': 's', 'query': '报告', 'scope': 'ACCOUNT'}
    assert http.post('/memories/search', json=payload, headers=headers).json()['data'] == []
    delegate = SimpleNamespace(search=lambda **kwargs: [SimpleNamespace(id='mine', payload=fake.rows['mine'])])
    governed = GovernedVectorStore(delegate, store)
    assert governed.search(filters={'user_id': USER}) == []
    date = (datetime.now(CST)-timedelta(seconds=1)).isoformat(timespec='microseconds')
    store.change(USER, APP, 'mine', 1, main.memory_digest(fake.rows['mine']), 'ACTIVE', date, False)
    assert governed.search() == []
    store.change(USER, APP, 'mine', 2, main.memory_digest(fake.rows['mine']), 'ACTIVE', None, False)
    assert len(governed.search()) == 1


def test_expiry_without_opt_in_only_filters_and_never_deletes(monkeypatch, isolate_memory_receipts):
    _, fake, _ = setup(monkeypatch)
    expired(isolate_memory_receipts, fake, auto_delete=False)
    assert isolate_memory_receipts.schedule_cleanup()
    isolate_memory_receipts.future.result(timeout=2)
    assert fake.deleted == [] and 'mine' in fake.rows
    assert not isolate_memory_receipts.lifecycle.allowed(USER, APP, 'mine')


def test_opted_in_cleanup_records_actual_absence_and_never_repeats(monkeypatch, isolate_memory_receipts):
    http, fake, headers = setup(monkeypatch)
    expired(isolate_memory_receipts, fake)
    for _ in range(2):
        assert isolate_memory_receipts.schedule_cleanup()
        isolate_memory_receipts.future.result(timeout=2)
    assert fake.deleted == ['mine']
    rows = http.post('/memories/lifecycle/list', json={'user_id': USER, 'app_id': APP}, headers=headers).json()['data']
    assert len(rows) == 1 and rows[0]['cleanupState'] == 'SUCCEEDED'
    assert http.post('/memories/lifecycle/list', json={'user_id': 'doorhandlecatch:user:43', 'app_id': APP}, headers=headers).json()['data'] == []


@pytest.mark.parametrize('fault', ['changed_content', 'foreign_owner', 'partial_delete'])
def test_changed_or_unknown_cleanup_stays_quarantined_without_replaying(monkeypatch, isolate_memory_receipts, fault):
    http, fake, headers = setup(monkeypatch)
    expired(isolate_memory_receipts, fake)
    original_delete = fake.delete
    if fault == 'changed_content': fake.rows['mine']['memory'] = '更新后的正文'
    elif fault == 'foreign_owner': fake.rows['mine']['user_id'] = 'doorhandlecatch:user:43'
    else:
        def failed(id): original_delete(id); raise OSError('PRIVATE_FAILURE')
        fake.delete = failed
    for _ in range(2):
        assert isolate_memory_receipts.schedule_cleanup()
        isolate_memory_receipts.future.result(timeout=2)
    assert isolate_memory_receipts.lifecycle.public(USER, APP, 'mine')['cleanupState'] == 'NEEDS_REVIEW'
    assert fake.deleted == (['mine'] if fault == 'partial_delete' else [])
    payload = {'user_id': USER, 'app_id': APP, 'memory_id': 'mine'}
    response = http.post('/memories/lifecycle/verify', json=payload, headers=headers)
    assert response.json()['data']['cleanupState'] == ('SUCCEEDED' if fault == 'partial_delete' else 'NEEDS_REVIEW')
    assert http.post('/memories/lifecycle/verify', json={**payload, 'user_id': 'doorhandlecatch:user:43'}, headers=headers).status_code == 404


def test_failed_pre_cleanup_audit_never_calls_delete(monkeypatch, isolate_memory_receipts):
    _, fake, _ = setup(monkeypatch)
    expired(isolate_memory_receipts, fake)
    def fail(*args): raise OSError('fixture journal unavailable')
    monkeypatch.setattr(isolate_memory_receipts.lifecycle, 'transition', fail)
    assert isolate_memory_receipts.schedule_cleanup()
    isolate_memory_receipts.future.result(timeout=2)
    assert fake.deleted == [] and isolate_memory_receipts.audit_unavailable.is_set()
    assert not isolate_memory_receipts.schedule_cleanup()


def test_cleanup_shares_write_slot_and_shutdown_fence_until_actual_finish(tmp_path, monkeypatch):
    _, fake, _ = setup(monkeypatch)
    started, release = threading.Event(), threading.Event()
    original = fake.delete
    def slow(id): started.set(); assert release.wait(5); original(id)
    fake.delete = slow
    writer = MemoryWriter(tmp_path/'fenced', lambda: fake, threading.Lock())
    expired(writer, fake)
    try:
        assert writer.schedule_cleanup() and started.wait(2)
        assert not writer.schedule_cleanup()
        writer.close(wait=False)
        with pytest.raises(OSError): MemoryWriter(tmp_path/'fenced', lambda: None, threading.Lock())
    finally: release.set(); writer.close()
    assert fake.deleted == ['mine']
    again = MemoryWriter(tmp_path/'fenced', lambda: fake, threading.Lock())
    try: assert again.lifecycle.public(USER, APP, 'mine')['cleanupState'] == 'SUCCEEDED'
    finally: again.close()


def test_policy_and_audit_are_atomic(monkeypatch, isolate_memory_receipts):
    http, fake, headers = setup(monkeypatch)
    def failed(*args): raise OSError('fixture event audit failure')
    monkeypatch.setattr(isolate_memory_receipts.lifecycle, '_event', failed)
    assert http.post('/memories/owned/lifecycle', json=policy(fake), headers=headers).status_code == 503
    assert isolate_memory_receipts.lifecycle.get(USER, APP, 'mine') is None
    assert not fake.deleted


def test_outcome_audit_failure_fences_extraction_and_keeps_cleanup_unknown(monkeypatch, isolate_memory_receipts):
    _, fake, _ = setup(monkeypatch)
    expired(isolate_memory_receipts, fake)
    original = isolate_memory_receipts.lifecycle.transition
    def failed(row, source, target):
        if source == 'RUNNING': raise OSError('fixture completion audit failure')
        return original(row, source, target)
    monkeypatch.setattr(isolate_memory_receipts.lifecycle, 'transition', failed)
    assert isolate_memory_receipts.schedule_cleanup()
    isolate_memory_receipts.future.result(timeout=2)
    assert fake.deleted == ['mine'] and isolate_memory_receipts.audit_unavailable.is_set()
    assert isolate_memory_receipts.lifecycle.public(USER, APP, 'mine')['cleanupState'] == 'RUNNING'
    assert not isolate_memory_receipts.lifecycle.allowed(USER, APP, 'mine')


def test_native_sdk_chroma_context_filter_and_expiry_removal(tmp_path, monkeypatch):
    monkeypatch.setenv('MEM0_TELEMETRY', 'false');monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'false')
    from mem0 import Memory
    import mem0.memory.main as native
    monkeypatch.setattr(native, 'capture_event', lambda *args, **kwargs: None)
    monkeypatch.setattr(native, 'lemmatize_for_bm25', lambda text: text)
    monkeypatch.setattr(native, 'extract_entities_batch', lambda texts: [[] for _ in texts])
    memory = Memory.from_config({
        'llm': {'provider':'openai','config':{'api_key':'fixture','model':'fixture','openai_base_url':'http://127.0.0.1:1/v1'}},
        'embedder': {'provider':'openai','config':{'api_key':'fixture','model':'fixture','embedding_dims':4,'openai_base_url':'http://127.0.0.1:1/v1'}},
        'vector_store': {'provider':'chroma','config':{'path':str(tmp_path/'chroma'),'collection_name':'lifecycle_test'}},
        'history_db_path':str(tmp_path/'history.sqlite3')})
    memory.embedding_model.embed=lambda *args,**kwargs:[.1,.2,.3,.4]
    memory.embedding_model.embed_batch=lambda texts,*args,**kwargs:[[.1,.2,.3,.4] for _ in texts]
    id=memory.add('PRIVATE_EXCLUDED_PREFERENCE',user_id=USER,agent_id=APP,run_id='s',infer=False)['results'][0]['id']
    writer=MemoryWriter(tmp_path/'receipts',lambda:memory,threading.Lock())
    memory.vector_store=GovernedVectorStore(memory.vector_store,writer.lifecycle)
    try:
        writer.lifecycle.change(USER,APP,id,0,main.memory_digest(memory.get(id)),'EXCLUDED',None,False)
        assert memory.vector_store.search(query='x',vectors=[.1,.2,.3,.4],top_k=5,filters={'user_id':USER,'agent_id':APP})==[]
        prompts=[]
        def model(*args,**kwargs):prompts.extend(kwargs['messages']);return '{"memory":[]}'
        memory.llm.generate_response=model
        assert writer.submit(USER,APP,'s','新提问',None,'new')['status']=='SUCCEEDED'
        assert 'PRIVATE_EXCLUDED_PREFERENCE' not in json.dumps(prompts)
        date=(datetime.now(CST)-timedelta(seconds=1)).isoformat(timespec='microseconds')
        writer.lifecycle.change(USER,APP,id,1,main.memory_digest(memory.get(id)),'ACTIVE',date,True)
        assert writer.schedule_cleanup();writer.future.result(timeout=3)
        assert memory.get(id) is None and memory.vector_store.collection.count()==0
        assert writer.lifecycle.public(USER,APP,id)['cleanupState']=='SUCCEEDED'
    finally:writer.close()


def test_process_death_during_cleanup_is_not_replayed(tmp_path):
    import subprocess,sys,queue
    directory=tmp_path/'crash'
    fake=FakeMemory();writer=MemoryWriter(directory,lambda:fake,threading.Lock());expired(writer,fake);writer.close()
    code='''
import sys,threading
from pathlib import Path
from memory_service.write_receipts import MemoryWriter
row={"id":"mine","user_id":"doorhandlecatch:user:42","agent_id":"doorhandlecatch","run_id":"sess_one","memory":"本人报告偏好","updated_at":"2026-10-13T12:00:00Z"}
class Memory:
 def get(self,id):return row
 def delete(self,id):
  Path(sys.argv[1],"partial-write").write_text("done")
  print("DELETING",flush=True)
  threading.Event().wait()
writer=MemoryWriter(sys.argv[1],lambda:Memory(),threading.Lock())
writer.schedule_cleanup();writer.future.result()
'''
    child=subprocess.Popen([sys.executable,'-c',code,str(directory)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    messages=queue.Queue();reader=threading.Thread(target=lambda:messages.put(child.stdout.readline()),daemon=True);reader.start()
    try:
        assert messages.get(timeout=10).strip()=='DELETING'
        assert (directory/'partial-write').exists()
    finally:
        child.kill();child.wait(timeout=5);reader.join(timeout=2);child.stdout.close();child.stderr.close()
    again=MemoryWriter(directory,lambda:fake,threading.Lock())
    try:
        assert again.lifecycle.public(USER,APP,'mine')['cleanupState']=='NEEDS_REVIEW'
        assert again.schedule_cleanup();again.future.result(timeout=2)
        assert fake.deleted==[]
    finally:again.close()


@pytest.mark.parametrize('enabled', [True, False])
def test_real_lifespan_scheduler_only_removes_consented_memories_when_enabled(tmp_path, monkeypatch, enabled):
    import asyncio
    from mem0 import Memory
    _, fake, _ = setup(monkeypatch)
    class Client:
        def with_options(self,**kwargs):return self
    fake.llm=SimpleNamespace(client=Client());fake.embedding_model=SimpleNamespace(client=Client())
    data=tmp_path/'runtime';writer=MemoryWriter(data/'bridge_receipts',lambda:fake,threading.Lock());expired(writer,fake);writer.close()
    monkeypatch.setenv('MEM0_DATA_DIR',str(data));monkeypatch.setenv('MEM0_LIFECYCLE_CLEANUP_ENABLED',str(enabled).lower())
    for name in ['DASHSCOPE_API_KEY','EMBEDDING_API_KEY']:monkeypatch.setenv(name,'fixture')
    monkeypatch.setattr(Memory,'from_config',lambda config:fake)
    timing=main.bounded_setting
    monkeypatch.setattr(main,'bounded_setting',lambda name,*args:.02 if name=='MEM0_CLEANUP_INTERVAL_SECONDS' else timing(name,*args))
    original=main.memory_writer
    async def exercise():
        async with main.lifespan(main.app):
            if enabled:
                async def deleted():
                    while not fake.deleted:await asyncio.sleep(.01)
                await asyncio.wait_for(deleted(),timeout=2)
            else:await asyncio.sleep(.08)
            assert fake.deleted==(['mine'] if enabled else [])
    try:asyncio.run(exercise())
    finally:main.memory_writer=original
