import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from memory_service import main
from memory_service.lifecycle import GovernedVectorStore

USER,APP='doorhandlecatch:user:42','doorhandlecatch'


@pytest.fixture
def native(tmp_path,monkeypatch,isolate_memory_receipts):
    monkeypatch.setenv('MEM0_TELEMETRY','false');monkeypatch.setenv('ANONYMIZED_TELEMETRY','false');monkeypatch.setenv('MEM0_BRIDGE_TOKEN','fixture');monkeypatch.setenv('MEM0_DUPLICATE_REVIEW_ENABLED','true')
    from mem0 import Memory
    import mem0.memory.main as sdk
    monkeypatch.setattr(sdk,'capture_event',lambda *args,**kwargs:None)
    monkeypatch.setattr(sdk,'lemmatize_for_bm25',lambda text:text)
    monkeypatch.setattr(sdk,'extract_entities_batch',lambda texts:[[] for _ in texts])
    memory=Memory.from_config({
        'llm':{'provider':'openai','config':{'api_key':'fixture','model':'fixture','openai_base_url':'http://127.0.0.1:1/v1'}},
        'embedder':{'provider':'openai','config':{'api_key':'fixture','model':'fixture','embedding_dims':4,'openai_base_url':'http://127.0.0.1:1/v1'}},
        'vector_store':{'provider':'chroma','config':{'path':str(tmp_path/'chroma'),'collection_name':'review_test'}},'history_db_path':str(tmp_path/'history.sqlite3')})
    memory.embedding_model.embed=lambda *args,**kwargs:[.1,.2,.3,.4]
    memory.embedding_model.embed_batch=lambda texts,*args,**kwargs:[[.1,.2,.3,.4] for _ in texts]
    memory.vector_store=GovernedVectorStore(memory.vector_store,isolate_memory_receipts.lifecycle)
    monkeypatch.setattr(main,'memory_instance',memory)
    def add(text,session,user=USER):return memory.add(text,user_id=user,agent_id=APP,run_id=session,infer=False)['results'][0]['id']
    source=add('报告默认采用 PDF 格式','s1');candidate=add('用户喜欢把报告保存成 PDF 文件','s2')
    calls=[]
    def model(*args,**kwargs):
        calls.append(kwargs['messages']);body=json.loads(kwargs['messages'][1]['content'])
        return json.dumps({'labels':[{'id':row['id'],'label':'DUPLICATE','topicRelation':'SAME_OBJECT',
            'equivalent':True,'incompatible':False,'sourceAnchor':body['source'][:80],
            'candidateAnchor':row['text'][:80]} for row in body['candidates']]})
    memory.llm.generate_response=model
    http=TestClient(main.app);headers={'X-Doorhandle-Memory-Token':'fixture','X-Doorhandle-Memory-Protocol':'2'}
    return SimpleNamespace(memory=memory,writer=isolate_memory_receipts,add=add,source=source,candidate=candidate,http=http,headers=headers,calls=calls)


def start(n,id='review'):
    body={'user_id':USER,'app_id':APP,'memory_id':n.source,'request_id':id,'expected_digest':main.memory_digest(n.memory.get(n.source)),'expected_revision':n.writer.lifecycle.public(USER,APP,n.source)['revision']}
    response=n.http.post('/memories/reviews/start',json=body,headers=n.headers)
    assert response.status_code in [200,202],response.text
    n.writer.future.result(timeout=5)
    return n.http.post('/memories/reviews/get',json={'user_id':USER,'app_id':APP,'request_id':id},headers=n.headers).json()['data']


def resolve(n,review,choice='KEEP_SOURCE',id='decision'):
    return n.http.post('/memories/reviews/resolve',json={'user_id':USER,'app_id':APP,'request_id':review['id'],'decision_id':id,'expected_revision':review['revision'],'candidate_id':n.candidate,'choice':choice},headers=n.headers)


def test_native_cross_session_provenance_and_same_account_hash_deduplication(native):
    n=native
    n.memory.llm.generate_response=lambda *args,**kwargs:'{"memory":[{"text":"用户偏好黑色背景"}]}'
    first=n.writer.submit(USER,APP,'one','第一次提到背景',None,'first')
    second=n.writer.submit(USER,APP,'two','再次提到背景',None,'second')
    assert first['status']==second['status']=='SUCCEEDED'
    assert len(first['results'])==1 and second['results']==[]
    assert n.memory.get(first['results'][0]['id'])['run_id']=='one'
    other=n.writer.submit('doorhandlecatch:user:43',APP,'two','同样偏好',None,'other')
    assert len(other['results'])==1


