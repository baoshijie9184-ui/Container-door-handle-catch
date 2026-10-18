import json
import logging
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from memory_service import main
from memory_service.write_receipts import MemoryWriter, ReceiptError


USER = "doorhandlecatch:user:42"
APP = "doorhandlecatch"


class Memory:
    def __init__(self):
        self.calls = 0
        self.rows = {}

    def add(self, content, **kwargs):
        self.calls += 1
        self.rows["stored"] = {"id": "stored", "memory": content, "user_id": kwargs["user_id"], "agent_id": kwargs["agent_id"]}
        return {"results": [{"id": "stored", "event": "ADD", "memory": content}]}

    def get(self, id):
        return self.rows.get(id)


def test_success_survives_restart_and_never_saves_plaintext_in_receipts(tmp_path):
    memory = Memory()
    directory = tmp_path / "receipts"
    writer = MemoryWriter(directory, lambda: memory, threading.Lock())
    result = writer.submit(USER, APP, "session", "PRIVATE_CONVERSATION_正文", {"source": "test"}, "request")
    assert result["status"] == "SUCCEEDED" and result["results"] == [{"id": "stored", "event": "ADD"}]
    assert result["updatedAt"].endswith("+08:00")
    writer.close()
    again = MemoryWriter(directory, lambda: memory, threading.Lock())
    try:
        assert again.submit(USER, APP, "session", "PRIVATE_CONVERSATION_正文", {"source": "test"}, "request")["status"] == "SUCCEEDED"
        assert memory.calls == 1
        assert b"PRIVATE_CONVERSATION" not in again.store.path.read_bytes()
        with pytest.raises(ReceiptError) as error:
            again.receipt("doorhandlecatch:user:43", APP, "request")
        assert error.value.status == 404
        with pytest.raises(ReceiptError) as error:
            again.submit(USER, APP, "session", "different content", {"source": "test"}, "request")
        assert error.value.status == 409
    finally:
        again.close()


def test_one_live_writer_fences_other_processes_and_shutdown_keeps_fence_until_actual_finish(tmp_path):
    started, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        started.set(); assert release.wait(5); return {"results": []}
    directory = tmp_path / "writer"
    writer = MemoryWriter(directory, lambda: SimpleNamespace(add=slow), threading.Lock(), response_wait=.03)
    try:
        assert writer.submit(USER, APP, "s", "x", None, "one")["status"] == "RUNNING"
        assert started.is_set()
        writer.close(wait=False)
        with pytest.raises(OSError):
            MemoryWriter(directory, lambda: None, threading.Lock())
    finally:
        release.set(); writer.close()
    restarted = MemoryWriter(directory, lambda: None, threading.Lock()); restarted.close()


def test_wait_timeout_keeps_writer_slot_repeated_same_request_only_reads_receipt(tmp_path):
    started, release = threading.Event(), threading.Event()
    calls = []
    def slow(*args, **kwargs):
        calls.append(kwargs["user_id"]); started.set(); assert release.wait(5); return {"results": []}
    writer = MemoryWriter(tmp_path / "receipts", lambda: SimpleNamespace(add=slow), threading.Lock(), response_wait=.03)
    try:
        result = writer.submit(USER, APP, "session", "private", None, "one")
        assert result["status"] == "RUNNING" and started.is_set()
        with ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(lambda _: writer.submit(USER, APP, "session", "private", None, "one")["status"], range(36)))
        assert set(statuses) == {"RUNNING"} and calls == [USER]
        with pytest.raises(ReceiptError) as error:
            writer.submit(USER, APP, "session", "new", None, "two")
        assert error.value.status == 503 and "not started" in error.value.detail
        with pytest.raises(ReceiptError):
            writer.receipt(USER, APP, "two")
        release.set(); writer.future.result(timeout=2)
        assert writer.receipt(USER, APP, "one")["status"] == "SUCCEEDED"
    finally:
        release.set(); writer.close()


