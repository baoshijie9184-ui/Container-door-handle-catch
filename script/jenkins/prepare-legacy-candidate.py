"""Prepare private ECS RAG candidates from verified legacy and current cloud data.

Never mounts an original volume writable, invokes a paid model, executes the old
Windows environment, or promotes a candidate. All state belongs to one fixed CI
attempt. A moving online source fails closed instead of pretending it quiesced.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time


ROOT = Path(__file__).resolve().parents[2]
MIB = 1024 ** 2
GIB = 1024 ** 3
DISK_FLOOR = 2 * GIB + 256 * MIB
MAX_BYTES = 512 * MIB
MAX_FILES = 16384
MAX_RAG_RECORDS = 1000
LABEL = 'io.doorhandle.legacy-candidate'


def need(value, message):
    if not value:
        raise ValueError(message)


def canonical(value, *, exists=True):
    path = Path(value)
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=exists) == path,
         'Legacy candidate paths must be canonical and unlinked')
    return path


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''): value.update(block)
    return value.hexdigest()


def read(path, maximum=16 * MIB):
    path = canonical(path)
    need(path.is_file() and path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077
         and 0 < path.stat().st_size <= maximum, 'Private owned candidate evidence required')
    return json.loads(path.read_text(encoding='utf8'))


def write(path, value):
    path = canonical(path, exists=False)
    need(not path.exists(), 'Candidate outcomes are immutable; use a fresh attempt')
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def file_inventory(root):
    root = canonical(root)
    need(root.is_dir(), 'Snapshot root must be a directory')
    rows, total = {}, 0
    def unreadable(error): raise error
    for current, directories, files in os.walk(root, followlinks=False, onerror=unreadable):
        for name in directories + files:
            path = Path(current) / name
            need(not path.is_symlink() and (path.is_dir() or path.is_file()), 'Snapshot cannot contain links or special files')
        for name in sorted(files):
            path = Path(current) / name; info = path.stat(); total += info.st_size
            need(total <= MAX_BYTES and len(rows) < MAX_FILES, 'Complete cloud volume exceeds its explicit snapshot bound')
            rows[path.relative_to(root).as_posix()] = {'bytes': info.st_size, 'sha256': digest(path)}
        directories.sort()
    return rows


def private_tree(root, uid, gid):
    def unreadable(error): raise error
    for current, directories, files in os.walk(root, followlinks=False, onerror=unreadable):
        for path in [Path(current), *(Path(current) / name for name in directories + files)]:
            need(not path.is_symlink(), 'Owned snapshot output contains a link')
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
            if (path.stat().st_uid, path.stat().st_gid) != (uid, gid): os.chown(path, uid, gid)


def sqlite_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=2)) as origin:
        origin.execute('PRAGMA query_only=ON')
        with contextlib.closing(sqlite3.connect(target)) as destination:
            deadline = time.monotonic() + 30
            def progress(*_):
                need(time.monotonic() < deadline, 'Online SQLite backup exceeded its stable-window budget')
            origin.backup(destination, pages=64, progress=progress, sleep=0.01)
            need(destination.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Independent SQLite restore integrity failed')


def source_read_only(source):
    entries = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        parts = line.split()
        if len(parts) < 7: continue
        mount = Path(re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), parts[4]))
        if source == mount or source.is_relative_to(mount): entries.append((len(mount.parts), mount, parts[5].split(',')))
    need(entries, 'The source read-only mount cannot be inspected')
    _, mount, options = max(entries)
    need(mount == source and 'ro' in options, 'A complete source volume must be mounted explicitly read-only')
    return True


def snapshot_volume(source, output, identity, uid, gid):
    """A real read-only stable window, two online copies and independent restore."""
    source, output = canonical(source), canonical(output, exists=False)
    need(not output.exists() and source not in output.parents, 'Cloud snapshot requires a new private destination')
    readonly = source_read_only(source)
    before = file_inventory(source)
    need(before, 'An empty volume cannot stand in for the actual complete cloud source')
    fs = os.statvfs(output.parent)
    required = 5 * sum(row['bytes'] for row in before.values()) + 64 * MIB
    need(fs.f_bavail * fs.f_frsize >= DISK_FLOOR + required, 'Cloud snapshot lacks its retained copies and real disk reserve')
    output.mkdir(mode=0o700)
    try:
        normalized = output / 'data'; normalized.mkdir(mode=0o700)
        second = output / 'sqlite-second'; second.mkdir(mode=0o700)
        databases = []
        for name in before:
            path = source / name
            with path.open('rb') as stream: header = stream.read(16)
            if header == b'SQLite format 3\x00': databases.append(name)
        need(databases, 'Cloud persistent volume has no proven SQLite database')
        for name in databases: sqlite_copy(source / name, normalized / name)
        archive = output / 'originals.tar'
        with tarfile.open(archive, 'x', format=tarfile.PAX_FORMAT, dereference=True) as package:
            for name, row in sorted(before.items()):
                path = source / name; info = package.gettarinfo(str(path), arcname=name)
                need(info.isfile() and info.size == row['bytes'], 'Source archive member changed')
                with path.open('rb') as stream: package.addfile(info, stream)
        sidecars = {name + suffix for name in databases for suffix in ('-wal', '-shm', '-journal')}
        for name in before:
            if name in databases or name in sidecars: continue
            target = normalized / name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        for name in databases:
            sqlite_copy(source / name, second / name)
            need(digest(normalized / name) == digest(second / name), 'Cloud SQLite changed across the complete snapshot window')
        after = file_inventory(source)
        need(after == before, 'Cloud files or SQLite/WAL/index bytes changed during the read-only stable window')
        restored = output / 'restored-originals'; restored.mkdir(mode=0o700)
        with tarfile.open(archive, 'r:') as package:
            seen = set()
            for member in package:
                need(member.isfile() and member.name in before and member.name not in seen
                     and member.size == before[member.name]['bytes'], 'Invalid independent full-volume restore member')
                target = restored / member.name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with package.extractfile(member) as origin, target.open('xb') as destination: shutil.copyfileobj(origin, destination, MIB)
                seen.add(member.name)
        need(file_inventory(restored) == before, 'Independent full-volume byte restore differs')
        report = {'version': 1, 'kind': 'doorhandle-current-volume-online-backup', 'status': 'RESTORED_VERIFIED',
            'identity': identity, 'fullVolume': True, 'sourceMountedReadOnly': readonly,
            'consistency': 'ALL_FILES_STABLE_AND_TWO_IDENTICAL_ONLINE_SQLITE_BACKUPS',
            'sourceBefore': before, 'sourceAfterSha256': sha(after), 'sourceInventorySha256': sha(before),
            'archiveSha256': digest(archive), 'archiveBytes': archive.stat().st_size,
            'normalizedFiles': file_inventory(normalized), 'sqliteDatabases': databases,
            'omittedIntegratedSidecars': sorted(sidecars & set(before)), 'capturedAtUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        write(output / 'snapshot-receipt.json', report)
        return report
    finally:
        private_tree(output, uid, gid)


def collection_catalog(directory):
    path = canonical(directory / 'chroma.sqlite3')
    with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        for table, columns in {'tenants': {'id'}, 'databases': {'id', 'name', 'tenant_id'},
                               'collections': {'id', 'name', 'database_id'}}.items():
            need(columns <= {row[1] for row in db.execute('PRAGMA table_info("' + table + '")')},
                 'The complete current Chroma tenant/database catalog cannot be proven')
        rows = [dict(row) for row in db.execute('SELECT c.id,c.name,d.name AS database_name,d.tenant_id '
            'FROM collections c JOIN databases d ON d.id=c.database_id ORDER BY d.tenant_id,d.name,c.name')]
        need(len(rows) <= 64, 'Chroma collection catalog exceeds the reviewed bound')
        return rows


def complete_chroma(directory, migration):
    from chromadb import PersistentClient
    from chromadb.config import Settings
    catalog = collection_catalog(directory); result = {}; clients = {}
    for row in catalog:
        scope = (row['tenant_id'], row['database_name'])
        client = clients.setdefault(scope, PersistentClient(path=str(directory), tenant=scope[0], database=scope[1],
                                                            settings=Settings(anonymized_telemetry=False)))
        collection = client.get_collection(row['name'], embedding_function=None)
        records = migration.read_collection(collection)
        need(str(collection.id) == row['id'], 'Chroma collection identity differs from its full snapshot catalog')
        key = json.dumps([*scope, row['name']], separators=(',', ':'))
        result[key] = {'tenant': scope[0], 'database': scope[1], 'name': row['name'], 'id': row['id'],
                       'metadata': collection.metadata, 'records': records, 'recordsSha256': sha(records)}
    need(collection_catalog(directory) == catalog, 'Reading complete Chroma changed the collection catalog')
    return result


def native_history(directory):
    path = canonical(directory / 'history.db')
    result = {}
    with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as database:
        database.row_factory = sqlite3.Row; database.execute('PRAGMA query_only=ON'); database.execute('BEGIN')
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in ('history', 'messages'):
            need(name in tables, 'Complete current native history/messages schema is missing')
            rows = database.execute('SELECT * FROM "' + name + '"').fetchall()
            need(len(rows) <= 200000 and all('id' in row.keys() for row in rows), 'Native history exceeds its complete read bound')
            result[name] = {sha([type(row['id']).__name__, row['id']]): sha(dict(row)) for row in rows}
            need(len(result[name]) == len(rows), 'Native history has ambiguous row identities')
    return result


NATIVE_SQL_SCRIPT = r'''
import hashlib,json,sqlite3,sys
from pathlib import Path
def h(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
root=Path(sys.argv[1]); result={'collections':{},'history':{}}
db=sqlite3.connect((root/'chroma/chroma.sqlite3').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert {'collections','segments','embeddings','collection_metadata'} <= tables
for row in db.execute('SELECT * FROM collections'):
 ident=row['id']; segments=[r[0] for r in db.execute("SELECT id FROM segments WHERE collection=? AND scope='METADATA'",(ident,))]
 count=sum(db.execute('SELECT COUNT(*) FROM embeddings WHERE segment_id=?',(segment,)).fetchone()[0] for segment in segments)
 metadata=sorted([dict(r) for r in db.execute('SELECT * FROM collection_metadata WHERE collection_id=?',(ident,))],key=lambda r:json.dumps(r,sort_keys=True))
 result['collections'][ident]={'name':row['name'],'rowSha256':h(dict(row)),'metadataSha256':h(metadata),'records':count}
db.close()
db=sqlite3.connect((root/'history.db').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
for name in ('history','messages'):
 rows=db.execute('SELECT * FROM "'+name+'"').fetchall();assert len(rows)<=200000
 result['history'][name]={h([type(row['id']).__name__,row['id']]):h(dict(row)) for row in rows}
 assert len(result['history'][name])==len(rows)
db.close();print(json.dumps(result,sort_keys=True))
'''


def native_sql_state(directory):
    result = subprocess.run([sys.executable, '-I', '-B', '-c', NATIVE_SQL_SCRIPT, str(directory)],
                            check=True, capture_output=True, timeout=30)
    need(len(result.stdout) <= 32 * MIB, 'Complete native SQLite evidence exceeds its bound')
    return json.loads(result.stdout)


def require_empty_native_collections(before):
    collections = before['collections']
    personal = [row for row in collections.values() if row['name'] == 'doorhandle_memories']
    need(len(personal) == 1 and all(not row['records'] for row in collections.values()),
         'Any nonempty original Mem0 collection requires proven model compatibility; never mix test vectors')
    need({row['id'] for row in collections.values()} == set(before['sqlite']['collections'])
         and all(row['records'] == 0 for row in before['sqlite']['collections'].values()),
         'Complete native collection API/SQLite emptiness evidence disagrees')


def data_worker(context_file):
    """Runs only in the already-admitted temporary Python image/checkout."""
    context = read(context_file)
    migration = module('candidate_legacy_stores', ROOT / 'script/memory/migrate_legacy_stores.py')
    migration.ecs_identity(context['identity']['instanceId'], context['identity']['machineId'])
    work = canonical(context['work']); rag_root = work / 'rag'; rag_root.mkdir(mode=0o700)
    shutil.copytree(work / 'cloud-chroma/data', rag_root / 'chroma')
    mem0 = work / 'mem0'; mem0.mkdir(mode=0o700)
    shutil.copytree(work / 'cloud-mem0/data', mem0 / 'data')
    native_before = {'collections': complete_chroma(mem0 / 'data/chroma', migration), 'history': native_history(mem0 / 'data'),
                     'sqlite': native_sql_state(mem0 / 'data')}
    require_empty_native_collections(native_before)
    write(work / 'mem0-before.json', native_before)
    legacy = work / 'legacy-rag-export-copy'; legacy.mkdir(mode=0o700)
    restored = canonical(context['legacyRestore'])
    native_source = migration.export_legacy(restored / 'personal_chroma/chroma.sqlite3', restored / 'legacy_history/history.db')
    need((len(native_source['records']), len(native_source['history']), len(native_source['messages'])) == (32, 33, 26),
         'Preserved native legacy source does not match the complete admitted 32/33/26 inventory')
    write(work / 'legacy-mem0-export.json', native_source)
    mapping = {'sourceBundleSha256': sha(native_source), 'currentAccountProofSha256': digest(work / 'owner-proof.json'),
        'targetTenantId': None, 'owners': [
            {'sourceOwner': 'admin', 'disposition': 'import', 'userId': 1, 'username': 'admin', 'reason': 'Previously admitted original account binding; freshly reverified on this ECS'},
            {'sourceOwner': 'doorhandlecatch:user:18', 'disposition': 'import', 'userId': 18, 'username': 'inspector.demo', 'reason': 'Previously admitted numeric principal; freshly reverified on this ECS'},
            {'sourceOwner': 'integration-user', 'disposition': 'archive', 'reason': 'Previously reviewed integration-only principal; no real user mapping'}]}
    migration.verify_accounts(mapping, work / 'owner-proof.json', context['identity'])
    projected = migration.project(native_source, mapping)
    need(len(projected['records']) == 30 and len(projected['archivedMemoryIds']) == 2,
         'Legacy native owner dispositions changed; do not infer a new account mapping')
    write(work / 'legacy-mem0-owner-map.json', mapping)
    write(work / 'legacy-mem0-read-verification.json', {'status': 'READ_AND_OWNER_VERIFIED_NOT_ACTIVATED',
        'sourceBundleSha256': sha(native_source), 'ownerMappingSha256': sha(mapping), 'sourceRecords': 32,
        'eligibleRecords': 30, 'activatedRecords': 0, 'archivedRecords': 2, 'sourceHistoryRows': 33, 'sourceMessageRows': 26,
        'eligibleHistoryRows': len(projected['history']), 'activatedHistoryRows': 0, 'archivedHistoryRows': projected['archivedHistoryRows'],
        'eligibleMessageRows': len(projected['messages']), 'activatedMessageRows': 0, 'archivedMessageRows': projected['archivedMessageRows'],
        'originalVectorAndIdReadbackVerified': True, 'modelCallsPerformed': False, 'semanticSearchVerified': False})
    shutil.copytree(restored / 'rag_chroma', legacy / 'rag_chroma')
    for name in ('original-manifest.json', 'restore-receipt.json'): shutil.copyfile(restored / name, legacy / name); os.chmod(legacy / name, 0o600)
    source = migration.rag_export(legacy, 83); write(work / 'legacy-rag-export.json', source)
    before = complete_chroma(rag_root / 'chroma', migration); write(work / 'cloud-chroma-before.json', before)
    from chromadb import PersistentClient
    from chromadb.config import Settings
    client = PersistentClient(path=str(rag_root / 'chroma'), tenant=context['tenant'], database=context['database'],
                              settings=Settings(anonymized_telemetry=False))
    target_key = json.dumps([context['tenant'], context['database'], migration.RAG_COLLECTION], separators=(',', ':'))
    existing = before.get(target_key)
    records = {}
    if existing:
        collection = client.get_collection(migration.RAG_COLLECTION, embedding_function=None)
        page = collection.get(limit=max(1, collection.count()), include=['documents', 'metadatas', 'embeddings'])
        for index, ident in enumerate(page['ids']):
            text, metadata, vector = page['documents'][index], page['metadatas'][index], page['embeddings'][index]
            need(isinstance(text, str) and text.strip() and isinstance(metadata, dict), 'Current cloud RAG text/metadata is incomplete')
            records[ident] = {'id': ident, 'document': text, 'metadata': metadata, 'embedding': list(map(float, vector)),
                'textSha256': hashlib.sha256(text.encode()).hexdigest(), 'originalVectorSha256': hashlib.sha256(migration.vector_bytes(vector)).hexdigest()}
    for row in source['records']:
        if row['id'] in records:
            need(records[row['id']]['document'] == row['document'] and records[row['id']]['metadata'] == row['metadata'],
                 'Legacy/cloud RAG ID conflicts require an explicit reviewed mapping')
        else: records[row['id']] = row
    need(83 <= len(records) <= MAX_RAG_RECORDS and sum(len(row['document'].encode()) for row in records.values()) <= 64 * MIB,
         'Complete preserved RAG union exceeds its bounded Java embedding admission')
    union = {'format': 1, 'kind': 'legacy-rag-private-export', 'collection': migration.RAG_COLLECTION,
        'legacySourceBundleSha256': sha(source), 'currentCloudSnapshotSha256': context['chromaSnapshotSha256'],
        'records': [records[key] for key in sorted(records)]}
    write(work / 'rag-union-export.json', union)
    java_source = ROOT / migration.JAVA_EMBEDDER
    policy = {'sourceBundleSha256': sha(union), 'collection': migration.RAG_COLLECTION, 'projectScopeVerified': True,
        'scopeEvidence': 'The admitted project legacy snapshot plus complete same-ECS project-level cloud RAG collection; no user-owned records accepted',
        'verifiedTargetRuntime': True, 'targetEmbeddingName': 'local-hashing-' + str(context['dimension']),
        'targetDimension': context['dimension'], 'applicationCommit': context['commit'], 'javaSourceSha256': digest(java_source),
        'expectedSourceRecords': len(records), 'dispositions': {key: 'import' for key in records},
        'targetIds': {key: key for key in records}}
    write(work / 'rag-policy.json', policy)
    migration.rag_reembed(union, policy, java_source, context['java'], work / 'java-rag-embedding', work / 'rag-embeddings.json')
    embeddings = read(work / 'rag-embeddings.json', 64 * MIB)
    prepared = migration.prepared_rag_records(union, policy, embeddings)['records']
    # Rebuild only the disposable target RAG collection. All original vectors
    # remain in the full-volume archive; all other collections remain untouched.
    metadata = {**((existing or {}).get('metadata') or {}), 'embedding': policy['targetEmbeddingName']}
    if existing: client.delete_collection(migration.RAG_COLLECTION)
    collection = client.create_collection(migration.RAG_COLLECTION, metadata=metadata, embedding_function=None)
    for offset in range(0, len(prepared), 100):
        batch = prepared[offset:offset + 100]
        collection.add(ids=[row['id'] for row in batch], documents=[row['document'] for row in batch],
                       metadatas=[row['metadata'] for row in batch], embeddings=[row['embedding'] for row in batch])
    after = complete_chroma(rag_root / 'chroma', migration); write(work / 'cloud-chroma-after.json', after)
    need({key: value for key, value in after.items() if key != target_key} == {key: value for key, value in before.items() if key != target_key},
         'Preparing RAG changed another cloud collection')
    actual = after[target_key]['records']; expected = {row['id']: {'metadata': row['metadata'], 'document': row['document'],
        'vectorSha256': hashlib.sha256(migration.vector_bytes(row['embedding'])).hexdigest()} for row in prepared}
    need(actual == expected, 'Complete preserved RAG text/metadata/FLOAT32 readback differs')
    receipt = {'version': 1, 'kind': 'doorhandle-legacy-rag-merge', 'status': 'MERGED_VERIFIED', 'identity': context['identity'],
        'commit': context['commit'], 'sourceSha256': context['sourceSha256'], 'legacyRecords': 83,
        'legacySourceBundleSha256': sha(source), 'sourceBundleSha256': sha(union), 'policySha256': sha(policy),
        'embeddingOutputSha256': digest(work / 'rag-embeddings.json'), 'cloudBeforeSha256': sha(before),
        'cloudAfterSha256': sha(after), 'currentCloudRagRecords': len((existing or {}).get('records', {})),
        'targetRecords': len(actual), 'cloudLogicalTextAndMetadataPreserved': True,
        'originalCloudVectorsRetainedInBackup': True, 'otherCollectionsPreserved': True,
        'allTargetVectorsReembeddedByFixedJava': True, 'modelCallsPerformed': False,
        'cloudSnapshotReceiptSha256': context['chromaSnapshotSha256'], 'legacyRestoreReceiptSha256': context['legacyRestoreReceiptSha256']}
    write(work / 'rag-merge-receipt.json', receipt)
    manifest = {'version': 1, 'kind': 'doorhandle-rag-preservation-v1', 'status': 'MERGED_VERIFIED',
        'applicationCommit': context['commit'], 'tenant': context['tenant'], 'database': context['database'],
        'collection': migration.RAG_COLLECTION, 'collectionId': str(collection.id), 'embeddingProtocol': 'doorhandle-local-hashing-v1',
        'embeddingDimension': context['dimension'], 'javaSourceSha256': digest(java_source), 'sourceBundleSha256': sha(union),
        'policySha256': sha(policy), 'embeddingOutputSha256': digest(work / 'rag-embeddings.json'),
        'mergeReceiptSha256': digest(work / 'rag-merge-receipt.json'), 'collectionSha256': sha(actual),
        'collectionDigestAlgorithm': 'PYTHON_CANONICAL_JSON_READ_COLLECTION_V1', 'recordCount': len(actual),
        'records': [{'id': key, 'documentSha256': hashlib.sha256(row['document'].encode()).hexdigest(),
                     'vectorFloat32Sha256': row['vectorSha256'], 'metadata': row['metadata']} for key, row in sorted(actual.items())]}
    need(len(encoded(manifest)) <= 2 * MIB, 'Private RAG preservation catalogue exceeds its explicit bound')
    write(work / 'rag-preservation-manifest.json', manifest)
    return {'status': 'MERGED_VERIFIED', 'legacyRecords': 83, 'targetRecords': len(actual),
            'ragManifestSha256': digest(work / 'rag-preservation-manifest.json')}


def owned_snapshot_helper(row, *, token, tag, name, image, volume, checkout):
    labels = row.get('Config', {}).get('Labels') or {}; host = row['HostConfig']
    need(labels.get(LABEL) == token and labels.get('io.doorhandle.release') == tag and row['Image'] == image
         and row['Name'] == '/' + name and row['Config']['User'] == '0:0' and row['Config']['Entrypoint'] == ['python']
         and host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] is True and not host['Privileged']
         and host['Memory'] == host['MemorySwap'] == 256 * MIB and host['RestartPolicy']['Name'] == 'no'
         and {entry.removeprefix('CAP_') for entry in host.get('CapDrop') or []} == {'ALL'}
         and {entry.removeprefix('CAP_') for entry in host.get('CapAdd') or []} == {'DAC_READ_SEARCH', 'DAC_OVERRIDE', 'CHOWN', 'FOWNER'},
         'Snapshot cleanup refused a foreign or changed container')
    mounts = row.get('Mounts', [])
    need(len(mounts) == 2 and any(mount['Type'] == 'volume' and mount['Name'] == volume
         and mount['Destination'] == '/source' and not mount['RW'] for mount in mounts)
         and any(mount['Type'] == 'bind' and mount['Source'] == str(checkout)
                 and mount['Destination'] == str(checkout) and mount['RW'] for mount in mounts),
         'Snapshot helper mounts escaped the read-only source or owned checkout')
    return row


def run(args):
    need(sys.platform == 'linux', 'Candidate preparation executes only on ECS')
    root = canonical(args.root); checkout = canonical(root / 'verification' / args.tag / 'checkout')
    need(ROOT == checkout and re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', args.tag)
         and re.fullmatch(r'[a-f0-9]{40}', args.commit) and args.tag.endswith('-' + args.commit[:12])
         and 32 <= args.dimension <= 8192, 'Fixed source candidate identity/dimension required')
    migration = module('candidate_source_preservation', checkout / 'script/memory/migrate_legacy_stores.py')
    identity = migration.ecs_identity(args.instance_id, args.machine_id)
    cutover = module('candidate_source_binding', checkout / 'script/docker/compact-cutover.py')
    cutover.fixed_source(root / 'inbox' / args.tag / 'source.tar.gz', checkout, args.source_sha256, args.commit)
    accepted_file = checkout.parent / 'verification-receipt.json'; accepted = read(accepted_file)
    need(all(accepted.get(key) == value for key, value in {'status': 'PASS', 'verificationExitCode': 0,
         'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
         'identity': {**identity, 'executionLocation': 'ECS'}}.items()), 'Candidate requires this build actual passing ECS verification')
    references = accepted.get('reportFiles', [])
    need(0 < len(references) < 10000, 'Source verification has no original artifact catalogue')
    seen = set()
    for item in references:
        name = item.get('path', '')
        need(name not in seen and '\\' not in name and '..' not in Path(name).parts
             and (name == 'driver.log' or name.startswith('reports/')), 'Invalid passing source artifact reference')
        seen.add(name)
        file = canonical(checkout / 'driver.log' if name == 'driver.log' else checkout / 'work/ci-evidence' / name[8:])
        need(file.is_relative_to(checkout) and file.stat().st_size == item['bytes'] and digest(file) == item['sha256'],
             'An actual source verification artifact is missing or changed')
    need('reports/receipt.json' in seen, 'Passing source verification omitted its executed result receipt')
    restore = canonical(checkout / 'work/legacy-source-restore')
    legacy_receipt = read(restore / 'restore-receipt.json'); original = read(restore / 'original-manifest.json')
    plan = migration.validate_preservation_plan(original)
    need(plan['profile'] == migration.PRESERVATION_KAFKA_PROFILE and plan['kafkaFiles'] == 309
         and plan['kafkaBytes'] == 1184990233 and plan['archiveEncoding'] == 'TAR_GZIP',
         'Complete runtime acceptance requires the independently preserved original Kafka log bytes')
    need(legacy_receipt.get('status') == 'RESTORED_VERIFIED' and legacy_receipt.get('files') == plan['files']
         and legacy_receipt.get('snapshotManifestSha256') == sha(original), 'Legacy source restore is not bound to its fixed snapshot')
    raw_snapshot = canonical(checkout / 'work/legacy-source-snapshot')
    migration.verify_preservation(raw_snapshot)
    need(digest(raw_snapshot / 'snapshot.json') == legacy_receipt['snapshotManifestSha256']
         and digest(raw_snapshot / 'originals.tar') == legacy_receipt['archiveSha256'], 'Sealed legacy inputs changed')
    tool = module('candidate_immutable_tools', checkout / 'script/jenkins/ecs-tool-runtime.py')
    tool_file = root / 'inbox' / args.tag / 'tool-runtime/manifest.json'
    tools, tool_sha = tool.admit(tool_file, root=root, tag=args.tag, commit=args.commit, source_sha=args.source_sha256,
        identity={**identity, 'executionLocation': 'ECS'}, source=checkout)
    common = module('candidate_original_inventory', checkout / 'script/docker/assignment-compat.py')
    work = checkout / 'work/legacy-candidate'; need(not work.exists(), 'Use a fresh candidate attempt; retained outcomes are not overwritten')
    work.mkdir(mode=0o700)
    token = secrets.token_hex(12); snapshots = {}; original_nodes = {}; original_volumes = {}; source_admissions = {}
    ownership = {'version': 1, 'kind': 'doorhandle-legacy-candidate-owner', 'token': token, 'release': args.tag,
        'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity,
        'pythonImage': tools['images']['python'], 'checkout': str(checkout), 'sources': {}}
    for service in ('chroma', 'mem0'):
        original_node = common.container(common.PROJECT, service)
        source_mounts = [mount for mount in original_node['Mounts'] if mount['Type'] == 'volume' and mount['Destination'] == '/data']
        need(original_node['State']['Running'] and len(source_mounts) == 1, 'Original source volume admission is ambiguous')
        ownership['sources'][service] = {'containerId': original_node['Id'], 'volume': source_mounts[0]['Name'],
                                         'helperName': 'doorhandle-legacy-' + token + '-' + service}
    write(work / 'owner.json', ownership)
    for service in ('chroma', 'mem0'):
        node = common.container(common.PROJECT, service); original_nodes[service] = node['Id']
        mounts = [mount for mount in node['Mounts'] if mount['Type'] == 'volume' and mount['Destination'] == '/data']
        need(node['State']['Running'] and len(mounts) == 1, 'Actual original cloud persistent service/volume missing')
        volume = mounts[0]['Name']; original_volumes[service] = volume; target = work / ('cloud-' + service)
        name = 'doorhandle-legacy-' + token + '-' + service
        command = ['docker', 'run', '--name', name, '--pull', 'never', '--network', 'none', '--read-only', '--user', '0:0',
            '--cap-drop', 'ALL', '--cap-add', 'DAC_READ_SEARCH', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER',
            '--security-opt', 'no-new-privileges:true', '--pids-limit', '128', '--memory', '256m', '--memory-swap', '256m',
            '--label', LABEL + '=' + token, '--label', 'io.doorhandle.release=' + args.tag,
            '--mount', 'type=volume,src=' + volume + ',dst=/source,readonly',
            '--mount', 'type=bind,src=' + str(checkout) + ',dst=' + str(checkout),
            '--entrypoint', 'python', tools['images']['python'], '-I', '-B', str(Path(__file__).resolve()), 'snapshot-volume',
            '--source', '/source', '--output', str(target), '--uid', str(os.getuid()), '--gid', str(os.getgid()),
            '--instance-id', args.instance_id, '--machine-id', args.machine_id]
        log = work / ('snapshot-' + service + '.log')
        cid = None
        try:
            with log.open('xb') as stream:
                os.chmod(log, 0o600); process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 600
                while process.poll() is None:
                    fs = os.statvfs(work)
                    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
                    need(fs.f_bavail * fs.f_frsize >= DISK_FLOOR and available >= GIB and time.monotonic() < deadline,
                         'Owned cloud snapshot reached its real resource/time reserve')
                    time.sleep(0.5)
                need(process.returncode == 0, 'Complete stable online snapshot failed; private originals retained')
        finally:
            found = subprocess.run(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'name=^/' + name + '$'], capture_output=True, check=True).stdout.decode().split()
            if found:
                cid = found[0]; row = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
                owned_snapshot_helper(row, token=token, tag=args.tag, name=name, image=tools['images']['python'],
                                      volume=volume, checkout=checkout)
                subprocess.run(['docker', 'stop', '--time', '5', cid], check=True, capture_output=True, timeout=15)
                final = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
                need(not final['State']['Running'] and final['State']['Pid'] == 0, 'Owned snapshot helper did not stop')
                subprocess.run(['docker', 'rm', cid], check=True, capture_output=True)
        snapshots[service] = digest(target / 'snapshot-receipt.json')
        after_node = common.container(common.PROJECT, service)
        need(after_node['Id'] == node['Id'] and all(after_node['State'][key] == node['State'][key]
             for key in ('Running', 'StartedAt', 'Pid')), 'Original source process changed during snapshot')
        write(target / 'source-admission.json', {'kind': 'doorhandle-current-volume-source-admission',
            'status': 'ORIGINAL_RUNNING_UNCHANGED', 'identity': identity, 'originalContainerId': node['Id'],
            'originalState': {key: node['State'][key] for key in ('Running', 'StartedAt', 'Pid')},
            'originalVolume': volume, 'snapshotReceiptSha256': snapshots[service],
            'helperImage': tools['images']['python'], 'sourceMountedReadOnly': True,
            'snapshotHelperContainerId': cid, 'snapshotHelperStopped': True})
        source_admissions[service] = digest(target / 'source-admission.json')
    backend = common.container(common.PROJECT, 'backend'); env = common.environment(backend)
    need(env.get('CHAT_ASSISTANT_CHROMA_COLLECTION', migration.RAG_COLLECTION) == migration.RAG_COLLECTION,
         'A custom current RAG collection needs explicit migration policy; do not silently switch it')
    mysql = common.container(common.PROJECT, 'mysql')
    accounts = [json.loads(line) for line in common.db(mysql,
        "SELECT JSON_OBJECT('userId',id,'username',username) FROM users WHERE id IN (1,18) ORDER BY id;").splitlines()]
    need(accounts == [{'userId': 1, 'username': 'admin'}, {'userId': 18, 'username': 'inspector.demo'}],
         'Fresh original ECS owner identities differ from the admitted monolith mappings')
    write(work / 'owner-proof.json', {'verifiedOnEcs': True, 'identity': identity, 'accounts': accounts,
        'verifiedAtUtc': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime()), 'source': 'READ_ONLY_ORIGINAL_USERS'})
    context = {'work': str(work), 'legacyRestore': str(restore), 'identity': identity, 'commit': args.commit,
        'sourceSha256': args.source_sha256, 'dimension': args.dimension,
        'tenant': env.get('CHAT_ASSISTANT_CHROMA_TENANT', 'default_tenant'),
        'database': env.get('CHAT_ASSISTANT_CHROMA_DATABASE', 'default_database'),
        'java': str(tool_file.parent / 'java'), 'chromaSnapshotSha256': snapshots['chroma'],
        'legacyRestoreReceiptSha256': digest(restore / 'restore-receipt.json')}
    write(work / 'private-context.json', context)
    try:
        with (work / 'data-worker.log').open('xb') as output:
            os.chmod(output.name, 0o600)
            result = subprocess.run([str(tool_file.parent / 'python'), '-I', '-B', str(Path(__file__).resolve()),
                'data-worker', '--context', str(work / 'private-context.json')], cwd=checkout, stdout=output,
                stderr=subprocess.STDOUT, timeout=600, env={key: value for key, value in os.environ.items() if key in ('PATH', 'LANG', 'LC_ALL')})
    except BaseException:
        tool.cleanup(tools)
        raise
    need(result.returncode == 0, 'RAG candidate preparation failed; no original cloud data was modified')
    mem0_files, rag_files = file_inventory(work / 'mem0/data'), file_inventory(work / 'rag/chroma')
    write(work / 'mem0-payload-files.json', mem0_files); write(work / 'rag-payload-files.json', rag_files)
    descriptor = {'version': 1, 'kind': 'doorhandle-legacy-candidate', 'status': 'PREPARED', 'release': args.tag,
        'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity,
        'verificationReceiptSha256': digest(accepted_file), 'toolManifestSha256': tool_sha,
        'legacyRestoreReceiptSha256': context['legacyRestoreReceiptSha256'], 'snapshots': snapshots,
        'legacySourceProfile': plan['profile'], 'legacyKafkaFiles': plan['kafkaFiles'], 'legacyKafkaBytes': plan['kafkaBytes'],
        'legacyKafkaReplay': 'NOT_PERFORMED',
        'sourceAdmissions': source_admissions,
        'ragDataDirectory': str(work / 'rag/chroma'), 'mem0DataDirectory': str(work / 'mem0/data'),
        'ragPayloadFilesSha256': digest(work / 'rag-payload-files.json'), 'mem0PayloadFilesSha256': digest(work / 'mem0-payload-files.json'),
        'mem0BeforeSha256': digest(work / 'mem0-before.json'),
        'legacyMem0ReadVerificationSha256': digest(work / 'legacy-mem0-read-verification.json'),
        'ragManifestSha256': digest(work / 'rag-preservation-manifest.json'), 'mergeReceiptSha256': digest(work / 'rag-merge-receipt.json'),
        'cloudChromaAfterSha256': digest(work / 'cloud-chroma-after.json'), 'originalContainers': original_nodes,
        'originalVolumes': original_volumes,
        'mem0Migration': 'LOCAL_30_NOT_ACTIVATED_SEMANTIC_NOT_VERIFIED_CLOUD_RECORDS_RETAINED',
        'modelCallsPerformed': False, 'productionPromotionAllowed': False}
    write(work / 'legacy-candidate.json', descriptor)
    public = {'status': 'PREPARED', 'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
        'identity': {**identity, 'executionLocation': 'ECS'}, 'legacyRagRecords': 83,
        'descriptorSha256': digest(work / 'legacy-candidate.json'), 'ragManifestSha256': descriptor['ragManifestSha256'],
        'modelCallsPerformed': False, 'productionPromotionAllowed': False}
    write(work / 'public-summary.json', public)
    return {**public, 'publicSummarySha256': digest(work / 'public-summary.json')}


def cleanup(args):
    need(sys.platform == 'linux', 'Candidate cleanup is ECS-only')
    root = canonical(args.root); checkout = canonical(root / 'verification' / args.tag / 'checkout')
    work = checkout / 'work/legacy-candidate'
    migration = module('candidate_cleanup_identity', ROOT / 'script/memory/migrate_legacy_stores.py')
    identity = migration.ecs_identity(args.instance_id, args.machine_id)
    def outcome(status, stopped=0):
        value = {'status': status, 'release': args.tag, 'identity': {**identity, 'executionLocation': 'ECS'},
                 'stoppedHelpers': stopped, 'sourceVolumesPreserved': True, 'hasPublicSummary': False}
        if (work / 'public-summary.json').exists():
            read(work / 'public-summary.json', 16384)
            value.update(hasPublicSummary=True, publicSummarySha256=digest(work / 'public-summary.json'))
        return value
    if not (work / 'owner.json').exists():
        return outcome('NO_RESOURCES')
    owner = read(work / 'owner.json')
    need(owner['identity'] == identity and owner['checkout'] == str(checkout) and owner['release'] == args.tag
         and owner['commit'] == args.commit and owner['sourceSha256'] == args.source_sha256,
         'Candidate cleanup belongs to another attempt or ECS')
    identifiers = subprocess.check_output(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + owner['token']]).decode().split()
    stopped = []
    for cid in identifiers:
        row = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
        source = next((value for value in owner['sources'].values() if row['Name'] == '/' + value['helperName']), None)
        need(source is not None and cid not in {value['containerId'] for value in owner['sources'].values()},
             'Candidate cleanup refused an original or unregistered helper')
        owned_snapshot_helper(row, token=owner['token'], tag=args.tag, name=source['helperName'],
                              image=owner['pythonImage'], volume=source['volume'], checkout=checkout)
        subprocess.run(['docker', 'stop', '--time', '5', cid], check=True, capture_output=True, timeout=15)
        final = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
        need(not final['State']['Running'] and final['State']['Pid'] == 0, 'Owned snapshot helper did not stop')
        subprocess.run(['docker', 'rm', cid], check=True, capture_output=True)
        stopped.append(cid)
    need(not subprocess.check_output(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=' + LABEL + '=' + owner['token']]).strip(),
         'A late candidate helper remains')
    return outcome('STOPPED', len(stopped))


def admit_runtime(ctx):
    work = canonical(ctx.checkout / 'work/legacy-candidate')
    file = work / 'legacy-candidate.json'; value = read(file)
    identity = {key: ctx.identity[key] for key in ('instanceId', 'machineId')}
    need(all(value.get(key) == entry for key, entry in {'version': 1, 'kind': 'doorhandle-legacy-candidate',
        'status': 'PREPARED', 'release': ctx.args.tag, 'commit': ctx.args.commit, 'sourceSha256': ctx.args.source_sha256,
        'legacySourceProfile': 'legacy-stores-with-windows-mcp-and-kafka-v1',
        'legacyKafkaFiles': 309, 'legacyKafkaBytes': 1184990233, 'legacyKafkaReplay': 'NOT_PERFORMED',
        'identity': identity, 'productionPromotionAllowed': False, 'modelCallsPerformed': False}.items()),
        'Legacy candidate belongs to another source, attempt or ECS')
    need(value['verificationReceiptSha256'] == digest(ctx.checkout.parent / 'verification-receipt.json')
         and value['legacyRestoreReceiptSha256'] == digest(ctx.checkout / 'work/legacy-source-restore/restore-receipt.json'),
         'Candidate source verification or original restore evidence changed')
    migration = module('runtime_preservation_profile', ROOT / 'script/memory/migrate_legacy_stores.py')
    original_file = ctx.checkout / 'work/legacy-source-restore/original-manifest.json'
    receipt = read(ctx.checkout / 'work/legacy-source-restore/restore-receipt.json')
    plan = migration.validate_preservation_plan(read(original_file))
    need(plan['profile'] == value['legacySourceProfile'] and plan['kafkaFiles'] == value['legacyKafkaFiles']
         and plan['kafkaBytes'] == value['legacyKafkaBytes'] and plan['archiveEncoding'] == 'TAR_GZIP'
         and digest(original_file) == receipt['snapshotManifestSha256'],
         'Runtime lost the complete original Kafka byte-preservation evidence')
    files = {'rag-preservation-manifest.json': 'ragManifestSha256', 'rag-merge-receipt.json': 'mergeReceiptSha256',
             'cloud-chroma-after.json': 'cloudChromaAfterSha256', 'mem0-before.json': 'mem0BeforeSha256',
             'legacy-mem0-read-verification.json': 'legacyMem0ReadVerificationSha256',
             'rag-payload-files.json': 'ragPayloadFilesSha256', 'mem0-payload-files.json': 'mem0PayloadFilesSha256'}
    for name, key in files.items(): need(digest(canonical(work / name)) == value[key], 'Private native candidate evidence changed')
    for service in ('chroma', 'mem0'):
        snapshot = work / ('cloud-' + service)
        receipt = read(snapshot / 'snapshot-receipt.json')
        need(digest(snapshot / 'snapshot-receipt.json') == value['snapshots'][service]
             and receipt['status'] == 'RESTORED_VERIFIED' and receipt['fullVolume'] is True
             and receipt['sourceMountedReadOnly'] is True
             and receipt['consistency'] == 'ALL_FILES_STABLE_AND_TWO_IDENTICAL_ONLINE_SQLITE_BACKUPS'
             and receipt['identity'] == identity and digest(snapshot / 'originals.tar') == receipt['archiveSha256']
             and file_inventory(snapshot / 'restored-originals') == receipt['sourceBefore']
             and file_inventory(snapshot / 'data') == receipt['normalizedFiles'], 'Complete current cloud backup/restore proof changed')
        admission = read(snapshot / 'source-admission.json')
        need(digest(snapshot / 'source-admission.json') == value['sourceAdmissions'][service]
             and admission['status'] == 'ORIGINAL_RUNNING_UNCHANGED' and admission['identity'] == identity
             and admission['originalContainerId'] == value['originalContainers'][service]
             and admission['originalVolume'] == value['originalVolumes'][service]
             and admission['originalState']['Running'] is True and admission['originalState']['Pid'] > 0
             and admission['snapshotReceiptSha256'] == value['snapshots'][service]
             and admission['sourceMountedReadOnly'] is True and admission['snapshotHelperStopped'] is True,
             'Original running/read-only source admission changed')
    for service in ('rag', 'mem0'):
        data = canonical(value[service + 'DataDirectory'])
        need(data == work / ('rag/chroma' if service == 'rag' else 'mem0/data')
             and file_inventory(data) == read(work / (service + '-payload-files.json')),
             'Materialization input escaped its immutable owned full candidate')
    return value, digest(file), work


def install_volume(source, target, uid=10001, gid=10001):
    source, target = canonical(source), canonical(target)
    expected = file_inventory(source)
    need(not list(target.iterdir()), 'Only an empty newly-owned volume may receive a candidate')
    for name in expected:
        destination = target / name; destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source / name, destination)
    need(file_inventory(target) == expected, 'Owned runtime volume differs from the full candidate')
    private_tree(target, uid, gid)
    return {'status': 'MATERIALIZED', 'files': len(expected), 'bytes': sum(row['bytes'] for row in expected.values()),
            'filesSha256': sha(expected), 'uid': uid, 'gid': gid}


def materialize_runtime(ctx, *, sources=None, suffix=''):
    value, descriptor_sha, work = admit_runtime(ctx)
    sources = sources or {'mem0': canonical(value['mem0DataDirectory']), 'chroma': canonical(value['ragDataDirectory'])}
    results = {}
    for service in ('mem0', 'chroma'):
        logical = 'doorhandle-' + service
        if suffix:
            ctx.config['volumes'][logical]['name'] = ctx.project + '_' + logical + '-' + suffix
        volume = ctx.config['volumes'][logical]['name']
        need(volume.startswith(ctx.project + '_') and volume not in value['originalVolumes'].values(),
             'Runtime native volume is not owned by this attempt')
        ctx.ops.docker('volume', 'create', '--label', 'io.doorhandle.rehearsal=' + ctx.project, volume)
        metadata = json.loads(ctx.ops.docker('volume', 'inspect', volume))[0]
        need(metadata.get('Labels', {}).get('io.doorhandle.rehearsal') == ctx.project, 'Native target volume ownership changed')
        helper = ROOT / 'script/jenkins/prepare-legacy-candidate.py'
        raw = ctx.ops.docker('run', '--rm', '--network', 'none', '--read-only', '--user', '0:0',
            '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER',
            '--security-opt', 'no-new-privileges:true', '--memory', '256m', '--memory-swap', '256m',
            '--label', 'io.doorhandle.rehearsal=' + ctx.project,
            '--mount', 'type=bind,src=' + str(helper) + ',dst=' + str(helper) + ',readonly',
            '--mount', 'type=bind,src=' + str(sources[service]) + ',dst=/candidate,readonly',
            '--mount', 'type=volume,src=' + volume + ',dst=/target', '--entrypoint', 'python', ctx.images['mem0'],
            '-I', '-B', str(helper), 'install-volume', '--source', '/candidate', '--output', '/target', timeout=180)
        result = json.loads(raw); need(result['status'] == 'MATERIALIZED' and result['filesSha256'] == sha(file_inventory(sources[service])),
                                      'Owned native volume payload readback differs')
        results[service] = {'volume': volume, **result}
    if not suffix:
        volume = ctx.config['volumes']['runtime-rag-preservation']['name']
        ctx.ops.docker('volume', 'create', '--label', 'io.doorhandle.rehearsal=' + ctx.project, volume)
        need(json.loads(ctx.ops.docker('volume', 'inspect', volume))[0].get('Labels', {}).get('io.doorhandle.rehearsal') == ctx.project,
             'Private RAG manifest volume is not owned by this attempt')
        raw = (work / 'rag-preservation-manifest.json').read_bytes()
        code = "import os,sys,hashlib,json;p='/target/preservation.json';d=sys.stdin.buffer.read(2097153);assert len(d)<=2097152;f=os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400),'wb');f.write(d);f.flush();os.fsync(f.fileno());f.close();os.chown('/target',10001,10001);os.chmod('/target',0o700);os.chown(p,10001,10001);os.chmod(p,0o400);print(json.dumps({'sha256':hashlib.sha256(open(p,'rb').read()).hexdigest(),'uid':os.stat(p).st_uid,'mode':os.stat(p).st_mode&0o777}))"
        copied = json.loads(ctx.ops.docker('run', '--rm', '-i', '--network', 'none', '--read-only', '--user', '0:0',
            '--cap-drop', 'ALL', '--cap-add', 'DAC_READ_SEARCH', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--memory', '128m', '--memory-swap', '128m',
            '--label', 'io.doorhandle.rehearsal=' + ctx.project, '--mount', 'type=volume,src=' + volume + ',dst=/target',
            '--entrypoint', 'python', ctx.images['mem0'], '-I', '-B', '-c', code, data=raw, timeout=30))
        need(copied == {'sha256': value['ragManifestSha256'], 'uid': 10001, 'mode': 0o400}, 'App-owned private manifest copy changed')
        results['manifest'] = copied
    result = {'status': 'MATERIALIZED', 'descriptorSha256': descriptor_sha, 'volumes': results}
    file = ctx.directory / ('native-materialization' + ('-' + suffix if suffix else '') + '.json'); ctx.common.write_json(file, result)
    return {'file': file.relative_to(ctx.attempt).as_posix(), 'sha256': digest(file)}


HTTP_CHROMA_SCRIPT = r'''
import hashlib,json,struct,sys,urllib.request,urllib.parse
v=json.load(sys.stdin);out={};queries=0
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('Redirect refused')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def get(url,body=None):
 req=urllib.request.Request('http://127.0.0.1:8000'+url,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json',**v['headers']},method='GET' if body is None else 'POST')
 with opener.open(req,timeout=20) as response:raw=response.read(33554433)
 assert len(raw)<=33554432;return json.loads(raw)
def h(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
for key,entry in v['catalog'].items():
 prefix='/api/v2/tenants/'+urllib.parse.quote(entry['tenant'],safe='')+'/databases/'+urllib.parse.quote(entry['database'],safe='')+'/collections/'
 collection=get(prefix+urllib.parse.quote(entry['name'],safe=''));assert collection['id']==entry['id']
 endpoint=prefix+urllib.parse.quote(collection['id'],safe='');count=get(endpoint+'/count');assert count==len(entry['records']) and count<=200000
 rows={};vectors={}
 for offset in range(0,count,200):
  page=get(endpoint+'/get',{'offset':offset,'limit':200,'include':['documents','metadatas','embeddings']})
  for i,ident in enumerate(page['ids']):
   assert ident not in rows;vector=page['embeddings'][i];raw=struct.pack('<'+'f'*len(vector),*vector)
   rows[ident]={'metadata':page['metadatas'][i],'document':page['documents'][i],'vectorSha256':hashlib.sha256(raw).hexdigest()};vectors[ident]=vector
 assert len(rows)==count and get(endpoint+'/count')==count
 if entry['name']==v['ragCollection'] and entry['tenant']==v['tenant'] and entry['database']==v['database']:
  for ident,vector in vectors.items():
   query=get(endpoint+'/query',{'query_embeddings':[vector],'n_results':count,'include':['distances','metadatas','documents']})
   assert ident in query['ids'][0];index=query['ids'][0].index(ident);assert abs(query['distances'][0][index])<=0.0001
   assert query['documents'][0][index]==rows[ident]['document'] and query['metadatas'][0][index]==rows[ident]['metadata'];queries+=1
 out[key]={'tenant':entry['tenant'],'database':entry['database'],'name':entry['name'],'id':collection['id'],'metadata':collection.get('metadata'),'records':rows,'recordsSha256':h(rows)}
for tenant,database in {(e['tenant'],e['database']) for e in v['catalog'].values()}:
 prefix='/api/v2/tenants/'+urllib.parse.quote(tenant,safe='')+'/databases/'+urllib.parse.quote(database,safe='')+'/collections'
 actual=get(prefix+'?limit=1000&offset=0');expected={e['id'] for e in v['catalog'].values() if e['tenant']==tenant and e['database']==database}
 assert {e['id'] for e in actual}==expected
print(json.dumps({'collections':out,'retrievalQueries':queries},sort_keys=True))
'''


def verify_runtime(ctx, phase):
    value, descriptor_sha, work = admit_runtime(ctx)
    need(phase in ('after-start', 'after-restart', 'after-volume-restore'), 'Unregistered native runtime verification phase')
    manifest = read(work / 'rag-preservation-manifest.json')
    expected = read(work / 'cloud-chroma-after.json', 64 * MIB)
    env = ctx.config['services']['backend']['environment']
    headers = {'x-chroma-token': env['CHAT_ASSISTANT_CHROMA_TOKEN']} if env.get('CHAT_ASSISTANT_CHROMA_TOKEN') else {}
    actual = json.loads(ctx.ops.docker('exec', '-i', ctx.row('chroma')['Id'], 'python', '-I', '-B', '-c', HTTP_CHROMA_SCRIPT,
        data=encoded({'catalog': expected, 'headers': headers, 'ragCollection': manifest['collection'],
                      'tenant': manifest['tenant'], 'database': manifest['database']}), timeout=180))
    need(actual['collections'] == expected and actual['retrievalQueries'] == manifest['recordCount'],
         'Actual post-startup HTTP RAG retrieval lost a cloud or imported record/source/vector')
    native = json.loads(ctx.ops.docker('exec', ctx.row('mem0')['Id'], 'python', '-I', '-B', '-c', NATIVE_SQL_SCRIPT, '/data', timeout=30))
    before = read(work / 'mem0-before.json', 32 * MIB)['sqlite']
    need(all(row['records'] == 0 and native['collections'].get(key) == row for key, row in before['collections'].items()),
         'Original cloud Mem0 collection identity/configuration/vector records changed')
    test_name = 'doorhandle_runtime_test_' + ctx.token
    need(all(key in before['collections'] or row['name'] == test_name for key, row in native['collections'].items()),
         'An unexpected native collection appeared outside the isolated test namespace')
    for table, rows in before['history'].items():
        need(all(native['history'][table].get(key) == checksum for key, checksum in rows.items()),
             'Existing current-cloud native history/messages changed after application startup')
    if phase == 'after-volume-restore':
        recovery = ctx.owner.get('nativeRecovery', {})
        directory = canonical(recovery.get('directory', ''))
        need(digest(directory / 'native-before-sql.json') == recovery.get('beforeSha256')
             and digest(directory / 'native-recovery.json') == recovery.get('recoveryProofSha256'),
             'Post-business native recovery evidence changed')
        previous = read(directory / 'native-before-sql.json', 32 * MIB)
        need(all(native['collections'].get(key) == row for key, row in previous['collections'].items())
             and all(native['history'][table].get(key) == checksum for table, rows in previous['history'].items()
                     for key, checksum in rows.items()), 'Native recovery lost a post-business collection/history/message record')
    result = {**ctx.context(), 'kind': 'doorhandle-legacy-runtime-readback', 'status': 'VERIFIED', 'phase': phase,
        'project': ctx.project, 'descriptorSha256': descriptor_sha, 'ragManifestSha256': value['ragManifestSha256'],
        'allCloudCollectionsSha256': sha(actual['collections']), 'retrievalQueries': actual['retrievalQueries'],
        'sourceAndDocumentAndFloat32Verified': True, 'preservedOriginalNativeCollections': len(before['collections']),
        'preservedOriginalHistoryRows': len(before['history']['history']), 'preservedOriginalMessageRows': len(before['history']['messages']),
        'nativeStateSha256': sha(native), 'eligibleLocalMem0Records': 30, 'activatedLocalMem0Records': 0, 'localMem0ArchivedRecords': 2,
        'localMem0SemanticStatus': 'NOT_ACTIVATED_SEMANTIC_NOT_VERIFIED', 'paidModelCalls': 0,
        'testNamespace': test_name, 'productionPromotionAllowed': False}
    file = ctx.directory / ('native-readback-' + phase + '.json')
    need(not file.exists(), 'Native phase readback must not overwrite an earlier outcome')
    ctx.common.write_json(file, result)
    reference = {'file': file.relative_to(ctx.attempt).as_posix(), 'sha256': digest(file)}
    ctx.owner.setdefault('nativeVerifications', {})[phase] = reference; ctx.save()
    return reference


def snapshot_runtime(ctx, folder):
    """Back up the POST-business owned volumes; original business stays running."""
    need(not folder.exists(), 'Native recovery backup must be a new retained outcome')
    folder.mkdir(mode=0o700)
    ctx.ops.docker('stop', '--time', '30', ctx.row('chroma')['Id'], timeout=60)
    need(not ctx.row('chroma')['State']['Running'], 'Owned Chroma did not freeze for complete recovery')
    results = {}
    native_before = None
    for service in ('mem0', 'chroma'):
        need(not ctx.row(service)['State']['Running'] and ctx.row(service)['State']['Pid'] == 0,
             'An owned native writer is still running at backup')
        volume = ctx.config['volumes']['doorhandle-' + service]['name']
        metadata = json.loads(ctx.ops.docker('volume', 'inspect', volume))[0]
        need(metadata.get('Labels', {}).get('io.doorhandle.rehearsal') == ctx.project, 'Native backup source is not owned')
        target = folder / service
        helper = ROOT / 'script/jenkins/prepare-legacy-candidate.py'
        if service == 'mem0':
            native_before = json.loads(ctx.ops.docker('run', '--rm', '--network', 'none', '--read-only', '--user', '0:0',
                '--cap-drop', 'ALL', '--cap-add', 'DAC_READ_SEARCH', '--memory', '128m', '--memory-swap', '128m',
                '--label', 'io.doorhandle.rehearsal=' + ctx.project, '--mount', 'type=volume,src=' + volume + ',dst=/source,readonly',
                '--entrypoint', 'python', ctx.images['mem0'], '-I', '-B', '-c', NATIVE_SQL_SCRIPT, '/source', timeout=30))
            write(folder / 'native-before-sql.json', native_before)
        ctx.ops.docker('run', '--rm', '--network', 'none', '--read-only', '--user', '0:0', '--cap-drop', 'ALL',
            '--cap-add', 'DAC_READ_SEARCH', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--memory', '256m', '--memory-swap', '256m',
            '--label', 'io.doorhandle.rehearsal=' + ctx.project,
            '--mount', 'type=volume,src=' + volume + ',dst=/source,readonly',
            '--mount', 'type=bind,src=' + str(ctx.checkout) + ',dst=' + str(ctx.checkout),
            '--mount', 'type=bind,src=' + str(helper) + ',dst=' + str(helper) + ',readonly',
            '--entrypoint', 'python', ctx.images['mem0'], '-I', '-B', str(helper), 'snapshot-volume',
            '--source', '/source', '--output', str(target), '--uid', str(os.getuid()), '--gid', str(os.getgid()),
            '--instance-id', ctx.identity['instanceId'], '--machine-id', ctx.identity['machineId'], timeout=300)
        receipt = read(target / 'snapshot-receipt.json')
        need(receipt['status'] == 'RESTORED_VERIFIED' and receipt['fullVolume'] is True, 'Owned full native backup was not restored')
        results[service] = {'file': str(target / 'snapshot-receipt.json'), 'sha256': digest(target / 'snapshot-receipt.json')}
    write(folder / 'native-recovery.json', {'status': 'RESTORED_VERIFIED', 'project': ctx.project, 'snapshots': results,
                                          'nativeBeforeSha256': digest(folder / 'native-before-sql.json'),
                                          'phase': 'POST_BUSINESS', 'originalBusinessResourcesChanged': False})
    return folder


def restore_runtime(ctx, folder):
    proof = read(folder / 'native-recovery.json')
    need(proof['status'] == 'RESTORED_VERIFIED' and proof['project'] == ctx.project and proof['phase'] == 'POST_BUSINESS',
         'Native recovery does not belong to this post-business runtime')
    need(digest(folder / 'native-before-sql.json') == proof['nativeBeforeSha256'], 'Post-business native before-state changed')
    sources = {}
    for service, descriptor in proof['snapshots'].items():
        file = canonical(descriptor['file']); receipt = read(file)
        need(digest(file) == descriptor['sha256'] and file.parent == folder / service
             and file_inventory(file.parent / 'data') == receipt['normalizedFiles'], 'Full native recovery backup changed')
        sources[service] = file.parent / 'data'
    reference = materialize_runtime(ctx, sources=sources, suffix='restored-' + secrets.token_hex(4))
    ctx.common.write_json(ctx.directory / 'compose.json', ctx.config)
    ctx.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '180', 'chroma', timeout=240)
    ctx.owner['nativeRecovery'] = {'directory': str(folder), 'beforeSha256': proof['nativeBeforeSha256'],
                                   'recoveryProofSha256': digest(folder / 'native-recovery.json')}
    ctx.save()
    return reference


def measure_runtime_volumes(ctx):
    result = {}
    code = "import os,json;from pathlib import Path;r=Path('/source');files=[p for p in r.rglob('*') if p.is_file()];assert all(not p.is_symlink() for p in r.rglob('*'));print(json.dumps({'files':len(files),'bytes':sum(p.stat().st_size for p in files)}))"
    for service in ('mem0', 'chroma'):
        volume = ctx.config['volumes']['doorhandle-' + service]['name']
        need(volume.startswith(ctx.project + '_'), 'Cannot measure a foreign native volume')
        result[service] = json.loads(ctx.ops.docker('run', '--rm', '--network', 'none', '--read-only', '--user', '0:0',
            '--cap-drop', 'ALL', '--cap-add', 'DAC_READ_SEARCH', '--memory', '128m', '--memory-swap', '128m',
            '--label', 'io.doorhandle.rehearsal=' + ctx.project, '--mount', 'type=volume,src=' + volume + ',dst=/source,readonly',
            '--entrypoint', 'python', ctx.images['mem0'], '-I', '-B', '-c', code, timeout=30))
        need(0 < result[service]['files'] <= MAX_FILES and 0 < result[service]['bytes'] <= MAX_BYTES,
             'Native recovery volume exceeds its actual complete snapshot bound')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('run')
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'): prepare.add_argument('--' + name, required=True)
    prepare.add_argument('--dimension', type=int, required=True)
    clean = sub.add_parser('cleanup')
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'): clean.add_argument('--' + name, required=True)
    snapshot = sub.add_parser('snapshot-volume')
    for name in ('source', 'output', 'instance-id', 'machine-id'): snapshot.add_argument('--' + name, required=True)
    snapshot.add_argument('--uid', required=True, type=int); snapshot.add_argument('--gid', required=True, type=int)
    worker = sub.add_parser('data-worker'); worker.add_argument('--context', required=True)
    install = sub.add_parser('install-volume')
    install.add_argument('--source', required=True); install.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'run': result = run(args)
        elif args.action == 'cleanup': result = cleanup(args)
        elif args.action == 'snapshot-volume': result = snapshot_volume(Path(args.source), Path(args.output),
            {'instanceId': args.instance_id, 'machineId': args.machine_id}, args.uid, args.gid)
        elif args.action == 'install-volume': result = install_volume(Path(args.source), Path(args.output))
        else: result = data_worker(args.context)
        print(json.dumps(result if args.action != 'snapshot-volume' else {'status': result['status']}, sort_keys=True)); return 0
    except BaseException as error:
        failure = {'status': 'FAILED', 'errorType': type(error).__name__}
        if args.action == 'run':
            try:
                need(re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', args.tag) and re.fullmatch(r'[a-f0-9]{40}', args.commit)
                     and re.fullmatch(r'[a-f0-9]{64}', args.source_sha256) and re.fullmatch(r'i-[a-z0-9]+', args.instance_id)
                     and re.fullmatch(r'[a-f0-9]{32}', args.machine_id), 'Invalid failed attempt identity')
                work = canonical(Path(args.root) / 'verification' / args.tag / 'checkout/work/legacy-candidate')
                failure.update(release=args.tag, commit=args.commit, sourceSha256=args.source_sha256,
                    identity={'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'},
                    modelCallsPerformed=False, productionPromotionAllowed=False)
                if not (work / 'public-summary.json').exists(): write(work / 'public-summary.json', failure)
                failure['publicSummarySha256'] = digest(work / 'public-summary.json')
            except BaseException: pass
        print(json.dumps(failure), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
