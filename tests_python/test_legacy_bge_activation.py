"""ECS-only legacy BGE activation contracts; no external provider or LLM calls."""
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import threading
import shutil
import subprocess
import sys
import sqlite3
from types import SimpleNamespace

import pytest

from tests_python import test_legacy_store_migration as legacy


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('legacy_bge_activation_contract', ROOT / 'script/jenkins/prepare-legacy-candidate.py')
candidate = importlib.util.module_from_spec(spec); spec.loader.exec_module(candidate)
migration = legacy.migration


def test_isolated_data_worker_imports_only_the_fixed_checkout_package(tmp_path):
    checkout = tmp_path / 'verification/ci-71-aaaaaaaaaaaa/checkout'
    helper = checkout / 'script/jenkins/prepare-legacy-candidate.py'; helper.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / 'script/jenkins/prepare-legacy-candidate.py', helper)
    package = checkout / 'memory_service'; package.mkdir()
    (package / '__init__.py').write_text('')
    shutil.copyfile(ROOT / 'memory_service/embedding_config.py', package / 'embedding_config.py')
    migration_file = checkout / 'script/memory/migrate_legacy_stores.py'; migration_file.parent.mkdir()
    migration_file.write_text("def ecs_identity(*args):\n from memory_service import embedding_config\n from pathlib import Path\n assert Path(embedding_config.__file__).resolve().parents[1] == Path(__file__).resolve().parents[2]\n print(embedding_config.MODEL)\n raise SystemExit(0)\n")
    context = checkout / 'context.json'; candidate.write(context, {'identity': {'instanceId': 'fixture', 'machineId': 'fixture'}})
    launcher = "import importlib.util,sys;s=importlib.util.spec_from_file_location('fixed_worker',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.data_worker(sys.argv[2])"
    result = subprocess.run([sys.executable, '-I', '-B', '-c', launcher, str(helper), str(context)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'BAAI/bge-m3'
    assert not list(checkout.rglob('__pycache__'))


@pytest.mark.parametrize('changed', [False, True])
def test_worker_command_uses_mounted_checkout_when_controller_loaded_from_release(tmp_path, changed):
    checkout = tmp_path / 'verification/ci-71-aaaaaaaaaaaa/checkout'
    release = tmp_path / 'releases/ci-71-aaaaaaaaaaaa'
    for folder in (checkout, release):
        helper = folder / 'script/jenkins/prepare-legacy-candidate.py'; helper.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'script/jenkins/prepare-legacy-candidate.py', helper)
    spec = importlib.util.spec_from_file_location('separate_release_bge_launcher', release / 'script/jenkins/prepare-legacy-candidate.py')
    controller = importlib.util.module_from_spec(spec); spec.loader.exec_module(controller)
    phase = checkout / 'work/runtime-acceptance/bge-after-start'; phase.mkdir(parents=True)
    context = phase / 'context.json'; candidate.write(context, {'fixture': True})
    if changed:
        with (checkout / 'script/jenkins/prepare-legacy-candidate.py').open('a') as stream: stream.write('\n# drift\n')
        with pytest.raises(ValueError, match='admitted mounted checkout'): controller.bge_worker_command(SimpleNamespace(checkout=checkout), phase, context)
    else:
        command = controller.bge_worker_command(SimpleNamespace(checkout=checkout), phase, context)
        docker_command = controller.bge_container_command(SimpleNamespace(checkout=checkout, project='owned-rehearsal',
            token='a' * 12, args=SimpleNamespace(tag='ci-71-' + 'a' * 12), images={'mem0': 'sha256:' + 'b' * 64}),
            'owned-bge-worker', phase, context)
        mounts = [docker_command[index + 1] for index, value in enumerate(docker_command) if value == '--mount']
        assert mounts == ['type=bind,src=' + str(checkout) + ',dst=' + str(checkout) + ',readonly',
                          'type=bind,src=' + str(phase) + ',dst=' + str(phase)]
        assert docker_command[-len(command):] == command and Path(command[2]).is_relative_to(checkout)
        assert Path(command[2]).is_relative_to(checkout) and not Path(command[2]).is_relative_to(release)
        spec = importlib.util.spec_from_file_location('actual_worker_mounted_root', command[2])
        worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
        assert worker.ROOT == checkout and command[-1] == str(context)


def test_actual_request_counter_survives_sliding_window_expiry_and_counts_failures():
    from collections import deque
    class Adapter:
        def __init__(self): self._calls = deque(); self.clock = 0
        def _request(self, texts):
            while self._calls and self.clock - self._calls[0] >= 60: self._calls.popleft()
            self._calls.append(self.clock)
            if texts == ['failed']: raise ValueError('provider failed')
            return texts
    adapter = Adapter(); original = Adapter._request
    with candidate.embedding_request_counter(Adapter) as count:
        assert adapter._request(['first']) == ['first']
        adapter.clock = 61; assert adapter._request(['second']) == ['second']
        assert len(adapter._calls) == 1 and count == {'attempted': 2, 'succeeded': 2}
        with pytest.raises(ValueError): adapter._request(['failed'])
        assert count == {'attempted': 3, 'succeeded': 2}
    assert Adapter._request is original


@pytest.mark.parametrize('damage', ['none', 'unknown-owner', 'other-app', 'wrong-bge-model', 'collision'])
def test_nonempty_cloud_union_preserves_bound_vectors_and_rejects_unproven_scope(tmp_path, inputs, damage):
    from chromadb import PersistentClient
    from chromadb.config import Settings
    from memory_service.embedding_config import SPACE_METADATA
    _, mapping = inputs
    client = PersistentClient(path=str(tmp_path / 'chroma'), settings=Settings(anonymized_telemetry=False))
    metadata = {'data': 'Original cloud inspection preference with enough detail for an independently bound retrieval question.',
                'user_id': 'doorhandlecatch:user:1', 'agent_id': 'doorhandlecatch'}
    if damage == 'unknown-owner': metadata['user_id'] = 'unverified-principal'
    if damage == 'other-app': metadata['agent_id'] = 'another-app'
    space = dict(SPACE_METADATA)
    if damage == 'wrong-bge-model': space['doorhandle_embedding_model'] = 'another-model'
    bound = client.create_collection(candidate.BGE_COLLECTION, metadata=space, embedding_function=None)
    bound.add(ids=['cloud-native'], metadatas=[metadata], embeddings=[[1.0] + [0.0] * 1023])
    old = client.create_collection('old-qwen-source', embedding_function=None)
    old_meta = {**metadata, 'data': 'Different text'} if damage == 'collision' else metadata
    old.add(ids=['cloud-native' if damage == 'collision' else 'cloud-old'], metadatas=[old_meta], embeddings=[[0.0, 1.0]])
    before = {'collections': candidate.complete_chroma(tmp_path / 'chroma', migration)}
    before['sqlite'] = {'collections': {row['id']: {'records': len(row['records'])} for row in before['collections'].values()}}
    frozen = copy.deepcopy(before)
    try:
        if damage != 'none':
            with pytest.raises(ValueError): candidate.cloud_memory_records(tmp_path, before, mapping, migration)
        else:
            rows, vectors = candidate.cloud_memory_records(tmp_path, before, mapping, migration)
            assert len(rows) == 2 and set(vectors) == {'cloud-native'} and vectors['cloud-native']['embedding'] == [1.0] + [0.0] * 1023
            assert all(row['metadata'] == metadata for row in rows)
        assert before == frozen and candidate.complete_chroma(tmp_path / 'chroma', migration) == before['collections']
    finally: client._system.stop()


def test_native_production_overlay_contains_only_admitted_persistent_volumes_and_public_protocol():
    names = {'doorhandle-mem0': 'native-mem0', 'doorhandle-chroma': 'native-chroma', 'native-rag-preservation': 'native-manifest'}
    result = candidate.production_overlay(names, {'embeddingDimension': 256, 'collection': 'knowledge',
        'tenant': 'default_tenant', 'database': 'default_database'}, 'a' * 40, 'b' * 64)
    assert set(result['services']) == {'mem0', 'backend'}
    assert all(value == {'external': True, 'name': names[key]} for key, value in result['volumes'].items())
    assert result['services']['mem0']['environment']['EMBEDDING_PROFILE'] == 'siliconflow-bge-m3-v1'
    raw = json.dumps(result)
    assert all(value not in raw for value in ('DB_PASSWORD', 'API_KEY', 'checkout', 'runtime_test_', 'model-fixture'))
    assert result['services']['backend']['volumes'][0]['read_only'] is True


@pytest.mark.parametrize('cloud_mode', ['empty', 'unbound', 'bound-idempotent'])
def test_real_chroma_merge_covers_all_30_history_messages_and_existing_cloud_records(tmp_path, monkeypatch, cloud_mode):
    from chromadb import PersistentClient
    from chromadb.config import Settings
    from memory_service.embedding_config import SPACE_METADATA
    work = tmp_path / 'candidate'; data = work / 'mem0/data'; data.mkdir(parents=True, mode=0o700)
    client = PersistentClient(path=str(data / 'chroma'), settings=Settings(anonymized_telemetry=False))
    original = client.create_collection('doorhandle_memories', embedding_function=None)
    source = legacy.legacy_bundle(); template = source['records'][0]
    source['records'] = []
    for index in range(32):
        row = copy.deepcopy(template); row['id'] = 'preserved-' + str(index)
        row['metadata'].update(user_id='admin' if index < 23 else 'doorhandlecatch:user:18' if index < 30 else 'integration-user',
            data='Inspection memory number ' + str(index) + ': retain original container images and require a human reviewer to verify coating defects before report approval.')
        row['textSha256'] = hashlib.sha256(row['metadata']['data'].encode()).hexdigest(); source['records'].append(row)
    h = source['history'][0]; m = source['messages'][0]
    source['history'] = [{**h, 'id': 'history-' + str(i), 'memory_id': 'preserved-' + str(i),
                          'new_memory': source['records'][min(i, 31)]['metadata']['data']} for i in range(33)]
    source['messages'] = [{**m, 'id': 'message-' + str(i), 'session_scope': 'user_id=' +
        ('admin' if i < 20 else 'doorhandlecatch:user:18' if i < 25 else 'integration-user')} for i in range(26)]
    mapping = legacy.owner_map(source)
    with sqlite3.connect(data / 'history.db') as db:
        db.execute('CREATE TABLE history (id TEXT PRIMARY KEY,memory_id TEXT,old_memory TEXT,new_memory TEXT,event TEXT,created_at DATETIME,updated_at DATETIME,is_deleted INTEGER,actor_id TEXT,role TEXT)')
        db.execute('CREATE TABLE messages (id TEXT PRIMARY KEY,session_scope TEXT,role TEXT,content TEXT,name TEXT,created_at DATETIME)')
        db.execute("INSERT INTO messages VALUES ('original-cloud-message','agent_id=doorhandlecatch&user_id=doorhandlecatch:user:1','user','preserve original cloud input',NULL,NULL)")
    existing_vector = [0.125] + [0.0] * 1023
    if cloud_mode == 'bound-idempotent':
        bound = client.create_collection(candidate.BGE_COLLECTION, metadata=SPACE_METADATA, embedding_function=None)
        projected = migration.project(source, mapping)['records'][0]
        bound.add(ids=[projected['id']], metadatas=[projected['metadata']], embeddings=[existing_vector])
    if cloud_mode == 'unbound':
        original.add(ids=['cloud-extra'], metadatas=[{'user_id': 'admin', 'data':
            'Current cloud preference: preserve all inspection evidence and include reviewer explanations in the final approved report.'}], embeddings=[[1.0, 0.0]])
    before = {'collections': candidate.complete_chroma(data / 'chroma', migration),
              'history': candidate.native_history(data), 'sqlite': candidate.native_sql_state(data)}
    candidate.write(work / 'mem0-before.json', before)
    snapshot = work / 'cloud-mem0'; snapshot.mkdir(); (snapshot / 'originals.tar').write_bytes(b'unit-fixture-original-byte-archive')
    identity = {'instanceId': 'fixture-instance', 'machineId': 'fixture-machine'}
    candidate.write(snapshot / 'snapshot-receipt.json', {'status': 'RESTORED_VERIFIED', 'fullVolume': True,
        'identity': identity, 'archiveSha256': candidate.digest(snapshot / 'originals.tar')})
    provider = work / 'provider-private.json'; candidate.write(provider, {'embeddingProfile': candidate.BGE_PROFILE,
        'model': candidate.BGE_MODEL, 'baseUrl': candidate.BGE_BASE, 'dimensions': None,
        'verifiedTargetRuntime': True, 'apiKey': 'fixture-not-a-real-key'})
    calls = []
    class FakeOpenAI:
        def __init__(self, **settings):
            assert settings['max_retries'] == 0 and settings['base_url'] == candidate.BGE_BASE
            self.embeddings = self
        def create(self, **request):
            calls.append(request)
            assert request['model'] == candidate.BGE_MODEL and 'dimensions' not in request
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[0.5] + [0.0] * 1023)
                for i in range(len(request['input']))], model=candidate.BGE_MODEL, usage=None)
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv('EMBEDDING_PROFILE', candidate.BGE_PROFILE)
    try:
        result = candidate.merge_legacy_mem0(work, data, source, mapping, {'identity': identity,
            'release': 'ci-71-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
            'bgeProviderFile': str(provider)}, migration)
        assert result['mergedRecords'] == 30 and result['mergedHistoryRows'] == 30 and result['mergedMessageRows'] == 25
        assert result['targetRecords'] == (31 if cloud_mode == 'unbound' else 30)
        assert result['currentCloudRecords'] == (0 if cloud_mode == 'empty' else 1)
        assert result['currentCloudReembeddedRecords'] == (1 if cloud_mode == 'unbound' else 0)
        assert [len(call['input']) for call in calls][:4] == [8, 8, 8, 6]
        after = candidate.read(work / 'mem0-after.json', 64 * candidate.MIB)
        old_key = next(k for k, v in before['collections'].items() if v['name'] == 'doorhandle_memories')
        assert after['collections'][old_key] == before['collections'][old_key]
        assert all(after['history']['messages'].get(k) == v for k, v in before['history']['messages'].items())
        if cloud_mode == 'bound-idempotent':
            row = client.get_collection(candidate.BGE_COLLECTION, embedding_function=None).get(ids=['preserved-0'], include=['embeddings'])
            assert list(row['embeddings'][0]) == existing_vector
    finally: client._system.stop()


