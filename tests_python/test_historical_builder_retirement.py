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
    numbers = {117, 118, 130, 132, 134, 137, 139, 141, 143, 145, 154, 156, 160, 166, 168, 173}
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


def test_recent_builder_permission_is_separate_and_pins_the_original_201_source_and_tools():
    assert resources.RECENT_BUILDER_SOURCES == {
        'ci-201-803baf401b5f': {
            'commit': '803baf401b5f9566283a59cb6a885a794b9d7d85',
            'sourceSha256': '5049079bdb37231b8ca2d59f7865269735ce0ce01cae56d0084a81924fa6767a',
            'toolsSha256': '352792942c7228c241c34637707f67d964f92ebcab2d8f31577ba6ca2affffdc',
        },
    }
    assert not set(resources.RECENT_BUILDER_SOURCES).intersection(resources.HISTORICAL_BUILDERS)
    assert len(resources.HISTORICAL_BUILDERS) == 16


@pytest.fixture
def recent_builder(monkeypatch):
    tag = 'ci-201-803baf401b5f'
    state = fixture_state((tag, '803baf401b5f9566283a59cb6a885a794b9d7d85',
                           '6fc35fc387502b40ee8990b617bd5b566c66b5fbeee9c7ddb2888c489b21846f',
                           'ede5921fbf249493de57e778'))
    state.context['sourceSha256'] = '5049079bdb37231b8ca2d59f7865269735ce0ce01cae56d0084a81924fa6767a'
    state.tools.update(state.context); state.summary.update(state.context)
    state.helpers = dict(resources.RECENT_MYSQL_HELPERS[tag])
    state.tools['helperSha256'] = state.helpers['compact-build-resources.py']
    state.tools['imageInputsHelperSha256'] = state.helpers['compact-image-inputs.py']
    state.row['Config']['Labels']['io.doorhandle.source'] = state.context['sourceSha256']
    state.row['State']['ExitCode'] = state.summary['cleanup']['builderExitCode'] = 1
    refresh_references(state)
    # Pure unit controls have synthetic engine/layer bytes. Replace only their
    # tools digest in this test scope; production pins remain fixed above.
    registry = copy.deepcopy(resources.RECENT_BUILDER_SOURCES)
    registry[tag]['toolsSha256'] = sha(raw(state.tools))
    monkeypatch.setattr(resources, 'RECENT_BUILDER_SOURCES', registry)
    return state


def test_recent_builder_requires_the_same_complete_original_controls_and_preserves_state(recent_builder):
    result = describe(recent_builder)
    assert result['release'] == 'ci-201-803baf401b5f' and result['exitCode'] == 1
    assert result['controlSha256']['tools'] == sha(raw(recent_builder.tools))
    assert result['containerId'] == recent_builder.row['Id'] and result['preservedVolume'] == recent_builder.volume
    assert result['imagesPreserved'] is result['volumesPreserved'] is result['directoriesPreserved'] is True


@pytest.mark.parametrize('damage', ['commit', 'source', 'tools', 'helper', 'unreviewed-release'])
def test_recent_builder_cannot_borrow_a_commit_source_tools_or_helper_revision(recent_builder, damage):
    if damage == 'commit': recent_builder.context['commit'] = 'f' * 40
    elif damage == 'source': recent_builder.context['sourceSha256'] = 'f' * 64
    elif damage == 'tools': recent_builder.tools['unreviewedField'] = True
    elif damage == 'helper': recent_builder.helpers['compact-build-resources.py'] = 'f' * 64
    else: recent_builder.context['release'] = 'ci-198-7af0903ee840'
    with pytest.raises(ValueError): describe(recent_builder)


@pytest.mark.parametrize('damage', ['live-pid', 'business-bind'])
def test_recent_builder_registration_does_not_bypass_live_process_or_business_mount_guards(recent_builder, damage):
    if damage == 'live-pid': recent_builder.row['State']['Pid'] = 1234
    else: recent_builder.row['Mounts'].append({'Type': 'bind', 'Source': '/srv/business', 'Destination': '/data', 'RW': True})
    with pytest.raises(ValueError): describe(recent_builder)


