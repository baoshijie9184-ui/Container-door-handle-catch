"""ECS-executed byte-only profile/opaque archive contracts; never run old MCP."""
import copy
import gzip
import importlib.util
import io
import os
from pathlib import Path
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('closed_legacy_preservation_contract', ROOT / 'script/memory/migrate_legacy_stores.py')
migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)


def profile_manifest(monkeypatch, combined=False, kafka=False):
    names = ['personal_chroma/chroma.sqlite3', 'legacy_history/history.db', 'rag_chroma/chroma.sqlite3']
    if combined or kafka:
        names.append('windows_mcp/fetch/installs/4d67f52a-38d6-4a12-9775-c7c50404ce3a/.venv/Scripts/python.exe')
    if kafka:
        names.append('legacy_kafka/topic-0/00000000000000000000.index')
    rows = []
    for name in names:
        label, relative = name.split('/', 1)
        rows.append({'path': name, 'sourcePath': migration.PRESERVATION_SOURCE_ROOTS[label] + '/' + relative,
            'bytes': 6, 'sha256': migration.sha(b'opaque'),
            'permissions': {'mode': 0o600, 'uid': 1000, 'gid': 1000, 'atimeNs': 1, 'mtimeNs': 2}})
    business = [row for row in rows if row['path'].split('/')[0] in ('personal_chroma', 'legacy_history', 'rag_chroma')]
    windows = [row for row in rows if row['path'].startswith('windows_mcp/')]
    kafka_rows = [row for row in rows if row['path'].startswith('legacy_kafka/')]
    # A synthetic fixture has its own reviewed catalog; production constants are
    # independently fixed to all actual 12/5278 member names, sizes and hashes.
    monkeypatch.setattr(migration, 'LEGACY_MEMBER_INVENTORY_SHA256', migration.preservation_member_inventory(business))
    monkeypatch.setattr(migration, 'WINDOWS_MCP_MEMBER_INVENTORY_SHA256', migration.preservation_member_inventory(windows))
    if kafka:
        monkeypatch.setattr(migration, 'LEGACY_KAFKA_MEMBER_INVENTORY_SHA256', migration.preservation_member_inventory(kafka_rows))
        monkeypatch.setattr(migration, 'LEGACY_KAFKA_FILE_COUNT', len(kafka_rows))
    result = {'format': 1, 'kind': 'legacy-stores-byte-preservation', 'status': 'COMPLETE',
        'profile': migration.PRESERVATION_KAFKA_PROFILE if kafka else migration.PRESERVATION_COMBINED_PROFILE if combined else migration.PRESERVATION_LEGACY_PROFILE,
        'archiveSha256': '9' * 64, 'inventorySha256': '8' * 64, 'files': rows, 'directories': [],
        'excludedFiles': [], 'originalBytes': sum(row['bytes'] for row in rows),
        'permissionPolicy': 'original modes/ownership/NTFS SDDL retained privately; ECS access stays owner-only'}
    if kafka:
        result['archiveEncoding'] = 'TAR_GZIP'
    return result


def test_original_profile_remains_optional_for_preexisting_minimal_snapshots(monkeypatch):
    manifest = profile_manifest(monkeypatch); manifest.pop('profile')
    plan = migration.validate_preservation_plan(manifest)
    assert plan['profile'] == migration.PRESERVATION_LEGACY_PROFILE and plan['windowsMcpFiles'] == 0


def test_combined_profile_counts_every_reviewed_opaque_member(monkeypatch):
    manifest = profile_manifest(monkeypatch, combined=True)
    plan = migration.validate_preservation_plan(manifest)
    assert plan['files'] == len(manifest['files']) and plan['businessFiles'] == 3 and plan['windowsMcpFiles'] == 1