@pytest.mark.parametrize('damage', ['none', 'test-volume', 'wrong-model', 'native-row-loss', 'rag-record-loss'])
def test_production_materialized_flag_requires_actual_pristine_mount_and_all_native_rows(tmp_path, monkeypatch, damage):
    state = tmp_path / 'state'; state.mkdir(); work = tmp_path / 'cutover'; work.mkdir()
    source = tmp_path / 'pristine'; source.mkdir()
    native = {'collections': {'owned': {'name': candidate.BGE_COLLECTION, 'records': 30}}, 'history': {'messages': {}, 'history': {}}}
    rag = {'knowledge': {'records': {'fixture-document': {'vectorSha256': 'a' * 64}}}}
    for name, value in [('mem0-after.json', {'sqlite': native}), ('rag-after.json', rag),
                        ('rag-preservation-manifest.json', {'collection': 'knowledge', 'tenant': 'default_tenant',
                           'database': 'default_database', 'recordCount': 83}), ('catalog.json', {})]:
        candidate.write(source / name, value)
    record = {'images': {'mem0': 'sha256:' + '1' * 64, 'chroma': 'sha256:' + '2' * 64},
        'volumes': {'doorhandle-mem0': {'name': 'pristine-memory'}, 'doorhandle-chroma': {'name': 'pristine-rag'},
                    'native-rag-preservation': {'name': 'pristine-manifest'}},
        'logicalBaselines': {key: {'file': str(source / name), 'sha256': candidate.digest(source / name)}
                            for key, name in [('mem0', 'mem0-after.json'), ('rag', 'rag-after.json')]},
        'pristinePayloads': {'doorhandle-chroma': {'catalogFile': str(source / 'catalog.json')}},
        'ragManifestSha256': candidate.digest(source / 'rag-preservation-manifest.json')}
    receipt = work / 'native-production-install.json'; candidate.write(receipt, record)
    binding = {'status': 'MATERIALIZED_PENDING_SERVICE_READBACK', 'release': 'ci-71-' + 'a' * 12,
        'commit': 'a' * 40, 'sourceSha256': 'b' * 64, 'identity': {'instanceId': 'fixture', 'machineId': 'c' * 32},
        'owner': 'f' * 24, 'installReceiptFile': str(receipt), 'installReceiptSha256': candidate.digest(receipt)}
    candidate.write(state / 'native-data.json', binding)
    nodes = {}
    for service, volume in [('mem0', 'pristine-memory'), ('chroma', 'pristine-rag')]:
        nodes[service] = {'Id': service, 'Image': record['images'][service], 'State': {'Running': True},
            'Mounts': [{'Destination': '/data', 'Type': 'volume', 'Name': volume}]}
    nodes['backend'] = {'Id': 'backend', 'Mounts': [{'Destination': '/run/doorhandle-rag', 'Name': 'pristine-manifest', 'RW': False}],
        'environment': {'CHAT_ASSISTANT_RAG_STARTUP_MODE': 'PRESERVE_EXISTING',
                        'CHAT_ASSISTANT_RAG_PRESERVATION_MANIFEST_SHA256': record['ragManifestSha256']}}
    if damage == 'test-volume': nodes['mem0']['Mounts'][0]['Name'] = 'runtime-test-memory'
    health = {'embedding_profile': candidate.BGE_PROFILE, 'embedding_collection': candidate.BGE_COLLECTION,
              'embedding_dimensions': 1024, 'bridge_auth_configured': True}
    if damage == 'wrong-model': health['embedding_profile'] = 'explicit-openai-compatible'
    def docker(*args, **kwargs):
        if args[1] == 'mem0':
            if args[-1] == '/data': return candidate.encoded({**native, 'collections': {}} if damage == 'native-row-loss' else native)
            return candidate.encoded(health)
        if args[1] == 'backend': return (record['ragManifestSha256'] + '  preservation.json').encode()
        assert args[:3] == ('exec', '-i', 'chroma')
        return candidate.encoded({'collections': {} if damage == 'rag-record-loss' else rag, 'retrievalQueries': 83})
    def update(path, value): path.write_bytes(candidate.encoded(value))
    controller = SimpleNamespace(state=state, work=work, journal={}, persist=lambda: None,
        common=SimpleNamespace(container=lambda project, service: nodes[service], environment=lambda row: row['environment'], write_json=update),
        ops=SimpleNamespace(docker=docker, healthy=lambda cid: True))
    monkeypatch.setattr(candidate, 'verify_production_mem0_contents', lambda *args: {'sha256': 'd' * 64, 'sourceMountedReadOnly': True})
    if damage != 'none':
        with pytest.raises(ValueError): candidate.verify_production_native(controller)
        assert candidate.read(state / 'native-data.json')['status'] == 'MATERIALIZED_PENDING_SERVICE_READBACK'
        assert not (work / 'native-production-readback.json').exists()
    else:
        result = candidate.verify_production_native(controller)
        assert result['productionDataMaterialized'] and result['actualNativeRowsVerified'] and result['actualRagRecordsVerified']
        assert candidate.read(state / 'native-data.json')['status'] == 'ACTIVE'
        assert controller.journal['nativeProductionReadback']['sha256'] == candidate.digest(work / 'native-production-readback.json')


