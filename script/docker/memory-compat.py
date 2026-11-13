#!/usr/bin/env python3
"""Quiesce, inspect durable memory protocol requirements, and preserve a compatible bridge."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from urllib.request import ProxyHandler,Request,build_opener

PROJECT = 'doorhandlecatch-monolith'
LABEL = 'io.doorhandle.memory-protocol'
DIGEST = re.compile(r'sha256:[a-f0-9]{64}')
CID = re.compile(r'[a-f0-9]{64}')
ZONE = dt.timezone(dt.timedelta(hours=8))
NATIVE_LABEL = 'io.doorhandle.memory-embedding-profile'
RAG_LABEL = 'io.doorhandle.rag-preservation-protocol'
RAG_PROTOCOL = '2'
NATIVE_PROFILE = 'siliconflow-bge-m3-v1'
NATIVE_COLLECTION = 'doorhandle_memories_bge_m3_v1'
NATIVE_MODEL = 'BAAI/bge-m3'
VECTOR_BACKEND_LABEL = 'io.doorhandle.memory-vector-backend'
VECTOR_GENERATION_LABEL = 'io.doorhandle.memory-storage-generation'
VECTOR_ID_LABEL = 'io.doorhandle.memory-id-protocol'
VECTOR_GENERATION = 'qdrant-bge-m3-v1'
VECTOR_ID_PROTOCOL = 'doorhandle-vector-sha256-v8-v1'
NATIVE_VOLUME_LABEL = 'io.doorhandle.native-cutover'
SHA = re.compile(r'[a-f0-9]{64}')
NATIVE_KEYS = set(('schemaVersion kind status release commit sourceSha256 identity owner installReceiptFile '
                   'installReceiptSha256 overlayFile overlaySha256').split())

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
 native=False
 vector=root/'chroma'/'chroma.sqlite3'
 if vector.exists() or vector.is_symlink():
  if any(p.is_symlink() for p in (vector,*vector.parents)):raise ValueError()
  with tempfile.TemporaryDirectory(prefix='memory-space-') as scratch:
   remaining=192*1024*1024
   for original in (vector,vector.with_name(vector.name+'-wal')):
    if not original.exists():continue
    with os.fdopen(os.open(original,os.O_RDONLY|os.O_NOFOLLOW),'rb') as source:
     before=os.fstat(source.fileno())
     if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>remaining:raise ValueError()
     remaining-=before.st_size
     with (Path(scratch)/original.name).open('xb') as target:shutil.copyfileobj(source,target,1024*1024)
     identity=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
     if identity(before)!=identity(os.fstat(source.fileno())) or identity(before)!=identity(original.stat()):raise ValueError()
   with closing(sqlite3.connect((Path(scratch)/vector.name).as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
    db.execute('PRAGMA query_only=ON')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collections'").fetchone():
     native=bool(db.execute("SELECT 1 FROM collections WHERE name='doorhandle_memories_bge_m3_v1' LIMIT 1").fetchone())
 result={'requiredProtocol':floor}
 marker=root/'vector-space.json'
 if marker.exists() or marker.is_symlink():
  info=marker.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>8192 or info.st_mode&0o077:raise ValueError()
  space=json.loads(marker.read_text());identity=space.get('identity',{})
  expected={'doorhandle_profile':'siliconflow-bge-m3-v1','doorhandle_model':'BAAI/bge-m3','doorhandle_dimensions':1024,'doorhandle_preprocessing':'utf8-newline-space-v1','doorhandle_storage_generation':'qdrant-bge-m3-v1','doorhandle_metric':'Cosine','doorhandle_id_protocol':'doorhandle-vector-sha256-v8-v1'}
  if set(space)!={'schemaVersion','backend','collection','identity','historyMode'} or space.get('schemaVersion')!=1 or space.get('backend')!='qdrant' or space.get('collection')!='doorhandle_memories_bge_m3_v1' or space.get('historyMode')!='single-writer-sqlite' or identity!=expected:raise ValueError()
  result['vectorSpace']=space
 if native:result['nativeEmbeddingProfile']='siliconflow-bge-m3-v1'
 print(json.dumps(result))
except Exception:
 raise SystemExit('Memory protocol storage cannot be verified')
'''
HEALTH = "import json,urllib.request;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=3))))"
NATIVE_PROBE = r'''import hashlib,json,os,shutil,sqlite3,stat,tempfile
from pathlib import Path
root=Path(os.environ['MEM0_DATA_DIR'])
def fail():raise ValueError('Native vector space cannot be verified')
try:
 if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):fail()
 result={}
 if os.environ.get('NATIVE_FULL_INVENTORY')=='1':
  files={};total=0
  def unreadable(error):raise error
  for current,dirs,names in os.walk(root,followlinks=False,onerror=unreadable):
   for name in dirs+names:
    info=(Path(current)/name).lstat()
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):fail()
   for name in sorted(names):
    path=Path(current)/name;info=path.stat();total+=info.st_size
    if info.st_nlink!=1 or total>512*1024**2 or len(files)>=16384:fail()
    h=hashlib.sha256()
    with path.open('rb') as stream:
     for raw in iter(lambda:stream.read(1048576),b''):h.update(raw)
    files[path.relative_to(root).as_posix()]={'bytes':info.st_size,'sha256':h.hexdigest()}
   dirs.sort()
  result.update(filesSha256=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),files=len(files))
 if os.environ.get('NATIVE_SPACE_REQUIRED','1')=='0':
  print(json.dumps(result));raise SystemExit(0)
 marker=root/'vector-space.json'
 if marker.exists() or marker.is_symlink():
  info=marker.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>8192 or info.st_mode&0o077:fail()
  space=json.loads(marker.read_text());identity=space.get('identity',{})
  expected={'doorhandle_profile':'siliconflow-bge-m3-v1','doorhandle_model':'BAAI/bge-m3','doorhandle_dimensions':1024,'doorhandle_preprocessing':'utf8-newline-space-v1','doorhandle_storage_generation':'qdrant-bge-m3-v1','doorhandle_metric':'Cosine','doorhandle_id_protocol':'doorhandle-vector-sha256-v8-v1'}
  if set(space)!={'schemaVersion','backend','collection','identity','historyMode'} or space.get('schemaVersion')!=1 or space.get('backend')!='qdrant' or space.get('collection')!='doorhandle_memories_bge_m3_v1' or space.get('historyMode')!='single-writer-sqlite' or identity!=expected:fail()
  result.update(collectionId='qdrant:doorhandle_memories_bge_m3_v1:qdrant-bge-m3-v1:doorhandle-vector-sha256-v8-v1',embeddingProfile='siliconflow-bge-m3-v1',collection='doorhandle_memories_bge_m3_v1',dimensions=1024,vectorSpace=space,vectorBackend='qdrant',storageGeneration='qdrant-bge-m3-v1')
  print(json.dumps(result));raise SystemExit(0)
 vector=root/'chroma'/'chroma.sqlite3'
 if not vector.is_file() or any(p.is_symlink() for p in (vector,*vector.parents)):fail()
 with tempfile.TemporaryDirectory(prefix='native-space-') as scratch:
  remaining=192*1024*1024
  for original in (vector,vector.with_name(vector.name+'-wal')):
   if not original.exists():continue
   with os.fdopen(os.open(original,os.O_RDONLY|os.O_NOFOLLOW),'rb') as origin:
    before=os.fstat(origin.fileno())
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>remaining:fail()
    remaining-=before.st_size
    with (Path(scratch)/original.name).open('xb') as target:shutil.copyfileobj(origin,target,1048576)
    signature=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
    if signature(before)!=signature(os.fstat(origin.fileno())) or signature(before)!=signature(original.stat()):fail()
  with sqlite3.connect((Path(scratch)/vector.name).as_uri()+'?mode=ro',uri=True,timeout=2) as db:
   db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
   rows=db.execute("SELECT id,dimension FROM collections WHERE name='doorhandle_memories_bge_m3_v1'").fetchall()
   if len(rows)!=1 or rows[0]['dimension']!=1024 or not isinstance(rows[0]['id'],str):fail()
   ident=rows[0]['id'];metadata={row['key']:dict(row) for row in db.execute('SELECT * FROM collection_metadata WHERE collection_id=?',(ident,))}
   expected={'doorhandle_embedding_profile':'siliconflow-bge-m3-v1','doorhandle_embedding_provider':'siliconflow','doorhandle_embedding_model':'BAAI/bge-m3','doorhandle_embedding_dimensions':1024}
   for key,value in expected.items():
    row=metadata.get(key,{})
    if (row.get('int_value') if type(value) is int else row.get('str_value'))!=value:fail()
 result.update(collectionId=ident,embeddingProfile='siliconflow-bge-m3-v1',collection='doorhandle_memories_bge_m3_v1',dimensions=1024)
 print(json.dumps(result))
except Exception:raise SystemExit('Native vector space cannot be verified')
'''


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


def native_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def native_file(path, state, *, maximum=16*1024**2):
    path,root=Path(path),Path(state).parent
    if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(root) or path.resolve(strict=True)!=path:
        raise GuardError('Native references must stay within the owned deployment root')
    for item in (path,*path.parents):
        info=item.lstat()
        if stat.S_ISLNK(info.st_mode) or (item==root or item.is_relative_to(root)) and (info.st_uid!=os.getuid() or info.st_mode&0o022):
            raise GuardError('Native reference ownership or ancestry changed')
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode) not in (0o400,0o600) or info.st_size>maximum:
        raise GuardError('Native evidence must remain a bounded private single regular file')
    return path


def native_read(path,state):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise GuardError('Duplicate native evidence field')
            result[key]=value
        return result
    path=native_file(path,state)
    raw=path.read_bytes()
    return json.loads(raw,object_pairs_hook=unique),hashlib.sha256(raw).hexdigest()


def native_identity(value):
    return (isinstance(value,dict) and set(value)=={'instanceId','machineId'}
            and re.fullmatch(r'i-[a-z0-9]+',value.get('instanceId',''))
            and re.fullmatch(r'[a-f0-9]{32}',value.get('machineId','')))


def native_ecs_context(value,expected):
    return (isinstance(value,dict) and set(value)=={'instanceId','machineId','executionLocation'}
            and value['executionLocation']=='ECS' and {key:value[key] for key in ('instanceId','machineId')}==expected)


def native_host_identity(expected):
    if sys.platform!='linux' or Path('/etc/machine-id').read_text().strip()!=expected['machineId']:
        raise GuardError('Native state belongs to another execution machine')
    opener=build_opener(ProxyHandler({}));base='http://100.100.100.200/latest/'
    with opener.open(Request(base+'api/token',data=b'',method='PUT',headers={'X-aliyun-ecs-metadata-token-ttl-seconds':'60'}),timeout=4) as response:
        token=response.read(4096).decode()
    with opener.open(Request(base+'meta-data/instance-id',headers={'X-aliyun-ecs-metadata-token':token}),timeout=4) as response:
        if response.read(256).decode().strip()!=expected['instanceId']:raise GuardError('Native state belongs to another ECS instance')


def native_capable(reference):
    rows=json.loads(docker('image','inspect',reference))
    labels=(rows[0].get('Config',{}).get('Labels') or {}) if len(rows)==1 else {}
    return (len(rows)==1 and rows[0].get('Id')==reference
            and labels.get(NATIVE_LABEL)==NATIVE_PROFILE and labels.get(VECTOR_BACKEND_LABEL)=='qdrant'
            and labels.get(VECTOR_GENERATION_LABEL)==VECTOR_GENERATION and labels.get(VECTOR_ID_LABEL)==VECTOR_ID_PROTOCOL)


def native_volumes(binding,receipt,config):
    expected=receipt['volumes'];services=config.get('services',{});definitions=config.get('volumes',{})
    overlay,_=native_read(binding['overlayFile'],Path(binding['overlayFile']).parent)
    for service,key in (('mem0','doorhandle-mem0-qdrant'),('qdrant','doorhandle-qdrant'),('backend','native-rag-preservation')):
        spec=services.get(service,{})
        target='/run/doorhandle-rag' if service=='backend' else '/data'
        mounts=[mount for mount in spec.get('volumes',[]) if mount.get('target')==target]
        if len(mounts)!=1 or mounts[0].get('type')!='volume' or mounts[0].get('source')!=key \
                or definitions.get(key,{}).get('name')!=expected[key]['name'] \
                or service=='backend' and mounts[0].get('read_only') is not True:
            raise GuardError('Native effective service mount differs from the persistent binding')
        rows=json.loads(docker('volume','inspect',expected[key]['name']))
        if len(rows)!=1 or rows[0].get('Name')!=expected[key]['name'] or rows[0].get('Driver')!='local' \
                or rows[0].get('Options') or rows[0].get('Labels')!=receipt['volumeLabels'][key]:
            raise GuardError('Native volume owner, source or driver differs from the install receipt')
    for service,spec in overlay['services'].items():
        env=services.get(service,{}).get('environment',{})
        if any(str(env.get(key))!=str(value) for key,value in spec.get('environment',{}).items()):
            raise GuardError('Native effective environment differs from the preserved vector space')
    env=services['mem0'].get('environment',{})
    if env.get('MEM0_DATA_DIR','/data')!='/data' \
            or any(key in env for key in ('DOORHANDLE_RUNTIME_ACCEPTANCE','DOORHANDLE_RUNTIME_PROJECT','MEM0_RUNTIME_TEST_COLLECTION')):
        raise GuardError('An acceptance namespace cannot replace production native data')
    backend_id,_=image(services.get('backend',{}).get('image',''))
    rows=json.loads(docker('image','inspect',backend_id))
    labels=rows[0].get('Config',{}).get('Labels') or {}
    if labels.get(RAG_LABEL)!=RAG_PROTOCOL or labels.get('io.doorhandle.semantic-vector-backend')!='qdrant' \
            or labels.get('io.doorhandle.semantic-storage-generation')!=VECTOR_GENERATION:
        raise GuardError('The backend cannot preserve the admitted RAG collection')


def validate_native_state(state,config=None,allow_pending=False):
    """Read immutable origin hashes; ordinary writes never re-hash a live volume."""
    state=Path(state);file=state/'native-data.json';overlay_file=state/'native-data.override.json'
    if not file.exists() and not file.is_symlink():
        if overlay_file.exists() or overlay_file.is_symlink():raise GuardError('Native overlay has no persistent binding')
        return None
    binding,_=native_read(file,state)
    statuses={'ACTIVE','MATERIALIZED_PENDING_SERVICE_READBACK'} if allow_pending else {'ACTIVE'}
    if set(binding)!=NATIVE_KEYS or type(binding.get('schemaVersion')) is not int or binding['schemaVersion']!=1 \
            or binding.get('kind')!='doorhandle-native-binding' or binding.get('status') not in statuses \
            or not re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}',binding.get('release','')) \
            or not re.fullmatch(r'[a-f0-9]{40}',binding.get('commit','')) \
            or not binding['release'].endswith('-'+binding['commit'][:12]) or not SHA.fullmatch(binding.get('sourceSha256','')) \
            or not native_identity(binding.get('identity')) or not re.fullmatch(r'[a-f0-9]{24}',binding.get('owner','')):
        raise GuardError('Native persistent binding is incomplete or not service-verified')
    native_host_identity(binding['identity'])
    receipt_file=native_file(binding['installReceiptFile'],state)
    relative=receipt_file.relative_to(state.parent).parts
    if len(relative)!=6 or relative[:3]!=('releases',binding['release'],'work') \
            or not re.fullmatch(r'compact-cutover-[a-f0-9]{10}',relative[3]) \
            or relative[4:]!=('native-final','native-production-install.json'):
        raise GuardError('Native install receipt escaped this release cutover')
    receipt,receipt_sha=native_read(receipt_file,state)
    overlay,overlay_sha=native_read(overlay_file,state)
    original_overlay,original_sha=native_read(receipt.get('overlayFile',''),state)
    same=('release','commit','sourceSha256','identity','owner')
    if binding['overlayFile']!=str(overlay_file) or Path(receipt.get('overlayFile',''))!=receipt_file.with_name('native-data.override.json') \
            or receipt_sha!=binding['installReceiptSha256'] \
            or overlay_sha!=binding['overlaySha256'] or original_sha!=receipt.get('overlaySha256') or original_sha!=overlay_sha \
            or overlay!=original_overlay or any(receipt.get(key)!=binding[key] for key in same) \
            or receipt.get('schemaVersion')!=1 or receipt.get('kind')!='doorhandle-pristine-native-install' \
            or receipt.get('status')!='MATERIALIZED_AND_VERIFIED':
        raise GuardError('Native install or overlay raw hashes differ from the persistent source binding')
    truths=('candidateSemanticVerified','productionDataMaterialized','originalVolumesMountedReadOnly','freshIndependentRestoreVerified')
    falsehoods=('runtimeTestVolumesPublished','sourceDriftDetected','privateCredentialFileCopiedIntoPayload')
    if any(receipt.get(key) is not True for key in truths) or any(receipt.get(key) is not False for key in falsehoods) \
            or receipt.get('embeddingProfile')!=NATIVE_PROFILE or receipt.get('embeddingCollection')!=NATIVE_COLLECTION \
            or receipt.get('embeddingDimensions')!=1024 or receipt.get('credentialSource')!='EXISTING_PRIVATE_ECS_ENV' \
            or any(receipt.get(key)!=value for key,value in {'activeRecords':30,'importedHistoryRows':30,'importedMessageRows':25,
                'archivedRecords':2,'archivedHistoryRows':3,'archivedMessageRows':1,'paidModelCalls':0,'llmCalls':0}.items()):
        raise GuardError('Candidate semantics alone cannot authorize production native materialization')
    keys={'doorhandle-mem0-qdrant','doorhandle-qdrant','native-rag-preservation'}
    if set(receipt.get('volumes',{}))!=keys or set(receipt.get('volumeLabels',{}))!=keys \
            or set(receipt.get('originalVolumes',{}))!={'mem0','chroma'}:
        raise GuardError('Native volume identity catalog is incomplete')
    names=[]
    for key in keys:
        name=receipt['volumes'][key].get('name','');names.append(name)
        labels={NATIVE_VOLUME_LABEL:binding['owner'],'io.doorhandle.release':binding['release'],
            'io.doorhandle.source':binding['sourceSha256'],'com.docker.compose.project':PROJECT,'com.docker.compose.volume':key}
        suffix={'doorhandle-mem0-qdrant':'mem0','doorhandle-qdrant':'qdrant','native-rag-preservation':'manifest'}[key]
        if name!='doorhandlecatch-monolith_native-'+binding['release']+'-'+binding['owner']+'-'+suffix \
                or name in receipt['originalVolumes'].values() or receipt['volumeLabels'][key]!=labels:
            raise GuardError('A pristine native volume has an unexpected owner or aliases its original')
    if len(set(names))!=3 or set(overlay)!={'services','volumes'} or set(overlay['services'])!={'mem0','backend'} \
            or set(overlay['volumes'])!=keys or any(overlay['volumes'][key]!={'name':receipt['volumes'][key]['name'],'external':True} for key in keys):
        raise GuardError('Native overlay escaped the admitted services and volumes')
    expected_mem0={'EMBEDDING_PROFILE':NATIVE_PROFILE,'EMBEDDING_MODEL':NATIVE_MODEL,
        'EMBEDDING_BASE_URL':'https://api.siliconflow.cn/v1','MEM0_VECTOR_BACKEND':'qdrant',
        'MEM0_STORAGE_GENERATION':VECTOR_GENERATION,'MEM0_QDRANT_COLLECTION':NATIVE_COLLECTION}
    if overlay['services']['mem0']!={'environment':expected_mem0}:
        raise GuardError('Native overlay attempted to change a memory field outside its vector-space protocol')
    backend=overlay['services']['backend'];env=backend.get('environment',{})
    expected_env={'CHAT_ASSISTANT_RAG_STARTUP_MODE':'PRESERVE_EXISTING',
        'CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST':'/run/doorhandle-rag/preservation.json',
        'CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST_SHA256':receipt.get('ragManifestSha256'),
        'CHAT_ASSISTANT_RAG_PRESERVATION_COMMIT':binding['commit'],
        'EMBEDDING_PROFILE':NATIVE_PROFILE,'EMBEDDING_MODEL':NATIVE_MODEL,'SEMANTIC_STORAGE_GENERATION':VECTOR_GENERATION,
        'SEMANTIC_RAG_COLLECTION':'doorhandle_rag_bge_m3_v1','SEMANTIC_KNOWLEDGE_COLLECTION':'doorhandle_knowledge_bge_m3_v1',
        'SEMANTIC_EXPERIENCE_COLLECTION':'doorhandle_experience_bge_m3_v1'}
    if set(backend)!={'environment','volumes'} or env!=expected_env \
            or backend['volumes']!=[{'type':'volume','source':'native-rag-preservation','target':'/run/doorhandle-rag','read_only':True}] \
            or receipt.get('vectorBackend')!='qdrant' or receipt.get('storageGeneration')!=VECTOR_GENERATION:
        raise GuardError('Native overlay attempted to bypass preserved Qdrant RAG initialization')
    binding={**binding,'nativeBindingSha256':native_hash({key:value for key,value in binding.items() if key!='status'}),'receipt':receipt}
    if config is not None:native_volumes(binding,receipt,config)
    return binding


def native_tree(directory,state):
    directory=Path(directory)
    if directory.resolve(strict=True)!=directory or not directory.is_relative_to(Path(state).parent):
        raise GuardError('Native payload directory escaped the deployment root')
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise GuardError('Native payload root must remain a private owned directory')
    result={};total=0
    def unreadable(error):raise error
    for current,dirs,names in os.walk(directory,followlinks=False,onerror=unreadable):
        for name in dirs+names:
            path=Path(current)/name;info=path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or info.st_uid!=os.getuid() or info.st_mode&0o077:
                raise GuardError('Native payload ownership or type changed')
        for name in sorted(names):
            path=native_file(Path(current)/name,state,maximum=512*1024**2);info=path.stat();total+=info.st_size
            if total>512*1024**2 or len(result)>=16384:raise GuardError('Native payload exceeded its bounded catalog')
            checksum=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024**2),b''):checksum.update(chunk)
            result[path.relative_to(directory).as_posix()]={'bytes':info.st_size,'sha256':checksum.hexdigest()}
        dirs.sort()
    return result


def native_reference(path,expected,sha,state):
    if Path(path)!=expected or not SHA.fullmatch(sha or ''):raise GuardError('Native reference path or digest differs')
    value,actual=native_read(expected,state)
    if actual!=sha:raise GuardError('Native original evidence changed')
    return value


def verify_native_install(binding,state):
    """Initial switch only: verify frozen source and the pristine non-test bytes."""
    receipt=binding['receipt'];root=Path(state).parent;tag=binding['release']
    output=Path(binding['installReceiptFile']).parent;checkout=root/'verification'/tag/'checkout'
    work=checkout/'work/legacy-candidate'
    freeze=native_reference(receipt.get('sourceFreezeFile',''),output.parent/'source-freeze.json',receipt.get('sourceFreezeSha256'),state)
    if freeze.get('schemaVersion')!=1 or freeze.get('kind')!='doorhandle-source-writer-freeze' or not native_ecs_context(freeze.get('ecs'),binding['identity']) \
            or not isinstance(freeze.get('writerContainers'),list) or not freeze['writerContainers'] \
            or any(not CID.fullmatch(value) for value in freeze['writerContainers']):
        raise GuardError('Native source writer freeze is not bound to this ECS')
    candidate=native_reference(work/'legacy-candidate.json',work/'legacy-candidate.json',receipt.get('candidateSha256'),state)
    if any(candidate.get(key)!=binding[key] for key in ('release','commit','sourceSha256','identity')) \
            or candidate.get('originalVolumes')!=receipt['originalVolumes'] \
            or set(candidate.get('originalContainers',{}))!={'mem0','chroma'} \
            or any(not CID.fullmatch(value) for value in candidate['originalContainers'].values()) \
            or not set(candidate.get('originalContainers',{}).values())<=set(freeze['writerContainers']):
        raise GuardError('Native original writers or candidate source changed')
    activation_file=checkout/'work/runtime-acceptance/native-semantic-activation.json'
    activation=native_reference(receipt.get('semanticActivationFile',''),activation_file,receipt.get('semanticActivationSha256'),state)
    if receipt.get('semanticActivation',{}).get('sha256')!=receipt['semanticActivationSha256'] \
            or checkout.parent/receipt['semanticActivation'].get('file','')!=activation_file:
        raise GuardError('Native semantic activation reference differs from its immutable source')
    phases={'after-start','after-restart','after-volume-restore'}
    if activation.get('kind')!='doorhandle-native-semantic-activation' or activation.get('status')!='VERIFIED_AND_ACTIVATED' \
            or any(activation.get(key)!=binding[key] for key in ('release','commit','sourceSha256')) \
            or not native_ecs_context(activation.get('identity'),binding['identity']) \
            or activation.get('candidateSha256')!=receipt['candidateSha256'] or activation.get('productionDataMaterialized') is not False \
            or activation.get('candidateSemanticVerified') is not True or set(activation.get('verifications',{}))!=phases:
        raise GuardError('Native candidate has no complete independent semantic activation evidence')
    for phase,references in activation['verifications'].items():
        for key,prefix in (('readback','native-readback-'),('semantic','bge-semantic-')):
            reference=references.get(key,{})
            expected=activation_file.with_name(prefix+phase+'.json')
            record=native_reference(checkout.parent/reference.get('file',''),expected,reference.get('sha256'),state)
            if record.get('phase')!=phase or record.get('paidModelCalls')!=0 or record.get('llmCalls')!=0 \
                    or record.get('candidateSha256',record.get('descriptorSha256'))!=receipt['candidateSha256']:
                raise GuardError('Native phase does not bind the actual candidate and no-paid-call boundary')
            if key=='readback' and (record.get('status')!='VERIFIED' or record.get('candidateSemanticVerified') is not True
                    or record.get('productionDataMaterialized') is not False or record.get('activatedLocalMem0Records')!=30):
                raise GuardError('Native phase has no completed actual legacy readback')
            if key=='semantic' and (record.get('status')!='SEMANTIC_BRIDGE_VERIFIED' or record.get('collection')!=NATIVE_COLLECTION \
                    or record.get('embeddingProfile')!=NATIVE_PROFILE or record.get('dimensions')!=1024
                    or record.get('semanticQueries',0)<2 or record.get('crossOwnerQueries')!=record['semanticQueries']
                    or record.get('nativeReadOnlyVerified') is not True or record.get('ownedRestoredCopy') is not True
                    or record.get('independentProcess') is not True):
                raise GuardError('Native semantic phase lacks actual owner, read-only and independent restore evidence')
    if set(receipt.get('freshSnapshots',{}))!={'mem0','chroma'} or set(receipt.get('pristinePayloads',{}))!={'doorhandle-mem0-qdrant','doorhandle-qdrant'}:
        raise GuardError('Native fresh snapshots or pristine payload sources are incomplete')
    for service,reference in receipt['freshSnapshots'].items():
        expected=output/('fresh-'+service)/'snapshot-receipt.json'
        proof=native_reference(reference.get('file',''),expected,reference.get('sha256'),state)
        if proof.get('status')!='RESTORED_VERIFIED' or proof.get('fullVolume') is not True or proof.get('sourceMountedReadOnly') is not True \
                or not isinstance(proof.get('sourceBefore'),dict) or not proof['sourceBefore'] \
                or not isinstance(proof.get('normalizedFiles'),dict) or not proof['normalizedFiles'] \
                or proof.get('identity')!=binding['identity'] or reference.get('sourceVolume')!=receipt['originalVolumes'][service] \
                or native_hash(proof.get('normalizedFiles'))!=reference.get('normalizedFilesSha256') \
                or native_hash(proof.get('sourceBefore'))!=reference.get('sourceBeforeSha256') \
                or proof.get('sourceInventorySha256')!=reference['sourceBeforeSha256'] or proof.get('sourceAfterSha256')!=reference['sourceBeforeSha256'] \
                or proof.get('archiveSha256')!=reference.get('archiveSha256'):
            raise GuardError('Native fresh read-only full-volume restore proof changed')
        archive=native_file(expected.with_name('originals.tar'),state,maximum=1024**3)
        checksum=hashlib.sha256()
        with archive.open('rb') as stream:
            for raw in iter(lambda:stream.read(1024**2),b''):checksum.update(raw)
        if checksum.hexdigest()!=reference['archiveSha256'] \
                or native_tree(expected.parent/'restored-originals',state)!=proof['sourceBefore'] \
                or native_tree(expected.parent/'data',state)!=proof['normalizedFiles']:
            raise GuardError('Native final source archive or independent restored bytes differ')
        seen=set();total=0
        class BoundedInfo(tarfile.TarInfo):
            @staticmethod
            def checked_header(value):
                if value.type not in (tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.XHDTYPE,tarfile.XGLTYPE) \
                        or not 0<=value.size<=(512*1024**2 if value.isfile() else 65536):
                    raise GuardError('Native original archive contains unsupported or excessive metadata')
                return value
            @classmethod
            def frombuf(cls,raw,encoding,errors):
                return cls.checked_header(super().frombuf(raw,encoding,errors))
            def _proc_member(self,archive):
                # Enforce before PAX allocation even on tarfile's _frombuf path.
                self.checked_header(self)
                return super()._proc_member(archive)
            def _proc_gnusparse_00(self,*unused):raise GuardError('Native original archive contains foreign sparse metadata')
            _proc_gnusparse_01=_proc_gnusparse_00
            _proc_gnusparse_10=_proc_gnusparse_00
        with tarfile.open(archive,'r:',tarinfo=BoundedInfo) as package:
            for entry in package:
                expected=proof['sourceBefore'].get(entry.name)
                if not entry.isfile() or expected is None or entry.name in seen or '..' in Path(entry.name).parts \
                        or Path(entry.name).is_absolute() or entry.size!=expected['bytes']:
                    raise GuardError('Native original archive does not contain the exact independently restored members')
                total+=entry.size
                if total>512*1024**2 or len(seen)>=16384:raise GuardError('Native original archive exceeded its complete source bound')
                member_sha=hashlib.sha256()
                with package.extractfile(entry) as stream:
                    for raw in iter(lambda:stream.read(1024**2),b''):member_sha.update(raw)
                if member_sha.hexdigest()!=expected['sha256']:raise GuardError('Native original archive member bytes changed')
                seen.add(entry.name)
        if seen!=set(proof['sourceBefore']):raise GuardError('Native original archive omitted a restored source file')
    for key,reference in receipt['pristinePayloads'].items():
        service='mem0' if key=='doorhandle-mem0-qdrant' else 'rag'
        expected=work/(service+'-payload-files.json')
        catalog=native_reference(reference.get('catalogFile',''),expected,reference.get('catalogSha256'),state)
        directory=work/('mem0/data' if service=='mem0' else 'qdrant-candidate')
        if Path(reference.get('directory',''))!=directory or native_tree(directory,state)!=catalog \
                or native_hash(catalog)!=reference.get('filesSha256') or receipt['volumes'][key].get('filesSha256')!=reference['filesSha256'] \
                or receipt['volumes'][key].get('payloadFilesSha256')!=reference['catalogSha256'] \
                or receipt['volumes'][key].get('files')!=len(catalog):
            raise GuardError('Native installed payload is not the pristine fixed-source candidate')


def probe_native_volume(image_id,mount,data='/data',*,full=False,space=True):
    result=json.loads(docker('run','--rm','--pull','never','--network','none','--no-healthcheck','--read-only','--cap-drop','ALL',
        '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=256m','--memory','384m','--cpus','1','--pids-limit','64',
        '--security-opt','no-new-privileges','--user','10001:10001','--mount',f"type=volume,src={mount['name']},dst={mount['destination']},readonly",
        '--env','MEM0_DATA_DIR='+data,'--env','NATIVE_FULL_INVENTORY='+('1' if full else '0'),
        '--env','NATIVE_SPACE_REQUIRED='+('1' if space else '0'),'--entrypoint','python',image_id,'-I','-B','-c',NATIVE_PROBE,timeout=60))
    if space and (result.get('embeddingProfile')!=NATIVE_PROFILE or result.get('collection')!=NATIVE_COLLECTION
            or result.get('vectorBackend')!='qdrant' or result.get('storageGeneration')!=VECTOR_GENERATION
            or result.get('dimensions')!=1024 or not isinstance(result.get('collectionId'),str) or not result['collectionId']):
        raise GuardError('The actual native volume has no verified BGE vector-space marker')
    return result


def probe_native_manifest(image_id,name,expected_sha):
    code="import hashlib,json,os,stat;from pathlib import Path;p=Path('/data/preservation.json');s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_uid==10001 and stat.S_IMODE(s.st_mode)==0o400 and 0<s.st_size<=2097152;assert os.listdir('/data')==['preservation.json'];print(json.dumps({'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))"
    result=json.loads(docker('run','--rm','--pull','never','--network','none','--no-healthcheck','--read-only','--cap-drop','ALL',
        '--memory','64m','--pids-limit','32','--security-opt','no-new-privileges','--user','10001:10001',
        '--mount','type=volume,src='+name+',dst=/data,readonly','--entrypoint','python',image_id,'-I','-B','-c',code,timeout=20))
    if result.get('sha256')!=expected_sha:raise GuardError('The pristine RAG manifest bytes differ from their owned volume')


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


def prepare(state, config, native_transition=None):
    memory, backend = container('mem0'), container('backend')
    desired = config.get('services',{}).get('mem0',{}).get('image')
    if not isinstance(desired,str) or not desired or any(c.isspace() for c in desired):
        raise GuardError('Missing target memory image')
    target_id, target_protocol = image(desired)
    current_id, current_protocol = image(memory['Image'])
    data, mount = data_mount(memory)
    native=validate_native_state(state,config,allow_pending=native_transition is not None)
    initial=native_transition is not None
    if native is None and config.get('services',{}).get('mem0',{}).get('environment',{}).get('EMBEDDING_PROFILE')==NATIVE_PROFILE:
        raise GuardError('BGE activation requires its materialized persistent native source proof')
    if initial:
        if not isinstance(native_transition,(str,os.PathLike)) or native is None \
                or native['status']!='MATERIALIZED_PENDING_SERVICE_READBACK' or Path(native_transition)!=Path(native['installReceiptFile']):
            raise GuardError('An explicit same-release pristine install receipt is required for a native volume switch')
        verify_native_install(native,state)
        if target_id!=native['receipt'].get('images',{}).get('mem0') \
                or image(config['services'].get('backend',{}).get('image',''))[0]!=native['receipt']['images'].get('backend') \
                or image(config['services'].get('qdrant',{}).get('image',''))[0]!=native['receipt']['images'].get('qdrant'):
            raise GuardError('The native install target images differ from their fixed production receipt')
        if mount['name']!=native['receipt']['originalVolumes']['mem0'] or data!='/data' or mount['destination']!='/data':
            raise GuardError('The native transition no longer names its original memory volume')
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
        native_floor=minimum.get('native')
        if initial and native_floor is not None:raise GuardError('An unknown or previously applied native transition cannot be replayed')
        if native is None and native_floor is not None:raise GuardError('The persistent native source binding is missing')
        if native is not None and not initial:
            expected={'bindingSha256':native['nativeBindingSha256'],'installReceiptSha256':native['installReceiptSha256'],
                'embeddingProfile':NATIVE_PROFILE,'collection':NATIVE_COLLECTION,'dimensions':1024}
            if not isinstance(native_floor,dict) or set(native_floor)!=set(expected)|{'collectionId'} \
                    or any(native_floor.get(key)!=value for key,value in expected.items()) or not native_floor.get('collectionId'):
                raise GuardError('The durable native floor is missing or differs from its immutable origin')
        result=json.loads(docker('run','--rm','--pull','never','--network','none','--no-healthcheck','--read-only','--cap-drop','ALL',
                                 '--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=256m','--memory','384m','--cpus','1','--pids-limit','64',
                                 '--security-opt','no-new-privileges','--user','10001:10001','--mount',f"type=volume,src={mount['name']},dst={mount['destination']},readonly",
                                 '--env','MEM0_DATA_DIR='+data,'--entrypoint','python',current_id,'-B','-c',PROBE,timeout=30))
        floor=result.get('requiredProtocol')
        if type(floor) is not int or floor<0:
            raise GuardError('Memory protocol result is invalid')
        floor=max(floor,minimum['requiredProtocol'])
        vector_floor=result.get('vectorSpace')
        if minimum.get('vectorSpace') is not None and minimum['vectorSpace']!=vector_floor:
            raise GuardError('The independent Qdrant generation floor disappeared or changed')
        if vector_floor is not None and native is None:
            raise GuardError('An existing Qdrant space requires its persistent verified install binding')
        if vector_floor is not None and native is None and not native_capable(target_id):
            raise GuardError('Qdrant storage cannot be downgraded to a Chroma-only memory reader')
        if native is None:
            write_json(minimum_path,{'requiredProtocol':floor,'dataMount':mount,'updatedAt':dt.datetime.now(ZONE).isoformat()})
        if result.get('nativeEmbeddingProfile') is not None and native is None:
            raise GuardError('An existing native vector space cannot be read without its persistent install proof')
        selected_mount=mount
        if native is not None:
            floor=max(floor,2)
            target_capable=native_capable(target_id)
            if initial and (not target_capable or target_protocol<floor):
                raise GuardError('The pristine native target requires a compatible BGE image')
            selected_mount={'name':native['receipt']['volumes']['doorhandle-mem0-qdrant']['name'],'destination':'/data'}
            if not initial and selected_mount!=mount:raise GuardError('The active native memory volume changed')
        else:target_capable=True
        keep=target_protocol<floor or not target_capable
        if keep and current_protocol<floor:
            raise GuardError('No compatible memory image; select a compatible recovery version')
        selected_id,selected_protocol=(current_id,current_protocol) if keep else (target_id,target_protocol)
        if native is not None:
            if not native_capable(selected_id):raise GuardError('No selected memory reader supports the persistent BGE floor')
            observed=probe_native_volume(selected_id,selected_mount,full=initial)
            if initial:
                installed=native['receipt']['volumes']['doorhandle-mem0-qdrant']
                if observed.get('filesSha256')!=installed['filesSha256'] or observed.get('files')!=installed['files']:
                    raise GuardError('The pristine memory volume differs from its full copied payload')
                rag=native['receipt']['volumes']['doorhandle-qdrant']
                rag_probe=probe_native_volume(selected_id,{'name':rag['name'],'destination':'/data'},full=True,space=False)
                if rag_probe.get('filesSha256')!=rag['filesSha256'] or rag_probe.get('files')!=rag['files']:
                    raise GuardError('The pristine RAG volume differs from its full copied payload')
                probe_native_manifest(selected_id,native['receipt']['volumes']['native-rag-preservation']['name'],native['receipt']['ragManifestSha256'])
                native_floor={'bindingSha256':native['nativeBindingSha256'],'installReceiptSha256':native['installReceiptSha256'],
                    'embeddingProfile':NATIVE_PROFILE,'collection':NATIVE_COLLECTION,'dimensions':1024,'collectionId':observed['collectionId']}
            elif observed['collectionId']!=native_floor['collectionId']:
                raise GuardError('The persistent native collection identity was reset')
            record.update(nativeBindingSha256=native['nativeBindingSha256'],nativeInitialTransition=initial,
                originalDataMount=mount,dataMount=selected_mount,nativeCollectionId=observed['collectionId'])
        minimum_value={'requiredProtocol':floor,'dataMount':selected_mount,'updatedAt':dt.datetime.now(ZONE).isoformat()}
        if native is not None:
            vector_floor=observed.get('vectorSpace')
        if vector_floor is not None:
            minimum_value['vectorSpace']=vector_floor
            record['vectorSpace']=vector_floor
        if native is not None:minimum_value['native']=native_floor
        if native is not None:write_json(minimum_path,minimum_value)
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
    if record.get('nativeBindingSha256') is not None:
        native=validate_native_state(state,allow_pending=record.get('nativeInitialTransition') is True)
        minimum=read_json(state/'memory-minimum.json')
        if native is None or native['nativeBindingSha256']!=record['nativeBindingSha256'] \
                or minimum.get('native',{}).get('bindingSha256')!=native['nativeBindingSha256'] \
                or minimum.get('dataMount')!=record['dataMount'] or not native_capable(memory['Image']) \
                or health.get('embedding_profile')!=NATIVE_PROFILE or health.get('embedding_collection')!=NATIVE_COLLECTION \
                or health.get('embedding_dimensions')!=1024 or health.get('vector_backend')!='qdrant' \
                or health.get('storage_generation')!=VECTOR_GENERATION or health.get('vector_id_protocol')!=VECTOR_ID_PROTOCOL \
                or health.get('history_mode')!='single-writer-sqlite':
            docker('stop','--time','30',memory['Id'],timeout=45)
            raise GuardError('The activated memory reader does not preserve the persistent native space')
        try:observed=probe_native_volume(memory['Image'],record['dataMount'])
        except Exception:
            docker('stop','--time','30',memory['Id'],timeout=45)
            raise
        if observed['collectionId']!=record['nativeCollectionId']:
            docker('stop','--time','30',memory['Id'],timeout=45)
            raise GuardError('The activated native collection differs from the pristine source')
    record.update(phase='VERIFIED',verifiedAt=dt.datetime.now(ZONE).isoformat());write_json(state/'memory-transition.json',record)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','verify','native-state']);parser.add_argument('--state',required=True);parser.add_argument('--lock-fd',type=int)
    parser.add_argument('--config');parser.add_argument('--allow-pending',action='store_true');parser.add_argument('--native-transition')
    args=parser.parse_args();state=Path(args.state)
    try:
        if state.name!='state' or not state.is_dir() or any(p.is_symlink() for p in (state,*state.parents)):
            raise GuardError('Invalid private deployment state directory')
        if args.action!='native-state' or args.lock_fd is not None:
            import fcntl
            if args.lock_fd is None:raise GuardError('An inherited deployment lock is required')
            descriptor=os.fstat(args.lock_fd);lock=(state/'deploy.lock').stat()
            if (descriptor.st_dev,descriptor.st_ino)!=(lock.st_dev,lock.st_ino):
                raise GuardError('Deployment lock identity differs')
            fcntl.flock(args.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.action=='prepare':print(prepare(state,json.load(sys.stdin),native_transition=Path(args.native_transition) if args.native_transition else None))
        elif args.action=='verify':verify(state)
        else:
            config=json.load(sys.stdin) if args.config=='-' else json.loads(Path(args.config).read_text()) if args.config else None
            native=validate_native_state(state,config,allow_pending=args.allow_pending)
            public={key:native[key] for key in ('status','release','commit','sourceSha256','installReceiptSha256','overlaySha256','nativeBindingSha256')} if native else {'status':'LEGACY_UNBOUND'}
            print(json.dumps(public))
    except Exception:
        print('Memory compatibility verification failed; backend remains gated. Review private transition state before recovery.',file=sys.stderr)
        raise SystemExit(6)


if __name__=='__main__':main()