@pytest.mark.parametrize('mutation', ['extra-member', 'changed-hash', 'changed-size', 'foreign-root', 'provider-file', 'unknown-profile', 'extra-metadata'])
def test_closed_profiles_reject_unreviewed_files_roots_and_metadata(monkeypatch, mutation):
    manifest = profile_manifest(monkeypatch, combined=True)
    if mutation == 'extra-member':
        row = copy.deepcopy(manifest['files'][-1]); row['path'] += '.extra'; row['sourcePath'] += '.extra'
        manifest['files'].append(row); manifest['originalBytes'] += row['bytes']
    if mutation == 'changed-hash': manifest['files'][-1]['sha256'] = '0' * 64
    if mutation == 'changed-size': manifest['files'][-1]['bytes'] += 1; manifest['originalBytes'] += 1
    if mutation == 'foreign-root': manifest['files'][-1]['sourcePath'] = 'D:/AI/lunwen1/DoorHandleCatch/deploy/cloud.env'
    if mutation == 'provider-file':
        manifest['files'][1]['path'] = 'legacy_history/config.json'
        manifest['files'][1]['sourcePath'] = migration.PRESERVATION_SOURCE_ROOTS['legacy_history'] + '/config.json'
    if mutation == 'unknown-profile': manifest['profile'] = 'any-project-directory'
    if mutation == 'extra-metadata': manifest['providerConfiguration'] = 'not an admitted source metadata field'
    with pytest.raises(migration.MigrationError): migration.validate_preservation_plan(manifest)


def test_regular_byte_members_preserve_hardlinked_sources_without_tar_links(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'first.bin').write_bytes(b'opaque executable bytes, never activated')
    os.link(source / 'first.bin', source / 'second.bin')
    inventory = {'sources': {'rag_chroma': {'files': [{'relativePath': name,
        'bytes': (source / name).stat().st_size, 'sha256': migration.file_sha(source / name),
        'mtimeNs': (source / name).stat().st_mtime_ns} for name in ('first.bin', 'second.bin')]}}}
    snapshot = tmp_path / 'snapshot'
    migration.preserve_sources(inventory, {'rag_chroma': str(source)}, snapshot)
    with tarfile.open(snapshot / 'originals.tar', 'r:') as archive:
        members = archive.getmembers()
        assert len(members) == 2 and all(member.isfile() and not member.islnk() for member in members)
        assert all(archive.extractfile(member).read() == (source / 'first.bin').read_bytes() for member in members)
    assert migration.verify_preservation(snapshot)['files'] == 2


def test_archive_cannot_add_an_unlisted_secret_sidecar(monkeypatch, tmp_path):
    manifest = profile_manifest(monkeypatch, combined=True)
    snapshot = tmp_path / 'snapshot'; snapshot.mkdir()
    with tarfile.open(snapshot / 'originals.tar', 'w') as archive:
        for row in manifest['files']:
            entry = tarfile.TarInfo(row['path']); entry.size = 6; archive.addfile(entry, io.BytesIO(b'opaque'))
        extra = tarfile.TarInfo('windows_mcp/private.env'); extra.size = 1; archive.addfile(extra, io.BytesIO(b'x'))
    manifest['archiveSha256'] = migration.file_sha(snapshot / 'originals.tar')
    migration.private_json(snapshot / 'snapshot.json', manifest)
    with pytest.raises(migration.MigrationError, match='Unexpected archive member'):
        migration.verify_preservation(snapshot)


def write_archive(snapshot, manifest, *, gzip=None, payloads=None):
    snapshot.mkdir()
    compressed = manifest.get('archiveEncoding') == 'TAR_GZIP' if gzip is None else gzip
    with tarfile.open(snapshot / 'originals.tar', 'w:gz' if compressed else 'w', format=tarfile.PAX_FORMAT) as archive:
        for row in manifest['files']:
            data = (payloads or {}).get(row['path'], b'opaque')
            entry = tarfile.TarInfo(row['path']); entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    manifest['archiveSha256'] = migration.file_sha(snapshot / 'originals.tar')
    migration.private_json(snapshot / 'snapshot.json', manifest)