@pytest.mark.parametrize('damage', ['none', 'vector', 'owner', 'document'])
def test_post_start_full_mem0_readback_rejects_same_count_content_replacement(tmp_path, monkeypatch, damage):
    source = tmp_path / 'releases/ci-71-aaaaaaaaaaaa'; helper = source / 'script/jenkins/prepare-legacy-candidate.py'
    helper.parent.mkdir(parents=True); shutil.copyfile(ROOT / 'script/jenkins/prepare-legacy-candidate.py', helper)
    work = source / 'work/compact-cutover-0123456789'; (work / 'native-final').mkdir(parents=True)
    rows = {'memory-id': {'metadata': {'user_id': 'doorhandlecatch:user:1', 'data': 'Keep original evidence'},
                          'document': None, 'vectorSha256': 'a' * 64}}
    expected = {'collections': {'collection': {'name': candidate.BGE_COLLECTION, 'records': rows}}, 'history': {'history': {}, 'messages': {}}}
    actual = copy.deepcopy(expected)
    if damage == 'vector': actual['collections']['collection']['records']['memory-id']['vectorSha256'] = 'b' * 64
    if damage == 'owner': actual['collections']['collection']['records']['memory-id']['metadata']['user_id'] = 'doorhandlecatch:user:18'
    if damage == 'document': actual['collections']['collection']['records']['memory-id']['document'] = 'replacement document'
    identity = {'instanceId': 'fixture', 'machineId': 'c' * 32}; memory = {'Id': 'm' * 64, 'State': {'Running': True}}
    record = {'owner': 'd' * 24, 'identity': identity, 'images': {'mem0': 'sha256:' + 'e' * 64},
              'volumes': {'doorhandle-mem0': {'name': 'pristine-memory'}}}
    calls = []
    def helper_operation(controller, name, image, arguments, mounts, token, **kwargs):
        calls.append((arguments, mounts))
        controller.journal['nativeHelpers'].append({'name': name, 'image': image, 'pid': 0, 'stopped': True,
            'exitCode': 0, 'memoryLimitBytes': 256 * candidate.MIB, 'memoryPeakMeasured': False})
        output = work / 'native-final/post-start-mem0'
        if 'snapshot-volume' in arguments:
            assert 'type=volume,src=pristine-memory,dst=/source,readonly' in mounts
            output.mkdir(); original = output / 'restored-originals'; original.mkdir()
            (original / 'raw.sqlite').write_bytes(b'private source fixture bytes')
            (output / 'originals.tar').write_bytes(b'fixture archive with separately checked digest')
            candidate.write(output / 'snapshot-receipt.json', {'status': 'RESTORED_VERIFIED', 'fullVolume': True,
                'identity': identity, 'sourceMountedReadOnly': True, 'archiveSha256': candidate.digest(output / 'originals.tar'),
                'sourceBefore': candidate.file_inventory(original)})
            return b'{}'
        assert 'inspect-native-copy' in arguments and arguments[arguments.index('--source') + 1] == str(output / 'data')
        assert all(not mount.startswith('type=volume') for mount in mounts)
        return candidate.encoded(actual)
    monkeypatch.setattr(candidate, 'cutover_helper', helper_operation)
    controller = SimpleNamespace(work=work, source=source, journal={'nativeHelpers': []},
        common=SimpleNamespace(container=lambda *args: memory))
    if damage != 'none':
        with pytest.raises(ValueError, match='FLOAT32 vector'): candidate.verify_production_mem0_contents(controller, memory, record, expected)
        assert not (work / 'native-final/production-memory-full-readback.json').exists()
    else:
        proof = candidate.verify_production_mem0_contents(controller, memory, record, expected)
        assert proof['sha256'] == candidate.digest(work / 'native-final/production-memory-full-readback.json')
        assert proof['sourceMountedReadOnly'] and proof['originalProcessUnchanged'] and len(calls) == 2