def test_account_extraction_context_never_expands_other_users_or_parallel_session_reads(native):
    n=native;calls=[]
    delegate=SimpleNamespace(search=lambda **kwargs:calls.append(kwargs['filters']) or [])
    wrapper=GovernedVectorStore(delegate,n.writer.lifecycle)
    original={'user_id':USER,'agent_id':APP,'run_id':'s1'}
    with wrapper.account_extraction(USER,APP):
        wrapper.search(filters=original)
        wrapper.search(filters={**original,'user_id':'doorhandlecatch:user:43'})
        thread=threading.Thread(target=lambda:wrapper.search(filters=original));thread.start();thread.join(timeout=2)
    wrapper.search(filters=original)
    assert calls[0]=={'user_id':USER,'agent_id':APP}
    assert all('run_id' in row for row in calls[1:]) and original['run_id']=='s1'


def test_owned_edit_uses_native_sdk_update_once_and_keeps_the_original_session(native):
    n=native;original=n.memory.get(n.source)
    result=n.http.post('/memories/owned/update',json={'user_id':USER,'app_id':APP,'memory_id':n.source,
        'expected_digest':main.memory_digest(original),'memory':'用户更正为 CSV 报告'},headers=n.headers)
    assert result.status_code==200
    saved=n.memory.get(n.source)
    assert saved['memory']=='用户更正为 CSV 报告' and saved['run_id']==original['run_id']
    assert not n.calls


def test_missing_vector_adapter_checks_absence_without_masking_corrupt_or_unavailable_storage(native):
    def fail(**kwargs):raise IndexError('fixture SDK result index')
    delegate=SimpleNamespace(get=fail,collection=SimpleNamespace(get=lambda **kwargs:{'ids':[]}))
    store=GovernedVectorStore(delegate,native.writer.lifecycle)
    assert store.get('absent') is None
    delegate.collection.get=lambda **kwargs:{'ids':['exists']}
    with pytest.raises(IndexError):store.get('exists')
    def unavailable(**kwargs):raise OSError('fixture store unavailable')
    delegate.collection.get=unavailable
    with pytest.raises(OSError):store.get('unknown')


def test_semantic_candidates_span_sessions_without_mutating_and_results_survive_refresh(native):
    n=native;review=start(n)
    assert review['status']=='READY' and review['judgmentStatus']=='COMPLETE'
    pair=next(row for row in review['candidates'] if row['id']==n.candidate)
    assert pair['label']=='DUPLICATE' and pair['item']['sourceSessionId']=='s2' and review['source']['sourceSessionId']=='s1'
    assert n.writer.lifecycle.allowed(USER,APP,n.candidate) and len(n.calls)==1
    from memory_service.duplicate_review import PROMPT_VERSION
    assert json.loads(n.writer.reviews.row(USER,APP,'review')['result_json'])['promptVersion']==PROMPT_VERSION
    for _ in range(3):
        response=n.http.post('/memories/reviews/get',json={'user_id':USER,'app_id':APP,'request_id':'review'},headers=n.headers)
        assert response.status_code==200
    assert len(n.calls)==1
    assert b'PDF' not in n.writer.store.path.read_bytes()


@pytest.mark.parametrize('choice',['KEEP_SOURCE','KEEP_CANDIDATE','KEEP_BOTH'])
def test_confirmed_resolutions_are_atomic_idempotent_and_preserve_original_text(native,choice):
    n=native;review=start(n);before=n.memory.vector_store.collection.count()
    result=resolve(n,review,choice)
    assert result.status_code==200 and result.json()['data']['revision']==2
    assert resolve(n,review,choice).status_code==200  # Same receipt, not a second lifecycle change.
    assert n.memory.vector_store.collection.count()==before
    assert n.writer.lifecycle.allowed(USER,APP,n.source)==(choice!='KEEP_CANDIDATE')
    assert n.writer.lifecycle.allowed(USER,APP,n.candidate)==(choice!='KEEP_SOURCE')
    assert n.memory.get(n.source)['memory']=='报告默认采用 PDF 格式'
    assert n.memory.get(n.candidate)['memory']=='用户喜欢把报告保存成 PDF 文件'
    assert resolve(n,review,'KEEP_BOTH' if choice!='KEEP_BOTH' else 'KEEP_SOURCE').status_code==409


def test_keep_both_hides_only_the_same_version_pair_on_future_analyses(native):
    n=native;review=start(n);assert resolve(n,review,'KEEP_BOTH').status_code==200
    assert start(n,'next')['candidates']==[]
    n.memory.update(n.candidate,'2026 年报告偏好更新为 PDF 加 CSV')
    assert any(row['id']==n.candidate for row in start(n,'updated')['candidates'])


