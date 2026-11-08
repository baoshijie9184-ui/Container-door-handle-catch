"""Build dependency provenance and cache admission; executed only on ECS."""
import hashlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import urllib.request

import pytest


SPEC = importlib.util.spec_from_file_location(
    'jenkins_buildkit_input', Path(__file__).resolve().parents[1] / 'script/jenkins/fetch-buildkit-build-input.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def fixture_image():
    filesystem = io.BytesIO()
    with tarfile.open(fileobj=filesystem, mode='w', format=tarfile.USTAR_FORMAT) as package:
        content = b'original upstream fixture bytes'; entry = tarfile.TarInfo('app/source.txt'); entry.size = len(content)
        package.addfile(entry, io.BytesIO(content))
    layer = gzip.compress(filesystem.getvalue(), mtime=0)
    config = helper.encoded({'os': 'linux', 'architecture': 'amd64',
        'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + hashlib.sha256(filesystem.getvalue()).hexdigest()]},
        'config': {'User': '1000:1000', 'Env': []}})
    desc = lambda raw: {'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    value = {'schemaVersion': 2, 'mediaType': helper.MEDIA,
        'config': {**desc(config), 'mediaType': 'application/vnd.oci.image.config.v1+json'},
        'layers': [{**desc(layer), 'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip'}]}
    raw = helper.encoded(value)
    fixed = {'VERSION': 'v0.34.2', 'REFERENCE': 'docker.io/moby/buildkit@' + desc(raw)['digest'],
             'IMAGE_ID': desc(config)['digest'], 'repository': 'moby/buildkit', 'manifestDigest': desc(raw)['digest']}
    blobs = {desc(raw)['digest'][7:]: raw, desc(config)['digest'][7:]: config, desc(layer)['digest'][7:]: layer}
    entries = {'oci-layout': helper.encoded({'imageLayoutVersion': '1.0.0'}),
               'index.json': helper.encoded({'schemaVersion': 2, 'manifests': [
                   {'mediaType': helper.MEDIA, 'digest': fixed['manifestDigest'], 'size': len(raw)}]})}
    entries.update({'blobs/sha256/' + sha: content for sha, content in blobs.items()})
    return fixed, value, raw, blobs, entries


def bundle(path, entries, extra=None):
    with tarfile.open(path, 'w') as archive:
        for name, raw in entries.items():
            row = tarfile.TarInfo(name); row.size = len(raw)
            archive.addfile(row, io.BytesIO(raw))
        if extra is not None:
            archive.addfile(extra, io.BytesIO(b'x' * extra.size) if extra.isfile() else None)
    return path


def test_literal_pins_do_not_execute_source(tmp_path):
    source = tmp_path / 'pins.py'
    source.write_text("raise RuntimeError('MUST_NOT_EXECUTE')\nVERSION='v0.34.2'\n"
                      "REFERENCE='docker.io/moby/buildkit@sha256:" + 'a' * 64 + "'\nIMAGE_ID='sha256:" + 'b' * 64 + "'\n")
    assert helper.pins(source)['manifestDigest'] == 'sha256:' + 'a' * 64


def test_duplicate_source_pin_refused(tmp_path):
    source = tmp_path / 'pins.py'
    source.write_text("VERSION='v0.34.2'\nVERSION='v0.34.3'\n")
    with pytest.raises(ValueError, match='DUPLICATE_BUILD_INPUT_PIN'):
        helper.pins(source)


def test_foreign_manifest_bytes_refused():
    fixed, _, raw, _, _ = fixture_image()
    with pytest.raises(ValueError, match='ORIGINAL_PINNED_MANIFEST_REQUIRED'):
        helper.manifest(raw + b' ', fixed)


def test_manifest_config_pin_not_interchangeable():
    fixed, value, _, _, _ = fixture_image()
    value['config']['digest'] = 'sha256:' + 'a' * 64
    raw = helper.encoded(value); fixed['manifestDigest'] = 'sha256:' + helper.checksum(raw)
    with pytest.raises(ValueError, match='PINNED_BUILD_DESCRIPTOR_INVALID'):
        helper.manifest(raw, fixed)


def test_closed_raw_oci_round_trip_binds_original_bytes(tmp_path):
    fixed, _, raw, _, entries = fixture_image()
    archive = bundle(tmp_path / 'original.tar', entries)
    result = helper.verify_bundle(archive, fixed)
    assert result['sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert result['manifestSha256'] == hashlib.sha256(raw).hexdigest()
    assert result['file'] == str(archive.absolute())
    assert result['runtimeExecuted'] is False and result['testsExecutedLocally'] is False


def test_corrupt_layer_with_same_descriptor_refused(tmp_path):
    fixed, value, _, _, entries = fixture_image()
    entries['blobs/sha256/' + value['layers'][0]['digest'][7:]] = b'forged'
    with pytest.raises(ValueError, match='OCI_ORIGINAL_BLOB_BYTES_DIFFER'):
        helper.verify_bundle(bundle(tmp_path / 'bad.tar', entries), fixed)


def test_unlisted_extra_blob_refused(tmp_path):
    fixed, _, _, _, entries = fixture_image()
    entries['blobs/sha256/' + 'f' * 64] = b'extra'
    with pytest.raises(ValueError, match='OCI_BLOB_CATALOGUE_NOT_CLOSED'):
        helper.verify_bundle(bundle(tmp_path / 'extra.tar', entries), fixed)


def test_duplicate_tar_member_refused(tmp_path):
    fixed, _, _, _, entries = fixture_image()
    duplicate = tarfile.TarInfo('index.json'); duplicate.size = 1
    with pytest.raises(ValueError, match='CLOSED_OCI_TAR_MEMBERS_REQUIRED'):
        helper.verify_bundle(bundle(tmp_path / 'duplicate.tar', entries, duplicate), fixed)


def test_link_tar_member_refused(tmp_path):
    fixed, _, _, _, entries = fixture_image()
    link = tarfile.TarInfo('blobs/sha256/' + 'a' * 64); link.type = tarfile.SYMTYPE; link.linkname = '/etc/passwd'
    with pytest.raises(ValueError, match='CLOSED_OCI_TAR_MEMBERS_REQUIRED'):
        helper.verify_bundle(bundle(tmp_path / 'link.tar', entries, link), fixed)


def test_index_cannot_select_additional_image(tmp_path):
    fixed, _, _, _, entries = fixture_image()
    value = json.loads(entries['index.json']); value['manifests'] *= 2
    entries['index.json'] = helper.encoded(value)
    with pytest.raises(ValueError, match='OCI_INDEX_MUST_SELECT_PINNED_MANIFEST'):
        helper.verify_bundle(bundle(tmp_path / 'multi.tar', entries), fixed)


def test_valid_existing_bundle_reused_without_registry(tmp_path, monkeypatch):
    fixed, _, _, _, entries = fixture_image()
    bundle(tmp_path / 'buildkit-oci.tar', entries)
    monkeypatch.setattr(helper, 'Registry', lambda *_: pytest.fail('cached bundle must not access registry'))
    assert helper.fetch(tmp_path, fixed)['status'] == 'PINNED_OCI_BUILD_INPUT_READY'


def test_fresh_fetch_preserves_original_blobs_and_is_deterministic(tmp_path, monkeypatch, capsys):
    fixed, value, raw, blobs, _ = fixture_image()
    requests = []

    class FakeRegistry:
        def __init__(self, _): pass
        def get(self, suffix):
            requests.append(suffix)
            return io.BytesIO(raw if suffix.startswith('manifests/') else blobs[suffix.split('sha256:')[1]])

    monkeypatch.setattr(helper, 'Registry', FakeRegistry)
    first = helper.fetch(tmp_path / 'a', fixed)
    second = helper.fetch(tmp_path / 'b', fixed)
    assert first['sha256'] == second['sha256']
    assert first['originalLayerBytes'] == value['layers'][0]['size']
    assert len(requests) == 6
    assert capsys.readouterr().err == ''


def test_incomplete_download_removes_only_owned_partial(tmp_path):
    target = tmp_path / 'cache'; target.mkdir()
    foreign = target / 'unknown.part'; foreign.write_bytes(b'keep')
    row = {'digest': 'sha256:' + 'a' * 64, 'size': 10}

    class ShortRegistry:
        def get(self, _): return io.BytesIO(b'bad')

    with pytest.raises(ValueError, match='ORIGINAL_BUILD_BLOB_HASH_DIFFERS'):
        helper.fetch_blob(ShortRegistry(), target, row)
    assert list(target.iterdir()) == [foreign]
    assert foreign.read_bytes() == b'keep'


def test_conflicting_existing_cache_not_overwritten(tmp_path):
    fixed, _, _, _, _ = fixture_image()
    original = tmp_path / 'buildkit-oci.tar'; original.write_bytes(b'not-a-tar')
    with pytest.raises((ValueError, tarfile.TarError)):
        helper.fetch(tmp_path, fixed)
    assert original.read_bytes() == b'not-a-tar'


def test_redirect_strips_registry_credentials():
    request = urllib.request.Request('https://registry-1.docker.io/v2/moby/buildkit/blobs/sha256:a',
                                     headers={'Authorization': 'Bearer private', 'X-Safe': 'kept'})
    redirected = helper.SecureRedirect().redirect_request(request, None, 302, 'Found', {}, 'https://cdn.example/blob')
    assert redirected.get_header('Authorization') is None and redirected.get_header('X-safe') == 'kept'


def test_https_redirect_cannot_downgrade_to_plaintext():
    request = urllib.request.Request('https://registry-1.docker.io/v2/')
    with pytest.raises(ValueError, match='BUILD_DOWNLOAD_REDIRECT_REQUIRES_TLS'):
        helper.SecureRedirect().redirect_request(request, None, 302, 'Found', {}, 'http://example/blob')


def test_relative_cache_root_refused_before_creating_files():
    fixed, _, _, _, _ = fixture_image()
    with pytest.raises(ValueError, match='BUILD_CACHE_REQUIRES_EXPLICIT_D_DRIVE_DIRECTORY'):
        helper.fetch('relative-cache', fixed)


@pytest.mark.parametrize('kind', [tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME,
                                 tarfile.GNUTYPE_SPARSE, tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_closed_header_rejects_extension_before_parser_allocation(tmp_path, monkeypatch, kind):
    fixed, _, _, _, _ = fixture_image()
    header = tarfile.TarInfo('index.json'); header.type = kind; header.size = 2 * 1024 ** 3
    archive = tmp_path / 'header.tar'; archive.write_bytes(header.tobuf(format=tarfile.USTAR_FORMAT) + b'\0' * 1024)
    def forbidden(*args, **kwargs): pytest.fail('Extended parser must not run')
    monkeypatch.setattr(tarfile.TarInfo, '_proc_pax', forbidden)
    monkeypatch.setattr(tarfile.TarInfo, '_proc_gnusparse_00', forbidden)
    with pytest.raises(ValueError, match='CLOSED_OCI_TAR_MEMBERS_REQUIRED'):
        helper.verify_bundle(archive, fixed)


@pytest.mark.parametrize('kind', ['nonzero', 'truncated'])
def test_bundle_tail_cannot_be_ignored(tmp_path, kind):
    fixed, _, _, _, entries = fixture_image(); archive = bundle(tmp_path / 'tail.tar', entries)
    raw = archive.read_bytes()
    end = sum(512 + ((len(value) + 511) // 512) * 512 for value in entries.values())
    archive.write_bytes(raw + b'foreign-tail' if kind == 'nonzero' else raw[:end])
    with pytest.raises(ValueError, match='NONZERO_OCI_ARCHIVE_TAIL|TRUNCATED_OCI_ARCHIVE_TERMINATOR'):
        helper.verify_bundle(archive, fixed)


@pytest.mark.parametrize('kind', ['duplicate-index', 'duplicate-layout', 'float-schema', 'bool-size', 'extra-index'])
def test_outer_oci_metadata_types_match_the_consumer(tmp_path, kind):
    fixed, _, _, _, entries = fixture_image(); index = json.loads(entries['index.json'])
    if kind == 'float-schema': index['schemaVersion'] = 2.0
    if kind == 'bool-size': index['manifests'][0]['size'] = True
    if kind == 'extra-index': index['foreign'] = True
    entries['index.json'] = helper.encoded(index)
    if kind == 'duplicate-index':
        entries['index.json'] = entries['index.json'].replace(b'"schemaVersion":2', b'"schemaVersion":2,"schemaVersion":2')
    if kind == 'duplicate-layout':
        entries['oci-layout'] = b'{"imageLayoutVersion":"1.0.0","imageLayoutVersion":"1.0.0"}'
    with pytest.raises(ValueError, match='DUPLICATE_BUILD_METADATA_FIELD|OCI_INDEX_MUST_SELECT_PINNED_MANIFEST'):
        helper.verify_bundle(bundle(tmp_path / 'metadata.tar', entries), fixed)
