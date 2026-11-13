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
import socket
import sqlite3
import subprocess
import sys
import tarfile
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
MIB = 1024 ** 2
GIB = 1024 ** 3
DISK_FLOOR = 2 * GIB + 256 * MIB
MAX_BYTES = 512 * MIB
MAX_FILES = 16384
MAX_RAG_RECORDS = 1000
LABEL = 'io.doorhandle.legacy-candidate'
BGE_PROFILE = 'siliconflow-bge-m3-v1'
BGE_MODEL = 'BAAI/bge-m3'
BGE_BASE = 'https://api.siliconflow.cn/v1'
BGE_COLLECTION = 'doorhandle_memories_bge_m3_v1'
BGE_DIMENSION = 1024
SEMANTIC_PHASES = ('after-start', 'after-restart', 'after-volume-restore')
BGE_VERIFIER_MEMORY = 768 * MIB
NATIVE_CUTOVER_LABEL = 'io.doorhandle.native-cutover'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *arguments):
        raise ValueError('Private bridge verification cannot follow redirects')


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


def admit_target_image(root, tag, commit, source_sha, identity, settings):
    """Consume this attempt's managed image preparation; never trust a naked tag/ID."""
    directory = canonical(Path(root) / 'verification' / tag / 'checkout/work/middleware-fixture/image-preparation')
    resources = module('legacy_qdrant_image_admission', ROOT / 'script/docker/compact-build-resources.py')
    context = {'release': tag, 'commit': commit, 'sourceSha256': source_sha,
               'identity': {key: identity[key] for key in ('instanceId', 'machineId', 'executionLocation') if key in identity}}
    context['identity']['executionLocation'] = 'ECS'
    proof = resources.admit_qdrant_image(directory.parents[2], context)
    image = proof['engineIdentity']['engineImageId']
    need('qdrantImage' not in settings or settings['qdrantImage'] == image,
         'Explicit Qdrant image differs from this build managed immutable image')
    return image


def private_bge_config(runtime):
    """Read only the explicitly prepared ECS profile; never inherit LLM keys."""
    runtime = canonical(runtime)
    path = canonical(runtime / 'deploy/cloud.env')
    need(path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077
         and 0 < path.stat().st_size <= MIB, 'Prepared ECS embedding settings must remain private')
    names = {'EMBEDDING_PROFILE', 'EMBEDDING_MODEL', 'EMBEDDING_BASE_URL', 'EMBEDDING_API_KEY', 'EMBEDDING_API_KEY_FILE'}
    selected = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=(.*)', line)
        if match is None or match[1] not in names: continue
        need(match[1] not in selected, 'Prepared embedding settings contain a duplicate field')
        value = match[2].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"): value = value[1:-1]
        selected[match[1]] = value
    need(selected.get('EMBEDDING_PROFILE') == BGE_PROFILE and selected.get('EMBEDDING_MODEL') == BGE_MODEL
         and selected.get('EMBEDDING_BASE_URL', '').rstrip('/') == BGE_BASE,
         'Legacy activation requires the exact prepared free BGE profile')
    literal, filename = selected.get('EMBEDDING_API_KEY'), selected.get('EMBEDDING_API_KEY_FILE')
    # The actual production Compose contract requires this private env value.
    # Do not admit file-only settings that cannot survive a normal deployment
    # or silently mount a transient candidate credential in production.
    need(bool(literal) and not filename, 'Current production Compose requires the persistent private ECS embedding env credential')
    need(isinstance(literal, str) and re.fullmatch(r'sk-[A-Za-z0-9_-]{20,4090}', literal), 'Prepared embedding credential is invalid')
    return {'embeddingProfile': BGE_PROFILE, 'model': BGE_MODEL, 'baseUrl': BGE_BASE, 'dimensions': None,
            'verifiedTargetRuntime': True, 'apiKey': literal}