def test_recent_builder_removal_uses_only_one_exact_container_and_preserves_the_original_state_volume(recent_builder):
    descriptor = describe(recent_builder)
    calls, inspect, remove, listing, references = callbacks(recent_builder)
    result = resources.historical_builder_remove(descriptor, inspect, remove, listing, references)
    assert calls.inspected == [recent_builder.row['Id'], recent_builder.row['Id']]
    assert calls.removed == calls.referenced == [recent_builder.row['Id']] and calls.listed == 1
    assert result['preservedVolume'] == recent_builder.volume and result['volumesPreserved'] is True


@pytest.mark.parametrize('damage', ['commit', 'source', 'tools', 'unregistered-null-commit'])
def test_recent_builder_remove_rechecks_original_source_and_tools_before_any_callback(recent_builder, damage):
    descriptor = describe(recent_builder)
    if damage == 'commit': descriptor['commit'] = 'f' * 40
    elif damage == 'source': descriptor['sourceSha256'] = 'f' * 64
    elif damage == 'tools': descriptor['controlSha256']['tools'] = 'f' * 64
    else: descriptor.update(release='ci-999-' + 'f' * 12, commit=None)
    calls, inspect, remove, listing, references = callbacks(recent_builder)
    with pytest.raises(ValueError):
        resources.historical_builder_remove(descriptor, inspect, remove, listing, references)
    assert calls.inspected == calls.referenced == calls.removed == [] and calls.listed == 0


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


CLOSED_RUNTIME_BUILDERS = {
    'ci-204-24f8eb4b02bf': {
        'commit': '24f8eb4b02bf290c6dd4e186eb78c5f3c80f3b88',
        'sourceSha256': '4b1fed5b2e0f0a80cd0006d7a536eff326f547448c5019ec3ceafa457532bd77',
        'toolsSha256': 'c139a726db51c56f685854b8994289915c2646c487402356e0d0c3833dc2b11d',
        'summarySha256': 'af1150421360df666a8f4209b1071e8638ea8b8ba674ade4a8b1e8e383446d5c',
        'measurementSha256': '0d7641f6b3666f259f4d3c505129f3e78a5e22cf0dc006e528ca678e7352fcaa',
        'containerId': '09646d9dcc4d135e804e40dcfb9718917d2b29c4296ef9fcf8fc9bf975461724',
        'ownerToken': '1b46c38a10f755860acc98ad',
    },
    'ci-207-eb286c623177': {
        'commit': 'eb286c623177b9d1bc23fe88223d81862c00bc71',
        'sourceSha256': '5973ac068fa44a1e7b69a443a820e30d780c35e4c0939e75b3703b9b426cbf2a',
        'toolsSha256': '521676007cc727d3c08f6f76b10afd206f59c5c76cda06e82773140559910732',
        'summarySha256': '9bb5bee53ee5276093d9d92a8341398b86e56f2a32a5ab46e84dc2e5fbdf5eec',
        'measurementSha256': 'a12987a5f47809cd5ce49f45b9fe0b0621f95bdb32bcefbae9a26e06bed870c3',
        'containerId': 'ee23bee6a53f673e013f0e92e0fd838c91514d0e30f845204ba9695dc7bce673',
        'ownerToken': '86466c0e61f9492890688a77',
    },
}


def test_closed_runtime_builder_pins_are_exact_and_do_not_extend_historical_or_recent_permissions():
    assert resources.CLOSED_RUNTIME_BUILDER_CONTROLS == CLOSED_RUNTIME_BUILDERS
    assert resources.CLOSED_RUNTIME_BUILDER_RECIPE_SHA256 == '259d40731626e366b9f974df221bf64ee2db7a2e13e41dc369c1e5bf47826104'
    assert resources.CLOSED_RUNTIME_BUILDER_HELPERS == {
        'compact-build-resources.py': '6a2011e02a274729c346af50e14763b882db596a7e6d75c88848cccf5b6e041e',
        'compact-image-inputs.py': '1db18e3d1aba9b426f6bfb6b34f22af96cb403c6a97ffef914ea35c308ea795e',
    }
    assert len(resources.HISTORICAL_BUILDERS) == 16 and set(resources.RECENT_BUILDER_SOURCES) == {'ci-201-803baf401b5f'}
    assert not set(CLOSED_RUNTIME_BUILDERS).intersection(resources.HISTORICAL_BUILDERS | resources.RECENT_BUILDER_SOURCES)
    assert 'ci-207-eb286c623177' not in resources.RECENT_MYSQL_FIXTURE_SOURCES


