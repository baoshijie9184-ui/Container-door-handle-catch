"""Byte-only Docker identity regressions, run by Jenkins on ECS only."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('compact_image_identity_under_test', ROOT / 'script/docker/compact-image-inputs.py')
OCI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OCI)
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
INDEX = 'application/vnd.oci.image.index.v1+json'
CONFIG = 'application/vnd.oci.image.config.v1+json'
LAYER = 'application/vnd.oci.image.layer.v1.tar+gzip'


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def tar_bytes(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, raw in members.items():
            row = tarfile.TarInfo(name); row.size = len(raw)
            archive.addfile(row, io.BytesIO(raw))
    return output.getvalue()


def image_fixture(kind='native', damage=None):
    expanded = tar_bytes({'app/data.txt': b'bounded synthetic build dependency\n'})
    layer = gzip.compress(expanded, mtime=0); diff = digest(expanded)
    config = OCI.encoded({'os': 'linux', 'architecture': 'amd64', 'rootfs': {'type': 'layers', 'diff_ids': [diff]}})
    image = digest(config); layer_id = digest(layer)
    config_name = 'blobs/sha256/' + image[7:]; layer_name = 'blobs/sha256/' + layer_id[7:]
    if kind == 'classic':
        return tar_bytes({'manifest.json': OCI.encoded([{'Config': image[7:] + '.json', 'Layers': ['saved/layer.tar']}]),
                          image[7:] + '.json': config, 'saved/layer.tar': layer,
                          'saved/VERSION': b'1.0\n', 'saved/json': b'{}', 'repositories': b'{}'}), image, diff, None
    manifest = {'schemaVersion': 2, 'mediaType': MANIFEST,
                'annotations': {'org.opencontainers.image.title': 'original source bytes differ from normalization'},
                'config': {'mediaType': CONFIG, 'digest': image, 'size': len(config)},
                'layers': [{'mediaType': LAYER, 'digest': layer_id, 'size': len(layer)}]}
    if damage == 'layer-size': manifest['layers'][0]['size'] += 1
    if damage == 'layer-media': manifest['layers'][0]['mediaType'] = 'application/vnd.oci.image.layer.v1.tar'
    if damage == 'config-size': manifest['config']['size'] += 1
    if damage == 'config-media': manifest['config']['mediaType'] = MANIFEST
    if damage == 'extra-leaf': manifest['subject'] = copy.deepcopy(manifest['config'])
    raw = OCI.encoded(manifest); root = {'mediaType': MANIFEST, 'digest': digest(raw), 'size': len(raw)}
    members = {config_name: config, layer_name: layer, 'blobs/sha256/' + root['digest'][7:]: raw}
    if kind == 'nested':
        child = {**root, 'annotations': {'fixture': 'child'}, 'platform': {'os': 'linux', 'architecture': 'amd64'}}
        nested = OCI.encoded({'schemaVersion': 2, 'mediaType': INDEX, 'manifests': [child]})
        root = {'mediaType': INDEX, 'digest': digest(nested), 'size': len(nested)}
        members['blobs/sha256/' + root['digest'][7:]] = nested
    decorated = {**root, 'annotations': {'io.containerd.image.name': 'fixture:unused'},
                 'platform': {'os': 'linux', 'architecture': 'amd64', 'variant': '', 'os.version': '', 'os.features': []}}
    if damage == 'descriptor-bool': decorated['size'] = True
    if damage == 'descriptor-extra': decorated['urls'] = ['https://invalid.example/no-fetch']
    if damage == 'annotations-type': decorated['annotations'] = {'fixture': 7}
    if damage == 'platform-type': decorated['platform']['os.features'] = 'not-a-list'
    if damage == 'platform-extra': decorated['platform']['features'] = []
    if damage == 'platform-arch': decorated['platform']['architecture'] = 'arm64'
    index = {'schemaVersion': 2, 'manifests': [decorated]}
    if damage == 'branch': index['manifests'].append(copy.deepcopy(decorated))
    if damage == 'schema-bool': index['schemaVersion'] = True
    members.update({'oci-layout': OCI.encoded({'imageLayoutVersion': '1.0.0'}), 'index.json': OCI.encoded(index)})
    if kind == 'dual': members['manifest.json'] = OCI.encoded([{'Config': config_name, 'Layers': [layer_name]}])
    if damage == 'extra-blob': members['blobs/sha256/' + 'f' * 64] = b'unreferenced'
    if damage == 'missing-layer': del members[layer_name]
    if damage == 'config-bytes': members[config_name] = config.replace(b'linux', b'LINUX')
    if damage == 'layer-bytes': members[layer_name] = layer[:-1] + bytes([layer[-1] ^ 1])
    if damage == 'manifest-bytes': members['blobs/sha256/' + root['digest'][7:]] += b' '
    if damage == 'duplicate-key': members['index.json'] = members['index.json'].replace(b'"schemaVersion":2', b'"schemaVersion":2,"schemaVersion":2')
    return tar_bytes(members), image, diff, root


def attested_image_fixture(dual=True, damage=None):
    """Docker 29 export observed on the pinned production worker dependency."""
    raw, image, diff, runtime = image_fixture('native')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as package:
        members = {entry.name: package.extractfile(entry).read() for entry in package}
    empty = b'{}' if damage != 'nonempty-config' else b'{"command":"never run"}'
    config = {'mediaType': 'application/vnd.oci.empty.v1+json', 'digest': digest(empty), 'size': len(empty), 'data': 'e30='}
    if damage == 'empty-config-data': config['data'] = 'e30K'
    predicate = 'https://slsa.dev/provenance/v1'
    payload = OCI.encoded({'_type': 'foreign' if damage == 'statement-type' else 'https://in-toto.io/Statement/v1',
        'predicateType': 'foreign' if damage == 'payload-type' else predicate,
        'subject': [{'name': 'fixture', 'digest': {'sha256': 'f' * 64 if damage == 'payload-subject' else runtime['digest'][7:]}}], 'predicate': {}})
    layer = {'mediaType': 'application/vnd.in-toto+json', 'digest': digest(payload), 'size': len(payload),
             'annotations': {'in-toto.io/predicate-type': predicate}}
    if damage == 'payload-media': layer['mediaType'] = LAYER
    manifest = {'schemaVersion': 2, 'mediaType': MANIFEST,
        'artifactType': 'application/vnd.docker.attestation.manifest.v1+json', 'config': config,
        'subject': copy.deepcopy(runtime), 'layers': [layer]}
    if damage == 'foreign-subject': manifest['subject']['digest'] = 'sha256:' + 'f' * 64
    if damage == 'bad-artifact': manifest['artifactType'] = MANIFEST
    if damage == 'layer-count': manifest['layers'].append(copy.deepcopy(layer))
    if damage == 'extra-manifest-field': manifest['urls'] = ['https://invalid.example/no-fetch']
    manifest_raw = OCI.encoded(manifest)
    attachment = {'mediaType': MANIFEST, 'digest': digest(manifest_raw), 'size': len(manifest_raw),
        'platform': {'os': 'unknown', 'architecture': 'unknown'},
        'annotations': {'vnd.docker.reference.type': 'attestation-manifest', 'vnd.docker.reference.digest': runtime['digest']}}
    if damage == 'second-runtime': attachment['platform'] = {'os': 'linux', 'architecture': 'amd64'}
    if damage == 'foreign-platform': attachment['platform'] = {'os': 'linux', 'architecture': 'arm64'}
    if damage == 'foreign-reference': attachment['annotations']['vnd.docker.reference.digest'] = 'sha256:' + 'f' * 64
    if damage == 'reference-type': attachment['annotations']['vnd.docker.reference.type'] = 'image'
    runtime_entry = {**runtime, 'platform': {'os': 'linux', 'architecture': 'amd64'}}
    nested = OCI.encoded({'schemaVersion': 2, 'mediaType': INDEX, 'manifests': [runtime_entry, attachment]})
    root = {'mediaType': INDEX, 'digest': digest(nested), 'size': len(nested)}
    members.update({'blobs/sha256/' + config['digest'][7:]: empty,
        'blobs/sha256/' + layer['digest'][7:]: payload,
        'blobs/sha256/' + attachment['digest'][7:]: manifest_raw,
        'blobs/sha256/' + root['digest'][7:]: nested,
        'index.json': OCI.encoded({'schemaVersion': 2, 'mediaType': INDEX, 'manifests': [root]})})
    if dual:
        runtime_manifest = json.loads(members['blobs/sha256/' + runtime['digest'][7:]])
        members['manifest.json'] = OCI.encoded([{'Config': 'blobs/sha256/' + image[7:],
            'Layers': ['blobs/sha256/' + row['digest'][7:] for row in runtime_manifest['layers']]}])
    if damage == 'config-bytes': members['blobs/sha256/' + config['digest'][7:]] = b'[]'
    if damage == 'payload-bytes': members['blobs/sha256/' + layer['digest'][7:]] = payload.replace(b'fixture', b'changed')
    if damage == 'attachment-bytes': members['blobs/sha256/' + attachment['digest'][7:]] += b' '
    if damage == 'missing-attachment': del members['blobs/sha256/' + attachment['digest'][7:]]
    if damage == 'extra-blob': members['blobs/sha256/' + 'f' * 64] = b'{}'
    return tar_bytes(members), image, diff, root


def inspect(tmp_path, raw, image=None, diff=None):
    archive = tmp_path / 'image.tar'; archive.write_bytes(raw)
    return OCI.inspect_docker_archive(archive, image, None if diff is None else [diff], OCI.MIB)


def stream(tmp_path, raw, image, diff, descriptor=None):
    return OCI.export_stream_to_oci(io.BytesIO(raw), tmp_path / 'output', image, [diff], OCI.MIB,
                                    lambda *_: None, lambda: None, expected_engine_descriptor=descriptor)


def test_classic_config_protocol_is_preserved_without_an_oci_load_descriptor(tmp_path):
    raw, image, diff, _ = image_fixture('classic')
    checked = inspect(tmp_path, raw, image, diff); exported = stream(tmp_path, raw, image, diff)
    measured = OCI.inspect_docker_stream(io.BytesIO(raw), image, [diff], OCI.MIB, lambda: None)
    for result in (checked, exported, measured):
        assert result['imageId'] == result['configDigest'] == image
        assert result['loadDescriptor'] is None
        assert result['layers'][0]['diffId'] == diff
    assert exported['manifestDigest'] == checked['manifestDigest']


@pytest.mark.parametrize('kind', ['native', 'dual', 'nested'])
@pytest.mark.parametrize('engine_mode', [False, True])
def test_config_and_original_load_identity_remain_distinct_through_stream_normalization(tmp_path, kind, engine_mode):
    raw, image, diff, original = image_fixture(kind)
    checked = inspect(tmp_path, raw)  # Existing inspection default derives config identity.
    result = stream(tmp_path, raw, None if engine_mode else image, diff, original if engine_mode else None)
    measured = OCI.inspect_docker_stream(io.BytesIO(raw), None if engine_mode else image, [diff], OCI.MIB,
                                         lambda: None, expected_engine_descriptor=original if engine_mode else None)
    assert original['digest'] != image
    for observed in (checked, result, measured):
        assert observed['imageId'] == observed['configDigest'] == image
        assert observed['loadDescriptor'] == original
        assert set(observed['loadDescriptor']) == {'mediaType', 'digest', 'size'}
        assert observed['manifestDigest'] != original['digest']
    assert result['manifestDigest'] == checked['manifestDigest']
    normalized = json.loads((tmp_path / 'output/index.json').read_bytes())['manifests'][0]
    assert normalized['digest'] == result['manifestDigest']
    assert result['dockerSaveStreamSha256'] == hashlib.sha256(raw).hexdigest()
    assert measured == result


@pytest.mark.parametrize('damage', ['layer-size', 'layer-media', 'config-size', 'config-media', 'extra-leaf',
    'descriptor-bool', 'descriptor-extra', 'annotations-type', 'platform-type', 'platform-extra', 'platform-arch',
    'branch', 'schema-bool', 'extra-blob', 'missing-layer', 'config-bytes', 'layer-bytes', 'manifest-bytes', 'duplicate-key'])
def test_complete_source_graph_cannot_be_replaced_by_a_matching_config_or_partial_descriptor(tmp_path, damage):
    raw, image, diff, original = image_fixture('dual', damage)
    with pytest.raises((ValueError, gzip.BadGzipFile, EOFError, OSError)):
        inspect(tmp_path, raw, image, diff)
    with pytest.raises((ValueError, gzip.BadGzipFile, EOFError, OSError)):
        stream(tmp_path, raw, None, diff, original)
    with pytest.raises((ValueError, gzip.BadGzipFile, EOFError, OSError, tarfile.ReadError)):
        OCI.inspect_docker_stream(io.BytesIO(raw), None, [diff], OCI.MIB, lambda: None, expected_engine_descriptor=original)


@pytest.mark.parametrize('damage', ['missing', 'bool-size', 'extra', 'digest', 'size', 'media', 'config-id'])
def test_engine_only_mode_requires_the_typed_exact_original_descriptor(tmp_path, damage):
    raw, image, diff, original = image_fixture('nested'); expected = copy.deepcopy(original)
    if damage == 'missing': expected = None
    if damage == 'bool-size': expected['size'] = True
    if damage == 'extra': expected['annotations'] = {}
    if damage == 'digest': expected['digest'] = 'sha256:' + 'f' * 64
    if damage == 'size': expected['size'] += 1
    if damage == 'media': expected['mediaType'] = MANIFEST
    if damage == 'config-id': expected['digest'] = image
    with pytest.raises(ValueError): stream(tmp_path, raw, None, diff, expected)
    with pytest.raises(ValueError):
        OCI.inspect_docker_stream(io.BytesIO(raw), None, [diff], OCI.MIB, lambda: None, expected_engine_descriptor=expected)


def test_pinned_config_and_diffids_are_still_required_in_the_original_protocol(tmp_path):
    raw, image, diff, descriptor = image_fixture()
    with pytest.raises(ValueError): stream(tmp_path, raw, descriptor['digest'], diff)
    with pytest.raises(ValueError):
        OCI.export_stream_to_oci(io.BytesIO(raw), tmp_path / 'bad-diff', image, ['sha256:' + 'f' * 64], OCI.MIB,
                                 lambda *_: None, lambda: None)
    classic, _image, _diff, _ = image_fixture('classic')
    with pytest.raises(ValueError): stream(tmp_path / 'classic', classic, None, diff, descriptor)


@pytest.mark.parametrize('dual', [False, True])
@pytest.mark.parametrize('engine_mode', [False, True])
def test_bound_docker_attestation_preserves_original_index_and_only_normalizes_runtime_layers(tmp_path, dual, engine_mode):
    raw, image, diff, original = attested_image_fixture(dual)
    checked = inspect(tmp_path, raw, image, diff)
    exported = stream(tmp_path, raw, None if engine_mode else image, diff, original if engine_mode else None)
    measured = OCI.inspect_docker_stream(io.BytesIO(raw), None if engine_mode else image, [diff], OCI.MIB,
        lambda: None, expected_engine_descriptor=original if engine_mode else None)
    assert measured == exported
    for result in (checked, exported, measured):
        assert result['loadDescriptor'] == original and result['configDigest'] == image
        assert result['manifestDigest'] not in (original['digest'], image)
        assert result['layerCount'] == 1 and result['layers'][0]['diffId'] == diff
    # The provenance bytes belong to the original graph, never an executable layer.
    assert {p.name for p in (tmp_path / 'output/blobs/sha256').iterdir()} == {
        image[7:], exported['manifestDigest'][7:], exported['layers'][0]['blobDigest'][7:]}


@pytest.mark.parametrize('damage', ['second-runtime', 'foreign-platform', 'foreign-reference', 'reference-type',
    'foreign-subject', 'bad-artifact', 'empty-config-data', 'nonempty-config', 'config-bytes', 'payload-media',
    'payload-type', 'payload-subject', 'statement-type', 'payload-bytes', 'attachment-bytes', 'missing-attachment',
    'extra-blob', 'layer-count', 'extra-manifest-field'])
def test_attestation_cannot_hide_another_platform_foreign_subject_or_unverified_bytes(tmp_path, damage):
    raw, image, diff, original = attested_image_fixture(damage=damage)
    with pytest.raises(ValueError): inspect(tmp_path, raw, image, diff)
    with pytest.raises(ValueError): stream(tmp_path, raw, None, diff, original)
    with pytest.raises(ValueError):
        OCI.inspect_docker_stream(io.BytesIO(raw), None, [diff], OCI.MIB, lambda: None, expected_engine_descriptor=original)


def test_metadata_measurement_has_no_filesystem_writes_and_streams_large_raw_layers_in_bounded_reads():
    layer = tar_bytes({'app/large.bin': b'x' * (5 * OCI.MIB)})
    diff = digest(layer)
    config = OCI.encoded({'os': 'linux', 'architecture': 'amd64', 'rootfs': {'type': 'layers', 'diff_ids': [diff]}})
    image = digest(config)
    raw = tar_bytes({'manifest.json': OCI.encoded([{'Config': image[7:] + '.json', 'Layers': ['saved/layer.tar']}]),
                     image[7:] + '.json': config, 'saved/layer.tar': layer})
    class BoundedSource(io.BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= OCI.MIB
            return super().read(size)
    with mock.patch.object(OCI, 'Path', side_effect=AssertionError('Measurement must not create files')), \
            mock.patch.object(OCI.os, 'open', side_effect=AssertionError('Measurement must not open output files')):
        result = OCI.inspect_docker_stream(BoundedSource(raw), image, [diff], 8 * OCI.MIB, lambda: None)
    assert result['layers'][0]['bytes'] == result['layers'][0]['uncompressedBytes'] == len(layer)
    assert result['layers'][0]['allocationUpperBoundBytes'] > 5 * OCI.MIB
    assert result['dockerSaveStreamBytes'] == len(raw)


def test_complete_measurement_rejects_truncation_duplicate_members_and_expansion_before_returning_proof():
    raw, image, diff, _ = image_fixture('classic')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as package:
        members = [(entry.name, package.extractfile(entry).read()) for entry in package]
        end = package.offset
    duplicate = io.BytesIO()
    with tarfile.open(fileobj=duplicate, mode='w') as package:
        for name, value in [*members, members[0]]:
            entry = tarfile.TarInfo(name); entry.size = len(value); package.addfile(entry, io.BytesIO(value))
    for changed, bound in ((raw[:end], OCI.MIB), (raw[:end - 1], OCI.MIB), (duplicate.getvalue(), OCI.MIB),
                           (raw + b'nonzero-tail', OCI.MIB), (raw, 100)):
        with pytest.raises((ValueError, EOFError, OSError, tarfile.ReadError)):
            OCI.inspect_docker_stream(io.BytesIO(changed), image, [diff], bound, lambda: None)
    with pytest.raises(ValueError):
        OCI.inspect_docker_stream(io.BytesIO(raw), 'sha256:' + 'f' * 64, [diff], OCI.MIB, lambda: None)
    with pytest.raises(ValueError):
        OCI.inspect_docker_stream(io.BytesIO(raw), image, ['sha256:' + 'f' * 64], OCI.MIB, lambda: None)
    for kind in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
                 tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
        header = tarfile.TarInfo('oversized-metadata'); header.type = kind; header.size = 5 * OCI.MIB
        with mock.patch.object(tarfile.TarInfo, '_proc_pax', side_effect=AssertionError('PAX must not allocate')):
            with pytest.raises(ValueError, match='extended metadata'):
                OCI.inspect_docker_stream(io.BytesIO(header.tobuf(format=tarfile.USTAR_FORMAT)), image, [diff],
                                         8 * OCI.MIB, lambda: None)
    guarded = OCI.bounded_tar_info(8 * OCI.MIB)
    with mock.patch.object(tarfile.TarInfo, '_proc_member', return_value=None):
        for _ in range(8):
            header = guarded('bounded-metadata'); header.type = tarfile.XHDTYPE; header.size = 4 * OCI.MIB
            header._proc_member(None)
        with pytest.raises(ValueError, match='extended metadata'): header._proc_member(None)
    guarded = OCI.bounded_tar_info(OCI.MIB)
    def nested(_header, _archive):
        child = guarded('recursive-metadata'); child.type = tarfile.GNUTYPE_LONGNAME
        return child._proc_member(None)
    with mock.patch.object(tarfile.TarInfo, '_proc_member', new=nested):
        header = guarded('recursive-metadata'); header.type = tarfile.GNUTYPE_LONGNAME
        with pytest.raises(ValueError, match='extended metadata'): header._proc_member(None)
