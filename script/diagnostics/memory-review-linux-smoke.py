"""Run only in an isolated, offline Linux container with /tmp storage; never mount production volumes."""
import json
import os
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
if sys.platform!='linux' or os.getenv('DOORHANDLE_ISOLATED_SMOKE')!='yes':raise RuntimeError('An explicitly isolated Linux test container is required')
from memory_service import main
from memory_service.lifecycle import GovernedVectorStore
from memory_service.write_receipts import MemoryWriter
from mem0 import Memory
import mem0.memory.main as sdk

sdk.capture_event=lambda *a,**k:None
sdk.lemmatize_for_bm25=lambda text:text
sdk.extract_entities_batch=lambda texts:[[] for _ in texts]
memory=Memory.from_config({
    'llm':{'provider':'openai','config':{'api_key':'fixture','model':'fixture','openai_base_url':'http://127.0.0.1:1/v1'}},
    'embedder':{'provider':'openai','config':{'api_key':'fixture','model':'fixture','embedding_dims':4,'openai_base_url':'http://127.0.0.1:1/v1'}},
    'vector_store':{'provider':'chroma','config':{'path':'/tmp/review-smoke/chroma','collection_name':'review_smoke'}},'history_db_path':'/tmp/review-smoke/history.sqlite3'})
memory.embedding_model.embed=lambda *a,**k:[.1,.2,.3,.4]
memory.embedding_model.embed_batch=lambda texts,*a,**k:[[.1,.2,.3,.4] for _ in texts]
writer=MemoryWriter('/tmp/review-smoke/receipts',lambda:memory,threading.Lock())
memory.vector_store=GovernedVectorStore(memory.vector_store,writer.lifecycle)
user,app='doorhandlecatch:user:42','doorhandlecatch';calls=[];checks=[]
def model(**kwargs):
    calls.append(1);body=json.loads(kwargs['messages'][1]['content'])
    return json.dumps({'labels':[{'id':r['id'],'label':'DUPLICATE'} for r in body['candidates']]})
memory.llm.generate_response=model
def add(text,session,owner=user):return memory.add(text,user_id=owner,agent_id=app,run_id=session,infer=False)['results'][0]['id']
def project(row):return {'id':row['id'],'memory':row['memory'],'sourceSessionId':row.get('run_id')}
source=add('报告默认采用 PDF 格式','one');candidate=add('用户喜欢 PDF 报告','two');foreign=add('PRIVATE_OTHER_ACCOUNT','two','doorhandlecatch:user:43')
try:
    result=writer.submit_review(user,app,'review',source,main.memory_digest(memory.get(source)),0,project)
    writer.future.result(timeout=5)
    result=writer.reviews.public(memory,user,app,'review',project)
    assert result['status']=='READY' and [p['id'] for p in result['candidates']]==[candidate]
    assert result['source']['sourceSessionId']=='one' and result['candidates'][0]['item']['sourceSessionId']=='two'
    assert foreign not in json.dumps(result);checks.append('Native Chroma cross-session review and account isolation')
    writer.reviews.resolve(memory,user,app,'review','decision',1,candidate,'KEEP_SOURCE')
    writer.reviews.resolve(memory,user,app,'review','decision',1,candidate,'KEEP_SOURCE')
    assert writer.lifecycle.public(user,app,candidate)['revision']==1 and memory.get(candidate)['memory']=='用户喜欢 PDF 报告'
    assert memory.vector_store.search(query='report',vectors=[.1,.2,.3,.4],top_k=5,filters={'user_id':user,'agent_id':app})[0].id==source
    assert not writer.lifecycle.allowed(user,app,candidate);checks.append('Idempotent audited exclusion preserves content and filters search')
    memory.update(source,'纠正后的 CSV 报告');assert memory.get(source)['memory']=='纠正后的 CSV 报告'
    assert writer.reviews.public(memory,user,app,'review',project)['sourceStale'];checks.append('Native update signature and stale review rejection')
    memory.delete(source);assert memory.get(source) is None;checks.append('Deleted native Chroma ID is independently confirmed absent')
finally:writer.close()
restarted=MemoryWriter('/tmp/review-smoke/receipts',lambda:memory,threading.Lock())
try:
    assert restarted.reviews.row(user,app,'review')['revision']==2 and not restarted.lifecycle.allowed(user,app,candidate)
    assert len(calls)==1;checks.append('Linux flock and SQLite WAL survive writer restart without replay')
finally:restarted.close()
print(json.dumps({'platform':sys.platform,'checks':checks,'passed':len(checks),'memorySdk':sdk.__file__,'existingVolumeMounted':False,'providerMode':'scripted, offline'},ensure_ascii=False))