@pytest.fixture(params=tuple(CLOSED_RUNTIME_BUILDERS))
def closed_builder(request, monkeypatch):
    tag = request.param; registered = CLOSED_RUNTIME_BUILDERS[tag]
    state = fixture_state((tag, registered['commit'], registered['containerId'], registered['ownerToken']))
    state.context['sourceSha256'] = registered['sourceSha256']
    state.tools.update(state.context); state.summary.update(state.context)
    state.helpers = dict(resources.CLOSED_RUNTIME_BUILDER_HELPERS)
    state.tools['helperSha256'] = state.helpers['compact-build-resources.py']
    state.tools['imageInputsHelperSha256'] = state.helpers['compact-image-inputs.py']
    state.row['Config']['Labels']['io.doorhandle.source'] = registered['sourceSha256']
    state.row['State']['ExitCode'] = state.summary['cleanup']['builderExitCode'] = 1
    # The captured actual builders have only the named persistent state mount;
    # HostConfig still records their original two tmpfs destinations.
    state.row['Mounts'] = state.row['Mounts'][:1]
    state.proof = {'path': 'inbox/' + tag + '/source.tar.gz', 'sha256': registered['sourceSha256'],
        'transportRecipeSha256': resources.CLOSED_RUNTIME_BUILDER_RECIPE_SHA256,
        'builderHelperSha256': dict(state.helpers)}
    refresh_references(state)
    # Unit controls have synthetic engine/layer bytes. Only their three raw
    # control hashes are substituted locally; the literal registry is checked
    # separately, and commit/archive/helper/object/owner pins stay unchanged.
    registry = copy.deepcopy(resources.CLOSED_RUNTIME_BUILDER_CONTROLS)
    for name in ('tools', 'summary', 'measurement'):
        registry[tag][name + 'Sha256'] = sha(raw(getattr(state, name)))
    monkeypatch.setattr(resources, 'CLOSED_RUNTIME_BUILDER_CONTROLS', registry)
    return state


def describe_closed(state, *, closed_runtime=True):
    return resources.historical_builder_descriptor(state.root, state.context, state.identity,
        raw(state.tools), raw(state.summary), raw(state.measurement), state.helpers, state.row,
        closed_runtime=closed_runtime, source_proof=state.proof)


def test_closed_runtime_stopped_builder_requires_the_exact_source_controls_and_retains_state(closed_builder):
    result = describe_closed(closed_builder)
    assert result['containerId'] == closed_builder.row['Id'] and result['ownerToken'] == closed_builder.summary['ownerToken']
    assert result['exitCode'] == 1 and result['preservedVolume'] == closed_builder.volume
    assert result['closedRuntimeSource'] == closed_builder.proof and result['closedRuntimeSource'] is not closed_builder.proof
    assert result['closedRuntimeSource']['builderHelperSha256'] is not closed_builder.proof['builderHelperSha256']
    assert result['imagesPreserved'] is result['volumesPreserved'] is result['directoriesPreserved'] is True


def test_closed_runtime_builder_requires_an_explicit_policy_at_both_admission_and_removal(closed_builder):
    with pytest.raises(ValueError): describe(closed_builder)
    descriptor = describe_closed(closed_builder)
    calls, inspect, remove, listing, references = callbacks(closed_builder)
    with pytest.raises(ValueError): resources.historical_builder_remove(descriptor, inspect, remove, listing, references)
    assert calls.inspected == calls.referenced == calls.removed == [] and calls.listed == 0


def test_closed_runtime_flag_cannot_be_a_truthy_non_boolean(closed_builder):
    descriptor = describe_closed(closed_builder)
    for policy in (1, 'true', None):
        with pytest.raises(ValueError): describe_closed(closed_builder, closed_runtime=policy)
        calls, inspect, remove, listing, references = callbacks(closed_builder)
        with pytest.raises(ValueError):
            resources.historical_builder_remove(descriptor, inspect, remove, listing, references, closed_runtime=policy)
        assert calls.inspected == calls.referenced == calls.removed == [] and calls.listed == 0