def test_provider_failure_is_unknown_judgment_and_never_erases_candidates(native):
    n=native
    def fail(*args,**kwargs):raise RuntimeError('PRIVATE_PROVIDER_ERROR')
    n.memory.llm.generate_response=fail
    result=start(n)
    assert result['status']=='READY' and result['judgmentStatus']=='UNAVAILABLE'
    assert result['candidates'][0]['label']=='UNSURE' and 'PRIVATE_PROVIDER_ERROR' not in json.dumps(result)
    assert n.writer.lifecycle.allowed(USER,APP,n.candidate)


@pytest.mark.parametrize('response',['{"labels":[]}','{"labels":[{"id":"FOREIGN","label":"DUPLICATE"}]}','{"labels":[{"id":"C0","label":"DELETE_ALL"}]}'])
def test_invalid_model_output_is_not_authorization_or_a_successful_judgment(native,response):
    n=native;n.memory.llm.generate_response=lambda **kwargs:response
    result=start(n);assert result['judgmentStatus']=='UNAVAILABLE' and result['candidates'][0]['label']=='UNSURE'


@pytest.mark.parametrize('change',['body','lifecycle','source_deleted'])
def test_stale_memory_or_control_version_cannot_be_resolved(native,change):
    n=native;review=start(n)
    if change=='body':n.memory.update(n.candidate,'改为 CSV')
    elif change=='lifecycle':n.writer.lifecycle.change(USER,APP,n.candidate,0,main.memory_digest(n.memory.get(n.candidate)),'EXCLUDED',None,False)
    else:n.memory.delete(n.source)
    assert resolve(n,review).status_code==409
    current=n.http.post('/memories/reviews/get',json={'user_id':USER,'app_id':APP,'request_id':'review'},headers=n.headers).json()['data']
    assert current['sourceStale'] if change=='source_deleted' else current['candidates'][0]['stale']


def test_owner_authentication_and_candidate_membership_are_rechecked(native):
    n=native;review=start(n)
    assert n.http.post('/memories/reviews/get',json={'user_id':'doorhandlecatch:user:43','app_id':APP,'request_id':'review'},headers=n.headers).status_code==404
    assert n.http.post('/memories/reviews/get',json={'user_id':USER,'app_id':APP,'request_id':'review'}).status_code==401
    foreign=n.add('PRIVATE_OTHER_ACCOUNT','other','doorhandlecatch:user:43')
    bad={'user_id':USER,'app_id':APP,'request_id':'foreign','memory_id':foreign,'expected_digest':'a'*64,'expected_revision':0}
    assert n.http.post('/memories/reviews/start',json=bad,headers=n.headers).status_code==404
    assert n.http.post('/memories/reviews/resolve',json={'user_id':USER,'app_id':APP,'request_id':'review','decision_id':'bad','expected_revision':1,'candidate_id':foreign,'choice':'KEEP_SOURCE'},headers=n.headers).status_code==404
    assert 'PRIVATE_OTHER_ACCOUNT' not in json.dumps(review)


def test_resolution_audit_failure_rolls_back_the_control_and_review_revision(native,monkeypatch):
    n=native;review=start(n)
    def fail(*args):raise OSError('fixture audit unavailable')
    monkeypatch.setattr(n.writer.lifecycle,'_event',fail)
    assert resolve(n,review).status_code==503
    assert n.writer.lifecycle.allowed(USER,APP,n.candidate)
    assert n.writer.reviews.row(USER,APP,'review')['revision']==1


def test_waiting_review_does_not_block_reads_and_duplicate_start_does_not_call_the_model_again(native):
    n=native;release=threading.Event();started=threading.Event();calls=[]
    original=n.memory.llm.generate_response
    def slow(**kwargs):calls.append(1);started.set();assert release.wait(10);return original(**kwargs)
    n.memory.llm.generate_response=slow;n.writer.response_wait=.02
    body={'user_id':USER,'app_id':APP,'memory_id':n.source,'request_id':'pending','expected_digest':main.memory_digest(n.memory.get(n.source)),'expected_revision':0}
    try:
        result=n.http.post('/memories/reviews/start',json=body,headers=n.headers);assert result.status_code==202
        # 202 acknowledges scheduling, not that Chroma lookup and model startup
        # have already happened. Synchronize the actual waiting-model boundary.
        assert started.wait(5)
        for _ in range(2):
            result=n.http.post('/memories/reviews/start',json=body,headers=n.headers);assert result.status_code==202
        assert started.is_set() and calls==[1]
        assert n.http.get('/health').status_code==200
        assert n.http.post('/memories/owned/list',json={'user_id':USER,'app_id':APP},headers=n.headers).status_code==200
        assert n.http.post('/memories/reviews/start',json={**body,'request_id':'new'},headers=n.headers).status_code==503
    finally:release.set();n.writer.future.result(timeout=3)


