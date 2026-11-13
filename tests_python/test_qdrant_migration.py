"""Qdrant migration contracts; provider/LLM calls are never made by these tests."""
import copy
import os
import uuid

import pytest

from script.memory import qdrant_migration as target
from memory_service.qdrant_store import ID_PROTOCOL, point_id
from tests_python import qdrant_fixture

ecs_memory_qdrant = qdrant_fixture.ecs_memory_qdrant


def record(logical='legacy-public-id', owner='doorhandlecatch:user:1'):
    return {'id': logical, 'metadata': {'data': 'Preserve inspection evidence', 'user_id': owner,
            'agent_id': 'doorhandlecatch'}, 'embedding': [3.0, 4.0] + [0.0] * 1022}


def test_provider_and_stored_fingerprints_are_different_but_semantically_equal():
    raw, stored = record()['embedding'], [.6, .8] + [0.] * 1022
    target.normalized_agreement(raw, stored)
    assert target.fingerprint(raw) != target.fingerprint(stored)
    with pytest.raises(ValueError): target.normalized_agreement(raw, [1.] + [0.] * 1023)
    with pytest.raises(ValueError): target.normalized_agreement([0.] * 1024, stored)
    with pytest.raises(ValueError): target.fingerprint([0.] * 256)
    with pytest.raises(ValueError): target.fingerprint([float('nan')] + [0.] * 1023)


def test_java_manifest_binds_first_stored_vector_and_exact_derived_system_scope():
    source = {'id': 'document@generation:0', 'document': 'Preserve source text',
              'metadata': {'source': 'archive', 'title': 'Inspection'}, 'embedding': record()['embedding']}
    frozen = copy.deepcopy(source)
    imported = {'provenance': {source['id']: {'rawVectorSha256': 'a' * 64,
        'storedVectorSha256': 'b' * 64, 'cosineNormalizationVerified': True}}}
    manifest = target.rag_manifest('c' * 40, 'generation', [source], imported)
    assert manifest['schemaVersion'] == 2 and manifest['identity']['idProtocol'] == ID_PROTOCOL
    assert manifest['records'][0]['metadata'] == {**source['metadata'], 'kind': 'SYSTEM_RAG',
        'generation': 'generation', 'visibility': 'SYSTEM', 'lifecycle': 'ACTIVE'}
    assert manifest['records'][0]['rawVectorSha256'] != manifest['records'][0]['storedVectorSha256']
    assert source == frozen


@pytest.fixture
def remote_memory(ecs_memory_qdrant, monkeypatch):
    config, client = ecs_memory_qdrant
    owned = 'doorhandle_test_migration_' + uuid.uuid4().hex
    monkeypatch.setitem(target.COLLECTIONS, 'mem0', owned)
    scheme = 'https' if config['https'] else 'http'
    remote = target.Remote(scheme + '://' + config['host'] + ':' + str(config['port']),
                           os.environ['DOORHANDLE_TEST_QDRANT_KEY_FILE'])
    try:
        yield remote, owned
    finally:
        if client.collection_exists(owned): client.delete_collection(owned)


def test_real_qdrant_import_preserves_public_id_owner_and_first_stored_float32(remote_memory):
    remote, collection = remote_memory
    first = remote.import_records(collection, [record()])
    stored = first['records']['legacy-public-id']
    assert stored['physicalId'] == point_id(collection, 'legacy-public-id')
    assert stored['payload']['doorhandle_logical_id'] == 'legacy-public-id'
    assert stored['payload']['user_id'] == 'doorhandlecatch:user:1'
    assert first['provenance']['legacy-public-id']['cosineNormalizationVerified'] is True
    assert first['provenance']['legacy-public-id']['rawVectorSha256'] != stored['storedVectorSha256']
    second = remote.import_records(collection, [record()])
    assert first['inserted'] == 1 and second['inserted'] == 0 and second['records'] == first['records']
    with pytest.raises(ValueError): remote.import_records(collection, [record(owner='doorhandlecatch:user:18')])
    assert remote.catalog(collection) == first['records']


class SnapshotNode:
    """Protocol fixture: it proves guard logic, not a real engine recovery."""
    def __init__(self, base, catalog, source=None, corrupt=False):
        self.base, self.catalogue, self.source, self.corrupt = base, copy.deepcopy(catalog), source, corrupt

    def complete_catalog(self):
        return copy.deepcopy(self.catalogue)

    def request(self, method, route, body=None):
        if route == '/collections': return {'collections': [{'name': key} for key in self.catalogue]}
        if route.endswith('/snapshots'):
            assert method == 'POST'
            return {'name': 'owned.snapshot', 'checksum': 'a' * 64, 'size': 1024}
        assert method == 'PUT' and route.endswith('/snapshots/recover?wait=true')
        assert body['priority'] == 'snapshot' and body['location'].startswith('file:///qdrant/recovery/')
        collection = route.split('/')[2]
        self.catalogue[collection] = copy.deepcopy(self.source.catalogue[collection])
        if self.corrupt: self.catalogue[collection]['records']['logical']['storedVectorSha256'] = 'f' * 64
        return True


@pytest.mark.parametrize('corrupt', [False, True])
def test_snapshot_recovery_requires_independent_empty_server_and_exact_stored_catalogue(corrupt):
    catalog = {name: {'identity': {'idProtocol': ID_PROTOCOL}, 'records': {
        'logical': {'physicalId': point_id(name, 'logical'), 'storedVectorSha256': 'a' * 64, 'payload': {}}}}
        for name in target.COLLECTIONS.values()}
    source = SnapshotNode('http://127.0.0.1:61001', catalog)
    recovered = SnapshotNode('http://127.0.0.1:61002', {}, source=source, corrupt=corrupt)
    if corrupt:
        with pytest.raises(ValueError): target.Remote.snapshot_recovery(source, recovered, '/qdrant/recovery')
    else:
        proof = target.Remote.snapshot_recovery(source, recovered, '/qdrant/recovery')
        assert proof['status'] == 'RESTORED_VERIFIED' and proof['exactStoredFloat32Verified'] is True
        assert proof['independentServer'] is True and len(proof['snapshots']) == 4
        with pytest.raises(ValueError): target.Remote.snapshot_recovery(source, recovered, '/qdrant/recovery')
    with pytest.raises(ValueError): target.Remote.snapshot_recovery(source, source, '/qdrant/recovery')