def test_closed_runtime_builder_archive_recipe_and_both_helpers_cannot_drift(closed_builder):
    for damage in ('missing', 'path', 'sha256', 'recipe', 'resource-helper', 'inputs-helper', 'extra-helper', 'helpers'):
        state = copy.deepcopy(closed_builder)
        if damage == 'missing': state.proof = None
        elif damage == 'path': state.proof['path'] = 'inbox/ci-206-2236077d98bf/source.tar.gz'
        elif damage == 'sha256': state.proof['sha256'] = 'f' * 64
        elif damage == 'recipe': state.proof['transportRecipeSha256'] = 'f' * 64
        elif damage == 'resource-helper': state.proof['builderHelperSha256']['compact-build-resources.py'] = 'f' * 64
        elif damage == 'inputs-helper': state.proof['builderHelperSha256']['compact-image-inputs.py'] = 'f' * 64
        elif damage == 'extra-helper': state.proof['builderHelperSha256']['other.py'] = 'f' * 64
        else: state.helpers['compact-build-resources.py'] = 'f' * 64
        with pytest.raises(ValueError): describe_closed(state)


def test_closed_runtime_builder_original_context_and_all_three_raw_control_pins_are_required(closed_builder):
    for damage in ('commit', 'source', 'release', 'tools', 'summary', 'measurement'):
        state = copy.deepcopy(closed_builder)
        if damage == 'commit': state.context['commit'] = 'f' * 40
        elif damage == 'source': state.context['sourceSha256'] = 'f' * 64
        elif damage == 'release': state.context['release'] = 'ci-206-2236077d98bf'
        else: getattr(state, damage)['unreviewed-field'] = True
        with pytest.raises(ValueError): describe_closed(state)


def test_closed_runtime_builder_actual_ownership_inactivity_and_mount_guards_remain_enforced(closed_builder):
    for damage in ('cid', 'owner', 'commit-label', 'source-label', 'live-pid', 'running', 'privileged', 'state-volume', 'business-bind'):
        state = copy.deepcopy(closed_builder)
        if damage == 'cid': state.row['Id'] = 'f' * 64
        elif damage == 'owner': state.row['Config']['Labels'][resources.LABEL] = 'f' * 24
        elif damage == 'commit-label': state.row['Config']['Labels']['io.doorhandle.release'] = 'ci-206-2236077d98bf'
        elif damage == 'source-label': state.row['Config']['Labels']['io.doorhandle.source'] = 'f' * 64
        elif damage == 'live-pid': state.row['State']['Pid'] = 1234
        elif damage == 'running': state.row['State'].update(Status='running', Running=True, Pid=1234)
        elif damage == 'privileged': state.row['HostConfig']['Privileged'] = True
        elif damage == 'state-volume': state.row['Mounts'][0]['Name'] = 'business-data'
        else: state.row['Mounts'].append({'Type': 'bind', 'Source': '/srv/business', 'Destination': '/data', 'RW': True})
        with pytest.raises(ValueError): describe_closed(state)


def test_closed_runtime_builder_removal_is_one_ordinary_cid_callback_with_state_volume_preserved(closed_builder):
    descriptor = describe_closed(closed_builder)
    calls, inspect, remove, listing, references = callbacks(closed_builder)
    result = resources.historical_builder_remove(descriptor, inspect, remove, listing, references, closed_runtime=True)
    assert calls.inspected == [closed_builder.row['Id'], closed_builder.row['Id']]
    assert calls.referenced == calls.removed == [closed_builder.row['Id']] and calls.listed == 1
    assert result == {'status': 'REMOVED', 'release': closed_builder.context['release'], 'containerId': closed_builder.row['Id'],
        'preservedVolume': closed_builder.volume, 'imagesPreserved': True, 'volumesPreserved': True, 'directoriesPreserved': True}


def test_closed_runtime_remove_readmits_archive_helpers_controls_owner_and_state_before_callbacks(closed_builder):
    original = describe_closed(closed_builder)
    for damage in ('commit', 'source', 'tools', 'summary', 'measurement', 'recipe', 'helper', 'missing-proof', 'cid', 'owner', 'volume'):
        descriptor = copy.deepcopy(original)
        if damage == 'commit': descriptor['commit'] = 'f' * 40
        elif damage == 'source': descriptor['sourceSha256'] = 'f' * 64
        elif damage in ('tools', 'summary', 'measurement'): descriptor['controlSha256'][damage] = 'f' * 64
        elif damage == 'recipe': descriptor['closedRuntimeSource']['transportRecipeSha256'] = 'f' * 64
        elif damage == 'helper': descriptor['closedRuntimeSource']['builderHelperSha256']['compact-image-inputs.py'] = 'f' * 64
        elif damage == 'missing-proof': descriptor.pop('closedRuntimeSource')
        elif damage == 'cid': descriptor['containerId'] = 'f' * 64
        elif damage == 'owner': descriptor['ownerToken'] = 'f' * 24
        else: descriptor['preservedVolume'] = 'business-data'
        calls, inspect, remove, listing, references = callbacks(closed_builder)
        with pytest.raises(ValueError):
            resources.historical_builder_remove(descriptor, inspect, remove, listing, references, closed_runtime=True)
        assert calls.inspected == calls.referenced == calls.removed == [] and calls.listed == 0


