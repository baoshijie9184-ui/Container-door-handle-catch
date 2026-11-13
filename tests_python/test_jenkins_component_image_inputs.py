"""Public component input regressions, executed only by the ECS source verifier.

Synthetic OCI bytes exercise the real provenance/DiffID code. No test here
downloads images, executes a container, or represents upstream image evidence.
"""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tests_python.test_jenkins_buildkit_build_input import fixture_image, bundle
from tests_python.test_compact_build_resources import archive_actor

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


FETCH = load('component_fetch_test', 'script/jenkins/fetch-buildkit-build-input.py')
TRANSFER = load('component_transfer_test', 'script/jenkins/transfer-candidate-build-tools.py')
RES = load('component_resources_test', 'script/docker/compact-build-resources.py')
OCI = load('component_oci_test', 'script/docker/compact-image-inputs.py')
CONTEXT = {'release': 'ci-123-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
           'identity': {'executionLocation': 'ECS', 'instanceId': 'i-fixture', 'machineId': 'c' * 32}}


def repeated_image():
    fixed, value, _raw, blobs, _entries = fixture_image()
    original_config = json.loads(blobs[fixed['IMAGE_ID'][7:]])
    original_config['rootfs']['diff_ids'] *= 2
    config = FETCH.encoded(original_config); config_id = 'sha256:' + FETCH.checksum(config)
    value['config'].update(digest=config_id, size=len(config)); value['layers'] *= 2
    raw = FETCH.encoded(value); manifest_id = 'sha256:' + FETCH.checksum(raw)
    fixed.update(component='qdrant', IMAGE_ID=config_id, manifestDigest=manifest_id,
        REFERENCE='docker.io/qdrant/qdrant@' + manifest_id, repository='qdrant/qdrant',
        compressedLayerBytes=sum(row['size'] for row in value['layers']))
    layer_id = value['layers'][0]['digest'][7:]
    blobs = {manifest_id[7:]: raw, config_id[7:]: config, layer_id: blobs[layer_id]}
    entries = {'oci-layout': FETCH.encoded({'imageLayoutVersion': '1.0.0'}),
        'index.json': FETCH.encoded({'schemaVersion': 2, 'manifests': [
            {'mediaType': FETCH.MEDIA, 'digest': manifest_id, 'size': len(raw)}]}),
        **{'blobs/sha256/' + digest: content for digest, content in blobs.items()}}
    return fixed, value, raw, blobs, entries, original_config['rootfs']['diff_ids']


def shared_archive(tmp_path, raw, component='qdrant'):
    checksum = hashlib.sha256(raw).hexdigest()
    folder = tmp_path / 'build-inputs' / component; folder.mkdir(parents=True, mode=0o700)
    folder.parent.chmod(0o700); folder.chmod(0o700)
    path = folder / (checksum + '.tar'); path.write_bytes(raw); path.chmod(0o600)
    return {'file': str(path), 'sha256': checksum, 'bytes': len(raw)}


@pytest.mark.parametrize('component', ['qdrant', 'prometheus', 'alertmanager'])
def test_current_literal_component_pins_match_resource_owner_without_executing_source(component):
    fixed = FETCH.pins(ROOT / 'script/docker/compact-build-resources.py', component)
    pin = RES.component_pin(component)
    assert fixed['REFERENCE'] == pin['reference'] and fixed['IMAGE_ID'] == pin['config']
    assert fixed['compressedLayerBytes'] == pin['compressedBytes']
    assert TRANSFER.binding('/owned', 'a' * 64, 10240, component)['file'] == '/owned/build-inputs/' + component + '/' + 'a' * 64 + '.tar'


