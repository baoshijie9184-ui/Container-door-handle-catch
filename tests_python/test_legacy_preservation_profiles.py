"""ECS-executed byte-only profile/opaque archive contracts; never run old MCP."""
import copy
import importlib.util
import io
import os
from pathlib import Path
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('closed_legacy_preservation_contract', ROOT / 'script/memory/migrate_legacy_stores.py')
migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)


def profile_manifest(monkeypatch, combined=False):
    names = ['personal_chroma/chroma.sqlite3', 'legacy_history/history.db', 'rag_chroma/chroma.sqlite3']
    if combined:
        names.append('windows_mcp/fetch/installs/4d67f52a-38d6-4a12-9775-c7c50404ce3a/.venv/Scripts/python.exe')
    rows = []
    for name in names:
        label, relative = name.split('/', 1)
        rows.append({'path': name, 'sourcePath': migration.PRESERVATION_SOURCE_ROOTS[label] + '/' + relative,
            'bytes': 6, 'sha256': migration.sha(b'opaque'),
            'permissions': {'mode': 0o600, 'uid': 1000, 'gid': 1000, 'atimeNs': 1, 'mtimeNs': 2}})
    business = [row for row in rows if not row['path'].startswith('windows_mcp/')]
    windows = [row for row in rows if row['path'].startswith('windows_mcp/')]
    # A synthetic fixture has its own reviewed catalog; production constants are
    # independently fixed to all actual 12/5278 member names, sizes and hashes.
    monkeypatch.setattr(migration, 'LEGACY_MEMBER_INVENTORY_SHA256', migration.preservation_member_inventory(business))
    monkeypatch.setattr(migration, 'WINDOWS_MCP_MEMBER_INVENTORY_SHA256', migration.preservation_member_inventory(windows))
    return {'format': 1, 'kind': 'legacy-stores-byte-preservation', 'status': 'COMPLETE',
        'profile': migration.PRESERVATION_COMBINED_PROFILE if combined else migration.PRESERVATION_LEGACY_PROFILE,
        'archiveSha256': '9' * 64, 'inventorySha256': '8' * 64, 'files': rows, 'directories': [],
        'excludedFiles': [], 'originalBytes': sum(row['bytes'] for row in rows),
        'permissionPolicy': 'original modes/ownership/NTFS SDDL retained privately; ECS access stays owner-only'}


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
