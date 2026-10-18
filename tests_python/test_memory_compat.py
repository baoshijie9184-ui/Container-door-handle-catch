"""Deployment protocol exercises; native SQLite probes and a stateful Docker protocol substitute."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
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