def source_fixture(monkeypatch, tmp_path, *, kafka=False, combined=False, kafka_payload=b'opaque'):
    manifest = profile_manifest(monkeypatch, kafka=kafka, combined=combined)
    roots = {}; sources = {}
    for row in manifest['files']:
        label, relative = row['path'].split('/', 1)
        root = tmp_path / 'source' / label; path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = kafka_payload if label == 'legacy_kafka' else b'opaque'
        path.write_bytes(payload)
        roots[label] = str(root)
        sources.setdefault(label, {'files': []})['files'].append({'relativePath': relative, 'bytes': len(payload),
            'sha256': migration.sha(payload), 'mtimeNs': path.stat().st_mtime_ns})
    monkeypatch.setattr(migration, 'PRESERVATION_SOURCE_ROOTS', roots)
    if kafka:
        monkeypatch.setattr(migration, 'LEGACY_KAFKA_MEMBER_INVENTORY_SHA256', migration.preservation_member_inventory([
            {'path': 'legacy_kafka/' + row['relativePath'], 'bytes': row['bytes'], 'sha256': row['sha256']}
            for row in sources['legacy_kafka']['files']]))
    return {'profile': manifest['profile'], 'sources': sources}, roots


def test_kafka_profile_keeps_three_independent_catalogs_and_distinct_budgets(monkeypatch):
    manifest = profile_manifest(monkeypatch, kafka=True)
    original_business_sha = migration.LEGACY_MEMBER_INVENTORY_SHA256
    original_windows_sha = migration.WINDOWS_MCP_MEMBER_INVENTORY_SHA256
    plan = migration.validate_preservation_plan(manifest)
    assert plan['businessFiles'] == 3 and plan['businessBytes'] == 18
    assert plan['windowsMcpFiles'] == 1 and plan['windowsMcpBytes'] == 6
    assert plan['kafkaFiles'] == 1 and plan['kafkaBytes'] == 6
    assert plan['archiveEncoding'] == 'TAR_GZIP'
    assert plan['logicalByteLimit'] == 2 * 1024 ** 3
    assert plan['transportByteLimit'] == 512 * 1024 ** 2
    assert migration.LEGACY_MEMBER_INVENTORY_SHA256 == original_business_sha
    assert migration.WINDOWS_MCP_MEMBER_INVENTORY_SHA256 == original_windows_sha


@pytest.mark.parametrize('profile,encoding', [
    ('legacy', 'TAR_GZIP'), ('legacy', 'TAR'), ('combined', 'TAR_GZIP'), ('combined', 'TAR'),
    ('kafka', None), ('kafka', 'TAR'), ('kafka', 'ZIP')])
def test_encoding_metadata_is_closed_to_the_new_gzip_profile(monkeypatch, profile, encoding):
    manifest = profile_manifest(monkeypatch, combined=profile == 'combined', kafka=profile == 'kafka')
    if encoding is None:
        manifest.pop('archiveEncoding', None)
    else:
        manifest['archiveEncoding'] = encoding
    with pytest.raises(migration.MigrationError):
        migration.validate_preservation_plan(manifest)


@pytest.mark.parametrize('mutation', ['omit-kafka', 'replace-kafka', 'change-kafka-bytes', 'omit-windows', 'change-original'])
def test_complete_kafka_profile_rejects_omitted_or_replaced_original_members(monkeypatch, mutation):
    manifest = profile_manifest(monkeypatch, kafka=True)
    if mutation == 'omit-kafka': manifest['files'] = [row for row in manifest['files'] if not row['path'].startswith('legacy_kafka/')]
    if mutation == 'replace-kafka': manifest['files'][-1]['sha256'] = '0' * 64
    if mutation == 'change-kafka-bytes': manifest['files'][-1]['bytes'] -= 1
    if mutation == 'omit-windows': manifest['files'] = [row for row in manifest['files'] if not row['path'].startswith('windows_mcp/')]
    if mutation == 'change-original': manifest['files'][0]['sha256'] = '1' * 64
    manifest['originalBytes'] = sum(row['bytes'] for row in manifest['files'])
    with pytest.raises(migration.MigrationError):
        migration.validate_preservation_plan(manifest)