def test_executor_rejection_finishes_the_reserved_review_without_calling_the_model(native,monkeypatch):
    n=native
    def fail(*args,**kwargs):raise RuntimeError('fixture executor closed')
    monkeypatch.setattr(n.writer.executor,'submit',fail)
    body={'user_id':USER,'app_id':APP,'memory_id':n.source,'request_id':'rejected','expected_digest':main.memory_digest(n.memory.get(n.source)),'expected_revision':0}
    result=n.http.post('/memories/reviews/start',json=body,headers=n.headers)
    assert result.status_code==503 and not n.calls
    assert n.writer.reviews.row(USER,APP,'rejected')['status']=='FAILED'
    assert n.writer.write_lock.acquire(blocking=False)
    n.writer.write_lock.release()


def test_real_sdk_usage_is_recorded_once_with_reported_zero_and_unknown_kept_distinct(native):
    import http.server
    import openai
    from mem0.llms.openai import OpenAILLM
    n=native;requests=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            candidates=json.loads(body['messages'][1]['content'])['candidates']
            result={'id':'fixture','object':'chat.completion','created':1,'model':'fixture','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps({'labels':[{'id':row['id'],'label':'RELATED'} for row in candidates]})}}],
                    'usage':{'prompt_tokens':17,'completion_tokens':0,'total_tokens':17}}
            payload=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def log_message(self,*args):pass
    http=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    client=openai.OpenAI(api_key='fixture',base_url=f'http://127.0.0.1:{http.server_port}/v1',max_retries=0,timeout=2)
    original=n.memory.llm.config.response_callback
    try:
        n.memory.llm.client=client;n.memory.llm.generate_response=OpenAILLM.generate_response.__get__(n.memory.llm,OpenAILLM)
        result=start(n);assert result['usageSource']=='PROVIDER' and result['inputTokens']==17 and result['outputTokens']==0 and result['totalTokens']==17
        assert result['modelCalled'] is True and result['modelMillis'] is not None
        assert n.memory.llm.config.response_callback is original
        assert n.memory.llm.client is client and client.timeout==2 and client.max_retries==0
        n.http.post('/memories/reviews/get',json={'user_id':USER,'app_id':APP,'request_id':'review'},headers=n.headers)
        assert len(requests)==1
    finally:client.close();http.shutdown();http.server_close();thread.join(timeout=2)


@pytest.mark.parametrize('setting',['0','61','nan','invalid'])
def test_manual_review_deadline_is_bounded_and_does_not_change_the_extraction_client(native,monkeypatch,setting):
    from memory_service.duplicate_review import review_request_budget
    original=native.memory.llm.client;monkeypatch.setenv('MEM0_DUPLICATE_REVIEW_TIMEOUT_SECONDS',setting)
    with pytest.raises(ValueError):
        with review_request_budget(native.memory.llm):raise AssertionError('Invalid timeout was accepted')
    assert native.memory.llm.client is original


def test_manual_review_budget_restores_the_same_client_after_error(native,monkeypatch):
    from memory_service.duplicate_review import review_request_budget
    monkeypatch.setenv('MEM0_DUPLICATE_REVIEW_TIMEOUT_SECONDS','30');original=native.memory.llm.client
    with pytest.raises(RuntimeError):
        with review_request_budget(native.memory.llm):
            assert native.memory.llm.client.timeout==30 and native.memory.llm.client.max_retries==0
            raise RuntimeError('fixture provider timeout')
    assert native.memory.llm.client is original and not original.is_closed()


def test_restart_retains_completed_review_and_marks_only_interrupted_jobs(native,tmp_path):
    from memory_service.write_receipts import MemoryWriter
    n=native;result=start(n);n.writer.reviews.reserve(USER,APP,'interrupted',n.source,main.memory_digest(n.memory.get(n.source)),0)
    directory=n.writer.fence.path;n.writer.close()
    restarted=MemoryWriter(directory,lambda:n.memory,threading.Lock())
    try:
        assert restarted.reviews.row(USER,APP,result['id'])['status']=='READY'
        assert restarted.reviews.row(USER,APP,'interrupted')['status']=='INTERRUPTED'
        assert len(n.calls)==1
    finally:restarted.close()
