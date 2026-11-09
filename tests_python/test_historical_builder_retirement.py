"""Synthetic proof and callback checks, executed only by Jenkins on ECS.

These tests never address Docker, historical source executors, or business
data. Local inspection is restricted to parsing this file without importing it.
"""
import copy
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE = Path(__file__).resolve().parents[1] / 'script/docker/compact-build-resources.py'
SPEC = importlib.util.spec_from_file_location('historical_builder_resource_tests', MODULE)
resources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resources)
CI_ROOT = Path('/home/ecs-user/doorhandle-ci')
IDENTITY = {'instanceId': 'i-2zeieuov2aum486jm1ek',
            'machineId': '1ebe8f77e3104ab6a49a9386e38abd20', 'executionLocation': 'ECS'}
OLD = [
    ('ci-117-8c898996cc28', '8c898996cc28ce30fd6531710511f833cccb4864',
     'fb5038ca5280788981866fdeeacf9bfdc3e41a1a572ce296458ed3f56f014fce', 'bd2b788d55c093cc2ab97846'),
    ('ci-118-6481f7fa6021', '6481f7fa6021eb36592a081d04f385886c03412a',
     '2c83b9c1a7f1d3b867759a4cbe88e504dcbf28e2339403980d9e96dafdaefb3b', 'fde51da1789e95894d7ba42e'),
    ('ci-130-9a588271dadb', '9a588271dadb135ec4284392ef7b9c9c55ea511d',
     '5bce3b55a78e8efcf4ef351a815af9e644bc0b8592be7bc51816f82c65bcc158', '1adf007e2590d715aa855877'),
]


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def test_reviewed_manifest_is_identical_across_python_controller_and_builder_and_powershell():
    root = MODULE.parents[2]
    source = (root / 'script/jenkins/retire-failed-native-jar-duplicates.py').read_text(encoding='utf8')
    def assigned(tree, name):
        return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
    syntax = ast.parse(source)
    approved = assigned(syntax, 'APPROVED_OLD'); pins = assigned(syntax, 'APPROVED_BUILDER_TOOLS')
    script = (root / 'script/jenkins/retire-failed-native-jar-duplicates.ps1').read_text(encoding='utf8')
    reader = script.split("$reader=@'\n", 1)[1].split("\n'@", 1)[0]
    local = assigned(ast.parse(reader), 'approved')
    numbers = {117, 118, 130, 132, 134, 137, 139, 141, 143, 145, 154, 156, 160, 162, 166, 168}
    assert {int(tag.split('-')[1]) for tag in approved} == numbers
    assert approved == resources.HISTORICAL_BUILDERS and set(pins) == set(approved)
    assert len(local) == len(approved) == 16 and len({number for number, _, _ in local}) == 16
    for number, commit, preservation_sha in local:
        tag = 'ci-' + str(number) + '-' + commit[:12]
        assert approved[tag] == commit and resources.SHA.fullmatch(preservation_sha) and resources.SHA.fullmatch(pins[tag])


def test_newly_reviewed_terminal_builders_use_the_same_complete_original_control_guards():
    for tag, commit in resources.HISTORICAL_BUILDERS.items():
        if int(tag.split('-')[1]) < 132: continue
        state = fixture_state((tag, commit, 'a' * 64, 'b' * 24))
        result = describe(state)
        assert result['release'] == tag and result['commit'] == commit
        state.row['State']['Running'] = True
        with pytest.raises(ValueError): describe(state)


def refresh_references(state):
    state.tools['resourceEvidence']['sha256'] = sha(raw(state.summary))
    state.tools['imageMeasurementSha256'] = sha(raw(state.measurement))