@pytest.mark.parametrize('kafka', [False, True])
def test_each_profile_rejects_logical_bytes_above_its_bound_before_archive_io(monkeypatch, kafka):
    manifest = profile_manifest(monkeypatch, kafka=kafka)
    limit = 2 * 1024 ** 3 if kafka else 512 * 1024 ** 2
    manifest['files'][-1]['bytes'] = limit + 1
    manifest['originalBytes'] = sum(row['bytes'] for row in manifest['files'])
    with pytest.raises(migration.MigrationError, match='budget|bound'):
        migration.validate_preservation_plan(manifest)


@pytest.mark.parametrize('combined', [False, True])
def test_original_closed_profiles_still_produce_and_restore_raw_tar(monkeypatch, tmp_path, combined):
    inventory, roots = source_fixture(monkeypatch, tmp_path, combined=combined)
    snapshot = tmp_path / 'snapshot'
    result = migration.preserve_sources(inventory, roots, snapshot)
    assert (snapshot / 'originals.tar').read_bytes()[:2] != b'\x1f\x8b'
    manifest = migration.read_json(snapshot / 'snapshot.json')
    assert 'archiveEncoding' not in manifest
    plan = migration.validate_preservation_plan(manifest)
    assert plan['archiveEncoding'] == 'TAR' and plan['kafkaFiles'] == plan['kafkaBytes'] == 0
    restored = tmp_path / 'restored'
    receipt = migration.verify_preservation(snapshot, restored)
    assert receipt['files'] == result['files'] and receipt['bytes'] == result['bytes']
    assert all((restored / row['path']).read_bytes() == b'opaque' for row in manifest['files'])


@pytest.mark.parametrize('tail_bytes', [123, 1024 * 1024])
def test_gzip_preservation_restores_sparse_trailing_zero_bytes_and_original_digest(monkeypatch, tmp_path, tail_bytes):
    payload = b'head' + bytes(1024 * 1024 - 4) + bytes(1024 * 1024 + tail_bytes)
    inventory, roots = source_fixture(monkeypatch, tmp_path, kafka=True, kafka_payload=payload)
    snapshot = tmp_path / 'snapshot'
    migration.preserve_sources(inventory, roots, snapshot)
    assert (snapshot / 'originals.tar').read_bytes()[:2] == b'\x1f\x8b'
    assert (snapshot / 'originals.tar').stat().st_size < len(payload) // 10
    restored = tmp_path / 'restored'
    receipt = migration.verify_preservation(snapshot, restored)
    recovered = restored / 'legacy_kafka/topic-0/00000000000000000000.index'
    assert recovered.stat().st_size == len(payload) and recovered.read_bytes() == payload
    assert migration.file_sha(recovered) == migration.sha(payload)
    if hasattr(recovered.stat(), 'st_blocks'):
        assert recovered.stat().st_blocks * 512 < len(payload)
    assert set(receipt) == {'status', 'archiveSha256', 'snapshotManifestSha256', 'files', 'bytes'}
    assert receipt['status'] == 'RESTORED_VERIFIED'


@pytest.mark.parametrize('profile', ['none', 'legacy', 'combined'])
def test_gzip_bytes_cannot_be_smuggled_through_an_old_raw_profile(monkeypatch, tmp_path, profile):
    manifest = profile_manifest(monkeypatch, combined=profile == 'combined')
    if profile == 'none': manifest.pop('profile')
    snapshot = tmp_path / 'snapshot'; write_archive(snapshot, manifest, gzip=True)
    with pytest.raises(migration.MigrationError, match='encoding'):
        migration.verify_preservation(snapshot)


def test_new_profile_cannot_label_raw_tar_as_gzip(monkeypatch, tmp_path):
    manifest = profile_manifest(monkeypatch, kafka=True)
    snapshot = tmp_path / 'snapshot'; write_archive(snapshot, manifest, gzip=False)
    with pytest.raises(migration.MigrationError, match='encoding'):
        migration.verify_preservation(snapshot)


def test_gzip_transport_tampering_is_detected_before_unpacking(monkeypatch, tmp_path):
    manifest = profile_manifest(monkeypatch, kafka=True)
    snapshot = tmp_path / 'snapshot'; write_archive(snapshot, manifest)
    archive = snapshot / 'originals.tar'; data = bytearray(archive.read_bytes()); data[-1] ^= 1; archive.write_bytes(data)
    with pytest.raises(migration.MigrationError, match='archive digest'):
        migration.verify_preservation(snapshot)