def semantic_plan(bundle, mapping, migration, cloud_records=None):
    """Bind partial-source natural-language questions to exact owned legacy IDs.

    This is a repeatable source-anchored retrieval check, not a broad human quality
    benchmark. Questions are neither original documents nor saved source vectors.
    All questions/IDs remain in the private ECS candidate, never public receipts.
    """
    projected = migration.project(bundle, mapping)
    all_records = {row['id']: row for row in projected['records']}
    for row in cloud_records or []:
        if row['id'] in all_records:
            need(all_records[row['id']]['metadata'] == row['metadata'], 'Cloud/legacy memory ownership or text conflicts')
        else: all_records[row['id']] = row
    owners = sorted({row['metadata']['user_id'] for row in all_records.values()})
    need(len(owners) >= 2, 'Semantic activation requires two explicitly mapped account scopes')
    cases = []
    groups = [('LEGACY', projected['records'])]
    if cloud_records: groups.append(('CURRENT_CLOUD', cloud_records))
    for origin, source_rows in groups:
      for owner in sorted({row['metadata']['user_id'] for row in source_rows}):
        rows = sorted((row for row in source_rows if row['metadata']['user_id'] == owner),
                      key=lambda row: (-len(row['metadata']['data']), row['id']))
        row = rows[0]; text = ' '.join(row['metadata']['data'].split())
        need(bool(text), 'Legacy semantic query needs a nonempty source anchor')
        anchor = text[:min(96, max(1, len(text) // 2))]
        if ' ' in anchor: anchor = anchor.rsplit(' ', 1)[0]
        query = 'What should be remembered about ' + anchor.rstrip(' .,:;!?') + '?'
        need(query != text and len(query.encode()) <= 8000 and bool(anchor),
             'Semantic question cannot repeat the complete memory or omit its source anchor')
        case = {'owner': owner, 'query': query, 'querySha256': hashlib.sha256(query.encode()).hexdigest(),
            'expectedId': row['id'], 'expectedTextSha256': row['textSha256'],
            'topK': min(5, sum(r['metadata']['user_id'] == owner for r in all_records.values()))}
        if cloud_records: case['origin'] = origin
        if not any(c['owner'] == owner and c['querySha256'] == case['querySha256'] for c in cases): cases.append(case)
    result = {'version': 1, 'kind': 'doorhandle-legacy-bge-semantic-plan', 'protocol': 'SOURCE_ANCHORED_NATURAL_LANGUAGE_QUERY_V1',
        'sourceBundleSha256': migration.sha(migration.canonical(bundle)), 'ownerMappingSha256': migration.sha(migration.canonical(mapping)),
        'embeddingProfile': BGE_PROFILE, 'model': BGE_MODEL, 'collection': BGE_COLLECTION, 'dimensions': BGE_DIMENSION,
        'cases': cases}
    if cloud_records: result['currentCloudRecordsSha256'] = sha(cloud_records)
    return result


def cloud_memory_records(data, before, mapping, migration):
    """Read all frozen cloud records and prove their exact project/account scope.

    Unmarked vectors remain in their original collection. Only a separately
    named, already model-bound BGE collection can reuse original vectors.
    """
    from chromadb import PersistentClient
    from chromadb.config import Settings
    from memory_service.embedding_config import SPACE_METADATA
    owners = {entry['sourceOwner']: 'doorhandlecatch:user:' + str(entry['userId'])
              for entry in mapping['owners'] if entry['disposition'] == 'import'}
    owners.update({value: value for value in list(owners.values())})
    need(set(before['sqlite']['collections']) == {row['id'] for row in before['collections'].values()},
         'Complete native API/SQLite collection catalogue differs')
    records = {}; bound_vectors = {}; clients = {}
    for key, scope in sorted(before['collections'].items()):
        need(before['sqlite']['collections'][scope['id']]['records'] == len(scope['records']), 'Cloud collection count differs from SQLite')
        if not scope['records']: continue
        need(scope['tenant'] == 'default_tenant' and scope['database'] == 'default_database',
             'A nondefault Mem0 namespace requires an explicit account/project migration policy')
        client = clients.setdefault(key, PersistentClient(path=str(data / 'chroma'), tenant=scope['tenant'], database=scope['database'],
                                                        settings=Settings(anonymized_telemetry=False)))
        collection = client.get_collection(scope['name'], embedding_function=None)
        bound = scope['name'] == BGE_COLLECTION
        if bound: need(all((scope['metadata'] or {}).get(k) == v for k, v in SPACE_METADATA.items()),
                       'Existing BGE collection lacks its exact provider/model/dimension identity')
        for offset in range(0, collection.count(), 500):
            page = collection.get(offset=offset, limit=500, include=['metadatas', 'documents', 'embeddings'])
            for index, ident in enumerate(page['ids']):
                meta = dict(page['metadatas'][index] or {}); text = meta.get('data'); owner = meta.get('user_id')
                need(isinstance(ident, str) and isinstance(text, str) and text.strip() and len(text.encode()) <= 8000
                     and owner in owners and meta.get('agent_id') in (None, 'doorhandlecatch')
                     and page['documents'][index] in (None, text), 'A cloud memory has unknown owner/application/text provenance')
                raw = migration.vector_bytes(page['embeddings'][index])
                meta.update(user_id=owners[owner], agent_id='doorhandlecatch')
                row = {'id': ident, 'metadata': meta, 'textSha256': hashlib.sha256(text.encode()).hexdigest(),
                       'originalVectorSha256': hashlib.sha256(raw).hexdigest(), 'embedding': list(map(float, page['embeddings'][index]))}
                if ident in records: need(records[ident]['metadata'] == meta, 'Cloud collections reuse an ID for different memory/owner')
                else: records[ident] = row
                if bound:
                    need(len(row['embedding']) == BGE_DIMENSION and page['metadatas'][index] == meta,
                         'Bound BGE memory has inconsistent vector dimension or owner namespace')
                    bound_vectors[ident] = row
                    records[ident] = row
    need(len(records) <= 1000, 'Cloud memory union exceeds the reviewed bounded migration')
    return [records[key] for key in sorted(records)], bound_vectors


def verify_semantic_bridge(bundle, mapping, plan, base, token, migration, cloud_records=None):
    projected = migration.project(bundle, mapping)
    expected = semantic_plan(bundle, mapping, migration, cloud_records)
    need(plan == expected, 'Semantic questions or expected legacy IDs changed')
    by_id = {row['id']: row for row in projected['records']}
    by_id.update({row['id']: row for row in cloud_records or []})
    by_owner = {owner: {row['id'] for row in by_id.values() if row['metadata']['user_id'] == owner}
                for owner in {row['metadata']['user_id'] for row in by_id.values()}}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), migration.NoRedirect())

    def request(body, authenticated=True):
        headers = {'Content-Type': 'application/json', 'X-Doorhandle-Memory-Protocol': '2'}
        if authenticated: headers['X-Doorhandle-Memory-Token'] = token
        try:
            with opener.open(urllib.request.Request(base + '/memories/search', data=encoded(body), headers=headers, method='POST'), timeout=30) as response:
                raw = response.read(2 * MIB + 1); need(len(raw) <= 2 * MIB, 'Semantic response exceeds its private bound')
                return response.status, json.loads(raw)
        except urllib.error.HTTPError as error: return error.code, None

    observed = []; provider_requests = 0
    for case in plan['cases']:
        body = {'user_id': case['owner'], 'app_id': 'doorhandlecatch', 'query': case['query'], 'scope': 'ACCOUNT', 'top_k': case['topK']}
        code, _ = request(body, authenticated=False)
        need(code == 401, 'Unauthenticated semantic search was not denied')
        for owner in (case['owner'], next(value for value in sorted(by_owner) if value != case['owner'])):
            code, result = request({**body, 'user_id': owner}); provider_requests += 1
            need(code == 200 and isinstance(result, dict) and result.get('code') == 200 and isinstance(result.get('data'), list), 'Actual owned BGE search failed')
            items = result['data']
            need(all(isinstance(item, dict) and isinstance(item.get('id'), str) and isinstance(item.get('memory'), str)
                     for item in items), 'Semantic search returned an invalid result shape')
            ids = [item['id'] for item in items]
            need(len(ids) == len(set(ids)) and set(ids) <= by_owner[owner]
                 and not set(ids).intersection(projected['archivedMemoryIds']), 'Actual semantic search crossed an owner or private archive boundary')
            need(all(hashlib.sha256(item.get('memory', '').encode()).hexdigest() == by_id[item['id']]['textSha256'] for item in items),
                 'Actual semantic search returned another source text')
            if owner == case['owner']:
                need(case['expectedId'] in ids and len(ids) <= case['topK'], 'Actual natural-language BGE query did not retrieve its bound legacy target')
                observed.append({'ownerSha256': hashlib.sha256(owner.encode()).hexdigest(), 'querySha256': case['querySha256'],
                    'expectedIdSha256': hashlib.sha256(case['expectedId'].encode()).hexdigest(), 'rank': ids.index(case['expectedId']) + 1,
                    'topK': case['topK'], 'sourceTextSha256': case['expectedTextSha256'], 'unauthenticatedReadStatus': 401})
            else:
                need(case['expectedId'] not in ids, 'A foreign account retrieved the original query target')
    return {'status': 'SEMANTIC_BRIDGE_VERIFIED', 'planSha256': sha(plan), 'queryProtocol': plan['protocol'],
        'queries': observed, 'semanticQueries': len(observed), 'crossOwnerQueries': len(observed),
        'embeddingRequests': provider_requests, 'paidModelCalls': 0, 'llmCalls': 0}


def validate_semantic_receipt(value, plan):
    expected = {(hashlib.sha256(case['owner'].encode()).hexdigest(), case['querySha256']): case for case in plan['cases']}
    rows = value.get('queries')
    need(isinstance(rows, list) and len(rows) == len(expected) >= 2 and value.get('planSha256') == sha(plan)
         and value.get('queryProtocol') == plan['protocol'] and value.get('semanticQueries') == value.get('crossOwnerQueries') == len(expected)
         and value.get('embeddingRequests') == 2 * len(expected), 'Semantic receipt lacks the exact actual owner queries')
    seen = set()
    for row in rows:
        key = (row.get('ownerSha256'), row.get('querySha256')); case = expected.get(key)
        need(case is not None and key not in seen
             and row.get('expectedIdSha256') == hashlib.sha256(case['expectedId'].encode()).hexdigest()
             and row.get('sourceTextSha256') == case['expectedTextSha256'] and row.get('topK') == case['topK']
             and type(row.get('rank')) is int and 1 <= row['rank'] <= case['topK']
             and row.get('unauthenticatedReadStatus') == 401, 'Semantic receipt query target, rank or authorization differs')
        seen.add(key)
    need(value.get('embeddingProfile') == BGE_PROFILE and value.get('collection') == BGE_COLLECTION
         and value.get('model') == BGE_MODEL and value.get('dimensions') == BGE_DIMENSION
         and value.get('nativeReadOnlyVerified') is True and value.get('independentProcess') is True
         and value.get('ownedRestoredCopy') is True and value.get('paidModelCalls') == value.get('llmCalls') == 0
         and re.fullmatch(r'[a-f0-9]{64}', value.get('nativeBeforeSha256', ''))
         and value['nativeBeforeSha256'] == value.get('nativeAfterSha256'), 'Semantic provider or native before/after evidence differs')
    if value.get('vectorBackend') == 'qdrant':
        rag = value.get('ragVerification', {})
        need(value.get('storageGeneration') == 'qdrant-bge-m3-v1' and rag.get('status') == 'VERIFIED'
             and rag.get('queryProtocol') == 'SHARED_BRIDGE_SOURCE_TEXT_QUERY_V1' and rag.get('retrievalQueries', 0) >= 83
             and rag.get('profile') == BGE_PROFILE and rag.get('collection') == 'doorhandle_rag_bge_m3_v1'
             and type(rag.get('embeddingRequests')) is int and rag['embeddingRequests'] > 0
             and value.get('actualEmbeddingAttempts') == value.get('actualEmbeddingSuccesses') == value['embeddingRequests'] + rag['embeddingRequests']
             and rag.get('paidModelCalls') == rag.get('llmCalls') == 0,
             'Real Qdrant activation lacks shared-BGE RAG query/count evidence')


@contextlib.contextmanager
def embedding_request_counter(adapter):
    """Count real attempts cumulatively, independently of the rate-limit deque."""
    original = adapter._request; counts = {'attempted': 0, 'succeeded': 0}
    def request(instance, texts):
        counts['attempted'] += 1
        result = original(instance, texts)
        counts['succeeded'] += 1
        return result
    adapter._request = request
    try: yield counts
    finally: adapter._request = original


def verify_rag_shared_bridge(base, token, manifest, remote):
    """Real protected embedding route plus scoped Qdrant retrieval, no LLM."""
    from script.memory.qdrant_migration import COLLECTIONS, point_id
    rows = manifest['records']; collection = COLLECTIONS['rag']; generation = manifest['identity']['generation']
    need(manifest.get('kind') == 'QDRANT_RAG_TARGET' and manifest.get('schemaVersion') == 2
         and manifest['identity'].get('profile') == BGE_PROFILE and len(rows) >= 83,
         'Real RAG query verification requires its complete BGE target manifest')
    requests, checked = 0, []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for offset in range(0, len(rows), 8):
        batch = rows[offset:offset + 8]; request_id = 'legacy-rag-query-' + str(offset)
        body = {'app_id': 'doorhandlecatch', 'purpose': 'SYSTEM_RAG', 'user_id': 'doorhandlecatch:system',
                'request_id': request_id, 'texts': [row['text'] for row in batch]}
        req = urllib.request.Request(base + '/internal/embeddings', method='POST', data=encoded(body),
            headers={'Content-Type': 'application/json', 'X-Doorhandle-Memory-Token': token})
        with opener.open(req, timeout=90) as response: output = json.loads(response.read(4 * MIB))
        need(output.get('request_id') == request_id and output.get('profile') == BGE_PROFILE
             and output.get('model') == BGE_MODEL and output.get('dimensions') == 1024
             and output.get('preprocessing') == 'utf8-newline-space-v1' and output.get('input_count') == len(batch)
             and len(output.get('vectors', [])) == len(batch), 'Shared RAG embedding route returned another model space')
        requests += 1
        for row, vector in zip(batch, output['vectors']):
            filters = [{'key': key, 'match': {'value': value}} for key, value in (
                ('kind', 'SYSTEM_RAG'), ('generation', generation), ('visibility', 'SYSTEM'), ('lifecycle', 'ACTIVE'))]
            found = remote.request('POST', '/collections/' + collection + '/points/query',
                {'query': vector, 'filter': {'must': filters}, 'limit': min(5, len(rows)), 'with_payload': True})['points']
            need(any(point['id'] == point_id(collection, row['id']) for point in found)
                 and all(all(point['payload'].get(key) == value for key, value in (
                     ('kind', 'SYSTEM_RAG'), ('generation', generation), ('visibility', 'SYSTEM'), ('lifecycle', 'ACTIVE'))) for point in found),
                 'Shared BGE RAG query lost its source or crossed generation/visibility scope')
            checked.append(hashlib.sha256(row['id'].encode()).hexdigest())
    return {'status': 'VERIFIED', 'queryProtocol': 'SHARED_BRIDGE_SOURCE_TEXT_QUERY_V1',
            'retrievalQueries': len(checked), 'targetIdsSha256': sha(checked), 'embeddingRequests': requests,
            'profile': BGE_PROFILE, 'collection': collection, 'generation': generation, 'llmCalls': 0, 'paidModelCalls': 0}


def bge_worker_command(ctx, folder, context_file):
    helper = canonical(ctx.checkout / 'script/jenkins/prepare-legacy-candidate.py')
    need(digest(helper) == digest(Path(__file__).resolve()) and canonical(context_file).is_relative_to(folder),
         'BGE worker source/context escaped its admitted mounted checkout')
    return ['-I', '-B', str(helper), 'bge-verify-worker', '--context', str(context_file)]


def bge_container_command(ctx, name, folder, context_file):
    return ['create', '--name', name, '--pull', 'never', '--network', 'host', '--read-only',
        '--user', str(os.getuid()) + ':' + str(os.getgid()), '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--pids-limit', '128', '--memory', str(BGE_VERIFIER_MEMORY), '--memory-swap', str(BGE_VERIFIER_MEMORY),
        '--tmpfs', '/tmp:rw,nosuid,noexec,size=33554432', '--log-opt', 'max-size=1m', '--log-opt', 'max-file=1',
        '--label', 'io.doorhandle.rehearsal=' + ctx.project, '--label', 'io.doorhandle.bge-verifier=' + ctx.token,
        '--label', 'io.doorhandle.release=' + ctx.args.tag,
        '--mount', 'type=bind,src=' + str(ctx.checkout) + ',dst=' + str(ctx.checkout) + ',readonly',
        '--mount', 'type=bind,src=' + str(folder) + ',dst=' + str(folder),
        '--entrypoint', 'python', ctx.images['mem0'], *bge_worker_command(ctx, folder, context_file)]


def bge_verify_worker(context_file):
    """Real bridge lifecycle on an owned restored COPY, never a source/live volume."""
    context = read(context_file); folder = canonical(context['directory']); data = canonical(folder / 'data')
    need(context.get('kind') == 'doorhandle-owned-bge-verifier' and context.get('embeddingProfile') == BGE_PROFILE
         and folder.is_relative_to(ROOT / 'work') and canonical(context_file).parent == folder,
         'BGE verification worker escaped its owned candidate')
    credentials = read(context['credentialFile'], 8192)
    need(credentials.get('embeddingProfile') == BGE_PROFILE and credentials.get('model') == BGE_MODEL
         and credentials.get('baseUrl') == BGE_BASE and credentials.get('dimensions') is None, 'Free embedding transport changed')
    key = folder / 'embedding.key'
    with os.fdopen(os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
        stream.write(credentials['apiKey']); stream.flush(); os.fsync(stream.fileno())
    home = folder / 'home'; home.mkdir(mode=0o700)
    os.environ.update(HOME=str(home), XDG_CACHE_HOME=str(home / '.cache'), PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
        MEM0_DATA_DIR=str(data), EMBEDDING_PROFILE=BGE_PROFILE, EMBEDDING_MODEL=BGE_MODEL,
        EMBEDDING_BASE_URL=BGE_BASE, EMBEDDING_API_KEY_FILE=str(key), MEM0_BRIDGE_TOKEN=context['bridgeToken'],
        DASHSCOPE_API_KEY='unusable-no-llm-credential', DASHSCOPE_BASE_URL='http://127.0.0.1:9/v1',
        MEM0_LLM_MODEL='llm-disabled-for-legacy-readback', MODEL_CONFIG_ENABLED='false',
        MEM0_LIFECYCLE_CLEANUP_ENABLED='false', MEM0_DUPLICATE_REVIEW_ENABLED='false',
        MEM0_TELEMETRY='false', ANONYMIZED_TELEMETRY='false', EMBEDDING_REQUESTS_PER_MINUTE='60')
    need(context.get('vectorBackend') == 'qdrant' and context.get('storageGeneration') == 'qdrant-bge-m3-v1',
         'Real semantic bridge needs its independent Qdrant generation')
    os.environ.update(MEM0_VECTOR_BACKEND='qdrant', MEM0_QDRANT_COLLECTION=BGE_COLLECTION,
        MEM0_STORAGE_GENERATION='qdrant-bge-m3-v1', QDRANT_HOST=context['qdrantHost'],
        QDRANT_PORT=str(context['qdrantPort']), QDRANT_TLS='false', QDRANT_API_KEY_FILE=context['qdrantKeyFile'])
    for name in ('EMBEDDING_API_KEY', 'DOORHANDLE_RUNTIME_ACCEPTANCE', 'DOORHANDLE_RUNTIME_PROJECT', 'MEM0_RUNTIME_TEST_COLLECTION',
                 'MEM0_MODEL_GATEWAY_BASE_URL', 'MEM0_SOURCE_PATH'):
        os.environ.pop(name, None)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    from memory_service import main as bridge
    from memory_service import embedding_config as embedding_runtime
    migration = module('legacy_bge_bridge_source', ROOT / 'script/memory/migrate_legacy_stores.py')
    bundle = read(context['bundle'], 16 * MIB); mapping = read(context['mapping']); plan = read(context['plan'])
    need(sha(bundle) == context['sourceBundleSha256'] and sha(mapping) == context['ownerMappingSha256']
         and digest(context['plan']) == context['semanticPlanSha256'], 'BGE bridge inputs changed')
    before = native_sql_state(data)
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(32)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(bridge.app, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    llm_calls = []
    # The adapter deque is a rolling rate limit, not a cumulative I/O receipt.
    counter = embedding_request_counter(embedding_runtime.FreeBgeEmbedder)
    counters = counter.__enter__()
    try:
        thread.start(); deadline = time.monotonic() + 60
        while not server.started:
            need(thread.is_alive() and time.monotonic() < deadline, 'Owned BGE bridge did not start')
            time.sleep(0.05)
        def no_llm(*args, **kwargs):
            llm_calls.append(1); raise ValueError('Real LLM invocation is forbidden in native read verification')
        bridge.memory_instance.llm.generate_response = no_llm
        base = 'http://127.0.0.1:' + str(port)
        migration.verify_bridge(bundle, mapping, {'baseUrl': base, 'token': context['bridgeToken']}, folder / 'bridge-readback-private.json', context['identity'])
        cloud_records = read(context['cloudRecords'], 64 * MIB)
        semantic = verify_semantic_bridge(bundle, mapping, plan, base, context['bridgeToken'], migration, cloud_records)
        from script.memory.qdrant_migration import Remote
        remote = Remote('http://' + context['qdrantHost'] + ':' + str(context['qdrantPort']), context['qdrantKeyFile'])
        rag = verify_rag_shared_bridge(base, context['bridgeToken'], read(context['ragManifest'], 2 * MIB), remote)
        need(not llm_calls and counters['attempted'] == counters['succeeded'] == semantic['embeddingRequests'] + rag['embeddingRequests'],
             'A verifier used an unexpected model path or omitted the actual provider calls')
        semantic.update(identity=context['identity'], phase=context['phase'], collection=BGE_COLLECTION, dimensions=BGE_DIMENSION,
            embeddingProfile=BGE_PROFILE, model=BGE_MODEL, independentProcess=True, ownedRestoredCopy=True,
            sourceBundleSha256=context['sourceBundleSha256'], ownerMappingSha256=context['ownerMappingSha256'],
            semanticPlanSha256=context['semanticPlanSha256'], sourceSnapshotReceiptSha256=context['sourceSnapshotReceiptSha256'],
            bridgeReadbackSha256=digest(folder / 'bridge-readback-private.json'),
            actualEmbeddingAttempts=counters['attempted'], actualEmbeddingSuccesses=counters['succeeded'],
            ragVerification=rag, vectorBackend='qdrant', storageGeneration='qdrant-bge-m3-v1')
    finally:
        server.should_exit = True
        if thread.is_alive(): thread.join(timeout=30)
        counter.__exit__(None, None, None)
        need(not thread.is_alive(), 'Owned BGE bridge did not stop')
        sock.close()
        if key.exists(): key.unlink()
    after = native_sql_state(data)
    need(after == before, 'Actual native read/search changed a recovered source collection or native history/message row')
    semantic.update(nativeBeforeSha256=sha(before), nativeAfterSha256=sha(after), nativeReadOnlyVerified=True)
    validate_semantic_receipt(semantic, plan)
    write(folder / 'semantic-readback.json', semantic)
    return {'status': semantic['status'], 'semanticReceiptSha256': digest(folder / 'semantic-readback.json')}


def owned_bge_helper(row, ctx, name, directory):
    labels = row['Config'].get('Labels') or {}; host = row['HostConfig']
    need(row['Image'] == ctx.images['mem0'] and row['Name'] == '/' + name
         and labels.get('io.doorhandle.rehearsal') == ctx.project
         and labels.get('io.doorhandle.bge-verifier') == ctx.token
         and labels.get('io.doorhandle.release') == ctx.args.tag
         and host['NetworkMode'] == 'host' and host['ReadonlyRootfs'] is True
         and host['Memory'] == BGE_VERIFIER_MEMORY and host['MemorySwap'] == BGE_VERIFIER_MEMORY
         and not host.get('Privileged') and not host.get('PortBindings') and host['RestartPolicy']['Name'] == 'no'
         and row['Config']['User'] == str(os.getuid()) + ':' + str(os.getgid()), 'Free BGE verifier ownership/resources changed')
    binds = {mount['Destination']: mount for mount in row['Mounts'] if mount['Type'] == 'bind'}
    need(set(binds) == {str(ctx.checkout), str(directory)}
         and binds[str(ctx.checkout)]['Source'] == str(ctx.checkout) and binds[str(ctx.checkout)]['RW'] is False
         and binds[str(directory)]['Source'] == str(directory) and binds[str(directory)]['RW'] is True,
         'BGE helper is not restricted to fixed source and its independent owned restore')


def verify_bge_phase(ctx, phase):
    sys.path.insert(0, str(ROOT))
    need(phase in SEMANTIC_PHASES, 'Unknown BGE read verification phase')
    value, _, work = admit_runtime(ctx)
    folder = ctx.directory / ('bge-' + phase); need(not folder.exists(), 'A BGE phase result cannot be replayed')
    folder.mkdir(mode=0o700)
    # Real BGE is validated on a pristine restored COPY, not the mock app volume.
    source = canonical(value['mem0DataDirectory'])
    helper = canonical(ctx.checkout / 'script/jenkins/prepare-legacy-candidate.py')
    ctx.ops.docker('run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--user', '0:0',
        '--cap-drop', 'ALL', '--cap-add', 'DAC_READ_SEARCH', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER',
        '--memory', '256m', '--memory-swap', '256m', '--label', 'io.doorhandle.rehearsal=' + ctx.project,
        '--mount', 'type=bind,src=' + str(source) + ',dst=/source,readonly',
        '--mount', 'type=bind,src=' + str(ctx.checkout) + ',dst=' + str(ctx.checkout),
        '--entrypoint', 'python', ctx.images['mem0'], '-I', '-B', str(helper), 'snapshot-volume',
        '--source', '/source', '--output', str(folder / 'volume'), '--uid', str(os.getuid()), '--gid', str(os.getgid()),
        '--instance-id', ctx.identity['instanceId'], '--machine-id', ctx.identity['machineId'], timeout=300)
    proof = read(folder / 'volume/snapshot-receipt.json')
    need(proof['status'] == 'RESTORED_VERIFIED' and proof['fullVolume'] is True and proof['sourceMountedReadOnly'] is True,
         'BGE phase lacks its full-volume independent restore')
    credentials = folder / 'provider-private.json'; write(credentials, private_bge_config(ctx.runtime))
    readback = read(work / 'legacy-mem0-read-verification.json')
    context = {'kind': 'doorhandle-owned-bge-verifier', 'directory': str(folder / 'volume'), 'phase': phase,
        'identity': {key: ctx.identity[key] for key in ('instanceId', 'machineId')}, 'embeddingProfile': BGE_PROFILE,
        'credentialFile': str(credentials), 'bridgeToken': secrets.token_hex(32),
        'bundle': str(work / 'legacy-mem0-export.json'), 'mapping': str(work / 'legacy-mem0-owner-map.json'),
        'plan': str(work / 'mem0-semantic-plan.json'), 'cloudRecords': str(work / 'mem0-cloud-records.json'),
        'ragManifest': str(work / 'rag-preservation-manifest.json'),
        'sourceBundleSha256': readback['sourceBundleSha256'],
        'ownerMappingSha256': readback['ownerMappingSha256'], 'semanticPlanSha256': value['mem0SemanticPlanSha256'],
        'sourceSnapshotReceiptSha256': digest(folder / 'volume/snapshot-receipt.json')}
    context_file = folder / 'volume/context-private.json'
    expected = read(work / 'qdrant-after.json', 64 * MIB)
    snapshot = read(work / 'qdrant-snapshot-recovery.json')
    with candidate_qdrant(folder, value['qdrantImage'], ctx.token + secrets.token_hex(6), 'semantic',
                          recovery=work / 'qdrant-candidate/snapshots', project=ctx.project) as (remote, _, vector_key):
        for collection, item in snapshot['snapshots'].items():
            restore = {'location': 'file:///qdrant/recovery/' + collection + '/' + item['name'], 'priority': 'snapshot'}
            if item.get('checksum') is not None: restore['checksum'] = item['checksum']
            remote.request('PUT', '/collections/' + collection + '/snapshots/recover?wait=true',
                           restore)
        need(remote.complete_catalog() == expected, 'Real BGE phase recovered different stored vectors/payloads')
        context.update(qdrantHost='127.0.0.1', qdrantPort=urllib.parse.urlsplit(remote.base).port,
                       qdrantKeyFile=str(vector_key), vectorBackend='qdrant', storageGeneration='qdrant-bge-m3-v1')
        write(context_file, context)
        name = 'doorhandle-bge-' + ctx.token + '-' + phase
        cid = None; stopped = None
        try:
            cid = ctx.ops.docker(*bge_container_command(ctx, name, folder, context_file), timeout=30).decode().strip()
            need(re.fullmatch(r'[a-f0-9]{64}', cid), 'Free BGE verifier container ID is invalid')
            ctx.owner.setdefault('bgeHelpers', {})[phase] = {'containerId': cid, 'name': name, 'directory': str(folder)}; ctx.save()
            owned_bge_helper(json.loads(ctx.ops.docker('inspect', cid))[0], ctx, name, folder)
            ctx.ops.docker('start', cid, timeout=30)
            with ctx.resources.lock: ctx.resources.sample()
            exit_code = ctx.ops.docker('wait', cid, timeout=300).decode().strip()
            logs = ctx.ops.docker('logs', cid, timeout=20)
            need(len(logs) <= 2 * MIB, 'Free BGE verifier private log exceeded its bound')
            with (folder / 'worker-private.log').open('xb') as stream:
                os.chmod(stream.name, 0o600); stream.write(logs)
            need(exit_code == '0', 'Actual free BGE bridge semantic verification failed; private evidence retained')
        finally:
            if cid:
                row = json.loads(ctx.ops.docker('inspect', cid))[0]; owned_bge_helper(row, ctx, name, folder)
                ctx.ops.docker('stop', '--time', '5', cid, timeout=20)
                final = json.loads(ctx.ops.docker('inspect', cid))[0]
                need(not final['State']['Running'] and not final['State'].get('Restarting') and final['State']['Pid'] == 0,
                     'Owned free BGE verifier did not stop')
                with ctx.resources.lock: ctx.resources.sample()
                stopped = {'containerId': cid, 'image': final['Image'], 'pid': 0, 'exitCode': final['State']['ExitCode']}
                ctx.ops.docker('rm', '--volumes', cid, timeout=30)
            for secret in (credentials, context_file, folder / 'volume/embedding.key'):
                if secret.exists():
                    need(secret.is_file() and not secret.is_symlink() and secret.stat().st_uid == os.getuid(), 'Owned verifier secret path changed')
                    secret.unlink()
        need(remote.complete_catalog() == expected, 'A real BGE read changed stored vectors or ownership payloads')
    result = read(folder / 'volume/semantic-readback.json')
    qdrant_cleanup = read(folder / 'qdrant-private-semantic/stopped.json')
    need(qdrant_cleanup.get('image') == value['qdrantImage'] and qdrant_cleanup.get('pid') == 0
         and qdrant_cleanup.get('exitCode') == 0, 'Independent Qdrant verifier did not finish a clean owned stop')
    validate_semantic_receipt(result, read(work / 'mem0-semantic-plan.json'))
    need(result.get('status') == 'SEMANTIC_BRIDGE_VERIFIED' and result.get('phase') == phase
         and result.get('semanticPlanSha256') == value['mem0SemanticPlanSha256'] and result.get('nativeReadOnlyVerified') is True
         and result.get('sourceSnapshotReceiptSha256') == context['sourceSnapshotReceiptSha256']
         and result.get('semanticQueries', 0) >= 2 and result['crossOwnerQueries'] == result['semanticQueries']
         and result['embeddingProfile'] == BGE_PROFILE and result['dimensions'] == BGE_DIMENSION
         and result['paidModelCalls'] == result['llmCalls'] == 0 and stopped and stopped['exitCode'] == 0,
         'BGE phase receipt lacks actual semantic/owner/restore/cleanup evidence')
    result.update(kind='doorhandle-legacy-bge-semantic-readback', version=1,
        actualRuntimeVolumeSha256=hashlib.sha256(str(source).encode()).hexdigest(),
        verificationSubject='INDEPENDENT_REAL_BGE_CANDIDATE', appRuntimeValidationMode='ISOLATED_MOCK_QDRANT_RUNTIME',
        qdrantSnapshotRecoverySha256=value['qdrantSnapshotRecoverySha256'], vectorBackend='qdrant', helperCleanup=stopped,
        qdrantHelperCleanup=qdrant_cleanup,
        candidateSha256=digest(work / 'legacy-candidate.json'), phaseSnapshotSha256=context['sourceSnapshotReceiptSha256'])
    file = ctx.directory / ('bge-semantic-' + phase + '.json'); write(file, result)
    return {'file': file.relative_to(ctx.attempt).as_posix(), 'sha256': digest(file)}


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


def snapshot_volume(source, output, identity, uid, gid, *, store_kind='legacy-sqlite'):
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
        need(store_kind in ('legacy-sqlite', 'qdrant')
             and (bool(databases) if store_kind == 'legacy-sqlite' else not databases and (source / 'storage').is_dir()),
             'Persistent volume does not match its explicit admitted store kind')
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
            'consistency': 'ALL_FILES_STABLE_AND_TWO_IDENTICAL_ONLINE_SQLITE_BACKUPS' if store_kind == 'legacy-sqlite'
                           else 'ALL_FILES_STABLE_FROZEN_QDRANT_STORAGE', 'storeKind': store_kind,
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
if (root/'chroma/chroma.sqlite3').is_file():
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
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 rows=db.execute('SELECT * FROM "'+name+'"').fetchall() if name in tables else [];assert len(rows)<=200000
 result['history'][name]={h([type(row['id']).__name__,row['id']]):h(dict(row)) for row in rows}
 assert len(result['history'][name])==len(rows)
db.close();print(json.dumps(result,sort_keys=True))
'''


def native_sql_state(directory):
    result = subprocess.run([sys.executable, '-I', '-B', '-c', NATIVE_SQL_SCRIPT, str(directory)],
                            check=True, capture_output=True, timeout=30)
    need(len(result.stdout) <= 32 * MIB, 'Complete native SQLite evidence exceeds its bound')
    return json.loads(result.stdout)


def data_worker(context_file):
    """Runs only in the already-admitted temporary Python image/checkout."""
    # The registered python -I launcher clears PYTHONPATH. Admit only this fixed
    # checkout, so the pinned memory_service adapter can be imported by merge.
    os.umask(0o077)
    sys.path.insert(0, str(ROOT))
    context = read(context_file)
    need(context.get('vectorBackend') == 'qdrant', 'New candidates require explicit Qdrant source/target separation')
    return qdrant_data_worker(context)


@contextlib.contextmanager
def candidate_qdrant(work, image, token, role, *, recovery=None, project=None):
    """An owned, immutable, loopback-only node; original services are never used."""
    need(re.fullmatch(r'sha256:[a-f0-9]{64}', image) and re.fullmatch(r'[a-f0-9]{24}', token)
         and role in ('candidate', 'recovery', 'semantic'), 'Invalid Qdrant helper identity')
    row = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image]))[0]
    need(row.get('Id') == image and row.get('Os') == 'linux' and row.get('Architecture') == 'amd64'
         and not row.get('Config', {}).get('OnBuild'), 'Prepared Qdrant image identity/platform changed')
    root = work / ('qdrant-' + role); root.mkdir(mode=0o700)
    for name in ('storage', 'snapshots'): (root / name).mkdir(mode=0o700)
    private = work / ('qdrant-private-' + role); private.mkdir(mode=0o700)
    key = private / 'api-key'; key.write_text(secrets.token_hex(32)); os.chmod(key, 0o600)
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0)); second.bind(('127.0.0.1', 0))
        port, grpc = first.getsockname()[1], second.getsockname()[1]
    config = private / 'server.json'
    write(config, {'service': {'host': '127.0.0.1', 'http_port': port, 'grpc_port': grpc,
                             'api_key': key.read_text()},
                   'storage': {'storage_path': '/qdrant/storage', 'snapshots_path': '/qdrant/snapshots'},
                   'telemetry_disabled': True})
    name = 'doorhandle-qdrant-' + token + '-' + role
    command = ['docker', 'create', '--name', name, '--pull', 'never', '--network', 'host', '--read-only',
        '--user', str(os.getuid()) + ':' + str(os.getgid()), '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--pids-limit', '128', '--memory', '512m', '--memory-swap', '512m', '--restart', 'no',
        '--label', LABEL + '=' + token, '--label', 'io.doorhandle.vector-role=' + role,
        '--mount', 'type=bind,src=' + str(root / 'storage') + ',dst=/qdrant/storage',
        '--mount', 'type=bind,src=' + str(root / 'snapshots') + ',dst=/qdrant/snapshots',
        '--mount', 'type=bind,src=' + str(private) + ',dst=/run/doorhandle-vector,readonly']
    if recovery is not None:
        command += ['--mount', 'type=bind,src=' + str(canonical(recovery)) + ',dst=/qdrant/recovery,readonly']
    if project is not None:
        need(re.fullmatch(r'doorhandle-rehearsal-[a-f0-9]{12}', project), 'Invalid isolated Qdrant observer identity')
        command += ['--label', 'io.doorhandle.rehearsal=' + project, '--label', 'com.docker.compose.service=bge-qdrant']
    command += [image, './qdrant', '--config-path', '/run/doorhandle-vector/server.json']
    cid = None
    try:
        cid = subprocess.check_output(command).decode().strip()
        need(re.fullmatch(r'[a-f0-9]{64}', cid), 'Qdrant helper identity missing')
        write(private / 'owner.json', {'containerId': cid, 'image': image, 'name': name, 'token': token,
                                      'role': role, 'root': str(root)})
        subprocess.run(['docker', 'start', cid], check=True, capture_output=True)
        from script.memory.qdrant_migration import Remote
        remote = Remote('http://127.0.0.1:' + str(port), key)
        deadline = time.monotonic() + 90
        while True:
            try:
                remote.request('GET', '/collections'); break
            except (OSError, urllib.error.URLError):
                need(time.monotonic() < deadline, 'Owned Qdrant helper did not become ready'); time.sleep(.25)
        yield remote, root, key
    finally:
        if cid:
            current = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
            need(current['Id'] == cid and current['Image'] == image and current['Name'] == '/' + name
                 and (current['Config'].get('Labels') or {}).get(LABEL) == token
                 and current['Config'].get('User') == str(os.getuid()) + ':' + str(os.getgid())
                 and current['HostConfig']['NetworkMode'] == 'host', 'Qdrant cleanup owner changed')
            subprocess.run(['docker', 'stop', '--time', '30', cid], check=True, capture_output=True, timeout=45)
            stopped = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
            need(not stopped['State']['Running'] and stopped['State']['Pid'] == 0, 'Owned Qdrant writer did not freeze')
            write(private / 'stopped.json', {'containerId': cid, 'image': image, 'pid': 0, 'exitCode': stopped['State']['ExitCode']})
            subprocess.run(['docker', 'rm', cid], check=True, capture_output=True)
        for secret in (key, config):
            if secret.exists(): secret.unlink()


def qdrant_data_worker(context):
    """Convert immutable source copies into a fresh BGE/Qdrant target, once."""
    from script.memory import qdrant_migration as target
    from memory_service.qdrant_store import persist_storage_floor, vector_identity
    migration = module('candidate_legacy_stores', ROOT / 'script/memory/migrate_legacy_stores.py')
    migration.ecs_identity(context['identity']['instanceId'], context['identity']['machineId'])
    work = canonical(context['work'])
    mem0 = work / 'mem0'; mem0.mkdir(mode=0o700)
    shutil.copytree(work / 'cloud-mem0/data', mem0 / 'data')
    native_before = {'collections': complete_chroma(mem0 / 'data/chroma', migration), 'history': native_history(mem0 / 'data'),
                     'sqlite': native_sql_state(mem0 / 'data')}
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
    need(len(projected['records']) == 30 and len(projected['archivedMemoryIds']) == 2
         and len(projected['history']) == 30 and len(projected['messages']) == 25
         and projected['archivedHistoryRows'] == 3 and projected['archivedMessageRows'] == 1,
         'Legacy native owner dispositions changed; do not infer a new account mapping')
    write(work / 'legacy-mem0-owner-map.json', mapping)
    # Chroma is now an immutable archival copy, never the running vector store.
    cloud, _ = cloud_memory_records(mem0 / 'data', native_before, mapping, migration)
    write(work / 'mem0-cloud-records.json', cloud)
    config = read(context['bgeProviderFile'], 8192)
    migration.reembed(native_source, mapping, config, work / 'mem0-bge-embeddings.json')
    generated = read(work / 'mem0-bge-embeddings.json', 16 * MIB)
    prepared_memories = migration.prepared_records(native_source, mapping, generated)['records']
    by_id = {row['id']: row for row in prepared_memories}
    need(not {row['id'] for row in cloud}.intersection(projected['archivedMemoryIds']), 'Archived test memory overlaps cloud business data')
    pending = []
    for row in cloud:
        if row['id'] in by_id:
            need(row['metadata'] == by_id[row['id']]['metadata'], 'Cloud/legacy logical memory identity conflicts')
        else: pending.append(row)
    target.admit_lifecycle_import(mem0 / 'data', [row['id'] for row in projected['records']], migration,
                                  accepted_existing_ids={row['id'] for row in cloud})
    for offset in range(0, len(pending), 30):
        rows = pending[offset:offset + 30]
        export = {'format': migration.FORMAT, 'kind': 'legacy-mem0-private-export', 'collection': 'CURRENT_CLOUD_UNION',
                  'dimension': None, 'sources': [], 'records': rows, 'history': [], 'messages': []}
        policy = {'sourceBundleSha256': sha(export), 'targetTenantId': None, 'owners': [
            {'sourceOwner': owner, 'disposition': 'import', 'userId': int(owner.rsplit(':', 1)[1]),
             'reason': 'Freshly verified same-ECS account binding'}
            for owner in sorted({row['metadata']['user_id'] for row in rows})]}
        output = work / ('cloud-bge-embeddings-' + str(offset) + '.json')
        migration.reembed(export, policy, config, output)
        for row in migration.prepared_records(export, policy, read(output, 16 * MIB))['records']: by_id[row['id']] = row
    history = target.merge_history(projected, mem0 / 'data', migration)
    write(work / 'mem0-semantic-plan.json', semantic_plan(native_source, mapping, migration, cloud))
    merged = {'mergedRecords': 30, 'mergedHistoryRows': 30, 'mergedMessageRows': 25,
              'currentCloudRecords': len(cloud), 'targetRecords': len(by_id), 'historyMode': 'single-writer-sqlite'}
    read_verification = {'status': 'MERGED_PENDING_SEMANTIC',
        'sourceBundleSha256': sha(native_source), 'ownerMappingSha256': sha(mapping), 'sourceRecords': 32,
        'eligibleRecords': 30, 'activatedRecords': 0, 'archivedRecords': 2, 'sourceHistoryRows': 33, 'sourceMessageRows': 26,
        'eligibleHistoryRows': len(projected['history']), 'mergedHistoryRows': 30, 'archivedHistoryRows': projected['archivedHistoryRows'],
        'eligibleMessageRows': len(projected['messages']), 'mergedMessageRows': 25, 'archivedMessageRows': projected['archivedMessageRows'],
        'originalVectorAndIdReadbackVerified': True, 'modelCallsPerformed': True, 'paidModelCalls': 0, 'llmCalls': 0,
        'semanticSearchVerified': False, 'embeddingProfile': BGE_PROFILE, 'collection': BGE_COLLECTION, 'dimensions': BGE_DIMENSION, 'targetBackend': 'qdrant', **merged}
    shutil.copytree(restored / 'rag_chroma', legacy / 'rag_chroma')
    for name in ('original-manifest.json', 'restore-receipt.json'): shutil.copyfile(restored / name, legacy / name); os.chmod(legacy / name, 0o600)
    source = migration.rag_export(legacy, 83); write(work / 'legacy-rag-export.json', source)
    before = complete_chroma(work / 'cloud-chroma/data', migration); write(work / 'cloud-chroma-before.json', before)
    from chromadb import PersistentClient
    from chromadb.config import Settings
    client = PersistentClient(path=str(work / 'cloud-chroma/data'), tenant=context['tenant'], database=context['database'],
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
         'Complete preserved RAG union exceeds its bounded BGE embedding admission')
    union = {'format': 1, 'kind': 'legacy-rag-private-export', 'collection': migration.RAG_COLLECTION,
        'legacySourceBundleSha256': sha(source), 'currentCloudSnapshotSha256': context['chromaSnapshotSha256'],
        'records': [records[key] for key in sorted(records)]}
    write(work / 'rag-union-export.json', union)
    policy = {'sourceBundleSha256': sha(union), 'collection': target.COLLECTIONS['rag'], 'projectScopeVerified': True,
        'scopeEvidence': 'The admitted project legacy snapshot plus complete same-ECS project-level cloud RAG collection; no user-owned records accepted',
        'verifiedTargetRuntime': True, 'targetEmbeddingName': BGE_MODEL,
        'targetDimension': BGE_DIMENSION, 'applicationCommit': context['commit'],
        'expectedSourceRecords': len(records), 'dispositions': {key: 'import' for key in records},
        'targetIds': {key: key for key in records}}
    write(work / 'rag-policy.json', policy)
    migration.rag_bge_reembed(union, policy, config, work / 'rag-embeddings.json')
    embeddings = read(work / 'rag-embeddings.json', 64 * MIB)
    prepared = migration.prepared_bge_rag_records(union, policy, embeddings)
    generation = 'legacy-' + sha(union)[:24]
    token = context['token']
    with candidate_qdrant(work, context['qdrantImage'], token, 'candidate') as (remote, qroot, _):
        for name in target.COLLECTIONS.values(): remote.admit(name, create=True)
        imported_memories = remote.import_records(target.COLLECTIONS['mem0'], [by_id[key] for key in sorted(by_id)])
        imported_rag = remote.import_records(target.COLLECTIONS['rag'], prepared, kind='SYSTEM_RAG', generation=generation)
        after = remote.complete_catalog()
        write(work / 'qdrant-after.json', after)
        # Old artifact names are source compatibility references, not Chroma targets.
        write(work / 'cloud-chroma-after.json', {'backend': 'qdrant', 'catalog': after})
        with candidate_qdrant(work, context['qdrantImage'], token, 'recovery', recovery=qroot / 'snapshots') as (independent, _, _):
            recovery = remote.snapshot_recovery(independent, '/qdrant/recovery')
        write(work / 'qdrant-snapshot-recovery.json', recovery)
        first = remote.complete_catalog()
        need(first == after, 'Qdrant first stored fingerprint changed before freeze')
    # Copy no keys/configuration into the target payload. A stopped server is
    # mandatory before its complete storage tree is inventoried/materialized.
    persist_storage_floor(mem0 / 'data', BGE_COLLECTION, vector_identity({'EMBEDDING_PROFILE': BGE_PROFILE}))
    write(work / 'legacy-mem0-read-verification.json', read_verification)
    mem0_after = {'collections': native_before['collections'], 'history': native_history(mem0 / 'data'),
                  'sqlite': native_sql_state(mem0 / 'data'), 'vectorBackend': 'qdrant',
                  'qdrantCollection': imported_memories['records'], 'historyMode': 'single-writer-sqlite'}
    need(all(mem0_after['history'][table].get(key) == value for table, rows in native_before['history'].items() for key, value in rows.items()),
         'A current-cloud history or message row changed during Qdrant migration')
    write(work / 'mem0-after.json', mem0_after)
    memory_receipt = {'format': 1, 'status': 'MERGED_VERIFIED', 'identity': context['identity'],
        'sourceBundleSha256': sha(native_source), 'ownerMappingSha256': sha(mapping), 'embeddingOutputSha256': sha(generated),
        'activeRecords': 30, 'importedHistoryRows': 30, 'importedMessageRows': 25, 'archivedHistoryRows': 3, 'archivedMessageRows': 1,
        'archivedMemoryIds': projected['archivedMemoryIds'], 'targetCollection': BGE_COLLECTION, 'targetModel': BGE_MODEL,
        'targetBackend': 'qdrant', 'targetTotalRecords': len(imported_memories['records']),
        'storedVectors': imported_memories['provenance'], 'vectorIdProtocol': target.ID_PROTOCOL,
        'historyMode': history['historyMode'], 'originalChromaRetainedReadOnly': True}
    write(mem0 / 'data/legacy-bge-merge-receipt.json', memory_receipt)
    receipt = {'version': 2, 'kind': 'doorhandle-legacy-rag-merge', 'status': 'MERGED_VERIFIED', 'identity': context['identity'],
        'commit': context['commit'], 'sourceSha256': context['sourceSha256'], 'legacyRecords': 83,
        'legacySourceBundleSha256': sha(source), 'sourceBundleSha256': sha(union), 'policySha256': sha(policy),
        'embeddingOutputSha256': digest(work / 'rag-embeddings.json'), 'cloudBeforeSha256': sha(before),
        'cloudAfterSha256': sha(after), 'currentCloudRagRecords': len((existing or {}).get('records', {})),
        'targetRecords': len(imported_rag['records']), 'cloudLogicalTextAndMetadataPreserved': True,
        'originalCloudVectorsRetainedInBackup': True, 'otherSourceCollectionsRetainedInBackup': True,
        'allTargetVectorsReembeddedByBgeM3': True, 'modelCallsPerformed': True, 'paidModelCalls': 0, 'llmCalls': 0,
        'targetBackend': 'qdrant', 'cosineNormalizationVerified': True,
        'snapshotRecoverySha256': digest(work / 'qdrant-snapshot-recovery.json'),
        'cloudSnapshotReceiptSha256': context['chromaSnapshotSha256'], 'legacyRestoreReceiptSha256': context['legacyRestoreReceiptSha256']}
    write(work / 'rag-merge-receipt.json', receipt)
    manifest = target.rag_manifest(context['commit'], generation, prepared, imported_rag)
    need(len(encoded(manifest)) <= 2 * MIB, 'Private RAG preservation catalogue exceeds its explicit bound')
    write(work / 'rag-preservation-manifest.json', manifest)
    return {'status': 'MERGED_VERIFIED', 'legacyRecords': 83, 'targetRecords': len(imported_rag['records']),
            'ragManifestSha256': digest(work / 'rag-preservation-manifest.json'), 'legacyMem0MergedRecords': 30}


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
    settings = read(canonical(args.settings))
    required = {'version', 'sourceOffsets', 'java', 'sourceMysqlContainerId', 'sourceSchema'}
    need(required <= set(settings) <= required | {'legacyClockPolicy', 'mem0DependencyImage', 'qdrantImage'}
         and settings['version'] == 1, 'Candidate must reuse the reviewed fixture settings')
    qdrant_image = admit_target_image(root, args.tag, args.commit, args.source_sha256, identity, settings)
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
        'pythonImage': tools['images']['python'], 'qdrantImage': qdrant_image, 'checkout': str(checkout), 'sources': {}}
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
    bge_provider = work / 'bge-provider-private.json'
    write(bge_provider, private_bge_config(args.runtime))
    context = {'work': str(work), 'legacyRestore': str(restore), 'identity': identity, 'commit': args.commit, 'release': args.tag,
        'sourceSha256': args.source_sha256, 'dimension': args.dimension,
        'tenant': env.get('CHAT_ASSISTANT_CHROMA_TENANT', 'default_tenant'),
        'database': env.get('CHAT_ASSISTANT_CHROMA_DATABASE', 'default_database'),
        'java': str(tool_file.parent / 'java'), 'chromaSnapshotSha256': snapshots['chroma'],
        'vectorBackend': 'qdrant', 'qdrantImage': qdrant_image, 'token': token,
        'legacyRestoreReceiptSha256': digest(restore / 'restore-receipt.json'), 'bgeProviderFile': str(bge_provider)}
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
    finally:
        # This file is never part of a payload, public artifact or backup. Only
        # the executor-owned transient copy is removed, never the ECS credential.
        if bge_provider.exists():
            need(bge_provider.is_file() and not bge_provider.is_symlink() and bge_provider.stat().st_uid == os.getuid(),
                 'Temporary BGE credential ownership changed')
            bge_provider.unlink()
    need(result.returncode == 0, 'RAG candidate preparation failed; no original cloud data was modified')
    for owned in (work / 'mem0/data', work / 'qdrant-candidate'): private_tree(owned, os.getuid(), os.getgid())
    mem0_files, rag_files = file_inventory(work / 'mem0/data'), file_inventory(work / 'qdrant-candidate')
    write(work / 'mem0-payload-files.json', mem0_files); write(work / 'rag-payload-files.json', rag_files)
    descriptor = {'version': 1, 'kind': 'doorhandle-legacy-candidate', 'status': 'PREPARED', 'release': args.tag,
        'commit': args.commit, 'sourceSha256': args.source_sha256, 'identity': identity,
        'verificationReceiptSha256': digest(accepted_file), 'toolManifestSha256': tool_sha,
        'legacyRestoreReceiptSha256': context['legacyRestoreReceiptSha256'], 'snapshots': snapshots,
        'legacySourceProfile': plan['profile'], 'legacyKafkaFiles': plan['kafkaFiles'], 'legacyKafkaBytes': plan['kafkaBytes'],
        'legacyKafkaReplay': 'NOT_PERFORMED',
        'sourceAdmissions': source_admissions,
        'ragDataDirectory': str(work / 'qdrant-candidate'), 'mem0DataDirectory': str(work / 'mem0/data'),
        'vectorBackend': 'qdrant', 'vectorIdProtocol': 'doorhandle-vector-sha256-v8-v1',
        'storageGeneration': 'qdrant-bge-m3-v1', 'qdrantImage': qdrant_image,
        'targetCatalogueSha256': digest(work / 'qdrant-after.json'),
        'qdrantSnapshotRecoverySha256': digest(work / 'qdrant-snapshot-recovery.json'),
        'validationMode': 'REAL_BGE_PRESERVATION_CANDIDATE',
        'ragPayloadFilesSha256': digest(work / 'rag-payload-files.json'), 'mem0PayloadFilesSha256': digest(work / 'mem0-payload-files.json'),
        'mem0BeforeSha256': digest(work / 'mem0-before.json'),
        'mem0CloudRecordsSha256': digest(work / 'mem0-cloud-records.json'),
        'legacyMem0ReadVerificationSha256': digest(work / 'legacy-mem0-read-verification.json'),
        'mem0AfterSha256': digest(work / 'mem0-after.json'), 'mem0SemanticPlanSha256': digest(work / 'mem0-semantic-plan.json'),
        'mem0MergeReceiptSha256': digest(work / 'mem0/data/legacy-bge-merge-receipt.json'),
        'ragManifestSha256': digest(work / 'rag-preservation-manifest.json'), 'mergeReceiptSha256': digest(work / 'rag-merge-receipt.json'),
        'cloudChromaAfterSha256': digest(work / 'cloud-chroma-after.json'), 'originalContainers': original_nodes,
        'originalVolumes': original_volumes,
        'mem0Migration': 'BGE_30_MERGED_PENDING_SEMANTIC_CLOUD_RECORDS_RETAINED',
        'embeddingProfile': BGE_PROFILE, 'embeddingCollection': BGE_COLLECTION, 'embeddingDimensions': BGE_DIMENSION,
        'candidateSemanticVerified': False, 'productionDataMaterialized': False,
        'modelCallsPerformed': True, 'paidModelCalls': 0, 'llmCalls': 0, 'productionPromotionAllowed': False}
    write(work / 'legacy-candidate.json', descriptor)
    public = {'status': 'PREPARED', 'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
        'identity': {**identity, 'executionLocation': 'ECS'}, 'legacyRagRecords': 83,
        'descriptorSha256': digest(work / 'legacy-candidate.json'), 'ragManifestSha256': descriptor['ragManifestSha256'],
        'modelCallsPerformed': True, 'paidModelCalls': 0, 'llmCalls': 0,
        'legacyMem0MergedRecords': 30, 'candidateSemanticVerified': False, 'productionDataMaterialized': False,
        'embeddingProfile': BGE_PROFILE, 'productionPromotionAllowed': False,
        'vectorBackend': 'qdrant', 'storageGeneration': 'qdrant-bge-m3-v1',
        'validationMode': 'REAL_BGE_PRESERVATION_CANDIDATE',
        'qdrantSnapshotRecoverySha256': descriptor['qdrantSnapshotRecoverySha256']}
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
        role = (row['Config'].get('Labels') or {}).get('io.doorhandle.vector-role')
        if role is not None:
            need(role in ('candidate', 'recovery') and row['Image'] == owner['qdrantImage']
                 and row['Name'] == '/doorhandle-qdrant-' + owner['token'] + '-' + role
                 and row['HostConfig']['ReadonlyRootfs'] and row['HostConfig']['NetworkMode'] == 'host'
                 and row['Config']['User'] == str(os.getuid()) + ':' + str(os.getgid())
                 and cid not in {value['containerId'] for value in owner['sources'].values()},
                 'Qdrant cleanup refused an original or changed helper')
            roots = {str(work / ('qdrant-' + role) / name) for name in ('storage', 'snapshots')}
            roots.add(str(work / ('qdrant-private-' + role)))
            if role == 'recovery': roots.add(str(work / 'qdrant-candidate/snapshots'))
            need({mount['Source'] for mount in row['Mounts']} == roots,
                 'Qdrant cleanup mount ancestry differs from its owned candidate')
            subprocess.run(['docker', 'stop', '--time', '30', cid], check=True, capture_output=True, timeout=45)
            final = json.loads(subprocess.check_output(['docker', 'inspect', cid]))[0]
            need(not final['State']['Running'] and final['State']['Pid'] == 0, 'Owned Qdrant helper did not stop')
            subprocess.run(['docker', 'rm', cid], check=True, capture_output=True)
            for secret in ('api-key', 'server.json'):
                path = work / ('qdrant-private-' + role) / secret
                if path.exists():
                    need(path.is_file() and not path.is_symlink() and path.stat().st_uid == os.getuid(), 'Owned vector secret changed')
                    path.unlink()
            stopped.append(cid); continue
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
        'identity': identity, 'productionPromotionAllowed': False, 'modelCallsPerformed': True,
        'paidModelCalls': 0, 'llmCalls': 0, 'candidateSemanticVerified': False, 'productionDataMaterialized': False,
        'embeddingProfile': BGE_PROFILE, 'embeddingCollection': BGE_COLLECTION, 'embeddingDimensions': BGE_DIMENSION,
        'vectorBackend': 'qdrant', 'storageGeneration': 'qdrant-bge-m3-v1',
        'vectorIdProtocol': 'doorhandle-vector-sha256-v8-v1', 'validationMode': 'REAL_BGE_PRESERVATION_CANDIDATE'}.items()),
        'Legacy candidate belongs to another source, attempt or ECS')
    need(value['qdrantImage'] == admit_target_image(ctx.checkout.parents[2], ctx.args.tag, ctx.args.commit,
         ctx.args.source_sha256, identity, {}), 'Candidate Qdrant image is not this build admitted immutable input')
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
             'mem0-after.json': 'mem0AfterSha256', 'mem0-semantic-plan.json': 'mem0SemanticPlanSha256',
             'mem0-cloud-records.json': 'mem0CloudRecordsSha256',
             'mem0/data/legacy-bge-merge-receipt.json': 'mem0MergeReceiptSha256',
             'rag-payload-files.json': 'ragPayloadFilesSha256', 'mem0-payload-files.json': 'mem0PayloadFilesSha256',
             'qdrant-after.json': 'targetCatalogueSha256', 'qdrant-snapshot-recovery.json': 'qdrantSnapshotRecoverySha256'}
    for name, key in files.items(): need(digest(canonical(work / name)) == value[key], 'Private native candidate evidence changed')
    recovery = read(work / 'qdrant-snapshot-recovery.json')
    need(recovery.get('status') == 'RESTORED_VERIFIED' and recovery.get('backend') == 'qdrant'
         and recovery.get('independentServer') is True and recovery.get('exactStoredFloat32Verified') is True
         and recovery.get('storedCatalogSha256') == sha(read(work / 'qdrant-after.json', 64 * MIB)),
         'Candidate lacks its actual independent snapshot/first-stored-vector recovery proof')
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
        need(data == work / ('qdrant-candidate' if service == 'rag' else 'mem0/data')
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
    if sources is None:
        seed = ctx.directory / 'synthetic-native-seed'
        need(not seed.exists(), 'Synthetic runtime seed cannot be reused')
        for service in ('mem0', 'qdrant'):
            (seed / service).mkdir(mode=0o700, parents=True)
        (seed / 'qdrant/storage').mkdir(mode=0o700)
        (seed / 'qdrant/snapshots').mkdir(mode=0o700)
        sources = {service: seed / service for service in ('mem0', 'qdrant')}
    need(set(sources) == {'mem0', 'qdrant'}, 'Only owned synthetic Mem0/Qdrant data may enter app acceptance')
    results = {}
    for service in ('mem0', 'qdrant'):
        logical = 'doorhandle-mem0-qdrant' if service == 'mem0' else 'doorhandle-qdrant'
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
        volume = ctx.config['volumes']['runtime-qdrant-private']['name']
        ctx.ops.docker('volume', 'create', '--label', 'io.doorhandle.rehearsal=' + ctx.project, volume)
        need(json.loads(ctx.ops.docker('volume', 'inspect', volume))[0].get('Labels', {}).get('io.doorhandle.rehearsal') == ctx.project,
             'Vector credential volume is not owned by this attempt')
        key = secrets.token_hex(32)
        config = {'service': {'host': '0.0.0.0', 'http_port': 6333, 'grpc_port': 6334, 'api_key': key},
                  'storage': {'storage_path': '/data/storage', 'snapshots_path': '/data/snapshots'}, 'telemetry_disabled': True}
        code = """import os,sys,json
v=json.load(sys.stdin); assert set(v)=={'api-key','server.json'} and not os.listdir('/target')
for name,data in v.items():
 assert isinstance(data,str) and len(data.encode())<=8192
 path='/target/'+name
 with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400),'w') as stream:
  stream.write(data);stream.flush();os.fsync(stream.fileno())
 os.chown(path,10001,10001)
os.chown('/target',10001,10001);os.chmod('/target',0o700)
print(json.dumps({'status':'INSTALLED','uid':10001,'files':2}))
"""
        installed = json.loads(ctx.ops.docker('run', '--rm', '-i', '--network', 'none', '--read-only', '--user', '0:0',
            '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--memory', '128m', '--memory-swap', '128m',
            '--label', 'io.doorhandle.rehearsal=' + ctx.project, '--mount', 'type=volume,src=' + volume + ',dst=/target',
            '--entrypoint', 'python', ctx.images['mem0'], '-I', '-B', '-c', code,
            data=encoded({'api-key': key, 'server.json': json.dumps(config)}), timeout=30))
        need(installed == {'status': 'INSTALLED', 'uid': 10001, 'files': 2}, 'Owned Qdrant key installation failed')
        results['credentials'] = installed
    result = {'status': 'MATERIALIZED', 'descriptorSha256': descriptor_sha, 'volumes': results,
              'validationMode': 'ISOLATED_MOCK_QDRANT_RUNTIME', 'legacyDataPublished': False}
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


QDRANT_RUNTIME_SCRIPT = r'''import json,math,os,sys
from qdrant_client import QdrantClient
from qdrant_store import admit_collection,qdrant_config,vector_identity,point_id,vector_fingerprint
v=json.load(sys.stdin); client=QdrantClient(host=os.environ['QDRANT_HOST'],port=int(os.environ['QDRANT_PORT']),https=False,api_key=open(os.environ['QDRANT_API_KEY_FILE']).read().strip(),timeout=15)
identity=vector_identity(); result={}
assert identity['doorhandle_profile']==v['profile'] and identity['doorhandle_storage_generation']==v['storageGeneration']
if v.get('allowCreate'):
 for name in v['collections']: admit_collection(qdrant_config(name),client=client)
assert {row.name for row in client.get_collections().collections}==set(v['collections'])
for name in v['collections']:
 admit_collection(qdrant_config(name),client=client)
 records={}; offset=None
 for _ in range(64):
  rows,offset=client.scroll(name,limit=128,offset=offset,with_vectors=True,with_payload=True)
  for row in rows:
   p=row.payload; logical=p.get('doorhandle_logical_id') if name==v['memory'] else p.get('logical_id')
   assert isinstance(logical,str) and str(row.id)==point_id(name,logical) and logical not in records
   assert isinstance(row.vector,list) and len(row.vector)==1024 and all(math.isfinite(x) for x in row.vector) and abs(sum(x*x for x in row.vector)-1)<2e-5
   records[logical]={'physicalId':str(row.id),'payload':p,'storedVectorSha256':vector_fingerprint(row.vector)}
  if offset is None: break
 else: raise ValueError('Unbounded Qdrant pagination')
 result[name]={'identity':identity,'records':records}
client.close(); print(json.dumps(result,sort_keys=True))
'''


def runtime_qdrant_state(ctx):
    env = ctx.config['services']['backend']['environment']
    names = [env[key] for key in ('SEMANTIC_RAG_COLLECTION', 'SEMANTIC_KNOWLEDGE_COLLECTION', 'SEMANTIC_EXPERIENCE_COLLECTION')]
    memory = ctx.config['services']['mem0']['environment']['MEM0_RUNTIME_TEST_COLLECTION']; names.append(memory)
    command = ['run', '--rm', '-i', '--pull', 'never', '--network', ctx.config['networks']['doorhandle-network']['name'],
        '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--memory', '128m', '--memory-swap', '128m', '--label', 'io.doorhandle.rehearsal=' + ctx.project,
        '--mount', 'type=volume,src=' + ctx.config['volumes']['runtime-qdrant-private']['name'] + ',dst=/run/doorhandle-vector,readonly']
    for key in ('QDRANT_HOST', 'QDRANT_PORT', 'QDRANT_TLS', 'QDRANT_API_KEY_FILE', 'EMBEDDING_PROFILE',
                'EMBEDDING_MODEL', 'EMBEDDING_DIMENSIONS', 'MEM0_STORAGE_GENERATION'):
        command += ['--env', key + '=' + ctx.config['services']['mem0']['environment'][key]]
    command += ['--entrypoint', 'python', ctx.images['mem0'], '-I', '-B', '-c', QDRANT_RUNTIME_SCRIPT]
    return json.loads(ctx.ops.docker(*command, data=encoded({'collections': names, 'memory': memory, 'profile': 'explicit-openai-compatible',
                                  'storageGeneration': 'qdrant-explicit-test-v1', 'allowCreate': True}), timeout=90))


def verify_runtime(ctx, phase):
    value, descriptor_sha, work = admit_runtime(ctx)
    need(phase in SEMANTIC_PHASES, 'Unregistered native runtime verification phase')
    actual = runtime_qdrant_state(ctx)
    current_file = ctx.directory / ('runtime-qdrant-' + phase + '.json'); write(current_file, actual)
    if phase != 'after-start':
        baseline = read(ctx.directory / 'runtime-qdrant-after-start.json', 64 * MIB)
        need(all(actual.get(name, {}).get('identity') == row['identity']
                 and all(actual[name]['records'].get(key) == record for key, record in row['records'].items())
                 for name, row in baseline.items()), 'Synthetic Qdrant restart changed first stored vectors or payloads')
    native = json.loads(ctx.ops.docker('exec', ctx.row('mem0')['Id'], 'python', '-I', '-B', '-c', NATIVE_SQL_SCRIPT, '/data', timeout=30))
    if phase == 'after-volume-restore':
        recovery = ctx.owner.get('nativeRecovery', {}); directory = canonical(recovery.get('directory', ''))
        need(digest(directory / 'native-before-sql.json') == recovery.get('beforeSha256')
             and digest(directory / 'native-recovery.json') == recovery.get('recoveryProofSha256'),
             'Post-business native recovery evidence changed')
        need(native == read(directory / 'native-before-sql.json', 32 * MIB)
             and actual == read(directory / 'native-qdrant-before.json', 64 * MIB),
             'Synthetic full-volume restore lost post-business vectors, history or messages')
    semantic = verify_bge_phase(ctx, phase)
    semantic_value = read(ctx.attempt / semantic['file'])
    result = {**ctx.context(), 'kind': 'doorhandle-legacy-runtime-readback', 'status': 'VERIFIED', 'phase': phase,
        'project': ctx.project, 'descriptorSha256': descriptor_sha, 'ragManifestSha256': value['ragManifestSha256'],
        'verificationSubject': 'INDEPENDENT_REAL_BGE_CANDIDATE',
        'appRuntimeValidationMode': 'ISOLATED_MOCK_QDRANT_RUNTIME', 'vectorBackend': 'qdrant',
        'storageGeneration': 'qdrant-bge-m3-v1',
        'mockRuntimeCatalogueSha256': digest(current_file), 'mockRuntimePersistenceVerified': True,
        'allCloudCollectionsSha256': value['targetCatalogueSha256'],
        'retrievalQueries': semantic_value['ragVerification']['retrievalQueries'],
        'sourceAndDocumentAndFloat32Verified': True, 'nativeStateSha256': sha(native),
        'eligibleLocalMem0Records': 30, 'activatedLocalMem0Records': 30, 'localMem0ArchivedRecords': 2,
        'mergedLocalHistoryRows': 30, 'mergedLocalMessageRows': 25, 'archivedLocalHistoryRows': 3, 'archivedLocalMessageRows': 1,
        'localMem0SemanticStatus': 'PHASE_SEMANTIC_VERIFIED', 'bgeSemanticVerification': semantic,
        'candidateSemanticVerified': True, 'productionDataMaterialized': False, 'paidModelCalls': 0, 'llmCalls': 0,
        'testNamespace': 'doorhandle_runtime_test_' + ctx.token, 'productionPromotionAllowed': False}
    file = ctx.directory / ('native-readback-' + phase + '.json'); write(file, result)
    reference = {'file': file.relative_to(ctx.attempt).as_posix(), 'sha256': digest(file)}
    ctx.owner.setdefault('nativeVerifications', {})[phase] = reference; ctx.save()
    return reference


def finalize_semantic_activation(ctx):
    value, candidate_sha, work = admit_runtime(ctx)
    references = ctx.owner.get('nativeVerifications', {})
    need(set(references) == set(SEMANTIC_PHASES), 'All native semantic restart/restore phases are required')
    verified = {}
    for phase in SEMANTIC_PHASES:
        reference = references[phase]
        file = ctx.attempt / reference['file']
        need(file == ctx.directory / ('native-readback-' + phase + '.json') and digest(canonical(file)) == reference['sha256'],
             'Native semantic phase path or original receipt changed')
        readback = read(file)
        need(readback.get('phase') == phase and readback.get('status') == 'VERIFIED'
             and readback.get('descriptorSha256') == candidate_sha and readback.get('localMem0SemanticStatus') == 'PHASE_SEMANTIC_VERIFIED'
             and readback.get('activatedLocalMem0Records') == 30 and readback.get('mergedLocalHistoryRows') == 30
             and readback.get('verificationSubject') == 'INDEPENDENT_REAL_BGE_CANDIDATE'
             and readback.get('appRuntimeValidationMode') == 'ISOLATED_MOCK_QDRANT_RUNTIME'
             and readback.get('mergedLocalMessageRows') == 25 and readback.get('paidModelCalls') == readback.get('llmCalls') == 0,
             'Native semantic phase does not prove its complete actual legacy import')
        semantic_ref = readback['bgeSemanticVerification']; semantic_file = ctx.attempt / semantic_ref['file']
        need(semantic_file == ctx.directory / ('bge-semantic-' + phase + '.json') and digest(canonical(semantic_file)) == semantic_ref['sha256'],
             'Actual BGE semantic receipt changed')
        semantic = read(semantic_file)
        validate_semantic_receipt(semantic, read(work / 'mem0-semantic-plan.json'))
        need(semantic['candidateSha256'] == candidate_sha and semantic['semanticPlanSha256'] == value['mem0SemanticPlanSha256']
             and semantic['status'] == 'SEMANTIC_BRIDGE_VERIFIED' and semantic['phase'] == phase
             and semantic['embeddingProfile'] == BGE_PROFILE and semantic['collection'] == BGE_COLLECTION
             and semantic['dimensions'] == BGE_DIMENSION and semantic['semanticQueries'] >= 2
             and semantic['crossOwnerQueries'] == semantic['semanticQueries']
             and semantic['nativeReadOnlyVerified'] is True and semantic['independentProcess'] is True
             and semantic['ownedRestoredCopy'] is True and semantic['helperCleanup']['pid'] == 0
             and semantic.get('vectorBackend') == 'qdrant' and semantic.get('storageGeneration') == 'qdrant-bge-m3-v1'
             and semantic['helperCleanup']['exitCode'] == 0 and semantic['paidModelCalls'] == semantic['llmCalls'] == 0,
             'BGE activation cannot replace actual query/owner/restore evidence with a flag')
        measured = ctx.resources.summary['containers'].get(semantic['helperCleanup']['containerId'], {})
        need(measured.get('service') == 'bge-verifier' and measured.get('image') == ctx.images['mem0']
             and measured.get('peakBytes', 0) > 0 and measured.get('memoryLimitBytes') == BGE_VERIFIER_MEMORY
             and measured.get('oom') == measured.get('oomKills') == 0,
             'A semantic helper lacks its actual owned cgroup resource evidence')
        qdrant_cleanup = semantic.get('qdrantHelperCleanup', {})
        measured_qdrant = ctx.resources.summary['containers'].get(qdrant_cleanup.get('containerId'), {})
        need(qdrant_cleanup.get('pid') == 0 and qdrant_cleanup.get('exitCode') == 0
             and measured_qdrant.get('service') == 'bge-qdrant' and measured_qdrant.get('image') == value['qdrantImage']
             and measured_qdrant.get('memoryLimitBytes') == 512 * MIB and measured_qdrant.get('peakBytes', 0) > 0
             and measured_qdrant.get('oom') == measured_qdrant.get('oomKills') == 0,
             'Independent Qdrant recovery lacks its own actual bounded cgroup and cleanup evidence')
        verified[phase] = {'readback': reference, 'semantic': semantic_ref}
    result = {**ctx.context(), 'kind': 'doorhandle-native-semantic-activation', 'status': 'VERIFIED_AND_ACTIVATED',
        'project': ctx.project, 'candidateSha256': candidate_sha, 'semanticPlanSha256': value['mem0SemanticPlanSha256'],
        'mem0MergeReceiptSha256': value['mem0MergeReceiptSha256'], 'embeddingProfile': BGE_PROFILE,
        'collection': BGE_COLLECTION, 'dimensions': BGE_DIMENSION, 'activeRecords': 30, 'importedHistoryRows': 30,
        'importedMessageRows': 25, 'archivedRecords': 2, 'archivedHistoryRows': 3, 'archivedMessageRows': 1,
        'candidateSemanticVerified': True, 'productionDataMaterialized': False, 'productionPromotionAllowed': False,
        'verificationSubject': 'INDEPENDENT_REAL_BGE_CANDIDATE', 'appRuntimeValidationMode': 'ISOLATED_MOCK_QDRANT_RUNTIME',
        'vectorBackend': 'qdrant', 'storageGeneration': 'qdrant-bge-m3-v1',
        'paidModelCalls': 0, 'llmCalls': 0, 'verifications': verified}
    file = ctx.directory / 'native-semantic-activation.json'; write(file, result)
    return {'file': file.relative_to(ctx.attempt).as_posix(), 'sha256': digest(file)}


def production_overlay(volumes, rag, commit, rag_sha):
    """Preserved real-BGE target; credentials remain an external private mount."""
    need(rag.get('schemaVersion') == 2 and rag.get('kind') == 'QDRANT_RAG_TARGET'
         and rag.get('identity', {}).get('backend') == 'qdrant', 'A Chroma manifest cannot activate Qdrant')
    return {'services': {
        'mem0': {'environment': {'EMBEDDING_PROFILE': BGE_PROFILE, 'EMBEDDING_MODEL': BGE_MODEL,
            'EMBEDDING_BASE_URL': BGE_BASE, 'MEM0_VECTOR_BACKEND': 'qdrant',
            'MEM0_STORAGE_GENERATION': 'qdrant-bge-m3-v1', 'MEM0_QDRANT_COLLECTION': BGE_COLLECTION}},
        'backend': {'environment': {
            'CHAT_ASSISTANT_RAG_STARTUP_MODE': 'PRESERVE_EXISTING',
            'CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST': '/run/doorhandle-rag/preservation.json',
            'CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST_SHA256': rag_sha,
            'CHAT_ASSISTANT_RAG_PRESERVATION_COMMIT': commit,
            'EMBEDDING_PROFILE': BGE_PROFILE, 'EMBEDDING_MODEL': BGE_MODEL,
            'SEMANTIC_STORAGE_GENERATION': 'qdrant-bge-m3-v1',
            'SEMANTIC_RAG_COLLECTION': rag['identity']['collection'],
            'SEMANTIC_KNOWLEDGE_COLLECTION': 'doorhandle_knowledge_bge_m3_v1',
            'SEMANTIC_EXPERIENCE_COLLECTION': 'doorhandle_experience_bge_m3_v1'},
            'volumes': [{'type': 'volume', 'source': 'native-rag-preservation',
                         'target': '/run/doorhandle-rag', 'read_only': True}]}},
        'volumes': {key: {'name': name, 'external': True} for key, name in volumes.items()}}


def cutover_helper(controller, name, image, arguments, mounts, token, *, data=None, timeout=300):
    """One bounded, owner-labelled native file operation; no original RW mount."""
    disk_before = shutil.disk_usage(controller.work).free
    need(disk_before >= DISK_FLOOR, 'Production native helper lacks its actual host disk reserve')
    command = ['create', '--name', name, '--pull', 'never', '--network', 'none', '--read-only', '--user', '0:0',
        '--cap-drop', 'ALL', '--cap-add', 'DAC_READ_SEARCH', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER',
        '--security-opt', 'no-new-privileges:true', '--pids-limit', '128', '--memory', '256m', '--memory-swap', '256m',
        '--label', NATIVE_CUTOVER_LABEL + '=' + token, '--label', 'io.doorhandle.release=' + controller.args.tag]
    for mount in mounts: command += ['--mount', mount]
    if data is not None: command.append('-i')
    command += ['--entrypoint', 'python', image, *arguments]
    cid = controller.ops.docker(*command, timeout=30).decode().strip()
    need(re.fullmatch(r'[a-f0-9]{64}', cid), 'Production native helper ID is invalid')
    controller.journal.setdefault('nativeHelpers', []).append({'containerId': cid, 'name': name, 'token': token})
    controller.persist()
    try:
        row = json.loads(controller.ops.docker('inspect', cid))[0]
        need(row['Image'] == image and row['Config']['Labels'].get(NATIVE_CUTOVER_LABEL) == token
             and row['Config'].get('OpenStdin') is (data is not None)
             and row['HostConfig']['NetworkMode'] == 'none' and row['HostConfig']['Memory'] == row['HostConfig']['MemorySwap'] == 256 * MIB
             and not row['HostConfig']['Privileged'] and row['HostConfig']['ReadonlyRootfs'], 'Production native helper escaped its fixed admission')
        return controller.ops.docker('start', '-a', *(['-i'] if data is not None else []), cid, data=data, timeout=timeout)
    finally:
        row = json.loads(controller.ops.docker('inspect', cid))[0]
        need(row['Image'] == image and row['Config']['Labels'].get(NATIVE_CUTOVER_LABEL) == token,
             'Cannot stop a changed or foreign native helper')
        controller.ops.docker('stop', '--time', '5', cid, timeout=20)
        final = json.loads(controller.ops.docker('inspect', cid))[0]
        need(not final['State']['Running'] and not final['State'].get('Restarting') and final['State']['Pid'] == 0,
             'Production native helper did not stop')
        disk_after = shutil.disk_usage(controller.work).free
        evidence = {'pid': 0, 'exitCode': final['State']['ExitCode'], 'stopped': True, 'image': final['Image'],
            'memoryLimitBytes': final['HostConfig']['Memory'], 'memorySwapLimitBytes': final['HostConfig']['MemorySwap'],
            'oomKilled': final['State'].get('OOMKilled', False), 'network': final['HostConfig']['NetworkMode'],
            'diskAvailableBeforeBytes': disk_before, 'diskAvailableAfterBytes': disk_after,
            'memoryPeakMeasured': False, 'productionCapacityVerified': False}
        controller.journal['nativeHelpers'][-1].update(evidence)
        controller.persist()
        controller.ops.docker('rm', '--volumes', cid, timeout=30)
        need(evidence['exitCode'] == 0 and evidence['oomKilled'] is False and disk_after >= DISK_FLOOR,
             'Production native helper failed, exceeded memory or exhausted its actual disk reserve')


def prepare_production_native(controller):
    """Final frozen current-cloud restore and pristine, never-test volume install."""
    controller.assert_maintenance()
    private_bge_config(controller.runtime)  # Persistent ECS source, never a candidate transient key.
    root, tag = controller.root, controller.args.tag
    checkout = canonical(root / 'verification' / tag / 'checkout')
    adapter = SimpleNamespace(checkout=checkout, identity=controller.identity,
        args=SimpleNamespace(tag=tag, commit=controller.input['gitCommit'], source_sha256=controller.args.source_sha256))
    candidate, candidate_sha, work = admit_runtime(adapter)
    runtime = read(checkout.parent / 'runtime-acceptance.json')
    legacy = runtime.get('legacyData', {})
    need(runtime.get('status') == 'PASS' and legacy.get('candidateSemanticVerified') is True
         and legacy.get('localMem0SemanticStatus') == 'VERIFIED_AND_ACTIVATED'
         and legacy.get('candidateSha256') == candidate_sha and legacy.get('productionDataMaterialized') is False,
         'Production native installation needs complete semantic/runtime acceptance of this pristine candidate')
    activation = legacy.get('semanticActivation', {})
    activation_file = checkout.parent / activation.get('file', '')
    need(activation_file == checkout / 'work/runtime-acceptance/native-semantic-activation.json'
         and digest(canonical(activation_file)) == activation.get('sha256'), 'Production semantic activation evidence changed')
    need(not controller.journal.get('nativeProductionInstall'), 'An unknown production native install cannot be replayed')
    output = controller.work / 'native-final'; need(not output.exists(), 'Production native outcomes must be fresh')
    output.mkdir(mode=0o700); token = secrets.token_hex(12)
    controller.journal['nativeProductionOwner'] = token; controller.persist()
    account_rows = [json.loads(line) for line in controller.sql(
        "SELECT JSON_OBJECT('userId',id,'username',username) FROM users WHERE id IN (1,18) ORDER BY id;").splitlines()]
    admitted_accounts = read(work / 'owner-proof.json')['accounts']
    need(account_rows == admitted_accounts, 'Final frozen source accounts differ from the admitted legacy/cloud owners')
    final_accounts = output / 'current-account-proof.json'
    write(final_accounts, {'verifiedOnEcs': True, 'identity': {key: controller.identity[key] for key in ('instanceId', 'machineId')},
        'accounts': account_rows, 'verifiedAtUtc': time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime()),
        'source': 'READ_ONLY_FINAL_FROZEN_ORIGINAL_USERS'})
    image = controller.images['mem0']; helper = canonical(controller.source / 'script/jenkins/prepare-legacy-candidate.py')
    for service, label, value in (('mem0', 'io.doorhandle.memory-embedding-profile', BGE_PROFILE),
                                  ('backend', 'io.doorhandle.rag-preservation-protocol', '2')):
        labels = json.loads(controller.ops.docker('image', 'inspect', controller.images[service]))[0]['Config'].get('Labels') or {}
        need(labels.get(label) == value, 'Candidate image lacks its required persistent native-data capability')
    need(digest(helper) == digest(Path(__file__).resolve()), 'Final native helper differs from the fixed release source')
    snapshots = {}
    for service in ('mem0', 'chroma'):
        node = controller.common.container('doorhandlecatch-monolith', service)
        need(node['Id'] == candidate['originalContainers'][service] and not node['State']['Running']
             and not node['State'].get('Restarting') and node['State']['Pid'] == 0,
             'An original native writer was not frozen for the final full snapshot')
        mounts = [m for m in node['Mounts'] if m.get('Type') == 'volume' and m.get('Destination') == '/data']
        need(len(mounts) == 1 and mounts[0]['Name'] == candidate['originalVolumes'][service], 'Original production native mount drifted')
        destination = output / ('fresh-' + service)
        cutover_helper(controller, 'doorhandle-native-' + token + '-snapshot-' + service, image,
            ['-I', '-B', str(helper), 'snapshot-volume', '--source', '/source', '--output', str(destination),
             '--uid', str(os.getuid()), '--gid', str(os.getgid()), '--instance-id', controller.identity['instanceId'],
             '--machine-id', controller.identity['machineId']],
            ['type=volume,src=' + mounts[0]['Name'] + ',dst=/source,readonly',
             'type=bind,src=' + str(controller.source) + ',dst=' + str(controller.source) + ',readonly',
             'type=bind,src=' + str(controller.work) + ',dst=' + str(controller.work)], token)
        fresh = read(destination / 'snapshot-receipt.json'); prior = read(work / ('cloud-' + service) / 'snapshot-receipt.json')
        need(fresh['status'] == 'RESTORED_VERIFIED' and fresh['fullVolume'] is True and fresh['sourceMountedReadOnly'] is True
             and fresh['identity'] == prior['identity'] and fresh['normalizedFiles'] == prior['normalizedFiles']
             and file_inventory(destination / 'restored-originals') == fresh['sourceBefore']
             and digest(destination / 'originals.tar') == fresh['archiveSha256'],
             'Current full native volume drifted since the verified pristine candidate; explicit reconciliation is required')
        snapshots[service] = {'file': str(destination / 'snapshot-receipt.json'), 'sha256': digest(destination / 'snapshot-receipt.json'),
            'archiveSha256': fresh['archiveSha256'], 'sourceVolume': mounts[0]['Name'],
            'normalizedFilesSha256': sha(fresh['normalizedFiles']), 'sourceBeforeSha256': sha(fresh['sourceBefore'])}
    controller.assert_maintenance()
    names = {'doorhandle-mem0-qdrant': 'doorhandlecatch-monolith_native-' + tag + '-' + token + '-mem0',
             'doorhandle-qdrant': 'doorhandlecatch-monolith_native-' + tag + '-' + token + '-qdrant',
             'native-rag-preservation': 'doorhandlecatch-monolith_native-' + tag + '-' + token + '-manifest'}
    existing = controller.ops.docker('volume', 'ls', '--format', '{{.Name}}').decode().splitlines()
    need(not set(names.values()).intersection(existing) and not set(names.values()).intersection(candidate['originalVolumes'].values()),
         'A production native volume name is already present or aliases an original')
    installed = {}; labels = {}; pristine = {}
    for key, name in names.items():
        expected_labels = {NATIVE_CUTOVER_LABEL: token, 'io.doorhandle.release': tag,
            'io.doorhandle.source': controller.args.source_sha256, 'com.docker.compose.project': 'doorhandlecatch-monolith',
            'com.docker.compose.volume': key}
        arguments = ['volume', 'create']
        for key_name, value in expected_labels.items(): arguments += ['--label', key_name + '=' + value]
        controller.ops.docker(*arguments, name)
        row = json.loads(controller.ops.docker('volume', 'inspect', name))[0]
        need(row['Name'] == name and row['Driver'] == 'local' and not row.get('Options') and row.get('Labels') == expected_labels,
             'Production native volume ownership/driver changed')
        labels[key] = expected_labels
        if key == 'native-rag-preservation': continue
        service = 'mem0' if key == 'doorhandle-mem0-qdrant' else 'rag'
        source = canonical(candidate[service + 'DataDirectory'])
        expected = read(work / (service + '-payload-files.json'))
        need(file_inventory(source) == expected, 'Pristine candidate changed before final installation')
        raw = cutover_helper(controller, 'doorhandle-native-' + token + '-install-' + service, image,
            ['-I', '-B', str(helper), 'install-volume', '--source', '/candidate', '--output', '/target'],
            ['type=bind,src=' + str(helper) + ',dst=' + str(helper) + ',readonly',
             'type=bind,src=' + str(source) + ',dst=/candidate,readonly', 'type=volume,src=' + name + ',dst=/target'], token)
        result = json.loads(raw)
        need(result['status'] == 'MATERIALIZED' and result['filesSha256'] == sha(expected)
             and result['files'] == len(expected), 'Production native volume differs from the pristine non-test payload')
        installed[key] = {**result, 'name': name, 'payloadFilesSha256': digest(work / (service + '-payload-files.json'))}
        pristine[key] = {'directory': str(source), 'catalogFile': str(work / (service + '-payload-files.json')),
                         'catalogSha256': digest(work / (service + '-payload-files.json')), 'filesSha256': sha(expected)}
    manifest = read(work / 'rag-preservation-manifest.json')
    manifest_bytes = (work / 'rag-preservation-manifest.json').read_bytes()
    code = "import os,sys,json,hashlib;p='/target/preservation.json';d=sys.stdin.buffer.read(2097153);assert len(d)<=2097152;assert not os.listdir('/target');f=os.fdopen(os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o400),'wb');f.write(d);f.flush();os.fsync(f.fileno());f.close();os.chown(p,10001,10001);os.chown('/target',10001,10001);os.chmod('/target',0o700);print(json.dumps({'sha256':hashlib.sha256(open(p,'rb').read()).hexdigest(),'bytes':len(d)}))"
    copied = json.loads(cutover_helper(controller, 'doorhandle-native-' + token + '-manifest', image, ['-I', '-B', '-c', code],
        ['type=volume,src=' + names['native-rag-preservation'] + ',dst=/target'], token, data=manifest_bytes))
    need(copied['sha256'] == candidate['ragManifestSha256'], 'Production RAG preservation manifest changed')
    installed['native-rag-preservation'] = {'name': names['native-rag-preservation'], **copied}
    overlay = production_overlay(names, manifest, controller.input['gitCommit'], candidate['ragManifestSha256'])
    overlay_file = output / 'native-data.override.json'; write(overlay_file, overlay)
    result = {'schemaVersion': 1, 'kind': 'doorhandle-pristine-native-install', 'status': 'MATERIALIZED_AND_VERIFIED',
        'release': tag, 'commit': controller.input['gitCommit'], 'sourceSha256': controller.args.source_sha256,
        'identity': {key: controller.identity[key] for key in ('instanceId', 'machineId')}, 'owner': token,
        'candidateSha256': candidate_sha, 'semanticActivation': activation, 'semanticActivationSha256': activation['sha256'],
        'semanticActivationFile': str(activation_file), 'sourceFreezeFile': str(controller.work / 'source-freeze.json'),
        'pristinePayloads': pristine, 'images': {**controller.images, 'qdrant': candidate['qdrantImage']},
        'logicalBaselines': {'mem0': {'file': str(work / 'mem0-after.json'), 'sha256': digest(work / 'mem0-after.json')},
                             'rag': {'file': str(work / 'cloud-chroma-after.json'), 'sha256': digest(work / 'cloud-chroma-after.json')}},
        'finalAccountProof': {'file': str(final_accounts), 'sha256': digest(final_accounts)},
        'sourceFreezeSha256': digest(controller.work / 'source-freeze.json'), 'freshSnapshots': snapshots,
        'volumes': installed, 'volumeLabels': labels, 'overlayFile': str(overlay_file), 'overlaySha256': digest(overlay_file),
        'embeddingProfile': BGE_PROFILE, 'embeddingCollection': BGE_COLLECTION, 'embeddingDimensions': BGE_DIMENSION,
        'ragManifestSha256': candidate['ragManifestSha256'], 'originalVolumes': candidate['originalVolumes'],
        'vectorBackend': 'qdrant', 'storageGeneration': 'qdrant-bge-m3-v1',
        'candidateSemanticVerified': True, 'productionDataMaterialized': True, 'runtimeTestVolumesPublished': False,
        'originalVolumesMountedReadOnly': True, 'freshIndependentRestoreVerified': True, 'sourceDriftDetected': False,
        'credentialSource': 'EXISTING_PRIVATE_ECS_ENV', 'privateCredentialFileCopiedIntoPayload': False,
        'activeRecords': 30, 'importedHistoryRows': 30, 'importedMessageRows': 25, 'archivedRecords': 2,
        'archivedHistoryRows': 3, 'archivedMessageRows': 1, 'paidModelCalls': 0, 'llmCalls': 0}
    receipt = output / 'native-production-install.json'; write(receipt, result)
    controller.journal['nativeProductionInstall'] = {'file': str(receipt), 'sha256': digest(receipt),
        'overlayFile': str(overlay_file), 'overlaySha256': result['overlaySha256']}
    need(not (controller.state / 'native-data.json').exists() and not (controller.state / 'native-data.override.json').exists(),
         'Native installation cannot replace an existing persistent binding')
    write(controller.state / 'native-data.override.json', overlay)
    write(controller.state / 'native-data.json', {'schemaVersion': 1, 'kind': 'doorhandle-native-binding',
        'status': 'MATERIALIZED_PENDING_SERVICE_READBACK', 'release': tag, 'commit': controller.input['gitCommit'],
        'sourceSha256': controller.args.source_sha256, 'identity': result['identity'], 'owner': token,
        'installReceiptFile': str(receipt), 'installReceiptSha256': digest(receipt),
        'overlayFile': str(controller.state / 'native-data.override.json'), 'overlaySha256': digest(controller.state / 'native-data.override.json')})
    controller.persist()
    return controller.journal['nativeProductionInstall']


def inspect_native_copy(source, uid, gid):
    source = canonical(source)
    need(source.is_relative_to(ROOT / 'work') and source.name == 'data' and source.parent.name == 'post-start-mem0',
         'Native full content inspection accepts only its owned post-start restored copy')
    sys.path.insert(0, str(ROOT))
    migration = module('production_native_full_readback', ROOT / 'script/memory/migrate_legacy_stores.py')
    try:
        return {'collections': complete_chroma(source / 'chroma', migration), 'history': native_history(source)}
    finally: private_tree(source, uid, gid)


def verify_production_mem0_contents(controller, memory, record, expected):
    """Inspect SDK contents only on an independently recovered owned copy."""
    output = controller.work / 'native-final/post-start-mem0'
    need(not output.exists(), 'A production native full-content outcome cannot be replayed')
    helper = canonical(controller.source / 'script/jenkins/prepare-legacy-candidate.py')
    token = record['owner']; volume = record['volumes']['doorhandle-mem0-qdrant']['name']
    base_mounts = ['type=bind,src=' + str(controller.source) + ',dst=' + str(controller.source) + ',readonly',
                   'type=bind,src=' + str(controller.work) + ',dst=' + str(controller.work)]
    cutover_helper(controller, 'doorhandle-native-' + token + '-post-start-snapshot', record['images']['mem0'],
        ['-I', '-B', str(helper), 'snapshot-volume', '--source', '/source', '--output', str(output),
         '--uid', str(os.getuid()), '--gid', str(os.getgid()), '--instance-id', record['identity']['instanceId'],
         '--machine-id', record['identity']['machineId']],
        ['type=volume,src=' + volume + ',dst=/source,readonly', *base_mounts], token)
    proof = read(output / 'snapshot-receipt.json')
    need(proof.get('status') == 'RESTORED_VERIFIED' and proof.get('fullVolume') is True
         and proof.get('sourceMountedReadOnly') is True and proof.get('identity') == record['identity']
         and digest(output / 'originals.tar') == proof.get('archiveSha256')
         and file_inventory(output / 'restored-originals') == proof.get('sourceBefore'),
         'Post-start native content inspection lacks a complete actual read-only backup/restore')
    raw = cutover_helper(controller, 'doorhandle-native-' + token + '-post-start-readback', record['images']['mem0'],
        ['-I', '-B', str(helper), 'inspect-native-copy', '--source', str(output / 'data'),
         '--uid', str(os.getuid()), '--gid', str(os.getgid())], base_mounts, token)
    need(len(raw) <= 64 * MIB, 'Production native full-content readback exceeds its bounded private result')
    actual = json.loads(raw)
    need(actual == {'collections': expected['collections'], 'history': expected['history']},
         'Production startup changed a memory ID, owner, text, document, metadata or FLOAT32 vector')
    file = controller.work / 'native-final/production-memory-full-readback.json'; write(file, actual)
    live = controller.common.container('doorhandlecatch-monolith', 'mem0')
    need(live['Id'] == memory['Id'] and live['State']['Running'], 'The actual production memory process changed during full readback')
    return {'file': str(file), 'sha256': digest(file), 'snapshotSha256': digest(output / 'snapshot-receipt.json'),
            'collectionCount': len(actual['collections']), 'sourceMountedReadOnly': True, 'originalProcessUnchanged': True,
            'helpers': controller.journal['nativeHelpers'][-2:]}


def verify_production_native(controller):
    sys.path.insert(0, str(ROOT))
    """Read the actual production mounts/protocol after pristine installation.

    No test writes, extraction, embedding or caller-controlled collection switch.
    The persistent source receipt remains immutable when the service starts.
    """
    binding = read(controller.state / 'native-data.json')
    record = read(binding['installReceiptFile'])
    need(digest(Path(binding['installReceiptFile'])) == binding['installReceiptSha256']
         and binding['status'] == 'MATERIALIZED_PENDING_SERVICE_READBACK', 'Native production source proof changed')
    for service, key in (('mem0', 'doorhandle-mem0-qdrant'), ('qdrant', 'doorhandle-qdrant')):
        row = controller.common.container('doorhandlecatch-monolith', service)
        mounts = [m for m in row['Mounts'] if m.get('Destination') == '/data']
        need(row['State']['Running'] and controller.ops.healthy(row['Id']) and len(mounts) == 1
             and mounts[0].get('Type') == 'volume' and mounts[0].get('Name') == record['volumes'][key]['name']
             and row['Image'] == record['images'][service], 'Production service does not mount its admitted pristine owned volume')
    memory = controller.common.container('doorhandlecatch-monolith', 'mem0')
    health = json.loads(controller.ops.docker('exec', memory['Id'], 'python', '-I', '-B', '-c',
        "import json,urllib.request;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=5))))"))
    need(health.get('embedding_profile') == BGE_PROFILE and health.get('embedding_collection') == BGE_COLLECTION
         and health.get('embedding_dimensions') == BGE_DIMENSION and health.get('bridge_auth_configured') is True
         and health.get('vector_backend') == 'qdrant' and health.get('storage_generation') == 'qdrant-bge-m3-v1'
         and health.get('history_mode') == 'single-writer-sqlite',
         'Production memory runtime did not retain the verified BGE vector-space identity')
    baselines = record['logicalBaselines']
    for ref in baselines.values(): need(digest(canonical(ref['file'])) == ref['sha256'], 'Pristine native logical baseline changed')
    native = json.loads(controller.ops.docker('exec', memory['Id'], 'python', '-I', '-B', '-c', NATIVE_SQL_SCRIPT, '/data'))
    full_native = read(baselines['mem0']['file'], 64 * MIB)
    expected_native = full_native['sqlite']
    need(native == expected_native, 'Production startup changed an original or imported native collection/history/message row')
    contents = verify_production_mem0_contents(controller, memory, record, full_native)
    backend = controller.common.container('doorhandlecatch-monolith', 'backend')
    mounts = [m for m in backend['Mounts'] if m.get('Destination') == '/run/doorhandle-rag']
    env = controller.common.environment(backend)
    need(len(mounts) == 1 and mounts[0].get('Name') == record['volumes']['native-rag-preservation']['name']
         and not mounts[0]['RW'] and env.get('CHAT_ASSISTANT_RAG_STARTUP_MODE') == 'PRESERVE_EXISTING'
         and env.get('CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST_SHA256') == record['ragManifestSha256'],
         'Production RAG preservation manifest/env does not match the pristine source')
    observed = controller.ops.docker('exec', backend['Id'], 'sha256sum', '/run/doorhandle-rag/preservation.json').decode().split()[0]
    need(observed == record['ragManifestSha256'], 'Actual production RAG manifest differs')
    manifest = read(Path(record['pristinePayloads']['doorhandle-qdrant']['catalogFile']).parent / 'rag-preservation-manifest.json')
    need(manifest.get('schemaVersion') == 2 and manifest.get('kind') == 'QDRANT_RAG_TARGET'
         and manifest.get('identity', {}).get('backend') == 'qdrant', 'Production RAG requires the new Qdrant target proof')
    from script.memory.qdrant_migration import COLLECTIONS
    expected_rag = read(baselines['rag']['file'], 64 * MIB)['catalog']
    actual_qdrant = json.loads(controller.ops.docker('exec', '-i', memory['Id'], 'python', '-I', '-B', '-c', QDRANT_RUNTIME_SCRIPT,
        data=encoded({'collections': list(COLLECTIONS.values()), 'memory': BGE_COLLECTION, 'profile': BGE_PROFILE,
                      'storageGeneration': 'qdrant-bge-m3-v1', 'allowCreate': False}), timeout=180))
    need(actual_qdrant == expected_rag, 'Production Qdrant readback differs from first stored vectors, payloads or IDs')
    result = {'schemaVersion': 1, 'kind': 'doorhandle-native-production-readback', 'status': 'VERIFIED',
        'release': binding['release'], 'commit': binding['commit'], 'sourceSha256': binding['sourceSha256'],
        'identity': binding['identity'], 'owner': binding['owner'], 'installReceiptSha256': binding['installReceiptSha256'],
        'candidateSemanticVerified': True, 'productionDataMaterialized': True, 'runtimeTestVolumesPublished': False,
        'actualMountsVerified': True, 'embeddingProtocolVerified': True, 'ragManifestVerified': True,
        'actualNativeRowsVerified': True, 'actualRagRecordsVerified': True,
        'actualNativeContentsVerified': True, 'nativeContentReadback': contents,
        'paidModelCalls': 0, 'llmCalls': 0}
    write(controller.work / 'native-production-readback.json', result)
    controller.journal['nativeProductionReadback'] = {'file': str(controller.work / 'native-production-readback.json'),
        'sha256': digest(controller.work / 'native-production-readback.json')}
    controller.persist()
    binding['status'] = 'ACTIVE'; controller.common.write_json(controller.state / 'native-data.json', binding)
    return result


def snapshot_runtime(ctx, folder):
    """Back up the POST-business owned volumes; original business stays running."""
    need(not folder.exists(), 'Native recovery backup must be a new retained outcome')
    folder.mkdir(mode=0o700)
    write(folder / 'native-qdrant-before.json', runtime_qdrant_state(ctx))
    ctx.ops.docker('stop', '--time', '30', ctx.row('qdrant')['Id'], timeout=60)
    need(not ctx.row('qdrant')['State']['Running'], 'Owned Qdrant did not freeze for complete recovery')
    results = {}
    native_before = None
    for service in ('mem0', 'qdrant'):
        need(not ctx.row(service)['State']['Running'] and ctx.row(service)['State']['Pid'] == 0,
             'An owned native writer is still running at backup')
        volume = ctx.config['volumes']['doorhandle-mem0-qdrant' if service == 'mem0' else 'doorhandle-qdrant']['name']
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
            '--instance-id', ctx.identity['instanceId'], '--machine-id', ctx.identity['machineId'],
            '--store-kind', 'qdrant' if service == 'qdrant' else 'legacy-sqlite', timeout=300)
        receipt = read(target / 'snapshot-receipt.json')
        need(receipt['status'] == 'RESTORED_VERIFIED' and receipt['fullVolume'] is True, 'Owned full native backup was not restored')
        results[service] = {'file': str(target / 'snapshot-receipt.json'), 'sha256': digest(target / 'snapshot-receipt.json')}
    write(folder / 'native-recovery.json', {'status': 'RESTORED_VERIFIED', 'project': ctx.project, 'snapshots': results,
                                          'nativeBeforeSha256': digest(folder / 'native-before-sql.json'),
                                          'qdrantBeforeSha256': digest(folder / 'native-qdrant-before.json'),
                                          'phase': 'POST_BUSINESS', 'originalBusinessResourcesChanged': False})
    return folder


def restore_runtime(ctx, folder):
    proof = read(folder / 'native-recovery.json')
    need(proof['status'] == 'RESTORED_VERIFIED' and proof['project'] == ctx.project and proof['phase'] == 'POST_BUSINESS',
         'Native recovery does not belong to this post-business runtime')
    need(digest(folder / 'native-before-sql.json') == proof['nativeBeforeSha256']
         and digest(folder / 'native-qdrant-before.json') == proof['qdrantBeforeSha256'], 'Post-business native before-state changed')
    sources = {}
    for service, descriptor in proof['snapshots'].items():
        file = canonical(descriptor['file']); receipt = read(file)
        need(digest(file) == descriptor['sha256'] and file.parent == folder / service
             and file_inventory(file.parent / 'data') == receipt['normalizedFiles'], 'Full native recovery backup changed')
        sources[service] = file.parent / 'data'
    reference = materialize_runtime(ctx, sources=sources, suffix='restored-' + secrets.token_hex(4))
    ctx.common.write_json(ctx.directory / 'compose.json', ctx.config)
    ctx.dc('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '180', 'qdrant', timeout=240)
    ctx.owner['nativeRecovery'] = {'directory': str(folder), 'beforeSha256': proof['nativeBeforeSha256'],
                                   'recoveryProofSha256': digest(folder / 'native-recovery.json')}
    ctx.save()
    return reference


def measure_runtime_volumes(ctx):
    result = {}
    code = "import os,json;from pathlib import Path;r=Path('/source');files=[p for p in r.rglob('*') if p.is_file()];assert all(not p.is_symlink() for p in r.rglob('*'));print(json.dumps({'files':len(files),'bytes':sum(p.stat().st_size for p in files)}))"
    for service in ('mem0', 'qdrant'):
        volume = ctx.config['volumes']['doorhandle-mem0-qdrant' if service == 'mem0' else 'doorhandle-qdrant']['name']
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
    prepare.add_argument('--runtime', required=True, help='Original ECS private deployment directory; never an env value in argv')
    prepare.add_argument('--settings', required=True, help='Same reviewed private fixed-image settings used by the candidate build')
    clean = sub.add_parser('cleanup')
    for name in ('root', 'tag', 'commit', 'source-sha256', 'instance-id', 'machine-id'): clean.add_argument('--' + name, required=True)
    snapshot = sub.add_parser('snapshot-volume')
    for name in ('source', 'output', 'instance-id', 'machine-id'): snapshot.add_argument('--' + name, required=True)
    snapshot.add_argument('--uid', required=True, type=int); snapshot.add_argument('--gid', required=True, type=int)
    snapshot.add_argument('--store-kind', choices=('legacy-sqlite', 'qdrant'), default='legacy-sqlite')
    worker = sub.add_parser('data-worker'); worker.add_argument('--context', required=True)
    semantic_worker = sub.add_parser('bge-verify-worker'); semantic_worker.add_argument('--context', required=True)
    inspect = sub.add_parser('inspect-native-copy'); inspect.add_argument('--source', required=True)
    inspect.add_argument('--uid', type=int, required=True); inspect.add_argument('--gid', type=int, required=True)
    install = sub.add_parser('install-volume')
    install.add_argument('--source', required=True); install.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'run': result = run(args)
        elif args.action == 'cleanup': result = cleanup(args)
        elif args.action == 'snapshot-volume': result = snapshot_volume(Path(args.source), Path(args.output),
            {'instanceId': args.instance_id, 'machineId': args.machine_id}, args.uid, args.gid, store_kind=args.store_kind)
        elif args.action == 'install-volume': result = install_volume(Path(args.source), Path(args.output))
        elif args.action == 'bge-verify-worker': result = bge_verify_worker(args.context)
        elif args.action == 'inspect-native-copy': result = inspect_native_copy(args.source, args.uid, args.gid)
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
                attempts = 0
                if (work / 'mem0-bge-embeddings.json').is_file():
                    attempts = len(read(work / 'mem0-bge-embeddings.json', 16 * MIB).get('requests', []))
                failure.update(release=args.tag, commit=args.commit, sourceSha256=args.source_sha256,
                    identity={'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'},
                    modelCallsPerformed=attempts > 0, embeddingRequestsAttempted=attempts, paidModelCalls=0, llmCalls=0,
                    candidateSemanticVerified=False, productionDataMaterialized=False, productionPromotionAllowed=False)
                if not (work / 'public-summary.json').exists(): write(work / 'public-summary.json', failure)
                failure['publicSummarySha256'] = digest(work / 'public-summary.json')
            except BaseException: pass
        print(json.dumps(failure), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
