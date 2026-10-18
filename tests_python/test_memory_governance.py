import copy
from types import SimpleNamespace
from fastapi.testclient import TestClient
from memory_service import main


class FakeMemory:
    def __init__(self):
        self.rows={
            'mine':{'id':'mine','user_id':'doorhandlecatch:user:42','agent_id':'doorhandlecatch','run_id':'sess_one','memory':'本人报告偏好','updated_at':'2026-10-13T12:00:00Z'},
            'other':{'id':'other','user_id':'doorhandlecatch:user:43','agent_id':'doorhandlecatch','memory':'OTHER_PRIVATE_MEMORY'},
            'other-app':{'id':'other-app','user_id':'doorhandlecatch:user:42','agent_id':'another-app','memory':'OTHER_APP_PRIVATE_MEMORY'},
        }
        self.filters=None;self.deleted=[];self.updated=[]
        self.vector_store=SimpleNamespace(collection=self)
    def get(self,id=None,**kwargs):
        if not kwargs:return copy.deepcopy(self.rows.get(id))
        self.filters={key:condition['$eq'] for clause in kwargs['where']['$and'] for key,condition in clause.items()}
        rows=[r for r in self.rows.values() if all(r.get(k)==v for k,v in self.filters.items())]
        rows=rows[kwargs['offset']:kwargs['offset']+kwargs['limit']]
        return {'ids':[r['id'] for r in rows],'metadatas':[{**r,'data':r['memory']} for r in rows]}
    def get_all(self,**kwargs):
        self.filters=kwargs['filters'];return {'results':list(self.rows.values())}
    def delete(self,id):self.deleted.append(id);self.rows.pop(id)
    def update(self,id,text):
        self.updated.append((id,text));self.rows[id]['memory']=text;self.rows[id]['updated_at']='2026-10-14T16:00:00Z'


def client(monkeypatch):
    fake=FakeMemory();monkeypatch.setattr(main,'memory_instance',fake)
    monkeypatch.setenv('MEM0_BRIDGE_TOKEN','fixture-bridge-token')
    return TestClient(main.app),fake,{'X-Doorhandle-Memory-Token':'fixture-bridge-token'}