def fixture_state(old=OLD[0]):
    tag, commit, cid, token = old
    context = {'release': tag, 'commit': commit, 'sourceSha256': 'b' * 64}
    descriptor = {'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                  'digest': 'sha256:' + '8' * 64, 'size': 1192}
    diff_ids = ['sha256:' + '5' * 64]
    engine = {'engineImageId': descriptor['digest'], 'configDigest': resources.IMAGE_ID,
              'loadDescriptor': descriptor, 'diffIds': diff_ids, 'os': 'linux', 'architecture': 'amd64'}
    measurement = {'imageId': resources.IMAGE_ID, 'configDigest': resources.IMAGE_ID,
                   'manifestDigest': descriptor['digest'], 'loadDescriptor': copy.deepcopy(descriptor),
                   'compressedBytes': resources.BUILDKIT_LAYER_BYTES,
                   'layers': [{'diffId': value} for value in diff_ids]}
    helpers = {'compact-build-resources.py': 'a' * 64, 'compact-image-inputs.py': 'c' * 64}
    summary = {'version': 1, 'kind': 'doorhandle-candidate-build-resources', **context,
               'identity': copy.deepcopy(IDENTITY), 'ownerToken': token, 'status': 'PASS',
               'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
               'monitorFailure': None, 'originalDataChanged': False,
               'engineIdentity': copy.deepcopy(engine), 'rootlessProfile': resources.rootless_profile_proof(),
               'cleanup': {'creatorStopped': True, 'builderStopped': True, 'daemonImportTerminated': True,
                           'builderContainerId': cid, 'builderExitCode': 0}}
    directory = CI_ROOT / 'inbox' / tag / 'candidate-build-tools'
    tools = {'version': 1, 'kind': 'doorhandle-candidate-build-tools', **context,
             'identity': copy.deepcopy(IDENTITY), 'status': 'PREPARED', 'imageId': resources.IMAGE_ID,
             'imageReference': resources.REFERENCE, 'upstreamVersion': resources.VERSION,
             'licenseSha256': resources.LICENSE_SHA, 'licenseFile': str(directory / 'LICENSE'),
             'hostPluginInstalled': False, 'buildctlBundled': True, 'ociImageLoadVerified': True,
             'helperSha256': helpers['compact-build-resources.py'],
             'imageInputsHelperSha256': helpers['compact-image-inputs.py'],
             'resourceEvidence': {'file': str(directory / 'resource-summary.json'), 'sha256': ''},
             'engineIdentity': copy.deepcopy(engine), 'imageMeasurementSha256': '',
             'rootlessProfile': resources.rootless_profile_proof()}
    volume = 'doorhandle-builder-' + token + '-state'
    row = {'Id': cid, 'Name': '/doorhandle-builder-' + token, 'Image': engine['engineImageId'],
           'Config': {'User': '1000:1000', 'Labels': {resources.LABEL: token,
                       'io.doorhandle.release': tag, 'io.doorhandle.source': context['sourceSha256']}},
           'State': {'Status': 'exited', 'Running': False, 'Restarting': False, 'Paused': False,
                     'OOMKilled': False, 'Pid': 0, 'ExitCode': 0,
                     'StartedAt': '2026-11-08T01:00:00.000000000Z',
                     'FinishedAt': '2026-11-08T01:00:30.000000000Z'},
           'HostConfig': {'Privileged': False, 'Memory': resources.BUILDER_MEMORY,
                          'MemorySwap': resources.BUILDER_MEMORY, 'NanoCpus': 2 * 10 ** 9,
                          'PidsLimit': 1024, 'NetworkMode': 'bridge', 'RestartPolicy': {'Name': 'no'},
                          'AutoRemove': False,
                          'BlkioDeviceWriteBps': [{'Path': '/dev/vda', 'Rate': 64 * resources.MIB}],
                          'SecurityOpt': ['seccomp=unconfined', 'apparmor=' + resources.ROOTLESS_PROFILE,
                                          'systempaths=unconfined'], 'MaskedPaths': [], 'ReadonlyPaths': [],
                          'Tmpfs': {'/tmp': '', '/run/user/1000': ''}},
           'AppArmorProfile': resources.ROOTLESS_PROFILE,
           'Mounts': [{'Type': 'volume', 'Name': volume, 'Driver': 'local',
                       'Source': '/var/lib/docker/volumes/' + volume + '/_data',
                       'Destination': '/home/user/.local/share/buildkit', 'RW': True},
                      {'Type': 'tmpfs', 'Source': '', 'Destination': '/tmp', 'RW': True},
                      {'Type': 'tmpfs', 'Source': '', 'Destination': '/run/user/1000', 'RW': True}]}
    state = SimpleNamespace(root=CI_ROOT, context=context, identity=copy.deepcopy(IDENTITY), tools=tools,
                            summary=summary, measurement=measurement, helpers=helpers, row=row, volume=volume)
    refresh_references(state)
    return state


@pytest.fixture
def builder():
    return fixture_state()


def describe(state):
    return resources.historical_builder_descriptor(state.root, state.context, state.identity,
        raw(state.tools), raw(state.summary), raw(state.measurement), state.helpers, state.row)


def change(value, path, replacement):
    keys = path.split('.')
    for key in keys[:-1]:
        value = value[key]
    value[keys[-1]] = replacement


@pytest.mark.parametrize('old', OLD)
def test_reviewed_builders_can_bind_complete_original_control_bytes(old, monkeypatch):
    state = fixture_state(old)
    def refuse(*_args, **_kwargs):
        pytest.fail('The descriptor must use supplied original bytes, not filesystem, Docker or old code')
    monkeypatch.setattr(Path, 'open', refuse)
    monkeypatch.setattr(Path, 'read_bytes', refuse)
    monkeypatch.setattr(resources.subprocess, 'run', refuse)
    result = describe(state)
    assert all(result[key] == state.context[key] for key in ('release', 'commit', 'sourceSha256'))
    assert result['identity'] == IDENTITY and result['ownerToken'] == state.summary['ownerToken']
    assert result['containerId'] == state.row['Id'] and result['engineImageId'] == state.row['Image']
    assert result['exitCode'] == 0 and result['preservedVolume'] == state.volume
    assert result['inspectSha256'] == sha(resources.encoded(state.row))


@pytest.mark.parametrize(('field', 'value'), [
    ('release', 'ci-131-' + 'a' * 12), ('commit', 'f' * 40), ('sourceSha256', 'not-a-sha'),
])
def test_unreviewed_or_malformed_old_context_is_rejected(builder, field, value):
    builder.context[field] = value
    with pytest.raises(ValueError):
        describe(builder)


@pytest.mark.parametrize('role', ['tools', 'summary'])
@pytest.mark.parametrize(('path', 'value'), [
    ('release', 'ci-118-6481f7fa6021'), ('commit', 'f' * 40), ('sourceSha256', 'e' * 64),
    ('identity.machineId', 'f' * 32), ('identity.executionLocation', 'WINDOWS'),
])
def test_source_or_machine_drift_in_either_old_original_is_refused(builder, role, path, value):
    change(getattr(builder, role), path, value); refresh_references(builder)
    with pytest.raises(ValueError):
        describe(builder)


@pytest.mark.parametrize(('role', 'path', 'value'), [
    ('tools', 'kind', 'unowned-tools'), ('tools', 'status', 'PENDING'),
    ('tools', 'helperSha256', 'f' * 64), ('tools', 'imageInputsHelperSha256', 'f' * 64),
    ('tools', 'resourceEvidence.file', '/home/ecs-user/doorhandle-ci/inbox/other/resource-summary.json'),
    ('tools', 'resourceEvidence.sha256', 'f' * 64), ('tools', 'imageMeasurementSha256', 'f' * 64),
    ('summary', 'kind', 'unowned-resource-summary'), ('summary', 'status', 'FAILED'),
    ('summary', 'ownerToken', '0123456789'), ('summary', 'cleanup.creatorStopped', False),
    ('summary', 'cleanup.builderStopped', False), ('summary', 'cleanup.daemonImportTerminated', False),
    ('summary', 'cleanup.builderContainerId', 'f' * 64), ('summary', 'cleanup.builderExitCode', 1),
])
def test_original_control_schema_hash_and_owner_chain_are_required(builder, role, path, value):
    change(getattr(builder, role), path, value)
    if role == 'summary':
        refresh_references(builder)
    with pytest.raises(ValueError):
        describe(builder)


@pytest.mark.parametrize('damage', ['missing', 'extra', 'malformed'])
def test_two_archived_source_helper_hashes_form_a_closed_binding(builder, damage):
    if damage == 'missing':
        builder.helpers.pop('compact-image-inputs.py')
    elif damage == 'extra':
        builder.helpers['unreviewed.py'] = 'd' * 64
    else:
        builder.helpers['compact-build-resources.py'] = 'not-sha256'
    with pytest.raises(ValueError):
        describe(builder)


@pytest.mark.parametrize(('role', 'path', 'value'), [
    ('measurement', 'configDigest', 'sha256:' + 'f' * 64),
    ('measurement', 'manifestDigest', 'sha256:' + 'f' * 64),
    ('measurement', 'compressedBytes', resources.BUILDKIT_LAYER_BYTES + 1),
    ('tools', 'engineIdentity.engineImageId', resources.IMAGE_ID),
    ('summary', 'engineIdentity.engineImageId', resources.IMAGE_ID),
])
def test_rehashed_controls_cannot_rebind_a_config_or_manifest_engine_identity(builder, role, path, value):
    change(getattr(builder, role), path, value); refresh_references(builder)
    with pytest.raises(ValueError):
        describe(builder)


@pytest.mark.parametrize(('path', 'value'), [
    ('Id', 'f' * 64), ('Name', '/doorhandle-builder-' + 'f' * 24),
    ('Image', resources.IMAGE_ID), ('Config.User', '0:0'),
    ('Config.Labels.io-placeholder', 'unused'),
    ('State.Status', 'running'), ('State.Running', True), ('State.Restarting', True),
    ('State.Paused', True), ('State.OOMKilled', True), ('State.Pid', 1234), ('State.ExitCode', 1),
    ('State.StartedAt', '0001-01-01T00:00:00Z'), ('HostConfig.Privileged', True),
    ('HostConfig.Memory', resources.BUILDER_MEMORY - 1), ('HostConfig.MemorySwap', -1),
    ('HostConfig.NanoCpus', 10 ** 9), ('HostConfig.PidsLimit', 2048),
    ('HostConfig.NetworkMode', 'host'), ('HostConfig.RestartPolicy.Name', 'always'),
    ('HostConfig.MaskedPaths', ['/proc/kcore']), ('AppArmorProfile', 'unconfined'),
])
def test_actual_container_owner_state_and_sandbox_must_still_match(builder, path, value):
    if path == 'Config.Labels.io-placeholder':
        builder.row['Config']['Labels'][resources.LABEL] = 'f' * 24
    else:
        change(builder.row, path, value)
    with pytest.raises(ValueError):
        describe(builder)


@pytest.mark.parametrize('label', ['io.doorhandle.release', 'io.doorhandle.source'])
def test_same_name_or_builder_token_does_not_substitute_for_source_labels(builder, label):
    builder.row['Config']['Labels'][label] = 'other'
    with pytest.raises(ValueError):
        describe(builder)


@pytest.mark.parametrize('damage', ['bind', 'extra-volume', 'renamed-volume', 'volume-target', 'readonly-volume', 'extra-tmpfs'])
def test_only_the_original_buildkit_state_volume_and_two_tmpfs_mounts_are_allowed(builder, damage):
    if damage == 'bind':
        builder.row['Mounts'].append({'Type': 'bind', 'Source': '/srv/business', 'Destination': '/data', 'RW': True})
    elif damage == 'extra-volume':
        builder.row['Mounts'].append({'Type': 'volume', 'Name': 'business-data', 'Destination': '/data', 'RW': True})
    elif damage == 'renamed-volume':
        builder.row['Mounts'][0]['Name'] = 'another-build-state'
    elif damage == 'volume-target':
        builder.row['Mounts'][0]['Destination'] = '/var/lib/mysql'
    elif damage == 'readonly-volume':
        builder.row['Mounts'][0]['RW'] = False
    else:
        builder.row['Mounts'].append({'Type': 'tmpfs', 'Destination': '/unreviewed', 'RW': True})
    with pytest.raises(ValueError):
        describe(builder)


def test_inspect_decoder_accepts_only_one_bounded_json_container(builder):
    assert resources.historical_builder_inspect(raw([builder.row])) == builder.row


@pytest.mark.parametrize('body', [b'', b'[]', b'[{},{}]', b'{}', b'[{"Id":"a","Id":"b"}]', b'null', b'[' + b' ' * (2 * 1024 ** 2) + b']'],
                         ids=['empty', 'empty-list', 'multiple-rows', 'object', 'duplicate-key', 'null', 'oversized'])
def test_inspect_decoder_rejects_ambiguous_or_oversize_originals(body):
    with pytest.raises(ValueError):
        resources.historical_builder_inspect(body)


def callbacks(builder):
    calls = SimpleNamespace(inspected=[], referenced=[], removed=[], listed=0)
    def inspect(cid):
        calls.inspected.append(cid); return copy.deepcopy(builder.row)
    def references(cid):
        calls.referenced.append(cid)
    def remove(cid):
        calls.removed.append(cid)
    def listing():
        calls.listed += 1; return ['e' * 64]
    return calls, inspect, remove, listing, references


def test_removal_rechecks_exact_inspect_and_references_then_only_passes_full_container_id(builder):
    descriptor = describe(builder); calls, inspect, remove, listing, references = callbacks(builder)
    result = resources.historical_builder_remove(descriptor, inspect, remove, listing, references)
    assert calls.inspected == [builder.row['Id'], builder.row['Id']]
    assert calls.referenced == calls.removed == [builder.row['Id']] and calls.listed == 1
    assert result == {'status': 'REMOVED', 'release': builder.context['release'],
                      'containerId': builder.row['Id'], 'preservedVolume': builder.volume,
                      'imagesPreserved': True, 'volumesPreserved': True, 'directoriesPreserved': True}


@pytest.mark.parametrize('stage', ['initial-inspect', 'references', 'second-inspect'])
def test_pre_removal_unknown_or_running_state_never_reaches_the_delete_callback(builder, stage):
    descriptor = describe(builder); calls, inspect, remove, listing, references = callbacks(builder)
    original_inspect = inspect
    def changed_inspect(cid):
        row = original_inspect(cid)
        if stage == 'initial-inspect':
            raise FileNotFoundError('The old object disappeared, not a successful deletion')
        if stage == 'second-inspect' and len(calls.inspected) == 2:
            row['State'].update(Status='running', Running=True, Pid=1234)
        return row
    def blocked_references(cid):
        references(cid)
        if stage == 'references':
            raise ValueError('Another container references the old builder')
    with pytest.raises((ValueError, OSError)):
        resources.historical_builder_remove(descriptor, changed_inspect, remove, listing, blocked_references)
    assert calls.removed == [] and calls.listed == 0


@pytest.mark.parametrize('result', ['still-present', 'daemon-failed'])
def test_delete_without_a_successful_exact_absence_readback_never_reports_removed(builder, result):
    descriptor = describe(builder); calls, inspect, remove, _listing, references = callbacks(builder)
    def uncertain_listing():
        if result == 'daemon-failed':
            raise OSError('Cannot query Docker')
        return [builder.row['Id']]
    with pytest.raises((ValueError, OSError)):
        resources.historical_builder_remove(descriptor, inspect, remove, uncertain_listing, references)
    assert calls.removed == [builder.row['Id']]


@pytest.mark.parametrize('role', ['tools', 'summary', 'measurement'])
def test_duplicate_fields_in_any_original_control_are_not_an_authenticated_document(builder, role):
    values = {name: raw(getattr(builder, name)) for name in ('tools', 'summary', 'measurement')}
    values[role] = values[role][:-1] + b',"kind":"ambiguous","kind":"ambiguous"}'
    with pytest.raises(ValueError):
        resources.historical_builder_descriptor(builder.root, builder.context, builder.identity,
            values['tools'], values['summary'], values['measurement'], builder.helpers, builder.row)