@pytest.mark.parametrize('payload', [None, b'private-manifest-byte-fixture'])
def test_production_helper_opens_stdin_at_create_and_delivers_exact_manifest_bytes(tmp_path, monkeypatch, payload):
    calls = []; cid = 'a' * 64; image = 'sha256:' + 'b' * 64; token = 'c' * 24
    row = {'Image': image, 'Config': {'Labels': {candidate.NATIVE_CUTOVER_LABEL: token}, 'OpenStdin': payload is not None},
           'HostConfig': {'NetworkMode': 'none', 'Memory': 256 * candidate.MIB, 'MemorySwap': 256 * candidate.MIB,
                          'Privileged': False, 'ReadonlyRootfs': True},
           'State': {'Running': False, 'Restarting': False, 'Pid': 0, 'ExitCode': 0}}
    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == 'create':
            assert ('-i' in args) is (payload is not None)
            return cid.encode()
        if args[0] == 'inspect': return candidate.encoded([row])
        if args[0] == 'start':
            assert args == ('start', '-a', *(('-i',) if payload is not None else ()), cid)
            assert kwargs['data'] == payload
            return b'exact-helper-output'
        return b''
    monkeypatch.setattr(candidate.shutil, 'disk_usage', lambda path: SimpleNamespace(free=candidate.DISK_FLOOR + candidate.GIB))
    controller = SimpleNamespace(args=SimpleNamespace(tag='ci-71-' + 'a' * 12), journal={}, work=tmp_path,
                                 persist=lambda: None, ops=SimpleNamespace(docker=docker))
    assert candidate.cutover_helper(controller, 'owned-fixture', image, ['-I', '-B', '-c', 'pass'], [], token,
                                    data=payload) == b'exact-helper-output'
    assert controller.journal['nativeHelpers'][0]['stopped'] and calls[-1][0] == ('rm', '--volumes', cid)