def test_private_bridge_auth_and_health(monkeypatch):
    http,fake,headers=client(monkeypatch)
    payload={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch'}
    assert http.post('/memories/owned/list',json=payload).status_code==401
    assert http.post('/memories/owned/list',json=payload,headers={'X-Doorhandle-Memory-Token':'wrong'}).status_code==401
    assert fake.filters is None
    assert http.get('/health').status_code==200
    monkeypatch.delenv('MEM0_BRIDGE_TOKEN')
    assert http.post('/memories/owned/list',json=payload,headers=headers).status_code==503


def test_listing_filters_owner_app_and_hides_raw_metadata(monkeypatch):
    http,fake,headers=client(monkeypatch)
    response=http.post('/memories/owned/list',json={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch','limit':20},headers=headers)
    assert response.status_code==200
    assert fake.filters=={'user_id':'doorhandlecatch:user:42','agent_id':'doorhandlecatch'}
    data=response.json()['data'];assert len(data['items'])==1
    assert data['items'][0]['digest']==main.memory_digest(fake.rows['mine'])
    assert 'OTHER_PRIVATE_MEMORY' not in response.text and 'OTHER_APP_PRIVATE_MEMORY' not in response.text
    assert 'user_id' not in data['items'][0] and 'metadata' not in data['items'][0]


def test_foreign_missing_and_stale_versions_do_not_delete(monkeypatch):
    http,fake,headers=client(monkeypatch)
    base={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch','expected_digest':'a'*64}
    for id in ('other','missing','other-app'):
        result=http.post('/memories/owned/delete',json={**base,'memory_id':id},headers=headers)
        assert result.status_code==404 and 'PRIVATE' not in result.text
    stale=http.post('/memories/owned/delete',json={**base,'memory_id':'mine'},headers=headers)
    assert stale.status_code==409 and fake.deleted==[]
    approved=http.post('/memories/owned/delete',json={**base,'memory_id':'mine','expected_digest':main.memory_digest(fake.rows['mine'])},headers=headers)
    assert approved.status_code==200 and approved.json()['data']['deleted'] is True
    assert fake.deleted==['mine']


def test_unscoped_endpoints_retired_and_invalid_scope_rejected(monkeypatch):
    http,fake,headers=client(monkeypatch)
    assert http.get('/memories/doorhandlecatch:user:42',headers=headers).status_code==410
    assert http.delete('/memories/mine',headers=headers).status_code==410
    assert http.delete('/memories/user/doorhandlecatch:user:42',headers=headers).status_code==410
    for overrides in ({'user_id':'global'},{'app_id':'another-app'},{'limit':101}):
        body={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch',**overrides}
        assert http.post('/memories/owned/list',json=body,headers=headers).status_code==422
    assert fake.deleted==[]


def test_pages_cross_old_100_record_limit_without_foreign_leaks(monkeypatch):
    http,fake,headers=client(monkeypatch)
    original=fake.rows['mine']
    fake.rows={str(i):{**original,'id':str(i),'memory':f'记忆 {i}'} for i in range(125)}|{'foreign':fake.rows['other']}
    collected=[];offset=0
    while True:
        response=http.post('/memories/owned/list',json={'user_id':original['user_id'],'app_id':original['agent_id'],'limit':50,'offset':offset},headers=headers)
        assert response.status_code==200
        data=response.json()['data'];collected.extend(row['id'] for row in data['items'])
        assert 'OTHER_PRIVATE_MEMORY' not in response.text
        if not data['hasMore']:assert data['nextOffset'] is None;break
        assert data['nextOffset']==offset+50;offset=data['nextOffset']
    assert len(collected)==125 and len(set(collected))==125
    assert http.post('/memories/owned/list',json={'user_id':original['user_id'],'app_id':original['agent_id'],'offset':-1},headers=headers).status_code==422


def test_owned_read_and_update_require_owner_app_and_current_version(monkeypatch):
    http,fake,headers=client(monkeypatch)
    scope={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch'}
    for id in ('other','other-app','missing'):
        assert http.post('/memories/owned/get',json={**scope,'memory_id':id},headers=headers).status_code==404
        result=http.post('/memories/owned/update',json={**scope,'memory_id':id,'expected_digest':'a'*64,'memory':'新偏好'},headers=headers)
        assert result.status_code==404 and 'PRIVATE' not in result.text
    read=http.post('/memories/owned/get',json={**scope,'memory_id':'mine'},headers=headers)
    old=read.json()['data'];assert 'metadata' not in old
    payload={**scope,'memory_id':'mine','expected_digest':old['digest'],'memory':'  本人按月统计  '}
    assert http.post('/memories/owned/update',json=payload).status_code==401
    assert http.post('/memories/owned/update',json={**payload,'expected_digest':'a'*64},headers=headers).status_code==409
    assert fake.updated==[]
    saved=http.post('/memories/owned/update',json=payload,headers=headers)
    assert saved.status_code==200 and saved.json()['data']['updated']
    new=http.post('/memories/owned/get',json={**scope,'memory_id':'mine'},headers=headers).json()['data']
    assert new['memory']=='本人按月统计' and new['digest']!=old['digest'] and new['sourceSessionId']==old['sourceSessionId']
    assert http.post('/memories/owned/update',json=payload,headers=headers).status_code==409
    assert http.post('/memories/owned/delete',json={k:v for k,v in payload.items() if k!='memory'},headers=headers).status_code==409
    assert fake.updated==[('mine','本人按月统计')] and fake.deleted==[]


def test_edit_validation_and_unknown_outcome_do_not_leak_private_text(monkeypatch):
    http,fake,headers=client(monkeypatch)
    payload={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch','memory_id':'mine','expected_digest':main.memory_digest(fake.rows['mine'])}
    for content in ('','  \n  ','x'*4001):
        assert http.post('/memories/owned/update',json={**payload,'memory':content},headers=headers).status_code==422
    def unavailable(*args,**kwargs):raise RuntimeError('PRIVATE_TEXT_INTERNAL_CREDENTIAL')
    monkeypatch.setattr(fake,'update',unavailable)
    response=http.post('/memories/owned/update',json={**payload,'memory':'新正文'},headers=headers)
    assert response.status_code==503 and 'PRIVATE_TEXT' not in response.text


def test_chroma_paging_digest_matches_native_mem0_get_and_update(monkeypatch,caplog):
    """Real Chroma + native read/update, with isolated embedder/history and no LLM."""
    import chromadb
    from mem0 import Memory
    from mem0.vector_stores.chroma import ChromaDB
    import mem0.memory.main as native_main
    monkeypatch.setattr(native_main,'capture_event',lambda *a,**k:None)
    if hasattr(native_main,'display_first_run_notice'):
        monkeypatch.setattr(native_main,'display_first_run_notice',lambda *a,**k:None)
    monkeypatch.setattr(native_main,'extract_entities',lambda *a:[])
    monkeypatch.setattr(native_main,'lemmatize_for_bm25',lambda text:text)
    memory=Memory.__new__(Memory)
    embeddings=[];history=[]
    memory.embedding_model=SimpleNamespace(embed=lambda text,action:embeddings.append((text,action)) or [0.5,0.5])
    memory.db=SimpleNamespace(add_history=lambda *a,**k:history.append(a))
    memory._entity_store=None
    memory.vector_store=ChromaDB('memory_pagination_test',client=chromadb.EphemeralClient())
    memory.vector_store.insert(vectors=[[1.,0.],[0.,1.]],ids=['mine','foreign'],payloads=[
        {'data':'本人正文','user_id':'doorhandlecatch:user:42','agent_id':'doorhandlecatch','run_id':'original-session','created_at':'2026-10-13T12:00:00Z','updated_at':'2026-10-14T12:00:00Z'},
        {'data':'OTHER_PRIVATE_MEMORY','user_id':'doorhandlecatch:user:43','agent_id':'doorhandlecatch'}])
    http,_,headers=client(monkeypatch);monkeypatch.setattr(main,'memory_instance',memory)
    scope={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch'}
    listed=http.post('/memories/owned/list',json=scope,headers=headers)
    assert listed.status_code==200 and 'OTHER_PRIVATE_MEMORY' not in listed.text
    read=http.post('/memories/owned/get',json={**scope,'memory_id':'mine'},headers=headers)
    assert read.status_code==200 and read.json()['data']==listed.json()['data']['items'][0]
    payload={**scope,'memory_id':'mine','expected_digest':read.json()['data']['digest'],'memory':'PRIVATE_EDIT_BODY'}
    with caplog.at_level('INFO'):
        saved=http.post('/memories/owned/update',json=payload,headers=headers)
    assert saved.status_code==200 and saved.json()['data']['updated']
    assert embeddings==[('PRIVATE_EDIT_BODY','update')] and len(history)==1
    assert memory.get('mine')['memory']=='PRIVATE_EDIT_BODY' and memory.get('mine')['run_id']=='original-session'
    assert 'PRIVATE_EDIT_BODY' not in caplog.text
    listed=http.post('/memories/owned/list',json=scope,headers=headers).json()['data']['items'][0]
    assert listed['digest']==main.memory_digest(memory.get('mine')) and listed['digest']!=payload['expected_digest']
    assert http.post('/memories/owned/update',json=payload,headers=headers).status_code==409


def test_server_data_directory_keeps_vector_and_history_together(monkeypatch,tmp_path):
    for key in ('DASHSCOPE_API_KEY','EMBEDDING_API_KEY'):monkeypatch.setenv(key,'fixture-not-a-real-key')
    monkeypatch.setenv('MEM0_DATA_DIR',str(tmp_path/'memory-volume'))
    config=main.get_memory_config()
    assert config['vector_store']['config']['path']==str(tmp_path/'memory-volume'/'chroma')
    assert config['history_db_path']==str(tmp_path/'memory-volume'/'history.db')


def test_production_llm_constructor_accepts_generated_config_without_a_paid_request(monkeypatch,tmp_path):
    import inspect
    from mem0.configs.llms.openai import OpenAIConfig
    from mem0.utils.factory import LlmFactory
    for key in ('DASHSCOPE_API_KEY','EMBEDDING_API_KEY'):monkeypatch.setenv(key,'fixture-not-a-real-key')
    monkeypatch.setenv('MEM0_DATA_DIR',str(tmp_path/'config-probe'))
    for model in ['kimi-k3','kimi-k2.7-code','fixture-regular']:
        monkeypatch.setenv('MEM0_LLM_MODEL',model)
        config=main.get_memory_config()['llm']['config']
        if model.startswith('kimi-'):assert config['temperature']==1.0 and config['top_p']==0.95
        else:assert 'temperature' not in config and 'top_p' not in config
        assert ('is_reasoning_model' in config)==('is_reasoning_model' in inspect.signature(OpenAIConfig).parameters)
        client=LlmFactory.create('openai',config)
        try:assert client.config.model==config['model']
        finally:client.client.close()