def test_repeated_oci_layer_keeps_two_ordered_diffids_but_one_downloaded_blob(tmp_path, monkeypatch):
    fixed, _value, raw, blobs, _entries, diffs = repeated_image(); calls = []
    class Registry:
        def __init__(self, _fixed): pass
        def get(self, suffix):
            calls.append(suffix)
            return io.BytesIO(raw if suffix.startswith('manifests/') else blobs[suffix.split('sha256:')[1]])
    monkeypatch.setattr(FETCH, 'Registry', Registry)
    result = FETCH.fetch(tmp_path / 'cache', fixed)
    archive = Path(result['file']); before = archive.read_bytes()
    measured = OCI.inspect_docker_archive(archive, fixed['IMAGE_ID'], diffs, OCI.MIB)
    assert [row['diffId'] for row in measured['layers']] == diffs and measured['layerCount'] == 2
    assert len(calls) == 3  # Manifest, config, one unique layer.
    monkeypatch.setattr(FETCH, 'Registry', lambda *_: pytest.fail('Verified cache must not use the registry'))
    assert FETCH.fetch(tmp_path / 'cache', fixed)['sha256'] == result['sha256']
    assert archive.read_bytes() == before


def test_buildkit_keeps_its_original_duplicate_descriptor_denial():
    fixed, _value, raw, _blobs, _entries, _diffs = repeated_image(); fixed.pop('component')
    with pytest.raises(ValueError, match='BUILD_INPUT_CATALOGUE_EXCEEDS_BOUND'): FETCH.manifest(raw, fixed)


def test_duplicate_digest_cannot_claim_two_sizes_or_media_types():
    fixed, value, _raw, _blobs, _entries, _diffs = repeated_image()
    value['layers'] = copy.deepcopy(value['layers']); value['layers'][1]['size'] += 1
    raw = FETCH.encoded(value); fixed['manifestDigest'] = 'sha256:' + FETCH.checksum(raw)
    with pytest.raises(ValueError, match='BUILD_INPUT_CATALOGUE_EXCEEDS_BOUND'): FETCH.manifest(raw, fixed)


def test_stream_measurement_checks_every_repeated_position_and_rejects_legacy_repetition(tmp_path):
    fixed, _value, _raw, _blobs, entries, diffs = repeated_image()
    path = bundle(tmp_path / 'repeat.tar', entries)
    descriptor = json.loads(entries['index.json'])['manifests'][0]
    checked = OCI.inspect_docker_stream(io.BytesIO(path.read_bytes()), fixed['IMAGE_ID'], diffs, OCI.MIB,
        lambda: None, expected_engine_descriptor=descriptor)
    assert [row['diffId'] for row in checked['layers']] == diffs
    with pytest.raises(ValueError):
        OCI.inspect_docker_stream(io.BytesIO(path.read_bytes()), fixed['IMAGE_ID'], [diffs[0], 'sha256:' + 'f' * 64], OCI.MIB, lambda: None)
    members = {name: value for name, value in entries.items() if name.startswith('blobs/')}
    members.pop('blobs/sha256/' + fixed['manifestDigest'][7:])
    layer_name = next(name for name in members if name != 'blobs/sha256/' + fixed['IMAGE_ID'][7:])
    members['manifest.json'] = OCI.encoded([{'Config': 'blobs/sha256/' + fixed['IMAGE_ID'][7:], 'Layers': [layer_name, layer_name]}])
    legacy = bundle(tmp_path / 'legacy.tar', members)
    with pytest.raises(ValueError): OCI.inspect_docker_archive(legacy, fixed['IMAGE_ID'], diffs, OCI.MIB)


def test_component_archive_measures_original_shared_bytes_without_per_build_blob_copies(tmp_path, monkeypatch):
    fixed, _value, _raw, _blobs, entries, diffs = repeated_image()
    raw = bundle(tmp_path / 'input.tar', entries).read_bytes(); binding = shared_archive(tmp_path, raw)
    actor = archive_actor(tmp_path / 'output')
    monkeypatch.setattr(RES, 'component_pin', lambda component: {'reference': fixed['REFERENCE'], 'config': fixed['IMAGE_ID'],
        'compressedBytes': fixed['compressedLayerBytes']})
    result = RES.archive_layout(actor, tmp_path, binding, None, OCI, component='qdrant')
    assert result['configDigest'] == fixed['IMAGE_ID'] and [row['diffId'] for row in result['layers']] == diffs
    assert result['loadDescriptor'] == json.loads(entries['index.json'])['manifests'][0]
    assert Path(binding['file']).read_bytes() == raw and not list(actor.directory.glob('*-oci'))
    assert not list(actor.directory.glob('*.tar'))
    assert (actor.directory / 'qdrant-source-manifest.raw.json').read_bytes() == entries['blobs/sha256/' + fixed['manifestDigest'][7:]]
    assert {'official-archive-validation', 'measure-shared-qdrant'} == {row[0] for row in actor.phases}