@pytest.mark.parametrize("fault", ["exception", "swallowed_error", "swallowed_warning", "missing_vector"])
def test_partial_or_swallowed_failures_are_not_successful_or_replayed(tmp_path, fault):
    memory = Memory()
    original = memory.add
    def add(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == "exception": raise RuntimeError("PRIVATE_PROVIDER_TOKEN")
        if fault == "swallowed_error": logging.getLogger("mem0.memory.main").error("PRIVATE_PROVIDER_TOKEN")
        if fault == "swallowed_warning": logging.getLogger("mem0.memory.main").warning("PRIVATE_PROVIDER_TOKEN")
        if fault == "missing_vector": memory.rows.clear()
        return result
    memory.add = add
    writer = MemoryWriter(tmp_path / "receipt", lambda: memory, threading.Lock())
    try:
        assert writer.submit(USER, APP, "s", "PRIVATE", None, "one")["status"] == "NEEDS_REVIEW"
        assert writer.submit(USER, APP, "s", "PRIVATE", None, "one")["status"] == "NEEDS_REVIEW"
        assert memory.calls == 1
    finally:
        writer.close()


def test_pre_write_receipt_failure_prevents_sdk_call_and_frees_slot(tmp_path, monkeypatch):
    memory = Memory(); lock = threading.Lock()
    writer = MemoryWriter(tmp_path / "receipt", lambda: memory, lock)
    try:
        def fail(*args): raise OSError("fixture audit storage error")
        monkeypatch.setattr(writer.store, "reserve", fail)
        with pytest.raises(OSError): writer.submit(USER, APP, "s", "x", None, "one")
        assert memory.calls == 0 and not lock.locked()
    finally:
        writer.close()


def test_completion_winning_a_deadline_query_is_preserved(tmp_path, monkeypatch):
    writer = MemoryWriter(tmp_path / "receipt", lambda: None, threading.Lock())
    try:
        writer.store.reserve(USER, APP, "one", "fingerprint", -1)
        original = writer.store.get
        first = True
        def complete_after_snapshot(*args):
            nonlocal first
            row = original(*args)
            if first:
                first = False
                writer.store.finish(USER, APP, "one", "SUCCEEDED", [{"id": "stored", "event": "ADD"}])
            return row
        monkeypatch.setattr(writer.store, "get", complete_after_snapshot)
        receipt = writer.receipt(USER, APP, "one")
        assert receipt["status"] == "SUCCEEDED" and len(receipt["results"]) == 1
    finally:
        writer.close()


def test_outcome_audit_failure_is_unknown_and_fences_new_side_effects(tmp_path, monkeypatch):
    memory=Memory();writer=MemoryWriter(tmp_path/'receipt',lambda:memory,threading.Lock())
    original=writer.store.finish
    def fail(*args,**kwargs):raise OSError('fixture outcome audit failure')
    try:
        monkeypatch.setattr(writer.store,'finish',fail)
        with pytest.raises(ReceiptError) as error:writer.submit(USER,APP,'s','private',None,'one')
        assert error.value.status==503 and not error.value.not_started and memory.calls==1
        with pytest.raises(ReceiptError) as error:writer.submit(USER,APP,'s','new',None,'two')
        assert error.value.not_started and memory.calls==1
        monkeypatch.setattr(writer.store,'finish',original)
    finally:writer.close()
    restarted=MemoryWriter(tmp_path/'receipt',lambda:memory,threading.Lock())
    try:assert restarted.receipt(USER,APP,'one')['status']=='NEEDS_REVIEW'
    finally:restarted.close()


def test_deadline_is_review_state_and_does_not_claim_running_write_was_cancelled(tmp_path):
    release = threading.Event()
    writer = MemoryWriter(tmp_path / "receipt", lambda: SimpleNamespace(add=lambda *a, **k: (release.wait(5), {"results": []})[1]), threading.Lock(), response_wait=.03, operation_seconds=-1)
    try:
        assert writer.submit(USER, APP, "s", "x", None, "one")["status"] == "NEEDS_REVIEW"
        assert writer.write_lock.locked()
        release.set(); writer.future.result(timeout=2)
        assert writer.receipt(USER, APP, "one")["status"] == "SUCCEEDED"
    finally:
        release.set(); writer.close()


def test_process_death_marks_unknown_without_repeating_partial_write(tmp_path):
    directory = tmp_path / "process-receipts"
    # Only a test-owned child with an SDK substitute; marker is a stand-in for an already performed vector write.
    script = """
import json,sys,threading
from pathlib import Path
from types import SimpleNamespace
from memory_service.write_receipts import MemoryWriter
path=Path(sys.argv[1])
def partial(*args,**kwargs):
 (path/'partial-vector-write').write_text('written')
 print('SDK_STARTED',flush=True)
 threading.Event().wait(60)
writer=MemoryWriter(path,lambda:SimpleNamespace(add=partial),threading.Lock(),response_wait=.02)
writer.submit('doorhandlecatch:user:42','doorhandlecatch','s','private',None,'one')
threading.Event().wait(60)
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(directory)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=Path(__file__).resolve().parents[1])
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as reader:
            ready = reader.submit(child.stdout.readline)
            try: assert ready.result(timeout=10).strip() == "SDK_STARTED"
            except BaseException:
                child.kill(); raise
        assert child.poll() is None and (directory / "partial-vector-write").read_text() == "written"
        child.kill(); child.communicate(timeout=10)
        memory = Memory(); writer = MemoryWriter(directory, lambda: memory, threading.Lock())
        try:
            assert writer.receipt(USER, APP, "one")["status"] == "NEEDS_REVIEW"
            assert writer.submit(USER, APP, "s", "private", None, "one")["status"] == "NEEDS_REVIEW"
            assert memory.calls == 0
        finally: writer.close()
    finally:
        if child.poll() is None: child.kill()
        child.communicate(timeout=10)


def test_private_operation_endpoint_and_reserved_metadata_cannot_cross_accounts(monkeypatch):
    monkeypatch.setenv("MEM0_BRIDGE_TOKEN", "fixture")
    memory = Memory(); monkeypatch.setattr(main, "memory_instance", memory)
    client = TestClient(main.app); headers = {"X-Doorhandle-Memory-Token": "fixture"}
    body = {"user_id": USER, "app_id": APP, "run_id": "s", "content": "private", "request_id": "one"}
    assert client.post("/memories/add", json=body, headers=headers).status_code == 200
    request = {key: body[key] for key in ("user_id", "app_id", "request_id")}
    assert client.post("/memories/operations/get", json=request).status_code == 401
    result = client.post("/memories/operations/get", json=request, headers=headers)
    assert result.status_code == 200 and result.json()["data"]["status"] == "SUCCEEDED" and "private" not in result.text
    assert client.post("/memories/operations/get", json={**request, "user_id": "doorhandlecatch:user:43"}, headers=headers).status_code == 404
    assert client.post("/memories/add", json={**body, "metadata": {"user_id": "doorhandlecatch:user:43"}}, headers=headers).status_code == 422
    assert memory.calls == 1


def test_provider_timeout_configuration_preserves_clients_and_disables_retries(monkeypatch):
    from openai import OpenAI
    first = OpenAI(api_key="fixture-key", base_url="http://127.0.0.1:1/v1")
    second = OpenAI(api_key="embedding-fixture", base_url="http://127.0.0.1:2/v1")
    memory = SimpleNamespace(llm=SimpleNamespace(client=first), embedding_model=SimpleNamespace(client=second))
    monkeypatch.setenv("MEM0_PROVIDER_TIMEOUT_SECONDS", ".2")
    try:
        main.configure_provider_timeouts(memory)
        assert str(memory.llm.client.base_url) == "http://127.0.0.1:1/v1/" and memory.llm.client.api_key == "fixture-key"
        assert memory.llm.client.max_retries == memory.embedding_model.client.max_retries == 0
        assert memory.llm.client.timeout == memory.embedding_model.client.timeout == .2
    finally: first.close(); second.close()


def test_real_sdk_times_out_once_without_retrying(monkeypatch):
    import http.server
    import time
    import openai
    calls=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            time.sleep(.3)
            try:
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        def log_message(self,*args): pass
    http=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv("MEM0_PROVIDER_TIMEOUT_SECONDS", ".1")
    client=openai.OpenAI(api_key="fixture-not-real",base_url=f"http://127.0.0.1:{http.server_port}/v1")
    memory=SimpleNamespace(llm=SimpleNamespace(client=client),embedding_model=SimpleNamespace(client=client))
    try:
        main.configure_provider_timeouts(memory)
        with pytest.raises(openai.APITimeoutError): memory.llm.client.chat.completions.create(model="fixture",messages=[{"role":"user","content":"fixture"}])
        assert calls==["/v1/chat/completions"]
    finally: client.close();http.shutdown();http.server_close();thread.join(timeout=2)


def test_native_mem0_and_real_chroma_confirm_results_and_swallowed_provider_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("MEM0_TELEMETRY", "false"); monkeypatch.setenv("ANONYMIZED_TELEMETRY", "false")
    from mem0 import Memory as NativeMemory
    import mem0.memory.main as native
    monkeypatch.setattr(native,"capture_event",lambda *args,**kwargs:None)
    monkeypatch.setattr(native,"lemmatize_for_bm25",lambda text:text)
    monkeypatch.setattr(native,"extract_entities_batch",lambda texts:[[] for text in texts])
    memory=NativeMemory.from_config({
        "llm":{"provider":"openai","config":{"api_key":"fixture-not-real","model":"fixture","openai_base_url":"http://127.0.0.1:1/v1"}},
        "embedder":{"provider":"openai","config":{"api_key":"fixture-not-real","model":"fixture","embedding_dims":4,"openai_base_url":"http://127.0.0.1:1/v1"}},
        "vector_store":{"provider":"chroma","config":{"path":str(tmp_path/'chroma'),"collection_name":"receipt_test"}},
        "history_db_path":str(tmp_path/'history.sqlite3')})
    memory.embedding_model.embed=lambda *args,**kwargs:[.1,.2,.3,.4]
    memory.embedding_model.embed_batch=lambda texts,*args,**kwargs:[[.1,.2,.3,.4] for text in texts]
    memory.llm.generate_response=lambda *args,**kwargs:json.dumps({"memory":[{"text":"PRIVATE_EXPLICIT_PREFERENCE"}]})
    writer=MemoryWriter(tmp_path/'native-receipts',lambda:memory,threading.Lock())
    try:
        result=writer.submit(USER,APP,"session","请记住我的明确偏好",None,"first")
        assert result['status']=='SUCCEEDED' and len(result['results'])==1
        assert memory.get(result['results'][0]['id'])['memory']=='PRIVATE_EXPLICIT_PREFERENCE'
        assert memory.vector_store.collection.count()==1
        assert writer.submit(USER,APP,"session","请记住我的明确偏好",None,"first")['status']=='SUCCEEDED'
        assert memory.vector_store.collection.count()==1
        def failed(*args,**kwargs):raise RuntimeError('PRIVATE_UPSTREAM_ERROR')
        memory.llm.generate_response=failed
        # Mem0 catches this exception internally and returns no additions; the receipt must still require review.
        failed_receipt=writer.submit(USER,APP,"session","另一个偏好",None,"failed")
        assert failed_receipt['status']=='NEEDS_REVIEW' and memory.vector_store.collection.count()==1
    finally:writer.close()


def test_startup_initializes_private_receipt_subdirectory_and_shutdown_releases_fence(tmp_path,monkeypatch):
    import asyncio
    from mem0 import Memory as NativeMemory
    class Client:
        def with_options(self,**kwargs):return self
    memory=SimpleNamespace(llm=SimpleNamespace(client=Client()),embedding_model=SimpleNamespace(client=Client()))
    monkeypatch.setattr(NativeMemory,'from_config',lambda config:memory)
    for name in ['DASHSCOPE_API_KEY','EMBEDDING_API_KEY']:monkeypatch.setenv(name,'fixture')
    monkeypatch.setenv('MEM0_DATA_DIR',str(tmp_path/'data'))
    original=main.memory_writer
    async def exercise():
        async with main.lifespan(main.app):
            assert main.memory_writer.store.path==tmp_path/'data'/'bridge_receipts'/'write-receipts.sqlite3'
            assert (await main.health_check())['write_receipts']
        assert main.memory_writer is None
    try:asyncio.run(exercise())
    finally:main.memory_writer=original
    writer=MemoryWriter(tmp_path/'data'/'bridge_receipts',lambda:None,threading.Lock());writer.close()