def test_closed_runtime_removal_rechecks_after_reference_audit_and_never_forces_a_started_object(closed_builder):
    descriptor = describe_closed(closed_builder)
    calls, inspect, remove, listing, references = callbacks(closed_builder)
    def started(cid):
        row = inspect(cid)
        if len(calls.inspected) == 2: row['State'].update(Status='running', Running=True, Pid=1234)
        return row
    with pytest.raises(ValueError):
        resources.historical_builder_remove(descriptor, started, remove, listing, references, closed_runtime=True)
    assert calls.referenced == [closed_builder.row['Id']] and calls.removed == [] and calls.listed == 0


def test_closed_runtime_removal_rejects_unknown_references_or_unconfirmed_absence(closed_builder):
    descriptor = describe_closed(closed_builder)
    for stage in ('references', 'absence'):
        calls, inspect, remove, listing, references = callbacks(closed_builder)
        def checked_references(cid):
            references(cid)
            if stage == 'references': raise ValueError('Unadmitted stopped object still references this attempt')
        def uncertain_listing():
            listing(); return [closed_builder.row['Id']]
        with pytest.raises(ValueError):
            resources.historical_builder_remove(descriptor, inspect, remove, uncertain_listing, checked_references, closed_runtime=True)
        assert calls.removed == ([] if stage == 'references' else [closed_builder.row['Id']])


def test_closed_runtime_flag_does_not_admit_any_original_historical_or_201_builder(builder, recent_builder):
    for state in (builder, recent_builder):
        state.proof = {'path': 'inbox/' + state.context['release'] + '/source.tar.gz', 'sha256': state.context['sourceSha256'],
            'transportRecipeSha256': resources.CLOSED_RUNTIME_BUILDER_RECIPE_SHA256,
            'builderHelperSha256': dict(resources.CLOSED_RUNTIME_BUILDER_HELPERS)}
        with pytest.raises(ValueError): describe_closed(state)

@pytest.fixture
def failed_native_builder():
    state=fixture_state(('ci-221-'+'a'*12,'a'*40,'d'*64,'b'*24))
    state.proof={'path':'inbox/'+state.context['release']+'/source.tar.gz',
        'sha256':state.context['sourceSha256'],'failedNativePolicy':'failed-native-retention-v1',
        'mysqlFixtureStartSourceSha256':'79658b1e2982b14614d4c458c58e9b73af59349cf8f4edf874d3f76d83f91795',
        'builderHelperSha256':dict(state.helpers),'preparedToolsSha256':sha(raw(state.tools))}
    return state


def describe_failed_native(state):
    return resources.historical_builder_descriptor(state.root,state.context,state.identity,
        raw(state.tools),raw(state.summary),raw(state.measurement),state.helpers,state.row,
        failed_native=True,source_proof=state.proof)


def test_failed_native_builder_binds_original_controls_and_preserves_the_exact_state_volume(failed_native_builder):
    state=failed_native_builder;before=copy.deepcopy(state.proof)
    descriptor=describe_failed_native(state)
    assert descriptor['release']==state.context['release'] and descriptor['containerId']==state.row['Id']
    assert descriptor['preservedVolume']==state.volume and descriptor['ownerToken']==state.summary['ownerToken']
    expected={name:sha(raw(getattr(state,name))) for name in ('tools','summary','measurement')}
    assert descriptor['controlSha256']==expected==descriptor['failedNativeSource']['builderControlSha256']
    assert descriptor['failedNativeSource']['preparedToolsSha256']==expected['tools']
    assert descriptor['imagesPreserved'] is descriptor['volumesPreserved'] is descriptor['directoriesPreserved'] is True
    assert state.proof==before


