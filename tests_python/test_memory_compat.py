"""Deployment protocol exercises; native SQLite probes and a stateful Docker protocol substitute."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import tarfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from memory_service import main
from memory_service.write_receipts import MemoryWriter
from tests_python.test_memory_governance import FakeMemory

SPEC=importlib.util.spec_from_file_location('memory_compat',Path(__file__).resolve().parents[1]/'script/docker/memory-compat.py')
guard=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(guard)
OLD='sha256:'+'a'*64;NEW='sha256:'+'b'*64
BACKEND='c'*64;MEMORY='d'*64;REPLACED='e'*64


def probe(path):
    return subprocess.run([sys.executable,'-B','-c',guard.PROBE],env={**os.environ,'MEM0_DATA_DIR':str(path)},capture_output=True,text=True,timeout=8)


def test_real_sqlite_floor_tracks_committed_receipts_and_lifecycle_changes(tmp_path):
    directory=tmp_path/'data';directory.mkdir()
    assert json.loads(probe(directory).stdout)['requiredProtocol']==0
    writer=MemoryWriter(directory/'bridge_receipts',lambda:None,threading.Lock())
    try:
        assert json.loads(probe(directory).stdout)['requiredProtocol']==0
        writer.store.reserve('user','app','id','digest',120)
        assert json.loads(probe(directory).stdout)['requiredProtocol']==1
        writer.lifecycle.change('user','app','memory',0,'a'*64,'EXCLUDED',None,False)
        assert json.loads(probe(directory).stdout)['requiredProtocol']==2
        with writer.store.connect() as db:
            db.execute('DELETE FROM memory_write_receipt');db.execute('DELETE FROM memory_lifecycle');db.execute('DELETE FROM memory_cleanup_event');db.commit()
        assert json.loads(probe(directory).stdout)['requiredProtocol']==2
    finally:writer.close()


def test_probe_reads_uncheckpointed_wal_instead_of_ignoring_it(tmp_path):
    directory=tmp_path/'data';store=directory/'bridge_receipts';store.mkdir(parents=True)
    db=sqlite3.connect(store/'write-receipts.sqlite3')
    try:
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA wal_autocheckpoint=0');db.execute('CREATE TABLE memory_write_receipt(id TEXT)');db.execute('CREATE TABLE memory_lifecycle(memory_id TEXT)');db.commit()
        db.execute("INSERT INTO memory_lifecycle VALUES('private-id')");db.commit()
        originals={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in store.iterdir()}
        result=probe(directory)
        assert result.returncode==0 and json.loads(result.stdout)['requiredProtocol']==2
        assert 'private-id' not in result.stdout
        assert originals=={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in store.iterdir()}
    finally:db.close()


def test_probe_rejects_storage_larger_than_its_bounded_scratch(tmp_path):
    directory=tmp_path/'data';store=directory/'bridge_receipts';store.mkdir(parents=True)
    with (store/'write-receipts.sqlite3').open('wb') as stream:stream.truncate(192*1024*1024+1)
    result=probe(directory)
    assert result.returncode!=0 and 'cannot be verified' in result.stderr


def test_probe_can_infer_existing_tables_without_a_floor_marker_and_rejects_corruption(tmp_path):
    directory=tmp_path/'data';store=directory/'bridge_receipts';store.mkdir(parents=True);file=store/'write-receipts.sqlite3'
    with sqlite3.connect(file) as db:db.execute('CREATE TABLE memory_write_receipt(id TEXT)');db.execute("INSERT INTO memory_write_receipt VALUES('id')")
    assert json.loads(probe(directory).stdout)['requiredProtocol']==1
    file.write_bytes(b'not a SQLite database PRIVATE_FAILURE')
    result=probe(directory);assert result.returncode!=0 and 'PRIVATE_FAILURE' not in result.stderr


def test_bridge_rejects_future_protocol_before_recovering_or_changing_rows(tmp_path):
    directory=tmp_path/'data';writer=MemoryWriter(directory/'bridge_receipts',lambda:None,threading.Lock())
    writer.store.reserve('user','app','id','digest',120)
    with writer.store.connect() as db:db.execute('UPDATE bridge_protocol_floor SET required_version=3');db.commit()
    writer.close()
    assert json.loads(probe(directory).stdout)['requiredProtocol']==3
    with pytest.raises(ValueError,match='newer bridge'):MemoryWriter(directory/'bridge_receipts',lambda:None,threading.Lock())
    with sqlite3.connect(directory/'bridge_receipts'/'write-receipts.sqlite3') as db:
        assert db.execute('SELECT status FROM memory_write_receipt').fetchone()[0]=='RUNNING'


@pytest.mark.parametrize('damage',['missing','truncated','dropped_controls'])
def test_lost_or_incomplete_existing_journal_never_becomes_an_empty_legacy_store(tmp_path,damage):
    directory=tmp_path/'data';writer=MemoryWriter(directory/'bridge_receipts',lambda:None,threading.Lock())
    writer.lifecycle.change('user','app','memory',0,'a'*64,'EXCLUDED',None,False);writer.close()
    file=directory/'bridge_receipts'/'write-receipts.sqlite3'
    if damage=='missing':file.unlink()
    elif damage=='truncated':file.write_bytes(b'')
    else:
        with sqlite3.connect(file) as db:db.execute('DROP TABLE memory_lifecycle')
    assert probe(directory).returncode!=0
    with pytest.raises(ValueError):MemoryWriter(directory/'bridge_receipts',lambda:None,threading.Lock())
    if damage=='missing':assert not file.exists()


class Docker:
    def __init__(self, volume, *, floor=2,current=2,target=0):
        self.volume,self.floor,self.calls=volume,floor,[]
        self.protocols={OLD:target,NEW:current}
        self.rows={BACKEND:self.row(BACKEND,'backend',OLD),MEMORY:self.row(MEMORY,'mem0',NEW)}
        self.health_protocol=current;self.probe_failed=False
    def row(self,id,service,image):
        return {'Id':id,'Image':image,'State':{'Running':True,'Health':{'Status':'healthy'}},'Config':{'Env':['MEM0_DATA_DIR=/data','PRIVATE_TOKEN=must-not-be-copied'],
                'Labels':{'com.docker.compose.project':guard.PROJECT,'com.docker.compose.service':service}},
                'Mounts':[{'Type':'volume','Name':'project-memory','Destination':'/data'}]}
    def __call__(self,*args,**kwargs):
        self.calls.append(args)
        if args[0]=='ps':
            service=args[-1].split('=')[-1]
            ids=[k for k,v in self.rows.items() if v['Config']['Labels']['com.docker.compose.service']==service]
            return ('\n'.join(ids if '--no-trunc' in args else [value[:12] for value in ids])).encode()
        if args[0]=='inspect':return json.dumps([self.rows[args[1]]]).encode()
        if args[:2]==('image','inspect'):
            return json.dumps([{'Id':args[2],'Config':{'Labels':{guard.LABEL:str(self.protocols[args[2]])}}}]).encode()
        if args[0]=='stop':self.rows[args[-1]]['State']['Running']=False;return b''
        if args[0]=='start':self.rows[args[1]]['State']['Running']=True;return b''
        if args[0]=='run':
            assert not self.rows[BACKEND]['State']['Running'] and not self.rows[MEMORY]['State']['Running']
            assert args[args.index('--network')+1]=='none' and '--read-only' in args and '--pull' in args
            assert args[args.index('--tmpfs')+1]=='/tmp:rw,nosuid,nodev,noexec,size=256m'
            assert args[args.index('--memory')+1]=='384m' and args[args.index('--pids-limit')+1]=='64'
            assert args[args.index('--mount')+1]=='type=volume,src=project-memory,dst=/data,readonly'
            assert not any('PRIVATE_TOKEN' in str(arg) for arg in args)
            if self.probe_failed:raise guard.GuardError('probe failed')
            return json.dumps({'requiredProtocol':self.floor}).encode()
        if args[0]=='exec':return json.dumps({'status':'ok','memory_protocol':self.health_protocol,'write_receipts':True,'lifecycle':True,'bridge_auth_configured':True}).encode()
        raise AssertionError(args)


def test_legacy_target_preserves_exact_compatible_container_and_configuration(tmp_path,monkeypatch):
    docker=Docker(tmp_path);monkeypatch.setattr(guard,'docker',docker)
    original=copy.deepcopy(docker.rows[MEMORY]['Config'])
    assert guard.prepare(tmp_path,{'services':{'mem0':{'image':OLD}}})=='preserve'
    assert docker.rows[MEMORY]['State']['Running'] and not docker.rows[BACKEND]['State']['Running']
    assert docker.rows[MEMORY]['Config']==original
    guard.verify(tmp_path)
    record=json.loads((tmp_path/'memory-transition.json').read_text());assert record['phase']=='VERIFIED' and record['preserved']
    assert (tmp_path/'memory-activation-images.yml').read_text().endswith(NEW+'\n')
    assert record['createdAt'].endswith('+08:00')


def test_compatible_target_replaces_bridge_before_backend_may_resume(tmp_path,monkeypatch):
    docker=Docker(tmp_path,target=2);monkeypatch.setattr(guard,'docker',docker)
    assert guard.prepare(tmp_path,{'services':{'mem0':{'image':OLD}}})=='replace'
    assert not docker.rows[MEMORY]['State']['Running'] and not docker.rows[BACKEND]['State']['Running']
    docker.rows.pop(MEMORY);docker.rows[REPLACED]=docker.row(REPLACED,'mem0',OLD);docker.health_protocol=2
    guard.verify(tmp_path)
    assert json.loads((tmp_path/'memory-transition.json').read_text())['phase']=='VERIFIED'


def test_empty_volume_allows_legacy_rollback_but_persisted_floor_never_decreases(tmp_path,monkeypatch):
    docker=Docker(tmp_path,floor=0,current=2,target=0);monkeypatch.setattr(guard,'docker',docker)
    assert guard.prepare(tmp_path,{'services':{'mem0':{'image':OLD}}})=='replace'
    guard.write_json(tmp_path/'memory-minimum.json',{'requiredProtocol':2,'dataMount':{'name':'project-memory','destination':'/data'}})
    assert guard.prepare(tmp_path,{'services':{'mem0':{'image':OLD}}})=='preserve'
    assert json.loads((tmp_path/'memory-minimum.json').read_text())['requiredProtocol']==2


@pytest.mark.parametrize('fault',['probe','no_compatible_image','changed_volume','lying_health','changed_identity','backend_resumed'])
def test_unsafe_recovery_never_resumes_backend_or_accepts_an_unverified_bridge(tmp_path,monkeypatch,fault):
    docker=Docker(tmp_path,current=0 if fault=='no_compatible_image' else 2);monkeypatch.setattr(guard,'docker',docker)
    if fault=='probe':docker.probe_failed=True
    if fault in ['probe','no_compatible_image']:
        with pytest.raises(guard.GuardError):guard.prepare(tmp_path,{'services':{'mem0':{'image':OLD}}})
        assert not docker.rows[BACKEND]['State']['Running'] and not docker.rows[MEMORY]['State']['Running']
        assert json.loads((tmp_path/'memory-transition.json').read_text())['phase']=='FAILED'
        return
    guard.prepare(tmp_path,{'services':{'mem0':{'image':OLD}}})
    if fault=='changed_volume':docker.rows[MEMORY]['Mounts'][0]['Name']='different-memory'
    if fault=='lying_health':docker.health_protocol=0
    if fault=='changed_identity':docker.rows[REPLACED]=docker.rows.pop(MEMORY);docker.rows[REPLACED]['Id']=REPLACED
    if fault=='backend_resumed':docker.rows[BACKEND]['State']['Running']=True
    with pytest.raises(guard.GuardError):guard.verify(tmp_path,timeout=0)
    assert json.loads((tmp_path/'memory-transition.json').read_text())['phase']!='VERIFIED'
    assert not docker.rows[BACKEND]['State']['Running']


def test_protocol_negotiation_keeps_legacy_dtos_and_filters_private_retrieval(monkeypatch,isolate_memory_receipts):
    fake=FakeMemory();monkeypatch.setattr(main,'memory_instance',fake);monkeypatch.setenv('MEM0_BRIDGE_TOKEN','fixture')
    isolate_memory_receipts.lifecycle.change('doorhandlecatch:user:42','doorhandlecatch','mine',0,main.memory_digest(fake.rows['mine']),'EXCLUDED',None,False)
    http=TestClient(main.app);body={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch'};headers={'X-Doorhandle-Memory-Token':'fixture'}
    for version in ['0','1','2']:
        response=http.post('/memories/owned/list',json=body,headers={**headers,'X-Doorhandle-Memory-Protocol':version})
        item=response.json()['data']['items'][0]
        assert ('lifecycle' in item)==(version=='2')
        assert set(item)-{'lifecycle'}=={'id','memory','sourceSessionId','createdAt','updatedAt','digest'}
    fake.search=lambda *args,**kwargs:{'results':[{'id':'mine','memory':'not for the assistant'}]}
    response=http.post('/memories/search',json={**body,'run_id':'s','query':'报告','scope':'ACCOUNT'},headers=headers)
    assert response.json()['data']==[]


def test_legacy_pending_write_is_not_a_success_and_reconnect_does_not_replay(monkeypatch,isolate_memory_receipts):
    release=threading.Event();calls=[]
    def slow(*args,**kwargs):calls.append(1);assert release.wait(3);return {'results':[]}
    monkeypatch.setattr(main,'memory_instance',SimpleNamespace(add=slow));monkeypatch.setenv('MEM0_BRIDGE_TOKEN','fixture');isolate_memory_receipts.response_wait=.02
    http=TestClient(main.app);body={'user_id':'doorhandlecatch:user:42','app_id':'doorhandlecatch','run_id':'s','content':'private'};headers={'X-Doorhandle-Memory-Token':'fixture'}
    try:
        for _ in range(2):
            response=http.post('/memories/add',json=body,headers=headers)
            assert response.status_code==503 and response.headers.get('X-Memory-Operation-Started')=='true'
        assert calls==[1]
    finally:release.set();isolate_memory_receipts.future.result(timeout=2)
    assert http.post('/memories/add',json=body,headers=headers).status_code==200 and calls==[1]


def native_write(path,value):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    path.write_bytes(raw);path.chmod(0o600)
    return hashlib.sha256(raw).hexdigest()


def native_bytes(path,raw):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);path.write_bytes(raw);path.chmod(0o600)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


class NativeDocker(Docker):
    def __init__(self,state,receipt,config):
        super().__init__(state,current=2,target=2)
        self.receipt,self.config=receipt,config;self.capable={OLD};self.rag_capable={OLD};self.bad_probe=None
        self.volumes={value['name']:{'Name':value['name'],'Driver':'local','Options':{},'Labels':receipt['volumeLabels'][key]}
                      for key,value in receipt['volumes'].items()}
    def __call__(self,*args,**kwargs):
        if args[:2]==('image','inspect'):
            labels={guard.LABEL:'2'}
            if args[2] in self.capable:labels[guard.NATIVE_LABEL]=guard.NATIVE_PROFILE
            if args[2] in self.rag_capable:labels[guard.RAG_LABEL]='1'
            return json.dumps([{'Id':args[2],'Config':{'Labels':labels}}]).encode()
        if args[:2]==('volume','inspect'):return json.dumps([self.volumes[args[2]]]).encode()
        if args[0]=='run' and args[-1]==guard.NATIVE_PROBE:
            self.calls.append(args)
            mount=args[args.index('--mount')+1];name=mount.split('src=')[1].split(',')[0]
            value=next(row for row in self.receipt['volumes'].values() if row['name']==name)
            result={'files':value['files'],'filesSha256':value['filesSha256'],'collectionId':'11111111-2222-3333-4444-555555555555',
                    'embeddingProfile':guard.NATIVE_PROFILE,'collection':guard.NATIVE_COLLECTION,'dimensions':1024}
            if self.bad_probe:result.update(self.bad_probe)
            return json.dumps(result).encode()
        if args[0]=='run' and 'preservation.json' in args[-1]:
            self.calls.append(args);return json.dumps({'sha256':self.receipt['ragManifestSha256']}).encode()
        if args[0]=='run':
            # The ordinary journal floor probe still reads the stopped original
            # container; no source volume is ever mounted writable.
            assert not self.rows[BACKEND]['State']['Running'] and not self.rows[next(key for key in self.rows if key!=BACKEND)]['State']['Running']
            self.calls.append(args);return json.dumps({'requiredProtocol':2}).encode()
        if args[0]=='exec':
            self.calls.append(args)
            return json.dumps({'status':'ok','memory_protocol':2,'write_receipts':True,'lifecycle':True,'bridge_auth_configured':True,
                'embedding_profile':guard.NATIVE_PROFILE,'embedding_collection':guard.NATIVE_COLLECTION,'embedding_dimensions':1024}).encode()
        return super().__call__(*args,**kwargs)
    def activate(self):
        self.rows.pop(MEMORY,None)
        row=self.row(REPLACED,'mem0',OLD);row['Mounts'][0].update(Name=self.receipt['volumes']['doorhandle-mem0']['name'],RW=True)
        row['Config']['Env'] += ['EMBEDDING_PROFILE='+guard.NATIVE_PROFILE,'EMBEDDING_MODEL='+guard.NATIVE_MODEL,
                                 'EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1']
        self.rows[REPLACED]=row


@pytest.fixture
def native_install(tmp_path,monkeypatch):
    root=tmp_path/'native-root';state=root/'state';state.mkdir(parents=True,mode=0o700)
    tag='ci-75-'+'a'*12;commit='a'*40;source='b'*64;owner='f'*24
    identity={'instanceId':'i-fixture123','machineId':'c'*32}
    output=root/'releases'/tag/'work/compact-cutover-0123456789/native-final'
    work=root/'verification'/tag/'checkout/work/legacy-candidate'
    candidate={'release':tag,'commit':commit,'sourceSha256':source,'identity':identity,
        'originalVolumes':{'mem0':'project-memory','chroma':'project-chroma'},'originalContainers':{'mem0':MEMORY,'chroma':'f'*64}}
    candidate_sha=native_write(work/'legacy-candidate.json',candidate)
    freeze={'schemaVersion':1,'kind':'doorhandle-source-writer-freeze','ecs':{**identity,'executionLocation':'ECS'},'writerContainers':[MEMORY,BACKEND,'f'*64]}
    freeze_sha=native_write(output.parent/'source-freeze.json',freeze)
    phase_dir=work.parent/'runtime-acceptance';references={}
    for phase in ('after-start','after-restart','after-volume-restore'):
        phase_refs={}
        for key,prefix in (('readback','native-readback-'),('semantic','bge-semantic-')):
            record={'phase':phase,'candidateSha256':candidate_sha,'paidModelCalls':0,'llmCalls':0}
            if key=='readback':record.update(status='VERIFIED',candidateSemanticVerified=True,productionDataMaterialized=False,activatedLocalMem0Records=30)
            if key=='semantic':record.update(status='SEMANTIC_BRIDGE_VERIFIED',collection=guard.NATIVE_COLLECTION,
                embeddingProfile=guard.NATIVE_PROFILE,dimensions=1024,semanticQueries=2,crossOwnerQueries=2,
                nativeReadOnlyVerified=True,ownedRestoredCopy=True,independentProcess=True)
            file=phase_dir/(prefix+phase+'.json');checksum=native_write(file,record)
            phase_refs[key]={'file':file.relative_to(work.parents[2]).as_posix(),'sha256':checksum}
        references[phase]=phase_refs
    activation={**{key:candidate[key] for key in ('release','commit','sourceSha256','identity')},
        'kind':'doorhandle-native-semantic-activation','status':'VERIFIED_AND_ACTIVATED','candidateSha256':candidate_sha,
        'productionDataMaterialized':False,'candidateSemanticVerified':True,'verifications':references}
    activation['identity']={**identity,'executionLocation':'ECS'}
    activation_file=phase_dir/'native-semantic-activation.json';activation_sha=native_write(activation_file,activation)
    snapshots={};pristine={};volumes={};labels={}
    for service,key in (('mem0','doorhandle-mem0'),('chroma','doorhandle-chroma')):
        folder=output/('fresh-'+service);body=b'original full '+service.encode()
        catalog={'source.db':native_bytes(folder/'data/source.db',body)}
        native_bytes(folder/'restored-originals/source.db',body)
        archive=folder/'originals.tar'
        with tarfile.open(archive,'w') as package:
            item=tarfile.TarInfo('source.db');item.size=len(body);package.addfile(item,io.BytesIO(body))
        archive.chmod(0o600);archive_sha=hashlib.sha256(archive.read_bytes()).hexdigest()
        proof={'status':'RESTORED_VERIFIED','fullVolume':True,'sourceMountedReadOnly':True,'identity':identity,
            'normalizedFiles':catalog,'sourceBefore':catalog,'sourceInventorySha256':guard.native_hash(catalog),
            'sourceAfterSha256':guard.native_hash(catalog),'archiveSha256':archive_sha}
        file=folder/'snapshot-receipt.json';checksum=native_write(file,proof)
        snapshots[service]={'file':str(file),'sha256':checksum,'archiveSha256':archive_sha,
            'sourceVolume':candidate['originalVolumes'][service],'normalizedFilesSha256':guard.native_hash(catalog),
            'sourceBeforeSha256':guard.native_hash(catalog)}
        name='doorhandlecatch-monolith_native-'+tag+'-'+owner+'-'+('mem0' if service=='mem0' else 'chroma')
        directory=work/('mem0/data' if service=='mem0' else 'rag/chroma')
        payload={'pristine.bin':native_bytes(directory/'pristine.bin',b'pristine '+service.encode())}
        catalog_file=work/(('mem0' if service=='mem0' else 'rag')+'-payload-files.json')
        catalog_sha=native_write(catalog_file,payload)
        pristine[key]={'directory':str(directory),'catalogFile':str(catalog_file),'catalogSha256':catalog_sha,'filesSha256':guard.native_hash(payload)}
        volumes[key]={'name':name,'files':1,'filesSha256':guard.native_hash(payload),'payloadFilesSha256':catalog_sha}
    volumes['native-rag-preservation']={'name':'doorhandlecatch-monolith_native-'+tag+'-'+owner+'-manifest','sha256':'e'*64}
    for key in volumes:
        labels[key]={guard.NATIVE_VOLUME_LABEL:owner,'io.doorhandle.release':tag,'io.doorhandle.source':source,
                     'com.docker.compose.project':guard.PROJECT,'com.docker.compose.volume':key}
    rag_env={'CHAT_ASSISTANT_RAG_STARTUP_MODE':'PRESERVE_EXISTING','CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST':'/run/doorhandle-rag/preservation.json',
        'CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST_SHA256':'e'*64,'CHAT_ASSISTANT_RAG_PRESERVATION_COMMIT':commit,
        'CHAT_ASSISTANT_CHROMA_EMBEDDING_DIMENSION':'256','CHAT_ASSISTANT_CHROMA_COLLECTION':'project-rag',
        'CHAT_ASSISTANT_CHROMA_TENANT':'default_tenant','CHAT_ASSISTANT_CHROMA_DATABASE':'default_database'}
    overlay={'services':{'mem0':{'environment':{'EMBEDDING_PROFILE':guard.NATIVE_PROFILE,'EMBEDDING_MODEL':guard.NATIVE_MODEL,
        'EMBEDDING_BASE_URL':'https://api.siliconflow.cn/v1'}},'backend':{'environment':rag_env,'volumes':[
        {'type':'volume','source':'native-rag-preservation','target':'/run/doorhandle-rag','read_only':True}]}},
        'volumes':{key:{'name':value['name'],'external':True} for key,value in volumes.items()}}
    overlay_sha=native_write(output/'native-data.override.json',overlay);native_write(state/'native-data.override.json',overlay)
    receipt={'schemaVersion':1,'kind':'doorhandle-pristine-native-install','status':'MATERIALIZED_AND_VERIFIED',
        **{key:candidate[key] for key in ('release','commit','sourceSha256','identity')},'owner':owner,'candidateSha256':candidate_sha,
        'sourceFreezeFile':str(output.parent/'source-freeze.json'),'sourceFreezeSha256':freeze_sha,
        'semanticActivationFile':str(activation_file),'semanticActivationSha256':activation_sha,
        'semanticActivation':{'file':activation_file.relative_to(work.parents[2]).as_posix(),'sha256':activation_sha},
        'freshSnapshots':snapshots,'pristinePayloads':pristine,'volumes':volumes,'volumeLabels':labels,
        'overlayFile':str(output/'native-data.override.json'),'overlaySha256':overlay_sha,
        'images':{'mem0':OLD,'backend':OLD,'chroma':NEW},'originalVolumes':candidate['originalVolumes'],
        'candidateSemanticVerified':True,'productionDataMaterialized':True,'runtimeTestVolumesPublished':False,
        'originalVolumesMountedReadOnly':True,'freshIndependentRestoreVerified':True,'sourceDriftDetected':False,
        'privateCredentialFileCopiedIntoPayload':False,'credentialSource':'EXISTING_PRIVATE_ECS_ENV',
        'embeddingProfile':guard.NATIVE_PROFILE,'embeddingCollection':guard.NATIVE_COLLECTION,'embeddingDimensions':1024,
        'ragManifestSha256':'e'*64,'activeRecords':30,'importedHistoryRows':30,'importedMessageRows':25,
        'archivedRecords':2,'archivedHistoryRows':3,'archivedMessageRows':1,'paidModelCalls':0,'llmCalls':0}
    receipt_file=output/'native-production-install.json';receipt_sha=native_write(receipt_file,receipt)
    binding={'schemaVersion':1,'kind':'doorhandle-native-binding','status':'MATERIALIZED_PENDING_SERVICE_READBACK',
        **{key:candidate[key] for key in ('release','commit','sourceSha256','identity')},'owner':owner,
        'installReceiptFile':str(receipt_file),'installReceiptSha256':receipt_sha,
        'overlayFile':str(state/'native-data.override.json'),'overlaySha256':overlay_sha}
    native_write(state/'native-data.json',binding)
    config={'services':{'mem0':{'image':OLD,'environment':overlay['services']['mem0']['environment'],
            'volumes':[{'type':'volume','source':'doorhandle-mem0','target':'/data'}]},
        'chroma':{'image':NEW,'volumes':[{'type':'volume','source':'doorhandle-chroma','target':'/data'}]},
        'backend':{'image':OLD,**overlay['services']['backend']}},'volumes':overlay['volumes']}
    docker=NativeDocker(state,receipt,config);monkeypatch.setattr(guard,'docker',docker)
    monkeypatch.setattr(guard,'native_host_identity',lambda value:None)
    return SimpleNamespace(root=root,state=state,receipt=receipt,receipt_file=receipt_file,binding=binding,config=config,docker=docker,output=output)


def test_explicit_pristine_transition_switches_only_after_full_proofs_and_persists_native_floor(native_install):
    value=native_install
    with pytest.raises(guard.GuardError):guard.prepare(value.state,value.config)
    assert guard.prepare(value.state,value.config,native_transition=value.receipt_file)=='replace'
    floor=guard.read_json(value.state/'memory-minimum.json')
    assert floor['dataMount']['name']==value.receipt['volumes']['doorhandle-mem0']['name']
    assert floor['native']['collection']==guard.NATIVE_COLLECTION and floor['native']['dimensions']==1024
    value.docker.activate();guard.verify(value.state)
    assert guard.read_json(value.state/'memory-transition.json')['phase']=='VERIFIED'


def test_active_state_only_changes_status_and_allows_business_writes_without_rehashing_initial_payload(native_install):
    value=native_install;guard.prepare(value.state,value.config,native_transition=value.receipt_file)
    pending=guard.validate_native_state(value.state,allow_pending=True)['nativeBindingSha256']
    value.docker.activate();guard.verify(value.state)
    value.binding['status']='ACTIVE';native_write(value.state/'native-data.json',value.binding)
    assert guard.validate_native_state(value.state)['nativeBindingSha256']==pending
    # Simulate legitimate post-activation SQLite/index changes: only the original
    # immutable vector-space marker, named volume and origin remain mandatory.
    value.docker.bad_probe={'filesSha256':'0'*64}
    assert guard.prepare(value.state,value.config)=='replace'


def test_unsupported_rollback_preserves_the_exact_current_bge_reader_and_volume(native_install):
    value=native_install;guard.prepare(value.state,value.config,native_transition=value.receipt_file)
    value.docker.activate();guard.verify(value.state)
    value.binding['status']='ACTIVE';native_write(value.state/'native-data.json',value.binding)
    value.config['services']['mem0']['image']=NEW
    assert guard.prepare(value.state,value.config)=='preserve'
    record=guard.read_json(value.state/'memory-transition.json')
    assert record['selectedImage']==OLD and record['dataMount']['name']==value.receipt['volumes']['doorhandle-mem0']['name']


@pytest.mark.parametrize('damage',['candidate-only','receipt','overlay','identity','volume-owner','wrong-mount','test-namespace','wrong-data-directory','rag-reader'])
def test_native_state_rejects_unmaterialized_or_drifted_bindings(native_install,damage):
    value=native_install
    if damage=='candidate-only':
        value.receipt['productionDataMaterialized']=False
        value.binding['installReceiptSha256']=native_write(value.receipt_file,value.receipt);native_write(value.state/'native-data.json',value.binding)
    elif damage=='receipt':value.receipt_file.write_bytes(value.receipt_file.read_bytes()+b' ')
    elif damage=='overlay':(value.state/'native-data.override.json').write_bytes(b'{}')
    elif damage=='identity':
        value.binding['identity']={**value.binding['identity'],'machineId':'f'*32};native_write(value.state/'native-data.json',value.binding)
    elif damage=='volume-owner':value.docker.volumes[value.receipt['volumes']['doorhandle-mem0']['name']]['Labels']={}
    elif damage=='wrong-mount':value.config['volumes']['doorhandle-mem0']['name']='foreign-volume'
    elif damage=='test-namespace':value.config['services']['mem0']['environment']['MEM0_RUNTIME_TEST_COLLECTION']='test'
    elif damage=='wrong-data-directory':value.config['services']['mem0']['environment']['MEM0_DATA_DIR']='/tmp/empty-space'
    else:value.docker.rag_capable.clear()
    with pytest.raises(guard.GuardError):guard.validate_native_state(value.state,value.config,allow_pending=True)


@pytest.mark.parametrize('damage',['freeze','restore-bytes','pristine-bytes','phase','target-reader','target-payload','rag-payload'])
def test_initial_switch_rejects_missing_real_freeze_restore_payload_or_semantic_evidence(native_install,damage):
    value=native_install
    if damage=='freeze':Path(value.receipt['sourceFreezeFile']).write_bytes(b'{}')
    elif damage=='restore-bytes':(value.output/'fresh-mem0/restored-originals/source.db').write_bytes(b'changed')
    elif damage=='pristine-bytes':Path(value.receipt['pristinePayloads']['doorhandle-mem0']['directory'],'pristine.bin').write_bytes(b'changed')
    elif damage=='phase':Path(value.receipt['semanticActivationFile']).with_name('bge-semantic-after-restart.json').unlink()
    elif damage=='target-reader':value.docker.capable.clear()
    elif damage=='target-payload':value.docker.bad_probe={'filesSha256':'0'*64}
    else:
        original=value.docker.__class__.__call__
        def changed(self,*args,**kwargs):
            raw=original(self,*args,**kwargs)
            if args[0]=='run' and args[-1]==guard.NATIVE_PROBE and 'NATIVE_SPACE_REQUIRED=0' in args:
                result=json.loads(raw);result['filesSha256']='0'*64;return json.dumps(result).encode()
            return raw
        value.docker.__class__.__call__=changed
        try:
            with pytest.raises(guard.GuardError):guard.prepare(value.state,value.config,native_transition=value.receipt_file)
        finally:value.docker.__class__.__call__=original
        return
    with pytest.raises((guard.GuardError,FileNotFoundError)):
        guard.prepare(value.state,value.config,native_transition=value.receipt_file)


def test_floor_and_volume_identity_cannot_be_lost_on_subsequent_deploy_or_restore(native_install):
    value=native_install;guard.prepare(value.state,value.config,native_transition=value.receipt_file)
    value.docker.activate();guard.verify(value.state)
    value.binding['status']='ACTIVE';native_write(value.state/'native-data.json',value.binding)
    minimum=guard.read_json(value.state/'memory-minimum.json');minimum['native']['bindingSha256']='0'*64
    guard.write_json(value.state/'memory-minimum.json',minimum)
    with pytest.raises(guard.GuardError,match='durable native floor'):guard.prepare(value.state,value.config)


def test_native_overlay_without_binding_or_bge_config_without_proof_is_refused(tmp_path,monkeypatch):
    native_write(tmp_path/'native-data.override.json',{})
    with pytest.raises(guard.GuardError):guard.validate_native_state(tmp_path)
    (tmp_path/'native-data.override.json').unlink()
    docker=Docker(tmp_path,current=2,target=2);monkeypatch.setattr(guard,'docker',docker)
    with pytest.raises(guard.GuardError,match='materialized persistent'):
        guard.prepare(tmp_path,{'services':{'mem0':{'image':OLD,'environment':{'EMBEDDING_PROFILE':guard.NATIVE_PROFILE}}}})


@pytest.mark.parametrize('damage',['wrong-instance','wrong-machine','non-ecs','two-key-context'])
def test_freeze_and_semantic_ecs_contexts_require_three_keys_and_match_the_two_key_binding(damage):
    expected={'instanceId':'i-fixture123','machineId':'c'*32}
    context={**expected,'executionLocation':'ECS'}
    assert guard.native_ecs_context(context,expected)
    assert guard.native_identity(expected) and not guard.native_identity(context)
    if damage=='wrong-instance':context['instanceId']='i-other123'
    elif damage=='wrong-machine':context['machineId']='f'*32
    elif damage=='non-ecs':context['executionLocation']='WORKSTATION'
    else:context.pop('executionLocation')
    assert not guard.native_ecs_context(context,expected)


def test_native_state_cli_accepts_stdin_effective_config_without_printing_or_writing_its_credentials(native_install,monkeypatch,capsys):
    value=native_install
    value.config['services']['backend']['environment']['SPRING_DATASOURCE_PASSWORD']='PRIVATE_STDIN_ONLY'
    monkeypatch.setattr(sys,'argv',['memory-compat.py','native-state','--state',str(value.state),'--allow-pending','--config','-'])
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(value.config)))
    before={path.name:path.read_bytes() for path in value.state.iterdir()}
    guard.main()
    public=capsys.readouterr().out
    assert json.loads(public)['status']=='MATERIALIZED_PENDING_SERVICE_READBACK'
    assert 'PRIVATE_STDIN_ONLY' not in public and 'SPRING_DATASOURCE_PASSWORD' not in public
    assert {path.name:path.read_bytes() for path in value.state.iterdir()}==before


def test_real_readonly_sqlite_probe_requires_the_bge_dimension_and_persistent_model_marker(tmp_path):
    directory=tmp_path/'native-volume';vector=directory/'chroma/chroma.sqlite3';vector.parent.mkdir(parents=True)
    with sqlite3.connect(vector) as db:
        db.execute('CREATE TABLE collections(id TEXT PRIMARY KEY,name TEXT,dimension INTEGER)')
        db.execute('CREATE TABLE collection_metadata(collection_id TEXT,key TEXT,str_value TEXT,int_value INTEGER)')
        db.execute('INSERT INTO collections VALUES(?,?,?)',('11111111-2222-3333-4444-555555555555',guard.NATIVE_COLLECTION,1024))
        for key,value in {'doorhandle_embedding_profile':guard.NATIVE_PROFILE,'doorhandle_embedding_provider':'siliconflow',
                          'doorhandle_embedding_model':guard.NATIVE_MODEL,'doorhandle_embedding_dimensions':1024}.items():
            db.execute('INSERT INTO collection_metadata VALUES(?,?,?,?)',('11111111-2222-3333-4444-555555555555',key,
                        value if isinstance(value,str) else None,value if type(value) is int else None))
    db.close()
    before=hashlib.sha256(vector.read_bytes()).hexdigest()
    environment={**os.environ,'MEM0_DATA_DIR':str(directory),'NATIVE_FULL_INVENTORY':'1','NATIVE_SPACE_REQUIRED':'1'}
    result=subprocess.run([sys.executable,'-I','-B','-c',guard.NATIVE_PROBE],env=environment,capture_output=True,text=True,timeout=8)
    assert result.returncode==0
    observed=json.loads(result.stdout)
    assert observed['embeddingProfile']==guard.NATIVE_PROFILE and observed['dimensions']==1024 and observed['files']==1
    assert hashlib.sha256(vector.read_bytes()).hexdigest()==before
    assert json.loads(probe(directory).stdout)['nativeEmbeddingProfile']==guard.NATIVE_PROFILE
    with sqlite3.connect(vector) as db:db.execute("UPDATE collection_metadata SET str_value='wrong-model' WHERE key='doorhandle_embedding_model'")
    db.close()
    result=subprocess.run([sys.executable,'-I','-B','-c',guard.NATIVE_PROBE],env=environment,capture_output=True,text=True,timeout=8)
    assert result.returncode!=0 and 'Native vector space cannot be verified' in result.stderr
