#!/usr/bin/env python3
"""Quiesce, inspect durable memory protocol requirements, and preserve a compatible bridge."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

PROJECT = 'doorhandlecatch-monolith'
LABEL = 'io.doorhandle.memory-protocol'
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')
CID = re.compile(r'[a-f0-9]{64}')
ZONE = dt.timezone(dt.timedelta(hours=8))

# Run using the existing stopped bridge image, not a downloaded helper or an SDK entry point.
PROBE = '''import os,sqlite3,json,stat,tempfile,shutil
from pathlib import Path
from contextlib import closing
try:
 root=Path(os.environ['MEM0_DATA_DIR'])
 dbpath=root/'bridge_receipts'/'write-receipts.sqlite3'
 if not root.is_dir() or any(p.is_symlink() for p in (dbpath,*dbpath.parents)):
  raise ValueError()
 floor=0
 if not dbpath.exists() and (root/'bridge_receipts'/'writer.lock').exists():raise ValueError()
 if dbpath.exists():
  # A WAL database with no existing shm file may need to create one even in
  # mode=ro. Snapshot the quiesced source into bounded tmpfs; never make the
  # original volume writable or use immutable (which can ignore committed WAL).
  with tempfile.TemporaryDirectory(prefix='memory-protocol-') as scratch:
   copied=Path(scratch)/dbpath.name
   remaining=192*1024*1024
   for original in (dbpath,dbpath.with_name(dbpath.name+'-wal')):
    if original.is_symlink():raise ValueError()
    if not original.exists():continue
    with os.fdopen(os.open(original,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)),'rb') as source:
     before=os.fstat(source.fileno())
     if not stat.S_ISREG(before.st_mode) or before.st_size>remaining:raise ValueError()
     remaining-=before.st_size
     with (Path(scratch)/original.name).open('xb') as target:
      shutil.copyfileobj(source,target,1024*1024)
     after=os.fstat(source.fileno());current=original.stat()
     identity=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns)
     if identity(before)!=identity(after) or identity(before)!=identity(current):raise ValueError()
   with closing(sqlite3.connect(copied.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
    db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'memory_write_receipt' not in tables:raise ValueError()
    if 'bridge_protocol_floor' in tables:
     rows=db.execute('SELECT required_version FROM bridge_protocol_floor WHERE id=1').fetchall()
     if len(rows)!=1 or type(rows[0][0]) is not int or rows[0][0]<0:raise ValueError()
     floor=rows[0][0]
     required={'memory_write_receipt'} if floor>=1 else set()
     if floor>=2:required.update({'memory_lifecycle','memory_cleanup_event'})
     if not required.issubset(tables):raise ValueError()
    for table,version in [('memory_write_receipt',1),('memory_lifecycle',2),('memory_cleanup_event',2)]:
     if table in tables and db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():floor=max(floor,version)
 print(json.dumps({'requiredProtocol':floor}))
except Exception:
 raise SystemExit('Memory protocol storage cannot be verified')
'''
HEALTH = "import json,urllib.request;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=3))))"


class GuardError(Exception):
    pass


def docker(*args, timeout=30):
    try:
        result = subprocess.run(['docker', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=True)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise GuardError('Docker operation failed; memory remains gated') from None


def write_private(path, value):
    if path.is_symlink():
        raise GuardError('Memory state cannot be a link')
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
        stream.write(value);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name!='nt':
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)


def write_json(path, value):
    write_private(path,json.dumps(value,ensure_ascii=True,indent=2))


def read_json(path):
    if path.is_symlink():
        raise GuardError('Memory state cannot be a link')
    return json.loads(path.read_text(encoding='utf-8'))


def image(reference):
    rows = json.loads(docker('image','inspect',reference))
    if len(rows)!=1 or not DIGEST.fullmatch(rows[0].get('Id','')):
        raise GuardError('Memory image identity is unavailable')
    raw = (rows[0].get('Config',{}).get('Labels') or {}).get(LABEL,'0')
    if not isinstance(raw,str) or not re.fullmatch(r'[0-9]{1,4}',raw):
        raise GuardError('Memory image protocol is invalid')
    return rows[0]['Id'],int(raw)


def container(service):
    ids = docker('ps','-aq','--no-trunc','--filter',f'label=com.docker.compose.project={PROJECT}', '--filter',f'label=com.docker.compose.service={service}').decode().split()
    if len(ids)!=1 or not CID.fullmatch(ids[0]):
        raise GuardError('Expected exactly one existing application container')
    row = json.loads(docker('inspect',ids[0]))[0]
    labels = row.get('Config',{}).get('Labels') or {}
    if row.get('Id')!=ids[0] or labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service or not DIGEST.fullmatch(row.get('Image','')):
        raise GuardError('Application container identity changed')
    return row


def data_mount(row):
    data = next((s.split('=',1)[1] for s in row['Config'].get('Env',[]) if s.startswith('MEM0_DATA_DIR=')), '/data')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',data) or '..' in Path(data).parts:
        raise GuardError('Unexpected memory data directory')
    matches = [m for m in row.get('Mounts',[]) if m.get('Type')=='volume' and m.get('Name') and (data==m.get('Destination') or data.startswith(m.get('Destination','')+'/'))]
    if len(matches)!=1:
        raise GuardError('Expected a persistent named memory volume')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',matches[0]['Name']):
        raise GuardError('Invalid named memory volume')
    return data, {'name':matches[0]['Name'], 'destination':matches[0]['Destination']}


def prepare(state, config):
    memory, backend = container('mem0'), container('backend')
    desired = config.get('services',{}).get('mem0',{}).get('image')
    if not isinstance(desired,str) or not desired or any(c.isspace() for c in desired):
        raise GuardError('Missing target memory image')
    target_id, target_protocol = image(desired)
    current_id, current_protocol = image(memory['Image'])
    data, mount = data_mount(memory)
    record={'phase':'PREPARED','createdAt':dt.datetime.now(ZONE).isoformat(),'backend':backend['Id'],
            'originalContainer':memory['Id'],'originalImage':current_id,'desiredImage':target_id,'dataMount':mount}
    journal=state/'memory-transition.json'
    write_json(journal,record)
    try:
        # The backend must not read an unverified candidate, and no writer may raise the floor after the probe.
        docker('stop','--time','30',backend['Id'],timeout=45)
        docker('stop','--time','30',memory['Id'],timeout=45)
        if container('backend')['Id']!=backend['Id'] or container('backend')['State']['Running'] or container('mem0')['Id']!=memory['Id'] or container('mem0')['State']['Running']:
            raise GuardError('Application did not quiesce')
        record['phase']='QUIESCED';write_json(journal,record)
        minimum_path=state/'memory-minimum.json'
        minimum=read_json(minimum_path) if minimum_path.exists() else {'requiredProtocol':0,'dataMount':mount}
        if type(minimum.get('requiredProtocol')) is not int or minimum['requiredProtocol']<0 or minimum.get('dataMount')!=mount:
            raise GuardError('Memory volume or stored protocol requirement changed')
        result=json.loads(docker('run','--rm','--pull','never','--network','none','--no-healthcheck','--read-only','--cap-drop','ALL',
                                 '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=256m','--memory','384m','--cpus','1','--pids-limit','64',
                                 '--security-opt','no-new-privileges','--user','10001:10001','--mount',f"type=volume,src={mount['name']},dst={mount['destination']},readonly",
                                 '--env','MEM0_DATA_DIR='+data,'--entrypoint','python',current_id,'-B','-c',PROBE,timeout=30))
        floor=result.get('requiredProtocol')
        if type(floor) is not int or floor<0:
            raise GuardError('Memory protocol result is invalid')
        floor=max(floor,minimum['requiredProtocol'])
        write_json(minimum_path,{'requiredProtocol':floor,'dataMount':mount,'updatedAt':dt.datetime.now(ZONE).isoformat()})
        keep=target_protocol<floor
        if keep and current_protocol<floor:
            raise GuardError('No compatible memory image; select a compatible recovery version')
        selected_id,selected_protocol=(current_id,current_protocol) if keep else (target_id,target_protocol)
        pin=state/'memory-activation-images.yml'
        write_private(pin,'services:\n  mem0:\n    image: '+selected_id+'\n')
        record.update(phase='DECIDED',requiredProtocol=floor,selectedImage=selected_id,selectedProtocol=selected_protocol,preserved=keep)
        write_json(journal,record)
        if keep:docker('start',memory['Id'])  # Retain its exact environment, mounts, identity and network configuration.
        return 'preserve' if keep else 'replace'
    except Exception:
        record['phase']='FAILED';write_json(journal,record)
        raise


def verify(state, *, timeout=240):
    record=read_json(state/'memory-transition.json')
    if record.get('phase')!='DECIDED':raise GuardError('Memory transition has no verified decision')
    backend=container('backend')
    if backend['Id']!=record['backend'] or backend['State']['Running']:
        if backend['State']['Running']:docker('stop','--time','30',backend['Id'],timeout=45)
        raise GuardError('Backend resumed before memory verification')
    deadline=time.monotonic()+timeout
    while True:
        memory=container('mem0')
        _,mount=data_mount(memory)
        if memory['Image']!=record['selectedImage'] or mount!=record['dataMount'] or record['preserved'] and memory['Id']!=record['originalContainer']:
            docker('stop','--time','30',memory['Id'],timeout=45)
            raise GuardError('Activated memory image, identity or volume differs from the decision')
        health=memory['State'].get('Health',{}).get('Status')
        if memory['State']['Running'] and health=='healthy':break
        if health=='unhealthy' or time.monotonic()>=deadline:
            raise GuardError('Compatible memory did not become healthy')
        time.sleep(1)
    health=json.loads(docker('exec',memory['Id'],'python','-B','-c',HEALTH,timeout=8))
    reported=health.get('memory_protocol',0)
    required=max(record['requiredProtocol'],record['selectedProtocol'])
    if health.get('status')!='ok' or health.get('bridge_auth_configured') is not True or type(reported) is not int or reported<required or required>=1 and not health.get('write_receipts') or required>=2 and not health.get('lifecycle'):
        docker('stop','--time','30',memory['Id'],timeout=45)
        raise GuardError('Memory runtime protocol does not match its image')
    record.update(phase='VERIFIED',verifiedAt=dt.datetime.now(ZONE).isoformat());write_json(state/'memory-transition.json',record)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','verify']);parser.add_argument('--state',required=True);parser.add_argument('--lock-fd',type=int,required=True)
    args=parser.parse_args();state=Path(args.state)
    try:
        if state.name!='state' or not state.is_dir() or any(p.is_symlink() for p in (state,*state.parents)):
            raise GuardError('Invalid private deployment state directory')
        import fcntl
        descriptor=os.fstat(args.lock_fd);lock=(state/'deploy.lock').stat()
        if (descriptor.st_dev,descriptor.st_ino)!=(lock.st_dev,lock.st_ino):
            raise GuardError('Deployment lock identity differs')
        fcntl.flock(args.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action=='prepare':print(prepare(state,json.load(sys.stdin)))
        else:verify(state)
    except Exception:
        print('Memory compatibility verification failed; backend remains gated. Review private transition state before recovery.',file=sys.stderr)
        raise SystemExit(6)


if __name__=='__main__':main()