@pytest.mark.parametrize('component', ['qdrant', 'prometheus', 'alertmanager'])
def test_shared_custody_reuses_bytes_and_binds_each_release_pointer(tmp_path, monkeypatch, component):
    (tmp_path / 'inbox').mkdir(mode=0o700); inbox = tmp_path / 'inbox' / CONTEXT['release']; inbox.mkdir(mode=0o700)
    raw = b'synthetic public input'; binding = TRANSFER.binding(tmp_path, hashlib.sha256(raw).hexdigest(), len(raw), component)
    monkeypatch.setattr(TRANSFER.os, 'statvfs', lambda _: SimpleNamespace(f_bavail=8 * RES.GIB, f_frsize=1))
    attempt = 'd' * 32
    admitted = TRANSFER.probe(tmp_path, inbox, CONTEXT, binding, attempt, component)
    Path(admitted['stagingFile']).write_bytes(raw)
    result = TRANSFER.publish(tmp_path, inbox, CONTEXT, binding, attempt, component)
    assert result['componentArchive'] == binding and Path(binding['file']).read_bytes() == raw
    pointer = inbox / (component + '-image-input.json'); original = pointer.read_bytes()
    assert TRANSFER.probe(tmp_path, inbox, CONTEXT, binding, 'e' * 32, component)['status'] == 'REUSED'
    assert not TRANSFER.stage_path(inbox, 'e' * 32, component).exists() and pointer.read_bytes() == original
    checkout = tmp_path / 'verification' / CONTEXT['release'] / 'checkout'; checkout.mkdir(parents=True, mode=0o700)
    assert RES.component_input(checkout, CONTEXT, component) == binding
    with pytest.raises(ValueError): RES.component_input(checkout, {**CONTEXT, 'commit': 'f' * 40}, component)
    assert Path(binding['file']).read_bytes() == raw


def test_component_pointer_cannot_switch_cache_or_source_owner(tmp_path):
    inbox = tmp_path / 'inbox' / CONTEXT['release']; inbox.mkdir(parents=True, mode=0o700)
    checkout = tmp_path / 'verification' / CONTEXT['release'] / 'checkout'; checkout.mkdir(parents=True, mode=0o700)
    binding = TRANSFER.binding(tmp_path, 'd' * 64, 10240, 'qdrant')
    TRANSFER.component_reference(inbox, CONTEXT, binding, 'qdrant')
    with pytest.raises(ValueError, match='POINTER_DIFFERS'):
        TRANSFER.component_reference(inbox, {**CONTEXT, 'commit': 'f' * 40}, binding, 'qdrant')
    pointer = inbox / 'qdrant-image-input.json'; value = json.loads(pointer.read_text())
    value['componentArchive']['file'] = str(tmp_path / 'unowned.tar'); pointer.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='outside its immutable public cache'): RES.component_input(checkout, CONTEXT, 'qdrant')


@pytest.mark.parametrize('native,reused,failure', [(native, reused, failure)
    for native in (False, True) for reused, failure in ((False, False), (True, False), (False, True))])