def test_failed_native_builder_flag_does_not_expand_the_default_historical_api(failed_native_builder):
    state=failed_native_builder
    with pytest.raises(ValueError):
        resources.historical_builder_descriptor(state.root,state.context,state.identity,
            raw(state.tools),raw(state.summary),raw(state.measurement),state.helpers,state.row,source_proof=state.proof)
    descriptor=describe_failed_native(state);calls,inspect,remove,listing,references=callbacks(state)
    with pytest.raises(ValueError):
        resources.historical_builder_remove(descriptor,inspect,remove,listing,references)
    assert calls.inspected==calls.removed==calls.referenced==[] and calls.listed==0


@pytest.mark.parametrize('damage',['source','commit','tools','summary','measurement','helper','producer'])
def test_failed_native_builder_descriptor_rejects_source_or_prepared_control_drift(failed_native_builder,damage):
    state=failed_native_builder
    if damage=='source':state.context['sourceSha256']='f'*64
    elif damage=='commit':state.context['commit']='f'*40
    elif damage in ('tools','summary','measurement'):getattr(state,damage)['unreviewedMutation']=True
    elif damage=='helper':state.helpers['compact-build-resources.py']='f'*64
    else:state.proof['mysqlFixtureStartSourceSha256']='f'*64
    with pytest.raises(ValueError):describe_failed_native(state)


@pytest.mark.parametrize('damage',['running','live-pid','oom','business-bind'])
def test_failed_native_source_permission_never_bypasses_terminal_or_mount_guards(failed_native_builder,damage):
    state=failed_native_builder
    if damage=='running':state.row['State'].update(Status='running',Running=True,Pid=1234)
    elif damage=='live-pid':state.row['State']['Pid']=1234
    elif damage=='oom':state.row['State']['OOMKilled']=True
    else:state.row['Mounts'].append({'Type':'bind','Source':'/srv/business','Destination':'/private','RW':True})
    with pytest.raises(ValueError):describe_failed_native(state)


def test_failed_native_builder_removal_uses_one_exact_id_and_never_deletes_state_volume(failed_native_builder):
    state=failed_native_builder;descriptor=describe_failed_native(state)
    calls,inspect,remove,listing,references=callbacks(state)
    result=resources.historical_builder_remove(descriptor,inspect,remove,listing,references,failed_native=True)
    assert calls.inspected==[state.row['Id'],state.row['Id']]
    assert calls.removed==calls.referenced==[state.row['Id']] and calls.listed==1
    assert result['preservedVolume']==state.volume
    assert result['imagesPreserved'] is result['volumesPreserved'] is result['directoriesPreserved'] is True


@pytest.mark.parametrize('damage',['tools','summary','measurement','prepared-tools','producer','missing-proof'])
def test_failed_native_builder_remove_rechecks_original_source_and_controls_before_callbacks(failed_native_builder,damage):
    state=failed_native_builder;descriptor=describe_failed_native(state)
    if damage in ('tools','summary','measurement'):descriptor['controlSha256'][damage]='f'*64
    elif damage=='prepared-tools':descriptor['failedNativeSource']['preparedToolsSha256']='f'*64
    elif damage=='producer':descriptor['failedNativeSource']['mysqlFixtureStartSourceSha256']='f'*64
    else:descriptor.pop('failedNativeSource')
    calls,inspect,remove,listing,references=callbacks(state)
    with pytest.raises(ValueError):
        resources.historical_builder_remove(descriptor,inspect,remove,listing,references,failed_native=True)
    assert calls.inspected==calls.referenced==calls.removed==[] and calls.listed==0


@pytest.mark.parametrize('stage',['references','second-inspect'])
def test_failed_native_builder_late_occupant_or_start_prevents_any_remove(failed_native_builder,stage):
    state=failed_native_builder;descriptor=describe_failed_native(state)
    calls,inspect,remove,listing,references=callbacks(state)
    def current(cid):
        row=inspect(cid)
        if stage=='second-inspect' and len(calls.inspected)==2:row['State'].update(Status='running',Running=True,Pid=1234)
        return row
    def unoccupied(cid):
        references(cid)
        if stage=='references':raise ValueError('an unadmitted container still occupies the old attempt')
    with pytest.raises(ValueError):
        resources.historical_builder_remove(descriptor,current,remove,listing,unoccupied,failed_native=True)
    assert calls.removed==[] and calls.listed==0