@pytest.fixture
def inputs():
    bundle = legacy.legacy_bundle()
    texts = [
        'Container handle coating defects need a second human inspection before a quality report can be approved. '
        'The saved account preference is to retain the original image and inspection evidence for traceability.',
        'Model comparison reports should show precision and recall beside the inference latency for the current inspection batch. '
        'The inspector prefers reviewing model evaluation evidence before selecting a production model.',
        'This integration-only fixture must remain private and must never be attached to a real person.']
    for row, text in zip(bundle['records'], texts):
        row['metadata']['data'] = text; row['textSha256'] = hashlib.sha256(text.encode()).hexdigest()
    mapping = legacy.owner_map(bundle)
    return bundle, mapping


def test_semantic_plan_binds_partial_questions_to_both_actual_owner_targets(inputs):
    bundle, mapping = inputs; frozen = copy.deepcopy(bundle)
    plan = candidate.semantic_plan(bundle, mapping, migration)
    assert bundle == frozen and plan['sourceBundleSha256'] == migration.sha(migration.canonical(bundle))
    assert {case['owner'] for case in plan['cases']} == {'doorhandlecatch:user:1', 'doorhandlecatch:user:18'}
    assert {case['expectedId'] for case in plan['cases']} == {'legacy-memory-0', 'legacy-memory-1'}
    assert plan['collection'] == 'doorhandle_memories_bge_m3_v1' and plan['dimensions'] == 1024
    for case in plan['cases']:
        row = next(row for row in bundle['records'] if row['id'] == case['expectedId'])
        assert case['query'] != row['metadata']['data']
        assert case['querySha256'] != row['textSha256'] and case['topK'] <= 5
        assert case['expectedTextSha256'] == hashlib.sha256(row['metadata']['data'].encode()).hexdigest()


