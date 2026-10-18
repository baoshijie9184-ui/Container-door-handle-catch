"""Explicit isolated native bridge for opt-in Java/MySQL integration; all model responses are scripted."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory',required=True);parser.add_argument('--port',type=int,default=18091)
args=parser.parse_args();directory=Path(args.directory).resolve()
if not directory.is_relative_to((ROOT/'work').resolve()) or directory.exists():raise RuntimeError('Use a new, project-owned work directory')
directory.mkdir(parents=True,mode=0o700);os.environ.update({'MEM0_TELEMETRY':'false','ANONYMIZED_TELEMETRY':'false'})
from mem0 import Memory  # Select the installed production SDK before local source-path configuration.
from memory_service import main
from memory_service.lifecycle import GovernedVectorStore
from memory_service.write_receipts import MemoryWriter
import mem0.memory.main as sdk
import secrets
sdk.capture_event=lambda *a,**k:None;sdk.lemmatize_for_bm25=lambda text:text;sdk.extract_entities_batch=lambda texts:[[] for _ in texts]
token=secrets.token_hex(32);os.environ.update({'MEM0_BRIDGE_TOKEN':token,'MEM0_DUPLICATE_REVIEW_ENABLED':'true'})
memory=Memory.from_config({
    'llm':{'provider':'openai','config':{'api_key':'fixture','model':'fixture','openai_base_url':'http://127.0.0.1:1/v1'}},
    'embedder':{'provider':'openai','config':{'api_key':'fixture','model':'fixture','embedding_dims':4,'openai_base_url':'http://127.0.0.1:1/v1'}},
    'vector_store':{'provider':'chroma','config':{'path':str(directory/'chroma'),'collection_name':'review_integration'}},'history_db_path':str(directory/'history.sqlite3')})
memory.embedding_model.embed=lambda *a,**k:[.1,.2,.3,.4]
memory.embedding_model.embed_batch=lambda texts,*a,**k:[[.1,.2,.3,.4] for _ in texts]
main.memory_instance=memory;writer=MemoryWriter(directory/'receipts',lambda:memory,threading.Lock())
main.memory_writer=writer;main.memory_write_lock=writer.write_lock
memory.vector_store=GovernedVectorStore(memory.vector_store,writer.lifecycle)
def model(**kwargs):
    body=json.loads(kwargs['messages'][1]['content'])
    return json.dumps({'labels':[{'id':r['id'],'label':'DUPLICATE'} for r in body['candidates']]})
memory.llm.generate_response=model
cases={}
for index,name in enumerate(['normal','unknown','stale','concurrent','audit']):
    owner=970001+index
    def add(text,session):return memory.add(text,user_id='doorhandlecatch:user:'+str(owner),agent_id='doorhandlecatch',run_id=session,infer=False)['results'][0]['id']
    cases[name]={'ownerId':owner,'sourceId':add('报告默认采用 PDF 格式','first'),'candidateId':add('用户喜欢 PDF 报告','second')}
manifest={'bridgeUrl':'http://127.0.0.1:'+str(args.port),'bridgeToken':token,'cases':cases,'sdkSource':sdk.__file__,'providerMode':'scripted'}
path=directory/'bridge.json';path.write_text(json.dumps(manifest),encoding='utf-8');os.chmod(path,0o600)
print(json.dumps({'directory':str(directory),'port':args.port,'cases':list(cases),'paidModelCalls':False}),flush=True)
try:
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=args.port,lifespan='off',log_level='warning')
finally:writer.close()
