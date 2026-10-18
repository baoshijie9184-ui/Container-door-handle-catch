"""Opt-in native production SDK/Chroma evaluation with real extraction and embedding on synthetic users only."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
STEPS=[('first','请记住我的明确长期偏好：所有检测报告默认导出为 PDF 格式。'),
       ('second','再确认一次，我所有检测报告的默认导出格式仍然是 PDF。'),
       ('third','请记住另一个长期偏好：我的检测报告标题统一使用蓝色。')]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--directory',required=True);args=parser.parse_args()
    directory=Path(args.directory).resolve()
    if not args.live:parser.error('Paid extraction/embedding calls require --live')
    if directory.exists() or not directory.is_relative_to((ROOT/'work').resolve()):parser.error('Use a new, project-owned work directory')
    directory.mkdir(parents=True,mode=0o700)
    os.environ.update({'MEM0_TELEMETRY':'false','ANONYMIZED_TELEMETRY':'false'})
    from mem0 import Memory  # Installed production SDK, rather than configured local development fork.
    from memory_service import main as bridge
    from memory_service.lifecycle import GovernedVectorStore,memory_digest
    from memory_service.write_receipts import MemoryWriter,CST
    from memory_service.duplicate_review import model_metrics
    import mem0.memory.main as sdk
    os.environ.update({'MEM0_DATA_DIR':str(directory),'MEM0_TELEMETRY':'false','ANONYMIZED_TELEMETRY':'false'})
    config=bridge.get_memory_config();config['vector_store']['config']['collection_name']='longitudinal_eval'
    memory=Memory.from_config(config);bridge.configure_provider_timeouts(memory)
    calls=[];embedding_calls=[];checks=[];steps=[]
    native_model=memory.llm.generate_response
    def generate(*a,**kw):
        if len(calls)>=3:raise RuntimeError('Live model request limit reached')
        metrics={};calls.append(metrics)
        try:
            with model_metrics(memory,metrics):return native_model(*a,**kw)
        except Exception as error:metrics['errorType']=type(error).__name__;raise
    memory.llm.generate_response=generate
    for method in ['embed','embed_batch']:
        original=getattr(memory.embedding_model,method)
        def bounded(*a,_method=method,_original=original,**kw):
            if len(embedding_calls)>=18:raise RuntimeError('Live embedding operation limit reached')
            if _method=='embed_batch' and len(a[0])>100:raise RuntimeError('Embedding input batch exceeds budget')
            started=time.monotonic();metrics={'operation':_method};embedding_calls.append(metrics)
            try:return _original(*a,**kw)
            except Exception as error:metrics['errorType']=type(error).__name__;raise
            finally:metrics['millis']=round((time.monotonic()-started)*1000)
        setattr(memory.embedding_model,method,bounded)
    writer=MemoryWriter(directory/'bridge_receipts',lambda:memory,threading.Lock())
    memory.vector_store=GovernedVectorStore(memory.vector_store,writer.lifecycle)
    user,app='doorhandlecatch:user:980001','doorhandlecatch';new_user='doorhandlecatch:user:980002'
    def rows():
        result=memory.vector_store.collection.get(where={'$and':[{'user_id':{'$eq':user}},{'agent_id':{'$eq':app}}]},include=['metadatas'])
        return [{'id':id,'memory':meta['data'],'session':meta.get('run_id')} for id,meta in zip(result['ids'],result['metadatas'])]
    def check(name,passed):checks.append({'name':name,'passed':bool(passed)})
    try:
        for index,(session,text) in enumerate(STEPS):
            before=len(calls);started=time.monotonic()
            receipt=writer.submit(user,app,session,text,{'source':'synthetic-eval','turn_id':index+1},'synthetic-turn-'+str(index+1))
            writer.future.result(timeout=90);receipt=writer.receipt(user,app,receipt['requestId'])
            saved=rows();steps.append({'session':session,'receipt':receipt,'memories':saved,'millis':round((time.monotonic()-started)*1000)})
            check('step '+session+' has a verified receipt',receipt['status']=='SUCCEEDED')
            check('step '+session+' has at most one extraction request',len(calls)-before<=1)
            if index==0:check('explicit PDF preference extracted',any('PDF' in r['memory'].upper() for r in saved));first_count=len(saved)
            if index==1:check('repeated preference in another session adds no duplicate',len(saved)==first_count and receipt['results']==[])
            count=len(calls);again=writer.submit(user,app,session,text,{'source':'synthetic-eval','turn_id':index+1},receipt['requestId'])
            check('step '+session+' replay preserves receipt and makes no new call',again==receipt and len(calls)==count)
            print(json.dumps({'session':session,'status':receipt['status'],'memoryCount':len(saved),'millis':steps[-1]['millis']}),flush=True)
        saved=rows();pdf=[r for r in saved if 'PDF' in r['memory'].upper()]
        check('independent title preference extracted',any('蓝' in r['memory'] or 'blue' in r['memory'].lower() for r in saved))
        # Deliberate human correction, not a second inference asking the model to rewrite unknown results.
        if len(pdf)==1:
            id=pdf[0]['id'];original=memory.get(id);memory.update(id,'用户明确纠正：所有检测报告的默认导出格式为 CSV，不再使用 PDF。')
            corrected=memory.get(id);check('explicit correction preserves source session and exact content',corrected['run_id']==original['run_id'] and corrected['memory'].startswith('用户明确纠正'))
            query='我的检测报告默认应该使用哪种文件格式'
            found=memory.search(query,filters={'user_id':user,'agent_id':app},top_k=10)
            check('new account session retrieves corrected memory',any(r['id']==id and 'CSV' in r['memory'] for r in found.get('results',[])))
            foreign=memory.search(query,filters={'user_id':new_user,'agent_id':app},top_k=10)
            check('another synthetic account sees none of this user history',foreign.get('results')==[])
            writer.lifecycle.change(user,app,id,0,memory_digest(corrected),'EXCLUDED',None,False)
            found=memory.search(query,filters={'user_id':user,'agent_id':app},top_k=10)
            check('excluded corrected memory no longer returned',all(r['id']!=id for r in found.get('results',[])))
            expiry=(datetime.now(CST)-timedelta(seconds=1)).isoformat(timespec='microseconds')
            writer.lifecycle.change(user,app,id,1,memory_digest(corrected),'ACTIVE',expiry,False)
            found=memory.search(query,filters={'user_id':user,'agent_id':app},top_k=10)
            check('expired memory remains stored but is not retrieved',memory.get(id) is not None and all(r['id']!=id for r in found.get('results',[])))
        else:check('one unambiguous PDF record is available for controlled correction',False)
    except Exception as error:
        steps.append({'errorType':type(error).__name__});check('evaluation finished without unknown internal interruption',False)
    finally:writer.close()
    result={'at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'datasetVersion':2,'sdkSource':sdk.__file__,'mode':'real configured extraction and embedding, private synthetic users',
            'modelCalls':calls,'embeddingOperations':embedding_calls,'steps':steps,'checks':checks,'passed':all(c['passed'] for c in checks),'existingUserDataTouched':False,
            'limits':{'modelCalls':3,'embeddingOperations':18,'retryCount':0},'scope':'one bounded multi-session sequence; not weeks of longitudinal quality or production deployment'}
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'passed':sum(c['passed'] for c in checks),'allPassed':result['passed'],'modelCalls':len(calls),'embeddingOperations':len(embedding_calls)}))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