@pytest.mark.parametrize('damage', ['one-owner', 'short-anchor', 'mapping-sha'])
def test_semantic_plan_rejects_unproven_accounts_or_unusable_questions(inputs, damage):
    bundle, mapping = inputs
    if damage == 'one-owner': mapping['owners'][1].update(disposition='archive')
    if damage == 'short-anchor':
        bundle['records'][0]['metadata']['data'] = ''; mapping = legacy.owner_map(bundle)
    if damage == 'mapping-sha': mapping['sourceBundleSha256'] = '0' * 64
    with pytest.raises((ValueError, migration.MigrationError)):
        candidate.semantic_plan(bundle, mapping, migration)


@pytest.fixture
def bridge(inputs):
    bundle, mapping = inputs
    projected = migration.project(bundle, mapping)
    state = {'mode': 'normal', 'requests': []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append((self.path, body, self.headers.get('X-Doorhandle-Memory-Token')))
            authenticated = self.headers.get('X-Doorhandle-Memory-Token') == 'fixture-token'
            if not authenticated and state['mode'] != 'unauthenticated-open':
                self.send_response(401); self.end_headers(); return
            assert self.path == '/memories/search' and body['scope'] == 'ACCOUNT'
            rows = [row for row in projected['records'] if row['metadata']['user_id'] == body['user_id']]
            if state['mode'] == 'foreign-owner': rows = projected['records']
            if state['mode'] == 'missing-target': rows = []
            items = [{'id': row['id'], 'memory': row['metadata']['data']} for row in rows]
            if state['mode'] == 'changed-text':
                for row in items: row['memory'] += ' changed after snapshot'
            if state['mode'] == 'duplicate-id': items *= 2
            if state['mode'] == 'archived-row':
                items.append({'id': bundle['records'][2]['id'], 'memory': bundle['records'][2]['metadata']['data']})
            raw = json.dumps({'code': 200, 'data': items}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield 'http://127.0.0.1:' + str(server.server_port), state
    finally:
        server.shutdown(); thread.join(timeout=5); server.server_close()


def test_actual_http_semantic_queries_verify_target_text_and_cross_owner_isolation(inputs, bridge):
    bundle, mapping = inputs; base, state = bridge
    plan = candidate.semantic_plan(bundle, mapping, migration)
    result = candidate.verify_semantic_bridge(bundle, mapping, plan, base, 'fixture-token', migration)
    assert result['semanticQueries'] == result['crossOwnerQueries'] == 2
    assert result['embeddingRequests'] == 4 and result['paidModelCalls'] == result['llmCalls'] == 0
    assert all(row['rank'] == 1 and row['unauthenticatedReadStatus'] == 401 for row in result['queries'])
    assert len(state['requests']) == 6
    public = json.dumps(result)
    assert 'fixture-token' not in public and all(case['query'] not in public and case['expectedId'] not in public for case in plan['cases'])


@pytest.mark.parametrize('mode', ['foreign-owner', 'missing-target', 'changed-text', 'duplicate-id', 'archived-row', 'unauthenticated-open'])
def test_live_response_flags_cannot_replace_actual_target_and_authorization_checks(inputs, bridge, mode):
    bundle, mapping = inputs; base, state = bridge; state['mode'] = mode
    with pytest.raises(ValueError):
        candidate.verify_semantic_bridge(bundle, mapping, candidate.semantic_plan(bundle, mapping, migration), base, 'fixture-token', migration)


def test_changed_expected_target_is_rejected_before_any_network_request(inputs, bridge):
    bundle, mapping = inputs; base, state = bridge
    plan = candidate.semantic_plan(bundle, mapping, migration); plan['cases'][0]['expectedId'] = 'legacy-memory-2'
    with pytest.raises(ValueError, match='changed'):
        candidate.verify_semantic_bridge(bundle, mapping, plan, base, 'fixture-token', migration)
    assert state['requests'] == []


def provider_file(tmp_path, text):
    runtime = tmp_path / 'runtime'; deploy = runtime / 'deploy'; deploy.mkdir(parents=True)
    path = deploy / 'cloud.env'; path.write_text(text, encoding='utf8'); os.chmod(path, 0o600)
    return runtime, path


def test_private_prepared_profile_is_read_without_mutating_original_or_using_llm_key(tmp_path):
    text = 'EMBEDDING_PROFILE=siliconflow-bge-m3-v1\nEMBEDDING_MODEL=BAAI/bge-m3\nEMBEDDING_BASE_URL=https://api.siliconflow.cn/v1\nEMBEDDING_API_KEY=sk-' + 'a' * 30 + '\nDASHSCOPE_API_KEY=must-never-be-inherited\n'
    runtime, path = provider_file(tmp_path, text); before = path.read_bytes()
    config = candidate.private_bge_config(runtime)
    assert path.read_bytes() == before and config['apiKey'] == 'sk-' + 'a' * 30
    assert config['dimensions'] is None and 'must-never-be-inherited' not in json.dumps(config)


@pytest.mark.parametrize('change', ['model', 'provider', 'profile', 'missing-key', 'duplicate', 'two-keys', 'file-only'])
def test_private_profile_refuses_paid_or_ambiguous_fallbacks(tmp_path, change):
    text = 'EMBEDDING_PROFILE=siliconflow-bge-m3-v1\nEMBEDDING_MODEL=BAAI/bge-m3\nEMBEDDING_BASE_URL=https://api.siliconflow.cn/v1\nEMBEDDING_API_KEY=sk-' + 'a' * 30 + '\n'
    if change == 'model': text = text.replace('BAAI/bge-m3', 'Pro/BAAI/bge-m3')
    if change == 'provider': text = text.replace('api.siliconflow.cn', 'another.example')
    if change == 'profile': text = text.replace('siliconflow-bge-m3-v1', 'explicit-openai-compatible')
    if change == 'missing-key': text = '\n'.join(line for line in text.splitlines() if not line.startswith('EMBEDDING_API_KEY='))
    if change == 'duplicate': text += 'EMBEDDING_MODEL=BAAI/bge-m3\n'
    if change == 'two-keys': text += 'EMBEDDING_API_KEY_FILE=/never/read/this/file\n'
    if change == 'file-only': text = '\n'.join(line for line in text.splitlines() if not line.startswith('EMBEDDING_API_KEY=')) + '\nEMBEDDING_API_KEY_FILE=/never/read/this/file\n'
    runtime, path = provider_file(tmp_path, text); before = path.read_bytes()
    with pytest.raises(ValueError): candidate.private_bge_config(runtime)
    assert path.read_bytes() == before


def semantic_receipt(plan):
    return {'status': 'SEMANTIC_BRIDGE_VERIFIED', 'planSha256': candidate.sha(plan), 'queryProtocol': plan['protocol'],
        'semanticQueries': 2, 'crossOwnerQueries': 2, 'embeddingRequests': 4,
        'queries': [{'ownerSha256': hashlib.sha256(case['owner'].encode()).hexdigest(), 'querySha256': case['querySha256'],
            'expectedIdSha256': hashlib.sha256(case['expectedId'].encode()).hexdigest(), 'sourceTextSha256': case['expectedTextSha256'],
            'topK': case['topK'], 'rank': 1, 'unauthenticatedReadStatus': 401} for case in plan['cases']],
        'embeddingProfile': candidate.BGE_PROFILE, 'collection': candidate.BGE_COLLECTION, 'model': candidate.BGE_MODEL,
        'dimensions': 1024, 'nativeReadOnlyVerified': True, 'independentProcess': True, 'ownedRestoredCopy': True,
        'paidModelCalls': 0, 'llmCalls': 0, 'nativeBeforeSha256': 'a' * 64, 'nativeAfterSha256': 'a' * 64}


@pytest.mark.parametrize('damage', ['query-missing', 'wrong-target', 'rank', 'unauthenticated', 'wrong-model', 'old-collection',
                                   'dimension', 'paid', 'llm', 'drift', 'no-new-process', 'no-restore', 'request-count'])
def test_activation_receipt_requires_real_query_bindings_and_native_recovery(inputs, damage):
    plan = candidate.semantic_plan(*inputs, migration); value = semantic_receipt(plan)
    if damage == 'query-missing': value['queries'].pop()
    if damage == 'wrong-target': value['queries'][0]['expectedIdSha256'] = 'f' * 64
    if damage == 'rank': value['queries'][0]['rank'] = 99
    if damage == 'unauthenticated': value['queries'][0]['unauthenticatedReadStatus'] = 200
    if damage == 'wrong-model': value['model'] = 'qwen3.7-text-embedding-flash'
    if damage == 'old-collection': value['collection'] = 'doorhandle_memories'
    if damage == 'dimension': value['dimensions'] = 256
    if damage == 'paid': value['paidModelCalls'] = 1
    if damage == 'llm': value['llmCalls'] = 1
    if damage == 'drift': value['nativeAfterSha256'] = 'b' * 64
    if damage == 'no-new-process': value['independentProcess'] = False
    if damage == 'no-restore': value['ownedRestoredCopy'] = False
    if damage == 'request-count': value['embeddingRequests'] = 0
    with pytest.raises(ValueError): candidate.validate_semantic_receipt(value, plan)


def test_complete_semantic_receipt_is_source_anchored_and_does_not_assert_production_install(inputs):
    plan = candidate.semantic_plan(*inputs, migration); value = semantic_receipt(plan)
    candidate.validate_semantic_receipt(value, plan)
    assert 'productionDataMaterialized' not in value