def test_component_import_uses_shared_original_and_preserves_unknown_load_state(tmp_path, monkeypatch, native, reused, failure):
    fixed, _value, _raw, _blobs, entries, diffs = repeated_image()
    raw = bundle(tmp_path / 'input.tar', entries).read_bytes(); archive = shared_archive(tmp_path, raw)
    descriptor = json.loads(entries['index.json'])['manifests'][0]
    image_id = descriptor['digest'] if native else fixed['IMAGE_ID']
    row = {'Id': image_id, 'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Type': 'layers', 'Layers': diffs},
           'Config': {'Env': [], 'User': '1000:1000'}, 'Size': 1}
    if native: row['Descriptor'] = descriptor
    actor = archive_actor(tmp_path / 'output'); actor.daemon_import_unknown = False
    def docker(*arguments):
        if arguments[0] == 'info': return json.dumps([['driver-type', 'io.containerd.snapshotter.v1']] if native else []).encode()
        assert arguments[:2] == ('image', 'inspect'); return json.dumps([row]).encode()
    actor.docker = docker
    original_run = actor.run
    def run(arguments, name, **kwargs):
        if failure: raise OSError('Synthetic interrupted daemon import')
        return original_run(arguments, name, **kwargs)
    actor.run = run
    monkeypatch.setattr(RES, 'component_pin', lambda _: {'reference': fixed['REFERENCE'], 'config': fixed['IMAGE_ID'],
        'compressedBytes': fixed['compressedLayerBytes'], 'source': 'https://example.invalid/fixture', 'version': 'fixture'})
    monkeypatch.setattr(RES, 'Supervisor', lambda *_: actor)
    monkeypatch.setattr(RES, 'load_module', lambda *_: OCI)
    monkeypatch.setattr(RES, 'host_diff_ids', lambda _: set())
    monkeypatch.setattr(RES, 'registry_layout', lambda *_: pytest.fail('Explicit relay inputs must never use the registry'))
    with mock.patch.object(RES.subprocess, 'run', return_value=SimpleNamespace(returncode=0 if reused else 1)):
        if failure:
            with pytest.raises(OSError): RES.prepare_qdrant_image(actor.directory, CONTEXT, ROOT / 'script/docker', archive=archive)
            assert actor.daemon_import_unknown is True and actor.finishes == ['FAILED']
        else:
            result = RES.prepare_qdrant_image(actor.directory, CONTEXT, ROOT / 'script/docker', archive=archive)
            assert result['engineIdentity']['engineImageId'] == image_id
            assert result['componentArchive'] == archive and result['imageInputMode'] == 'LOCAL_JENKINS_RELAY'
            assert actor.daemon_import_unknown is False
            if reused: assert actor.calls == []
            else: assert actor.calls == [('qdrant-image-load', ['docker', 'load', '--input', archive['file']])]
            assert json.loads((actor.directory / 'public-input-cleanup.json').read_text())['status'] == 'SHARED_INPUT_PRESERVED'
    assert Path(archive['file']).read_bytes() == raw
    assert not list(actor.directory.glob('*.tar')) and not list(actor.directory.glob('*-oci'))


def test_component_upload_reserve_measures_already_present_archives_and_never_treats_them_as_free(tmp_path, monkeypatch):
    inbox = tmp_path / 'inbox' / CONTEXT['release']; inbox.mkdir(parents=True, mode=0o700)
    binding = TRANSFER.binding(tmp_path, 'd' * 64, 10240, 'prometheus')
    required = TRANSFER.FLOOR + binding['bytes'] + 64 * 1024
    monkeypatch.setattr(TRANSFER.os, 'statvfs', lambda _: SimpleNamespace(f_bavail=required - 1, f_frsize=1))
    with pytest.raises(ValueError, match='UPLOAD_DISK_RESERVE'):
        TRANSFER.probe(tmp_path, inbox, CONTEXT, binding, 'e' * 32, 'prometheus')
    assert not TRANSFER.stage_path(inbox, 'e' * 32, 'prometheus').exists()


def test_controller_prepares_all_components_after_fixed_source_upload_in_existing_stage():
    source = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    start = source.index("if ($Action -in @('PrepareTools', 'CleanupTools'))")
    prepare = source[start:source.index("if ($Action -eq 'VerifyEcs')", start)]
    assert prepare.index("@('artifacts/source.tar.gz','source.tar.gz')") < prepare.index("foreach($component in @('qdrant','prometheus','alertmanager'))")
    assert 'Send-CandidateBuildToolsArchive -Component $component' in prepare
    assert 'componentArchive' in source and 'rawArchiveArchived=$false' in source
    for file in ('middleware-fixture.py', 'observability-fixture.py'):
        text = (ROOT / 'script/jenkins' / file).read_text()
        assert 'archive=resources.component_input(' in text