def test_gzip_member_tampering_cannot_be_hidden_by_a_new_transport_digest(monkeypatch, tmp_path):
    manifest = profile_manifest(monkeypatch, kafka=True)
    snapshot = tmp_path / 'snapshot'
    write_archive(snapshot, manifest, payloads={manifest['files'][-1]['path']: b'change'})
    with pytest.raises(migration.MigrationError, match='member digest'):
        migration.verify_preservation(snapshot)


def test_gzip_member_cannot_expand_beyond_its_frozen_logical_size(monkeypatch, tmp_path):
    manifest = profile_manifest(monkeypatch, kafka=True)
    snapshot = tmp_path / 'snapshot'
    write_archive(snapshot, manifest, payloads={manifest['files'][-1]['path']: bytes(1024 * 1024)})
    with pytest.raises(migration.MigrationError, match='member size'):
        migration.verify_preservation(snapshot)


@pytest.mark.parametrize('header_type', [tarfile.XHDTYPE, tarfile.XGLTYPE])
@pytest.mark.parametrize('metadata_bytes', [65536, 65537])
def test_gzip_pax_metadata_limit_is_checked_before_decoding(monkeypatch, tmp_path, header_type, metadata_bytes):
    manifest = profile_manifest(monkeypatch, kafka=True)
    snapshot = tmp_path / 'snapshot'; snapshot.mkdir()
    # Use valid PAX records followed by every actual member. A malformed,
    # zero-filled header could fail at EOF without exercising the size guard.
    comment = 'x' * (metadata_bytes - len(str(metadata_bytes) + ' comment=\n'))
    with tarfile.open(snapshot / 'originals.tar', 'w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': comment} if header_type == tarfile.XGLTYPE else None) as archive:
        for index, row in enumerate(manifest['files']):
            entry = tarfile.TarInfo(row['path']); entry.size = row['bytes']
            if index == 0 and header_type == tarfile.XHDTYPE: entry.pax_headers = {'comment': comment}
            archive.addfile(entry, io.BytesIO(b'opaque'))
    with gzip.open(snapshot / 'originals.tar', 'rb') as raw:
        header = tarfile.TarInfo.frombuf(raw.read(512), 'utf-8', 'strict')
    assert header.type == header_type and header.size == metadata_bytes
    manifest['archiveSha256'] = migration.file_sha(snapshot / 'originals.tar')
    migration.private_json(snapshot / 'snapshot.json', manifest)
    if metadata_bytes == 65536:
        assert migration.verify_preservation(snapshot)['status'] == 'SNAPSHOT_VERIFIED'
    else:
        monkeypatch.setattr(tarfile.TarInfo, '_proc_pax',
            lambda *unused: pytest.fail('Oversize PAX must be rejected before the decoder reads its payload'))
        with pytest.raises(migration.MigrationError, match='metadata bound'):
            migration.verify_preservation(snapshot)


def test_gzip_cannot_smuggle_foreign_sparse_maps_through_pax_headers(monkeypatch, tmp_path):
    manifest = profile_manifest(monkeypatch, kafka=True)
    snapshot = tmp_path / 'snapshot'; snapshot.mkdir()
    with tarfile.open(snapshot / 'originals.tar', 'w:gz', format=tarfile.PAX_FORMAT) as archive:
        for row in manifest['files']:
            entry = tarfile.TarInfo(row['path']); entry.size = 6
            if row['path'].startswith('legacy_kafka/'):
                entry.pax_headers = {'GNU.sparse.map': '0,6'}
            archive.addfile(entry, io.BytesIO(b'opaque'))
    manifest['archiveSha256'] = migration.file_sha(snapshot / 'originals.tar')
    migration.private_json(snapshot / 'snapshot.json', manifest)
    with pytest.raises(migration.MigrationError, match='foreign GNU sparse'):
        migration.verify_preservation(snapshot)
