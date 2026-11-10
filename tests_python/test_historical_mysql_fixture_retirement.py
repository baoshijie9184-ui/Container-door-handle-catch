"""Pure stopped-container proof checks; Jenkins executes these only on ECS.

All passwords, Docker rows and data directory identities here are synthetic.
No test opens a database, starts a container or deletes a real data directory.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest


MODULE = Path(__file__).resolve().parents[1] / 'script/docker/compact-build-resources.py'
SPEC = importlib.util.spec_from_file_location('historical_mysql_fixture_resource_tests', MODULE)
resources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resources)
ROOT = Path('/home/ecs-user/doorhandle-ci')
IDENTITY = {'instanceId': 'i-2zeieuov2aum486jm1ek',
            'machineId': '1ebe8f77e3104ab6a49a9386e38abd20', 'executionLocation': 'ECS'}
SECRET = 'synthetic-private-mysql-password-never-in-evidence'


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def sha(value):
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def fixture():
    context = {'release': 'ci-143-f4b5c8d9e39b',
               'commit': 'f4b5c8d9e39bfe621c97fb1d9e82aea667bab08f', 'sourceSha256': 'b' * 64}
    work = str(ROOT / 'verification' / context['release'] / 'checkout/work/compact-fixtures')
    data = work + '/mysql-data'; cid = 'd' * 64; token = '0123456789'; port = 43127
    owner = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-owner', **context,
             'identity': copy.deepcopy(IDENTITY), 'phase': 'OWNED_SERVER_STOPPED', 'work': work,
             'token': token, 'containerId': cid, 'sourceContainerId': 'e' * 64,
             'image': 'sha256:' + 'f' * 64, 'containerName': 'doorhandle-compact-fixture-' + token,
             'dataDirectory': data, 'port': port, 'rootPassword': SECRET, 'schemas': []}
    cleanup = {'schemaVersion': 1, 'kind': 'doorhandle-compact-fixture-cleanup', **context,
               'identity': copy.deepcopy(IDENTITY), 'status': 'STOPPED', 'errors': [],
               'containerId': cid, 'sourceContainerUntouched': owner['sourceContainerId'],
               'dataDirectoryRetained': data, 'sourceDumpAndEvidenceRetained': True}
    row = {'Id': cid, 'Name': '/' + owner['containerName'], 'Image': owner['image'],
           'Config': {'Env': ['MYSQL_ROOT_PASSWORD=' + SECRET, 'MYSQL_VERSION=8.4.7'],
                      'Cmd': ['--datadir=' + data, '--port=' + str(port), '--bind-address=0.0.0.0',
                              '--mysqlx=OFF', '--event-scheduler=OFF', '--local-infile=OFF',
                              '--innodb-buffer-pool-size=268435456', '--max-connections=120'],
                      'Labels': {'io.doorhandle.compact-fixtures': token,
                                 'io.doorhandle.release': context['release'],
                                 'io.doorhandle.source': context['sourceSha256']}},
           'State': {'Status': 'exited', 'Running': False, 'Restarting': False, 'Paused': False,
                     'Pid': 0, 'ExitCode': 0, 'StartedAt': '2026-11-09T05:00:00.000000000Z',
                     'FinishedAt': '2026-11-09T05:10:00.000000000Z', 'OOMKilled': False},
           'ExecIDs': None,
           'HostConfig': {'Memory': 1536 * 1024 ** 2, 'MemorySwap': 1536 * 1024 ** 2,
                          'NanoCpus': 10 ** 9, 'PidsLimit': 256,
                          'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0},
                          'NetworkMode': 'bridge', 'IpcMode': 'private',
                          'AutoRemove': False, 'Privileged': False,
                          'PortBindings': {str(port) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]},
                          'Tmpfs': {'/var/lib/mysql': ''}},
           'Mounts': [{'Type': 'bind', 'Source': data, 'Destination': data, 'RW': True},
                      {'Type': 'tmpfs', 'Source': '', 'Destination': '/var/lib/mysql', 'RW': True}]}
    return SimpleNamespace(context=context, owner=owner, cleanup=cleanup, row=row,
                           data_metadata=[64771, 1900001, stat.S_IFDIR | 0o700, 999, 999])


def describe(value):
    return resources.historical_mysql_fixture_descriptor(ROOT, value.context, IDENTITY,
        value.owner, value.cleanup, value.row, value.data_metadata)


def change(value, path, replacement):
    parts = path.split('.')
    for part in parts[:-1]:
        value = value[part]
    value[parts[-1]] = replacement


def test_stopped_mysql_descriptor_preserves_the_uid999_directory_without_opening_it(fixture, monkeypatch):
    def refuse(*_args, **_kwargs):
        pytest.fail('The pure descriptor must not read private MySQL pages or run Docker')
    monkeypatch.setattr(Path, 'open', refuse)
    monkeypatch.setattr(Path, 'read_bytes', refuse)
    monkeypatch.setattr(resources.subprocess, 'run', refuse)
    result = describe(fixture)
    assert result['containerId'] == fixture.owner['containerId']
    assert result['dataDirectory'] == fixture.owner['dataDirectory']
    assert result['dataMetadata'] == fixture.data_metadata and result['preservedData'] is True
    assert result['inspectProjection'] == resources.historical_mysql_fixture_projection(fixture.row)
    assert result['inspectSha256'] == sha(resources.encoded(result['inspectProjection']))


def test_projection_and_descriptor_never_copy_env_password_or_other_unreviewed_fields(fixture):
    fixture.row['UnreviewedPrivateField'] = SECRET
    fixture.row['Config']['UnreviewedPrivateField'] = SECRET
    projection = resources.historical_mysql_fixture_projection(fixture.row)
    result = describe(fixture)
    for value in (projection, result):
        evidence = raw(value)
        assert SECRET.encode() not in evidence
        assert b'MYSQL_ROOT_PASSWORD' not in evidence and b'"Env"' not in evidence
        assert b'UnreviewedPrivateField' not in evidence and b'rootPassword' not in evidence


def test_only_the_fixed_binlog_disabled_sources_accept_their_exact_command_and_owner(fixture):
    for tag in ('ci-166-a3c084e1cf56', 'ci-168-a40c779d03a4', 'ci-173-45465e873d92'):
        encoded = json.dumps(vars(fixture)).replace(fixture.context['release'], tag).replace(
            fixture.context['commit'], resources.HISTORICAL_BUILDERS[tag])
        value = SimpleNamespace(**json.loads(encoded))
        if tag in ('ci-168-a40c779d03a4', 'ci-173-45465e873d92'):
            value.owner['binaryLoggingDisabled'] = True
            value.row['Config']['Cmd'].insert(6, '--skip-log-bin')
        assert describe(value)['preservedData'] is True
        wrong_owner = copy.deepcopy(value)
        if tag in ('ci-168-a40c779d03a4', 'ci-173-45465e873d92'):
            wrong_owner.owner.pop('binaryLoggingDisabled')
        else:
            wrong_owner.owner['binaryLoggingDisabled'] = True
        with pytest.raises(ValueError):
            describe(wrong_owner)
        wrong_command = copy.deepcopy(value)
        if tag in ('ci-168-a40c779d03a4', 'ci-173-45465e873d92'):
            wrong_command.row['Config']['Cmd'].remove('--skip-log-bin')
        else:
            wrong_command.row['Config']['Cmd'].insert(6, '--skip-log-bin')
        with pytest.raises(ValueError):
            describe(wrong_command)
        extra = copy.deepcopy(value)
        extra.row['Config']['Cmd'].append('--log-bin-trust-function-creators=ON')
        with pytest.raises(ValueError):
            describe(extra)


@pytest.mark.parametrize(('role', 'path', 'replacement'), [
    ('owner', 'phase', 'PREPARED'), ('owner', 'sourceContainerId', 'd' * 64),
    ('owner', 'work', '/home/ecs-user/doorhandle-ci/verification/other/checkout/work/compact-fixtures'),
    ('owner', 'dataDirectory', '/var/lib/mysql'), ('owner', 'port', 3306),
    ('cleanup', 'status', 'FAILED_OR_UNKNOWN'), ('cleanup', 'errors', ['OWNED_MYSQL_NOT_CONFIRMED']),
    ('cleanup', 'containerId', 'c' * 64), ('cleanup', 'sourceContainerUntouched', 'c' * 64),
    ('cleanup', 'dataDirectoryRetained', '/srv/production/mysql'),
    ('cleanup', 'sourceDumpAndEvidenceRetained', False),
])
def test_owner_and_completed_cleanup_must_bind_one_isolated_retained_directory(fixture, role, path, replacement):
    change(getattr(fixture, role), path, replacement)
    with pytest.raises(ValueError):
        describe(fixture)


@pytest.mark.parametrize(('path', 'replacement'), [
    ('Id', 'c' * 64), ('Image', 'sha256:' + 'c' * 64), ('Name', '/production-mysql'),
    ('State.Status', 'running'), ('State.Running', True), ('State.Restarting', True),
    ('State.Paused', True), ('State.Pid', 1234), ('ExecIDs', ['active-exec']),
    ('HostConfig.RestartPolicy.Name', 'always'), ('HostConfig.MemorySwap', -1),
    ('Config.Cmd', ['--datadir=/var/lib/mysql']),
])
def test_changed_container_or_active_state_never_authorizes_rm(fixture, path, replacement):
    change(fixture.row, path, replacement)
    with pytest.raises(ValueError):
        describe(fixture)


@pytest.mark.parametrize('label', ['io.doorhandle.compact-fixtures', 'io.doorhandle.release', 'io.doorhandle.source'])
def test_container_labels_must_match_the_exact_owner_and_fixed_source(fixture, label):
    fixture.row['Config']['Labels'][label] = 'other'
    with pytest.raises(ValueError):
        describe(fixture)


@pytest.mark.parametrize('damage', ['production-bind', 'extra-bind', 'volume', 'public-port', 'missing-tmpfs'])
def test_only_same_path_data_bind_loopback_port_and_original_tmpfs_are_allowed(fixture, damage):
    if damage == 'production-bind':
        fixture.row['Mounts'][0]['Source'] = '/srv/production/mysql'
    elif damage == 'extra-bind':
        fixture.row['Mounts'].append({'Type': 'bind', 'Source': '/srv/business', 'Destination': '/other', 'RW': True})
    elif damage == 'volume':
        fixture.row['Mounts'][0] = {'Type': 'volume', 'Name': 'business-data', 'Destination': fixture.owner['dataDirectory'], 'RW': True}
    elif damage == 'public-port':
        fixture.row['HostConfig']['PortBindings'][str(fixture.owner['port']) + '/tcp'][0]['HostIp'] = '0.0.0.0'
    else:
        fixture.row['HostConfig']['Tmpfs'] = {}
    with pytest.raises(ValueError):
        describe(fixture)


@pytest.mark.parametrize('metadata', [[64771, 1900001, stat.S_IFLNK | 0o700, 999, 999],
                                   [64771, 1900001, stat.S_IFDIR | 0o777, 999, 999],
                                   [64771, 1900001, stat.S_IFDIR | 0o700, 0, 0],
                                   [64771, 1900001]])
def test_data_metadata_is_an_exact_private_mysql_directory_identity(fixture, metadata):
    fixture.data_metadata = metadata
    with pytest.raises(ValueError):
        describe(fixture)


def admitted(fixture):
    result = describe(fixture)
    result['rawInspectSha256'] = sha(raw([fixture.row]))
    return result


def callbacks(fixture):
    calls = SimpleNamespace(inspected=[], removed=[], referenced=[], data=0)
    def inspect(cid):
        calls.inspected.append(cid)
        return raw([fixture.row])
    def remove(cid):
        calls.removed.append(cid)
    def listing():
        return ['e' * 64]
    def references(cid):
        calls.referenced.append(cid)
    def data():
        calls.data += 1
        return list(fixture.data_metadata)
    return calls, inspect, remove, listing, references, data


def test_only_exact_stopped_container_is_removed_and_directory_metadata_is_unchanged(fixture):
    descriptor = admitted(fixture); calls, inspect, remove, listing, references, data = callbacks(fixture)
    original = copy.deepcopy(fixture.owner), copy.deepcopy(fixture.cleanup), list(fixture.data_metadata)
    result = resources.historical_mysql_fixture_remove(descriptor, inspect, remove, listing, references, data)
    assert result['status'] == 'REMOVED' and result['containerId'] == fixture.owner['containerId']
    assert result['dataDirectoryPreserved'] is True
    assert calls.inspected == [fixture.owner['containerId'], fixture.owner['containerId']]
    assert calls.removed == calls.referenced == [fixture.owner['containerId']] and calls.data >= 2
    assert (fixture.owner, fixture.cleanup, fixture.data_metadata) == original


@pytest.mark.parametrize('when', ['before-first-inspect', 'after-reference-check'])
def test_env_change_is_detected_by_raw_sha_even_when_the_safe_projection_is_identical(fixture, when):
    descriptor = admitted(fixture); calls, inspect, remove, listing, references, data = callbacks(fixture)
    previous_projection = copy.deepcopy(descriptor['inspectProjection'])
    if when == 'before-first-inspect':
        fixture.row['Config']['Env'][0] = 'MYSQL_ROOT_PASSWORD=changed-synthetic-password'
    def change_at_reference(cid):
        references(cid)
        if when == 'after-reference-check':
            fixture.row['Config']['Env'][0] = 'MYSQL_ROOT_PASSWORD=changed-synthetic-password'
    with pytest.raises(ValueError):
        resources.historical_mysql_fixture_remove(descriptor, inspect, remove, listing, change_at_reference, data)
    assert resources.historical_mysql_fixture_projection(fixture.row) == previous_projection
    assert calls.removed == []


@pytest.mark.parametrize('when', ['before-rm', 'after-rm'])
def test_data_inode_change_is_never_reported_as_preserved(fixture, when):
    descriptor = admitted(fixture); calls, inspect, remove, listing, references, data = callbacks(fixture)
    def changed_data():
        value = data()
        if when == 'before-rm' or calls.removed:
            value[1] += 1
        return value
    with pytest.raises(ValueError):
        resources.historical_mysql_fixture_remove(descriptor, inspect, remove, listing, references, changed_data)
    assert calls.removed == ([] if when == 'before-rm' else [fixture.owner['containerId']])


def test_missing_post_rm_container_list_does_not_claim_success(fixture):
    descriptor = admitted(fixture); calls, inspect, remove, _listing, references, data = callbacks(fixture)
    def unavailable():
        raise OSError('Synthetic Docker readback unavailable')
    with pytest.raises((ValueError, OSError)):
        resources.historical_mysql_fixture_remove(descriptor, inspect, remove, unavailable, references, data)
    assert calls.removed == [fixture.owner['containerId']]


RECENT_MYSQL_TAGS = ('ci-195-2c2e65a0daa9', 'ci-198-7af0903ee840', 'ci-201-803baf401b5f')


def recent_mysql_fixture(fixture, tag=RECENT_MYSQL_TAGS[0]):
    commit, recipe = resources.RECENT_MYSQL_FIXTURE_SOURCES[tag]
    body = json.dumps(vars(fixture)).replace(fixture.context['release'], tag).replace(fixture.context['commit'], commit)
    value = SimpleNamespace(**json.loads(body))
    value.owner['binaryLoggingDisabled'] = True
    value.row['Config']['Cmd'].insert(6, '--skip-log-bin')
    proof = {'path': 'inbox/' + tag + '/source.tar.gz', 'sha256': value.context['sourceSha256'],
             'transportRecipeSha256': recipe, 'builderHelperSha256': dict(resources.RECENT_MYSQL_HELPERS[tag])}
    return value, proof


def describe_recent(value, proof):
    return resources.historical_mysql_fixture_descriptor(ROOT, value.context, IDENTITY,
        value.owner, value.cleanup, value.row, value.data_metadata, source_proof=proof)


@pytest.mark.parametrize('tag', RECENT_MYSQL_TAGS)
def test_recent_three_stopped_mysql_objects_require_their_explicit_source_and_hide_private_values(fixture, monkeypatch, tag):
    value, proof = recent_mysql_fixture(fixture, tag)
    def refuse(*_args, **_kwargs):
        pytest.fail('Recent object admission cannot read retained database pages or execute Docker')
    monkeypatch.setattr(Path, 'open', refuse); monkeypatch.setattr(Path, 'read_bytes', refuse)
    monkeypatch.setattr(resources.subprocess, 'run', refuse)
    proof['rootPassword'] = SECRET
    value.row['Config']['UnreviewedPrivateField'] = SECRET
    result = describe_recent(value, proof)
    assert tag not in resources.HISTORICAL_BUILDERS
    assert result['containerId'] == value.owner['containerId'] and result['preservedData'] is True
    assert result['dataMetadata'] == value.data_metadata and result['dataDirectory'] == value.owner['dataDirectory']
    assert result['fixtureSourceProof']['path'] == proof['path']
    assert result['fixtureSourceProof']['sha256'] == value.context['sourceSha256']
    assert result['fixtureSourceProof']['transportRecipeSha256'] == proof['transportRecipeSha256']
    assert value.owner['binaryLoggingDisabled'] is True
    assert result['inspectProjection']['Config']['Cmd'][6] == '--skip-log-bin'
    assert result['inspectProjection']['Config']['Cmd'].count('--skip-log-bin') == 1
    for document in (result, resources.historical_mysql_fixture_projection(value.row)):
        evidence = raw(document)
        assert SECRET.encode() not in evidence and b'MYSQL_ROOT_PASSWORD' not in evidence
        assert b'"Env"' not in evidence and b'rootPassword' not in evidence and b'UnreviewedPrivateField' not in evidence


@pytest.mark.parametrize('tag', RECENT_MYSQL_TAGS)
def test_recent_three_do_not_expand_default_historical_mysql_permission_without_source_proof(fixture, tag):
    value, _proof = recent_mysql_fixture(fixture, tag)
    historical = dict(resources.HISTORICAL_BUILDERS)
    with pytest.raises(ValueError): describe(value)
    assert resources.HISTORICAL_BUILDERS == historical and tag not in historical


@pytest.mark.parametrize('damage', ['transport-recipe', 'builder-helper', 'source-archive'])
def test_recent_mysql_source_recipe_helper_or_archive_hash_drift_refuses_admission(fixture, damage):
    value, proof = recent_mysql_fixture(fixture)
    if damage == 'transport-recipe': proof['transportRecipeSha256'] = 'a' * 64
    elif damage == 'builder-helper': proof['builderHelperSha256']['compact-build-resources.py'] = 'a' * 64
    else: proof['sha256'] = 'a' * 64
    with pytest.raises(ValueError): describe_recent(value, proof)


@pytest.mark.parametrize('damage', ['truthy-owner-flag', 'missing-switch', 'changed-switch'])
def test_recent_mysql_binlog_proof_requires_true_and_the_exact_skip_switch(fixture, damage):
    value, proof = recent_mysql_fixture(fixture)
    if damage == 'truthy-owner-flag': value.owner['binaryLoggingDisabled'] = 1
    elif damage == 'missing-switch': value.row['Config']['Cmd'].remove('--skip-log-bin')
    else: value.row['Config']['Cmd'][6] = '--skip-log-bin=ON'
    with pytest.raises(ValueError): describe_recent(value, proof)


@pytest.mark.parametrize('tag', RECENT_MYSQL_TAGS)
def test_recent_source_helper_result_cannot_mutate_the_shared_permission_registry(fixture, tag):
    value, proof = recent_mysql_fixture(fixture, tag)
    original = copy.deepcopy(resources.RECENT_MYSQL_HELPERS)
    admitted_source = resources.recent_mysql_fixture_source(value.context, proof)
    assert admitted_source['builderHelperSha256'] is not resources.RECENT_MYSQL_HELPERS[tag]
    assert admitted_source['builderHelperSha256'] is not proof['builderHelperSha256']
    admitted_source['builderHelperSha256']['compact-build-resources.py'] = 'a' * 64
    assert resources.RECENT_MYSQL_HELPERS == original and proof['builderHelperSha256'] == original[tag]
    assert resources.recent_mysql_fixture_source(value.context, proof)['builderHelperSha256'] == original[tag]


@pytest.mark.parametrize(('target', 'other'), [
    ('ci-195-2c2e65a0daa9', 'ci-201-803baf401b5f'),
    ('ci-201-803baf401b5f', 'ci-195-2c2e65a0daa9'),
])
def test_recent_mysql_helper_revision_from_another_reviewed_attempt_is_rejected(fixture, target, other):
    value, proof = recent_mysql_fixture(fixture, target)
    proof['builderHelperSha256'] = dict(resources.RECENT_MYSQL_HELPERS[other])
    with pytest.raises(ValueError): describe_recent(value, proof)


@pytest.mark.parametrize('tag', RECENT_MYSQL_TAGS)
def test_recent_mysql_source_commit_cannot_be_changed_under_a_registered_release(fixture, tag):
    value, proof = recent_mysql_fixture(fixture, tag)
    value.context['commit'] = 'a' * 40
    with pytest.raises(ValueError): describe_recent(value, proof)


@pytest.mark.parametrize(('tag', 'commit'), [
    ('ci-187-8e90ba50c691', '8e90ba50c691d561bd26b23f037fec1600e5e9de'),
    ('ci-188-df1e1a54d48e', 'df1e1a54d48e5005185f53459068fbe9efffe333'),
    ('ci-189-410506ad7c82', '410506ad7c82e302e623a2ac27b63dc345fcd131'),
])
def test_superseded_recent_mysql_attempt_does_not_keep_source_permission(fixture, tag, commit):
    value, proof = recent_mysql_fixture(fixture)
    value.context.update(release=tag, commit=commit)
    proof['path'] = 'inbox/' + tag + '/source.tar.gz'
    with pytest.raises(ValueError): resources.recent_mysql_fixture_source(value.context, proof)


def test_recent_remove_uses_one_ordinary_object_callback_and_preserves_retained_data_identity(fixture):
    value, proof = recent_mysql_fixture(fixture)
    descriptor = describe_recent(value, proof); descriptor['rawInspectSha256'] = sha(raw([value.row]))
    calls, inspect, remove, listing, references, data = callbacks(value)
    preserved = copy.deepcopy(value.owner), copy.deepcopy(value.cleanup), list(value.data_metadata)
    result = resources.historical_mysql_fixture_remove(descriptor, inspect, remove, listing, references, data)
    assert result['status'] == 'REMOVED' and result['containerId'] == value.owner['containerId']
    assert calls.inspected == [value.owner['containerId'], value.owner['containerId']]
    assert calls.removed == calls.referenced == [value.owner['containerId']] and calls.data >= 2
    assert result['dataDirectoryPreserved'] is True and result['imagesPreserved'] is True and result['volumesPreserved'] is True
    assert (value.owner, value.cleanup, value.data_metadata) == preserved


@pytest.mark.parametrize('when', ['before-rm', 'after-rm'])
def test_recent_remove_refuses_a_changed_retained_data_inode_at_either_readback(fixture, when):
    value, proof = recent_mysql_fixture(fixture)
    descriptor = describe_recent(value, proof); descriptor['rawInspectSha256'] = sha(raw([value.row]))
    calls, inspect, remove, listing, references, data = callbacks(value)
    def changed_data():
        metadata = data()
        if when == 'before-rm' or calls.removed: metadata[1] += 1
        return metadata
    with pytest.raises(ValueError):
        resources.historical_mysql_fixture_remove(descriptor, inspect, remove, listing, references, changed_data)
    assert calls.removed == ([] if when == 'before-rm' else [value.owner['containerId']])


def test_recent_remove_rechecks_source_proof_before_any_object_command(fixture):
    value, proof = recent_mysql_fixture(fixture)
    descriptor = describe_recent(value, proof); descriptor['rawInspectSha256'] = sha(raw([value.row]))
    descriptor['fixtureSourceProof']['transportRecipeSha256'] = 'a' * 64
    calls, inspect, remove, listing, references, data = callbacks(value)
    with pytest.raises(ValueError):
        resources.historical_mysql_fixture_remove(descriptor, inspect, remove, listing, references, data)
    assert calls.inspected == calls.removed == calls.referenced == [] and calls.data == 0
