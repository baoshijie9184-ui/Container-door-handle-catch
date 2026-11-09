"""ECS-only fixed-manifest/fake-backend contracts; no native deletion or SSH."""
import copy
from contextlib import contextmanager
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests_python.test_local_cold_retirement import FakeBackend, FakeCold, FakeAttestor, MemoryAudit


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('fixed_original_retirement_contract', ROOT / 'script/jenkins/retire-local-fixed-originals.py')
fixed = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(fixed)
core = fixed.load('retire-local-cold-stores.py')
PROFILE = 'legacy-project-originals-v1'


@pytest.fixture
def packet(monkeypatch):
    members = [{'sourcePath': fixed.ROOT + r'\memory_service\chroma_db\chroma.sqlite3', 'path': 'personal_chroma/chroma.sqlite3', 'bytes': 1, 'sha256': 'a' * 64},
        {'sourcePath': fixed.ROOT + r'\work\middlewares\kafka-data\events\0.log', 'path': 'legacy_kafka/events/0.log', 'bytes': 2, 'sha256': 'b' * 64},
        {'sourcePath': fixed.RETAINED_C_HISTORY, 'path': 'legacy_history/history.db', 'bytes': 65536, 'sha256': 'c' * 64}]
    def seal(rows): return json.dumps({'files': rows}, sort_keys=True).encode()
    raw = seal(members)
    recipe = {'manifestSha256': fixed.sha(raw), 'members': 3, 'selected': 2, 'bytes': 65539, 'retained': 1}
    monkeypatch.setattr(fixed, 'RECIPES', {PROFILE: recipe})
    return SimpleNamespace(rows=members, raw=raw, seal=seal, recipe=recipe)


def reseal(packet):
    packet.raw = packet.seal(packet.rows); packet.recipe['manifestSha256'] = fixed.sha(packet.raw)


@pytest.fixture
def scope(packet):
    selected, retained = fixed.select_manifest(PROFILE, packet.raw)
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    plan = {'profile': PROFILE, 'manifestSha256': packet.recipe['manifestSha256'], 'members': members, 'retained': retained,
            'current': {'release': 'ci-99-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64},
            'custody': {'release': 'ci-97-' + 'c' * 12}}
    events = []; proof = FakeCold(); backend = FakeBackend(events); attestor = FakeAttestor(events, proof)
    return SimpleNamespace(plan=plan, selected=selected, events=events, proof=proof, backend=backend,
                           attestor=attestor, audit=MemoryAudit(events))


def apply(scope): return fixed.apply_plan(scope.plan, core, scope.proof, scope.backend, scope.attestor, scope.audit)


@pytest.fixture
def transport(scope, tmp_path, monkeypatch):
    profile = 'additional-originals-v1'; directory = 'work/frozen-transport'
    monkeypatch.setattr(fixed, 'ROOT', str(tmp_path))
    monkeypatch.setattr(fixed, 'TRANSPORT_DIRECTORIES', {profile: directory})
    folder = tmp_path / directory; folder.mkdir(parents=True)
    archive = folder / 'originals.tar'; archive.write_bytes(b'opaque transport')
    value = {'archiveSha256': fixed.sha(archive.read_bytes()), 'archiveBytes': archive.stat().st_size,
             'files': [{'sourcePath': str(tmp_path / 'already-retired-payload.pth')}]}
    raw = json.dumps(value, sort_keys=True).encode(); manifest = folder / 'custody.json'; manifest.write_bytes(raw)
    recipe = {'manifestSha256': fixed.sha(raw)}; monkeypatch.setitem(fixed.RECIPES, profile, recipe)
    custody = {'manifestSha256': fixed.sha(raw), 'archiveSha256': value['archiveSha256'], 'archiveBytes': value['archiveBytes']}
    current = copy.deepcopy(scope.plan['current'])
    monkeypatch.setattr(core, 'canonical_control', lambda path: Path(path))
    monkeypatch.setattr(fixed, 'code_bindings', lambda *args: {'executorSha256': 'e' * 64})
    monkeypatch.setattr(fixed, 'bindings', lambda *args: (copy.deepcopy(current), copy.deepcopy(custody)))
    monkeypatch.setattr(fixed, 'observed_members', lambda rows, *_args: [
        {**row, 'fingerprint': [7, index + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for index, row in enumerate(rows)])
    for name in ('select_manifest', 'observe_model_link_group', 'verify_model_link_group'):
        monkeypatch.setattr(fixed, name, lambda *_: pytest.fail('transport accessed original payload/model logic'))
    plan = fixed.make_plan(profile, manifest, 'current', 'custody', core, SimpleNamespace(), SimpleNamespace(),
                           lambda resolver: scope.backend, selection='transport')
    scope.plan = plan
    args = SimpleNamespace(plan='synthetic-plan', plan_sha256='a' * 64, profile=profile, manifest=manifest,
        current_receipt='current', custody_receipt='custody', selection='transport')
    monkeypatch.setattr(core, 'control', lambda _: (plan, 'a' * 64))
    scope.events.clear()
    return SimpleNamespace(scope=scope, profile=profile, manifest=manifest, archive=archive, raw=raw,
        value=value, recipe=recipe, custody=custody, plan=plan, args=args, directory=directory)


def test_transport_plan_load_and_fake_apply_touch_only_the_two_frozen_package_files(transport):
    item = transport; assert fixed.load_plan(item.args, core, SimpleNamespace(), SimpleNamespace()) == item.plan
    assert {row['path'] for row in item.plan['members']} == {item.directory + '/custody.json', item.directory + '/originals.tar'}
    result = apply(item.scope)
    assert result['status'] == 'FIXED_TRANSPORT_RETIRED' and result['selection'] == 'transport'
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 0 and result['payloadFilesTouched'] is False
    assert item.manifest.read_bytes() == item.raw and item.archive.read_bytes() == b'opaque transport'
    assert len([row for row in item.scope.events if row[0] == 'delete-held']) == 2
    assert not any(row[0] == 'empty-dir-held' for row in item.scope.events)


def test_transport_refuses_a_copied_manifest_unknown_profile_and_any_cloud_archive_drift(transport):
    item = transport; copied = item.manifest.with_name('copied.json'); copied.write_bytes(item.raw)
    with pytest.raises(ValueError, match='FIXED_TRANSPORT_MANIFEST_LOCATION'):
        fixed.select_files(item.profile, copied, item.raw, 'transport')
    for profile in ('pth-aliases-v1', 'cold-store-originals-v1', 'local-mysql45-export'):
        with pytest.raises(ValueError, match='FIXED_TRANSPORT_PROFILE'):
            fixed.select_files(profile, item.manifest, item.raw, 'transport')
    for field in ('manifestSha256', 'archiveSha256', 'archiveBytes'):
        custody = copy.deepcopy(item.custody); custody[field] = custody[field] + 1 if field == 'archiveBytes' else 'f' * 64
        with pytest.raises(ValueError, match='TRANSPORT_AND_LIVE_CUSTODY_BINDING_DRIFT'):
            fixed.transport_custody(item.plan['members'], custody)


def test_transport_plan_mode_targets_and_model_groups_cannot_be_rewritten(transport, monkeypatch):
    item = transport
    for damage in ('removed-mode', 'rewritten-mode', 'extra-target', 'changed-target', 'model-group'):
        submitted = copy.deepcopy(item.plan)
        if damage == 'removed-mode': submitted.pop('selection')
        elif damage == 'rewritten-mode': submitted['selection'] = 'originals'
        elif damage == 'extra-target': submitted['members'].append(copy.deepcopy(submitted['members'][0]))
        elif damage == 'changed-target': submitted['members'][0]['path'] = 'work/unknown/originals.tar'
        else: submitted['closedModelHardlinkGroup'] = None
        monkeypatch.setattr(core, 'control', lambda _, plan=submitted: (plan, 'a' * 64))
        with pytest.raises(ValueError): fixed.load_plan(item.args, core, SimpleNamespace(), SimpleNamespace())
        with pytest.raises(ValueError): fixed.apply_plan(submitted, core, item.scope.proof, item.scope.backend, item.scope.attestor, item.scope.audit)
    assert not any(row[0] == 'delete-held' for row in item.scope.events)


def test_transport_refuses_deletion_without_a_fresh_authenticated_proof(transport):
    item = transport; item.scope.attestor.failure = True
    with pytest.raises(ValueError): apply(item.scope)
    assert not any(row[0] == 'delete-held' for row in item.scope.events)


def test_only_the_fixed_legacy_transport_has_an_approved_archive_size_when_the_manifest_omits_it(transport, monkeypatch):
    item = transport; profile = 'legacy-project-originals-v1'; value = dict(item.value); value.pop('archiveBytes')
    raw = json.dumps(value, sort_keys=True).encode(); manifest = item.manifest.with_name('snapshot.json')
    monkeypatch.setitem(fixed.TRANSPORT_DIRECTORIES, profile, item.directory)
    monkeypatch.setitem(fixed.RECIPES, profile, {'manifestSha256': fixed.sha(raw), 'approvedLegacyArchiveBytes': 81841366})
    selected, _ = fixed.select_files(profile, manifest, raw, 'transport')
    assert next(row['bytes'] for row in selected if row['path'].endswith('/originals.tar')) == 81841366
    custody = {'manifestSha256': fixed.sha(raw), 'archiveSha256': value['archiveSha256'], 'archiveBytes': 81841365}
    with pytest.raises(ValueError, match='TRANSPORT_AND_LIVE_CUSTODY_BINDING_DRIFT'): fixed.transport_custody(selected, custody)
    item.recipe['manifestSha256'] = fixed.sha(raw)
    with pytest.raises(ValueError, match='FIXED_TRANSPORT_ARCHIVE_BINDING_REQUIRED'):
        fixed.select_files(item.profile, item.manifest, raw, 'transport')


def test_fixed_legacy_selects_only_d_project_and_preserves_c_history_without_access(packet, monkeypatch):
    monkeypatch.setattr(Path, 'lstat', lambda *_: pytest.fail('Manifest selection must not inspect any source'))
    selected, retained = fixed.select_manifest(PROFILE, packet.raw)
    assert len(selected) == 2 and retained == [{'sourcePath': fixed.RETAINED_C_HISTORY,
        'reason': 'C_DRIVE_HISTORY_NEVER_ACCESSED', 'bytes': 65536}]
    assert {r['path'] for r in selected} == {'memory_service/chroma_db/chroma.sqlite3', 'work/middlewares/kafka-data/events/0.log'}


def test_unreviewed_raw_manifest_cannot_select_files_even_if_json_values_match(packet):
    with pytest.raises(ValueError, match='FIXED_RAW_MANIFEST_SHA'): fixed.select_manifest(PROFILE, packet.raw + b' ')


def test_additional_profile_admits_uploads_and_logs_without_admitting_c_history(packet, monkeypatch):
    name = 'additional-originals-v1'
    rows = [{'sourcePath': fixed.ROOT + r'\doorhandle-server\uploads\sample.jpg', 'bytes': 1, 'sha256': 'a' * 64},
            {'sourcePath': fixed.ROOT + r'\logs\backend.out.log', 'bytes': 2, 'sha256': 'b' * 64}]
    raw = packet.seal(rows); recipe = {'manifestSha256': fixed.sha(raw), 'members': 2, 'selected': 2, 'bytes': 3, 'retained': 0}
    monkeypatch.setitem(fixed.RECIPES, name, recipe)
    selected, retained = fixed.select_manifest(name, raw)
    assert len(selected) == 2 and retained == []
    rows[0] = copy.deepcopy(packet.rows[-1]); raw = packet.seal(rows); recipe['manifestSha256'] = fixed.sha(raw)
    with pytest.raises(ValueError, match='ONLY_FIXED_C_HISTORY'): fixed.select_manifest(name, raw)


@pytest.fixture
def residual_packet(packet, monkeypatch):
    name = 'residual-project-originals-v1'
    rows = [{'sourcePath': fixed.ROOT + r'\work\old-output\opaque.sql', 'bytes': 1, 'sha256': 'a' * 64},
            {'sourcePath': fixed.ROOT + r'\work\old-output\opaque.onnx', 'bytes': 2, 'sha256': 'b' * 64}]
    raw = packet.seal(rows)
    recipe = {'manifestSha256': fixed.sha(raw), 'members': 2, 'selected': 2, 'bytes': 3, 'retained': 0}
    monkeypatch.setitem(fixed.RECIPES, name, recipe)
    return SimpleNamespace(profile=name, rows=rows, raw=raw, recipe=recipe)


def residual_plan(scope, residual_packet):
    selected, retained = fixed.select_manifest(residual_packet.profile, residual_packet.raw)
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=residual_packet.profile, manifestSha256=residual_packet.recipe['manifestSha256'],
                      members=members, retained=retained, **fixed.residual_bindings(residual_packet.profile))
    return members


@pytest.fixture
def remaining_packet(packet, monkeypatch):
    profile = 'remaining-system-data-v1'
    groups = ['local-mysql45-export', 'protected-tool-receipts', 'remaining-agent-workspace',
              'remaining-memory-export', 'remaining-mysql-archives', 'remaining-user-skill-downloads']
    rows = [{'sourcePath': fixed.ROOT + '\\work\\remaining\\' + group + '\\opaque.bin',
             'member': 'work/remaining/' + group + '/opaque.bin', 'group': group, 'bytes': number,
             'sha256': str(number) * 64} for number, group in enumerate(groups, 1)]
    value = {'kind': 'doorhandle-additional-local-artifact-custody', 'version': 1, 'status': 'COMPLETE',
             'profile': profile, 'catalogSha256': 'd' * 64, 'originalFiles': len(rows),
             'originalBytes': sum(row['bytes'] for row in rows), 'files': rows}
    raw = json.dumps(value, sort_keys=True).encode()
    recipe = {'manifestSha256': fixed.sha(raw), 'catalogSha256': value['catalogSha256'], 'members': 6,
              'selected': 5, 'retained': 1, 'bytes': value['originalBytes'],
              'groups': {row['group']: [1, row['bytes']] for row in rows}}
    monkeypatch.setitem(fixed.RECIPES, profile, recipe)
    return SimpleNamespace(profile=profile, value=value, raw=raw, rows=rows, recipe=recipe)


def test_remaining_production_recipe_keeps_eight_unproved_tools_out_of_the_selected_78():
    recipe = fixed.RECIPES['remaining-system-data-v1']
    assert (recipe['members'], recipe['selected'], recipe['retained'], recipe['bytes']) == (86, 78, 8, 28695377)
    assert recipe['groups']['protected-tool-receipts'] == [8, 117235]
    assert sum(row[0] for row in recipe['groups'].values()) == 86
    assert sum(row[1] for row in recipe['groups'].values()) == 28695377


def test_remaining_selection_keeps_complete_tool_ownership_explicitly_blocked(remaining_packet):
    selected, retained = fixed.select_manifest(remaining_packet.profile, remaining_packet.raw)
    assert len(selected) == 5 and len(retained) == 1
    assert retained[0]['reason'] == 'COMPLETE_TOOL_TREE_OWNERSHIP_UNPROVED'
    assert 'protected-tool-receipts' in retained[0]['sourcePath']
    assert not any('protected-tool-receipts' in row['path'] for row in selected)


@pytest.mark.parametrize('damage', ['raw', 'profile', 'catalog', 'counts', 'group', 'group-counts'])
def test_remaining_profile_catalog_groups_and_raw_manifest_cannot_drift(remaining_packet, damage):
    value = copy.deepcopy(remaining_packet.value)
    if damage == 'profile': value['profile'] = 'residual-project-originals-v1'
    elif damage == 'catalog': value['catalogSha256'] = 'e' * 64
    elif damage == 'counts': value['originalFiles'] += 1
    elif damage == 'group': value['files'][0]['group'] = 'unreviewed'
    elif damage == 'group-counts': value['files'][0]['group'] = value['files'][-1]['group']
    raw = json.dumps(value, sort_keys=True).encode()
    if damage == 'raw': raw += b' '
    else: remaining_packet.recipe['manifestSha256'] = fixed.sha(raw)
    with pytest.raises(ValueError):
        fixed.select_manifest(remaining_packet.profile, raw)


def test_remaining_fake_apply_keeps_tools_and_directories_and_requires_source_guard_before_handles(scope, remaining_packet, monkeypatch):
    selected, retained = fixed.select_manifest(remaining_packet.profile, remaining_packet.raw)
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=remaining_packet.profile, manifestSha256=remaining_packet.recipe['manifestSha256'],
                      members=members, retained=retained, **fixed.residual_bindings(remaining_packet.profile))
    def checked(profile, rows):
        assert profile == remaining_packet.profile and rows == members
        scope.events.append(('remaining-source-guard',))
    monkeypatch.setattr(fixed, 'residual_source_guard', checked)
    result = apply(scope)
    assert result['filesDeleted'] == 5 and result['directoriesRemoved'] == 0 and result['retained'] == retained
    assert scope.events[0] == ('remaining-source-guard',)
    assert not any('protected-tool-receipts' in event[1] for event in scope.events if event[0] in ('hash', 'verify', 'delete-held'))


def test_remaining_source_guard_reads_only_registered_git_and_ancestor_metadata(remaining_packet, monkeypatch):
    selected, _ = fixed.select_manifest(remaining_packet.profile, remaining_packet.raw); observed = []
    helper = SimpleNamespace(residual_repository_guard=lambda paths: observed.extend(paths))
    monkeypatch.setattr(fixed, 'load', lambda name: helper if name == 'preserve-local-artifacts.py' else pytest.fail('unexpected helper'))
    fixed.residual_source_guard(remaining_packet.profile, selected)
    assert observed == [fixed.ROOT + '\\' + row['path'].replace('/', '\\') for row in selected]


@pytest.fixture
def partial_transport_packet(packet, monkeypatch):
    profile = 'legacy-partial-transports-v1'
    rows = []
    for index, (group, folder, name) in enumerate([
            ('legacy-memory-rag-transport', 'early-memory', 'originals.tar'),
            ('legacy-memory-rag-transport', 'early-memory', 'snapshot.json'),
            ('legacy-windows-mcp-transport', 'early-mcp', 'originals.tar'),
            ('legacy-windows-mcp-transport', 'early-mcp', 'snapshot.json')], 1):
        member = 'work/data-migration-' + folder + '/' + name
        rows.append({'sourcePath': fixed.ROOT + '\\' + member.replace('/', '\\'), 'member': member,
                     'group': group, 'bytes': index, 'sha256': str(index) * 64})
    value = {'kind': 'doorhandle-additional-local-artifact-custody', 'version': 1, 'status': 'COMPLETE',
             'profile': profile, 'catalogSha256': 'd' * 64, 'originalFiles': 4, 'originalBytes': 10,
             'archiveSha256': 'e' * 64, 'archiveBytes': 100, 'files': rows}
    raw = json.dumps(value, sort_keys=True).encode()
    recipe = {'manifestSha256': fixed.sha(raw), 'manifestBytes': len(raw), 'catalogSha256': value['catalogSha256'],
              'archiveSha256': value['archiveSha256'], 'archiveBytes': value['archiveBytes'],
              'members': 4, 'selected': 4, 'retained': 0, 'bytes': 10,
              'groups': {'legacy-memory-rag-transport': [2, 3], 'legacy-windows-mcp-transport': [2, 7]}}
    monkeypatch.setitem(fixed.RECIPES, profile, recipe)
    return SimpleNamespace(profile=profile, value=value, raw=raw, rows=rows, recipe=recipe)


@pytest.fixture
def business_record_packet(packet, monkeypatch):
    profile = 'remaining-business-records-v1'
    names = [('work/business-data-cleanup/query.json', 'remaining-business-cleanup'),
             ('work/agent-cards-local-mysql.json', 'retained-mysql-query-fixture-evidence'),
             ('work/jenkins/business-workbench-final.json', 'remaining-business-operations-evidence')]
    rows = [{'sourcePath': fixed.ROOT + '\\' + name.replace('/', '\\'), 'member': name,
             'group': group, 'bytes': number, 'sha256': str(number) * 64}
            for number, (name, group) in enumerate(names, 1)]
    value = {'kind': 'doorhandle-additional-local-artifact-custody', 'version': 1, 'status': 'COMPLETE',
             'profile': profile, 'catalogSha256': 'd' * 64, 'originalFiles': 3, 'originalBytes': 6,
             'archiveSha256': 'e' * 64, 'archiveBytes': 100, 'files': rows}
    raw = json.dumps(value, sort_keys=True).encode()
    recipe = {'manifestSha256': fixed.sha(raw), 'manifestBytes': len(raw), 'catalogSha256': value['catalogSha256'],
              'archiveSha256': value['archiveSha256'], 'archiveBytes': value['archiveBytes'],
              'members': 3, 'selected': 2, 'retained': 1, 'bytes': 6,
              'groups': {row['group']: [1, row['bytes']] for row in rows}}
    monkeypatch.setitem(fixed.RECIPES, profile, recipe)
    return SimpleNamespace(profile=profile, value=value, raw=raw, rows=rows, recipe=recipe)


def test_business_record_production_recipe_preserves_fourteen_unknowns_and_pins_only_the_250_reviewed_sources():
    recipe = fixed.RECIPES['remaining-business-records-v1']
    assert (recipe['members'], recipe['selected'], recipe['retained'], recipe['bytes']) == (250, 236, 14, 11537819)
    assert recipe['groups']['retained-mysql-query-fixture-evidence'] == [14, 5455]
    assert recipe['manifestSha256'] == 'd1531e2fee6325912f053492ebb91c47037fb36783216a0cf3f5c66c69e6406a'
    assert recipe['archiveSha256'] == 'cef73e24e689b7889f2a4903f091e35e686cf0f7bd0e68705106ed0cbda90612'
    assert (recipe['manifestBytes'], recipe['archiveBytes']) == (179248, 11735040)
    assert sum(row[0] for row in recipe['groups'].values()) == 250
    assert sum(row[1] for row in recipe['groups'].values()) == 11537819
    assert fixed.BUSINESS_RECEIPTS == fixed.load('preserve-local-artifacts.py').BUSINESS_RECEIPTS
    rows = [{'path': name} for name in fixed.BUSINESS_PROCESS_FILES]
    roots = {row['path'] for row in fixed.value_for(rows, profile='remaining-business-records-v1')['roots']}
    assert roots == fixed.BUSINESS_PROCESS_FILES
    assert {row['path'] for row in fixed.value_for(rows)['roots']} == {'work', 'work/jenkins'}
    with pytest.raises(ValueError, match='FIXED_BUSINESS_PROCESS_RECEIPTS_REQUIRED'):
        fixed.value_for([{'path': 'work/unreviewed.json'}], profile='remaining-business-records-v1')


def test_business_record_fake_retirement_never_opens_retained_mysql_and_still_requires_live_proof(scope, business_record_packet, monkeypatch):
    packet = business_record_packet; selected, retained = fixed.select_manifest(packet.profile, packet.raw)
    assert len(selected) == 2 and len(retained) == 1 and retained[0]['reason'] == 'MYSQL_QUERY_OR_FIXTURE_PURPOSE_UNCONFIRMED'
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=packet.profile, manifestSha256=packet.recipe['manifestSha256'],
                      members=members, retained=retained, **fixed.residual_bindings(packet.profile))
    def guard(profile, rows):
        assert profile == packet.profile and rows == members
        scope.events.append(('business-source-guard',))
    monkeypatch.setattr(fixed, 'residual_source_guard', guard)
    scope.attestor.failure = True
    with pytest.raises(ValueError, match='AUTHENTICATED_LIVE_SERVER_ATTESTATION_REQUIRED'): apply(scope)
    assert not any(row[0] == 'delete-held' for row in scope.events)
    scope.events.clear(); scope.attestor.failure = False
    result = apply(scope)
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 0 and result['retained'] == retained
    assert scope.events[0] == ('business-source-guard',)
    assert not any('agent-cards-local-mysql.json' in row[1] for row in scope.events if row[0] in ('hash', 'verify', 'delete-held'))
    scope.events.clear(); scope.plan.pop('businessRecordsScopeHelperSha256')
    with pytest.raises(ValueError, match='FIXED_RESIDUAL_SOURCE_GUARD_REQUIRED'): apply(scope)
    assert scope.events == []


def test_business_record_envelope_groups_and_jenkins_exception_cannot_expand(business_record_packet):
    packet = business_record_packet; original_recipe = copy.deepcopy(packet.recipe)
    selected, _ = fixed.select_manifest(packet.profile, packet.raw)
    resolver = fixed.StrictResolver(selected, profile=packet.profile)
    assert resolver('work/jenkins/business-workbench-final.json').endswith(r'\work\jenkins\business-workbench-final.json')
    assert resolver('work/jenkins').endswith(r'\work\jenkins')
    with pytest.raises(ValueError): resolver('work/jenkins/private.env')
    with pytest.raises(ValueError): fixed.StrictResolver(selected)('work/jenkins/business-workbench-final.json')
    for damage in ('raw', 'profile', 'catalog', 'group', 'retained-group', 'archiveSha256', 'archiveBytes', 'protected-path', 'member-alias'):
        value = copy.deepcopy(packet.value); packet.recipe.clear(); packet.recipe.update(original_recipe)
        if damage == 'profile': value['profile'] = 'remaining-system-data-v1'
        elif damage == 'catalog': value['catalogSha256'] = 'f' * 64
        elif damage == 'group': value['files'][0]['group'] = 'unreviewed'
        elif damage == 'retained-group': value['files'][1]['group'] = 'remaining-business-cleanup'
        elif damage == 'archiveSha256': value['archiveSha256'] = 'f' * 64
        elif damage == 'archiveBytes': value['archiveBytes'] += 1
        elif damage == 'protected-path':
            value['files'][2]['sourcePath'] = fixed.ROOT + r'\work\jenkins\private.env'
            value['files'][2]['member'] = 'work/jenkins/private.env'
        elif damage == 'member-alias': value['files'][0]['member'] = 'work/business-data-cleanup/other.json'
        raw = json.dumps(value, sort_keys=True).encode()
        if damage == 'raw': raw += b' '
        else: packet.recipe.update(manifestSha256=fixed.sha(raw), manifestBytes=len(raw))
        with pytest.raises(ValueError): fixed.select_manifest(packet.profile, raw)


def test_business_record_apply_cli_passes_its_exact_receipt_resolver_to_the_windows_backend(tmp_path, monkeypatch, capsys):
    profile = 'remaining-business-records-v1'; events = []
    plan = {'profile': profile, 'members': [{'path': name} for name in sorted(fixed.BUSINESS_RECEIPTS)]}
    audit = SimpleNamespace(directory=tmp_path, close=lambda: events.append('audit-closed'))
    cold = SimpleNamespace(utility=lambda: SimpleNamespace(write_json=lambda path, value: events.append((path, value))))
    proof = object(); attestor = object()
    def windows_backend(actual_cold, *, source_resolver):
        assert actual_cold is cold
        return SimpleNamespace(source_resolver=source_resolver)
    def live_attestor(actual_proof, args, *, helper_name):
        assert actual_proof is proof and args.profile == profile and helper_name == 'attest-fixed-originals.py'
        return attestor
    control = SimpleNamespace(Audit=lambda *_: audit, WindowsBackend=windows_backend, LiveAttestor=live_attestor)
    monkeypatch.setattr(fixed, 'os', SimpleNamespace(name='nt'))
    modules = {'retire-local-cold-stores.py': control, 'preserve-cold-stores.py': cold, 'attest-fixed-originals.py': proof}
    monkeypatch.setattr(fixed, 'load', lambda name: modules[name])
    monkeypatch.setattr(fixed, 'load_plan', lambda args, *_: plan)
    def apply_cli(actual_plan, actual_core, actual_proof, backend, actual_attestor, actual_audit):
        assert actual_plan is plan and actual_core is control and actual_proof is proof
        assert actual_attestor is attestor and actual_audit is audit
        for row in plan['members']:
            assert backend.source_resolver(row['path']) == fixed.ROOT + '\\' + row['path'].replace('/', '\\')
        with pytest.raises(ValueError): backend.source_resolver('work/jenkins/private.env')
        with pytest.raises(ValueError): backend.source_resolver('work/jenkins/business-workbench-final.json.bak')
        return {'status': 'SYNTHETIC_CLI_BACKEND_WIRED', 'originalFilesDeleted': 0}
    monkeypatch.setattr(fixed, 'apply_plan', apply_cli)
    assert fixed.main(['--profile', profile, '--manifest', 'not-opened', '--output', 'not-created', '--apply',
        '--ssh-host', 'not-contacted', '--plan', 'not-opened', '--plan-sha256', 'a' * 64,
        '--current-receipt', 'not-opened', '--custody-receipt', 'not-opened']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'SYNTHETIC_CLI_BACKEND_WIRED'
    assert events[-1] == 'audit-closed' and events[0][0] == tmp_path / 'result.json'


def test_partial_transport_production_recipe_selects_only_four_fixed_early_files():
    recipe = fixed.RECIPES['legacy-partial-transports-v1']
    assert (recipe['members'], recipe['selected'], recipe['retained'], recipe['bytes']) == (4, 4, 0, 155793058)
    assert recipe['manifestSha256'] == '7b9e2f51eb658b2eff8431b3b2fd5f003f1bfd9418e0947cd14c67ffbb12f6f2'
    assert recipe['archiveSha256'] == '904d67de3b7a57bc5cf40c8f1e6894a2445fa867bf5c65dfa1e809e8c12f041b'
    assert recipe['manifestBytes'] == 3583 and recipe['archiveBytes'] == 155801600
    assert recipe['groups'] == {'legacy-memory-rag-transport': [2, 3679161], 'legacy-windows-mcp-transport': [2, 152113897]}


def test_partial_transport_fake_apply_requires_exact_scope_helper_before_holding_four_sources(scope, partial_transport_packet, monkeypatch):
    packet = partial_transport_packet; selected, retained = fixed.select_manifest(packet.profile, packet.raw)
    assert len(selected) == 4 and retained == []
    members = [{**row, 'fingerprint': [7, index + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for index, row in enumerate(selected)]
    scope.plan.update(profile=packet.profile, manifestSha256=packet.recipe['manifestSha256'],
                      members=members, retained=retained, **fixed.residual_bindings(packet.profile))
    def guard(profile, rows):
        assert profile == packet.profile and rows == members
        scope.events.append(('partial-transport-source-guard',))
    monkeypatch.setattr(fixed, 'residual_source_guard', guard)
    result = apply(scope)
    assert result['filesDeleted'] == 4 and result['directoriesRemoved'] == 0 and result['retained'] == []
    assert scope.events[0] == ('partial-transport-source-guard',)
    scope.events.clear(); scope.plan.pop('partialTransportScopeHelperSha256')
    with pytest.raises(ValueError, match='FIXED_RESIDUAL_SOURCE_GUARD_REQUIRED'): apply(scope)
    assert scope.events == []


def test_partial_transport_selection_rejects_resealed_archive_groups_and_extra_or_protected_members(partial_transport_packet):
    packet = partial_transport_packet; original_recipe = copy.deepcopy(packet.recipe)
    for damage in ('raw', 'profile', 'catalog', 'group', 'fifth-member', 'archiveSha256', 'archiveBytes', 'protected-path'):
        value = copy.deepcopy(packet.value); packet.recipe.clear(); packet.recipe.update(original_recipe)
        if damage == 'profile': value['profile'] = 'remaining-system-data-v1'
        elif damage == 'catalog': value['catalogSha256'] = 'f' * 64
        elif damage == 'group': value['files'][0]['group'] = 'unknown-transport'
        elif damage == 'fifth-member': value['files'].append(copy.deepcopy(value['files'][0]))
        elif damage == 'archiveSha256': value['archiveSha256'] = 'f' * 64
        elif damage == 'archiveBytes': value['archiveBytes'] += 1
        elif damage == 'protected-path': value['files'][0]['sourcePath'] = fixed.ROOT + '\\work\\jenkins\\originals.tar'
        raw = json.dumps(value, sort_keys=True).encode()
        if damage == 'raw': raw += b' '
        else: packet.recipe.update(manifestSha256=fixed.sha(raw), manifestBytes=len(raw))
        with pytest.raises(ValueError): fixed.select_manifest(packet.profile, raw)


def test_residual_scope_uses_frozen_manifest_and_a_separate_metadata_only_source_guard(residual_packet, monkeypatch):
    selected, retained = fixed.select_manifest(residual_packet.profile, residual_packet.raw)
    assert len(selected) == 2 and retained == []
    seen = []
    helper = SimpleNamespace(residual_repository_guard=lambda paths: seen.extend(paths))
    monkeypatch.setattr(fixed, 'load', lambda name: helper if name == 'preserve-local-artifacts.py' else pytest.fail('unexpected helper'))
    fixed.residual_source_guard(residual_packet.profile, selected)
    assert seen == [fixed.ROOT + '\\' + row['path'].replace('/', '\\') for row in selected]
    fixed.residual_source_guard('additional-originals-v1', selected)
    assert len(seen) == 2


def test_residual_fake_apply_holds_every_original_and_obtains_fresh_custody_before_disposition(scope, residual_packet, monkeypatch):
    members = residual_plan(scope, residual_packet)
    def guard(profile, rows):
        assert profile == residual_packet.profile and rows == members
        scope.events.append(('source-metadata-guard',))
    monkeypatch.setattr(fixed, 'residual_source_guard', guard)
    result = apply(scope)
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 0
    assert scope.events[0] == ('source-metadata-guard',)
    live = next(i for i, row in enumerate(scope.events) if row[0] == 'live-ssh-proof')
    first_delete = next(i for i, row in enumerate(scope.events) if row[0] == 'delete-held')
    assert len([row for row in scope.events[:live] if row[0] == 'hash']) == 2 and live < first_delete


@pytest.mark.parametrize('why', ['guard-code-changed', 'new-foreign-repository', 'new-nested-repository'])
def test_residual_source_guard_failures_refuse_before_any_native_source_handle(scope, residual_packet, monkeypatch, why):
    residual_plan(scope, residual_packet)
    if why == 'guard-code-changed': scope.plan['residualScopeHelperSha256'] = '0' * 64
    else:
        def reject(*unused): raise ValueError('SOURCE_REPOSITORY_SCOPE_CHANGED')
        monkeypatch.setattr(fixed, 'residual_source_guard', reject)
    with pytest.raises(ValueError): apply(scope)
    assert not scope.events


@pytest.fixture
def alias_packet(packet, monkeypatch):
    profile = 'pth-aliases-v1'
    rows = [{'member': fixed.MODEL_ORIGIN_MEMBER, 'sourcePath': fixed.ROOT + r'\work\cloud\pth-model\best_stg2.pth',
             'bytes': fixed.MODEL_BYTES, 'sha256': fixed.MODEL_SHA256},
            {'member': 'uploads/other.jpg', 'sourcePath': fixed.ROOT + r'\uploads\other.jpg', 'bytes': 1, 'sha256': 'b' * 64}]
    raw = packet.seal(rows)
    recipe = {'manifestSha256': fixed.sha(raw), 'members': 2, 'selected': 2, 'bytes': fixed.MODEL_BYTES + 1, 'retained': 0}
    monkeypatch.setitem(fixed.RECIPES, profile, recipe)
    return SimpleNamespace(profile=profile, rows=rows, raw=raw, recipe=recipe, seal=packet.seal)


def test_alias_profile_derives_only_two_explicit_paths_from_exact_sealed_model_origin(alias_packet):
    selected, retained = fixed.select_manifest(alias_packet.profile, alias_packet.raw)
    assert selected == [{'path': name, 'bytes': fixed.MODEL_BYTES, 'sha256': fixed.MODEL_SHA256} for name in fixed.MODEL_ALIASES]
    assert retained == [] and all('other.jpg' not in row['path'] for row in selected)
    resolver = fixed.StrictResolver(selected)
    assert resolver('best_stg2.pth') == fixed.ROOT + r'\best_stg2.pth'
    with pytest.raises(ValueError): resolver('work/cloud/pth-model/best_stg2.pth')


@pytest.mark.parametrize('damage', ['raw-sha', 'missing-origin', 'duplicate-origin', 'wrong-source-path', 'wrong-member', 'size', 'hash'])
def test_alias_source_never_falls_back_to_a_similar_filename_or_old_alias_report(alias_packet, damage):
    if damage == 'raw-sha': alias_packet.raw += b' '
    else:
        row = alias_packet.rows[0]
        if damage == 'missing-origin': alias_packet.rows.pop(0)
        elif damage == 'duplicate-origin': alias_packet.rows.append(copy.deepcopy(row))
        elif damage == 'wrong-source-path': row['sourcePath'] = fixed.ROOT + r'\best_stg2.pth'
        elif damage == 'wrong-member': row['member'] = 'model/best_stg2.pth'
        elif damage == 'size': row['bytes'] += 1
        else: row['sha256'] = 'e' * 64
        alias_packet.raw = alias_packet.seal(alias_packet.rows); alias_packet.recipe['manifestSha256'] = fixed.sha(alias_packet.raw)
    with pytest.raises(ValueError): fixed.select_manifest(alias_packet.profile, alias_packet.raw)


@pytest.mark.parametrize('damage', ['origin', 'model-reference', 'alias-path', 'alias-hash', 'manifest', 'retained'])
def test_alias_apply_requires_closed_plan_and_current_model_reference_before_any_file_handle(scope, alias_packet, damage):
    selected, retained = fixed.select_manifest(alias_packet.profile, alias_packet.raw)
    reference = {'sourcePath': '/srv/doorhandle/models/best_stg2.pth', 'sha256': fixed.MODEL_SHA256}
    scope.proof.model_expected_reference = lambda: reference
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=alias_packet.profile, manifestSha256=alias_packet.recipe['manifestSha256'], members=members,
                      retained=retained, **fixed.alias_bindings(alias_packet.profile, scope.proof))
    if damage == 'origin': scope.plan['aliasOrigin'] = {}
    elif damage == 'model-reference': scope.plan['requiredServerModel'] = {'sourcePath': '/another/model.pth'}
    elif damage == 'alias-path': members[0]['path'] = 'uploads/unknown.pth'
    elif damage == 'alias-hash': members[0]['sha256'] = 'e' * 64
    elif damage == 'manifest': scope.plan['manifestSha256'] = 'e' * 64
    else: scope.plan['retained'] = [{'unknown': True}]
    with pytest.raises(ValueError): apply(scope)
    assert not scope.events


def test_two_aliases_cannot_be_retired_with_only_the_old_36_byte_custody_proof(scope, alias_packet, monkeypatch):
    proof = fixed.load('attest-fixed-originals.py')
    now = dt.datetime(2026, 11, 8, 0, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(proof, 'utc_now', lambda: now)
    selected, retained = fixed.select_manifest(alias_packet.profile, alias_packet.raw)
    current = {'release': 'ci-99-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
               'identity': core.IDENTITY, 'verificationReceiptSha256': 'c' * 64}
    recipe = proof.PROFILES[alias_packet.profile]
    custody = {**current, 'release': 'ci-97-' + 'd' * 12, 'commit': 'd' * 40,
        'publicReceiptSha256': 'e' * 64, 'restoreReceiptSha256': 'f' * 64,
        'manifestSha256': recipe['MANIFEST_SHA256'], 'archiveSha256': '1' * 64,
        'archiveBytes': 100, 'files': recipe['FILES'], 'bytes': recipe['ORIGINAL_BYTES']}
    members = [{**row, 'fingerprint': [7, i + 10, row['bytes'], 40, 50, 1, 0o100600, 32]} for i, row in enumerate(selected)]
    scope.plan.update(profile=alias_packet.profile, manifestSha256=alias_packet.recipe['manifestSha256'],
                      current=current, custody=custody, members=members, retained=retained,
                      **fixed.alias_bindings(alias_packet.profile, proof))
    class OldCustodyOnly:
        def fetch(self, plan, nonce):
            value = {'kind': proof.ATTESTATION_KIND, 'schemaVersion': 1, 'status': 'CUSTODY_FRESHLY_ATTESTED',
                'profile': alias_packet.profile, 'nonce': nonce, 'current': current, 'custody': custody,
                'issuedAtUtc': now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                'expiresAtUtc': (now + dt.timedelta(seconds=300)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}
            value['proofDigest'] = proof.sha(proof.encoded(value)); return value
    with pytest.raises(ValueError): fixed.apply_plan(scope.plan, core, proof, scope.backend, OldCustodyOnly(), scope.audit)
    assert len([e for e in scope.events if e[0] == 'hash']) == 2
    assert not any(e[0] == 'delete-held' for e in scope.events)


@pytest.mark.parametrize('damage', ['other-c-file', 'c-schema', 'outside-d-project', 'protected-checkout', 'jenkins', 'git',
                                  'shared-mysql', 'shared-redis', 'unc', 'traversal', 'ads', 'case-alias'])
def test_resealed_scope_changes_still_cannot_cross_project_or_shared_boundaries(packet, damage):
    replacements = {'other-c-file': r'C:\Users\19771\other.db', 'outside-d-project': r'D:\OtherProject\file.db',
        'protected-checkout': fixed.ROOT + r'\work\ecs-only-20261105\micro-followup\checkout\private.db',
        'jenkins': fixed.ROOT + r'\work\jenkins\control.db', 'git': fixed.ROOT + r'\.git\index',
        'shared-mysql': fixed.ROOT + r'\work\middlewares\mysql\data\ibdata1',
        'shared-redis': fixed.ROOT + r'\work\middlewares\redis\dump.rdb', 'unc': r'\\server\share\x.db',
        'traversal': fixed.ROOT + r'\work\x\..\private.db', 'ads': fixed.ROOT + r'\logs\x:stream'}
    if damage == 'c-schema': packet.rows[-1]['path'] = 'other/history.db'
    elif damage == 'case-alias': packet.rows[1]['sourcePath'] = packet.rows[0]['sourcePath'].upper()
    else: packet.rows[0]['sourcePath'] = replacements[damage]
    reseal(packet)
    with pytest.raises(ValueError): fixed.select_manifest(PROFILE, packet.raw)


@pytest.mark.parametrize('damage', ['omitted', 'extra', 'wrong-bytes', 'boolean-bytes', 'wrong-sha', 'new-profile'])
def test_fixed_counts_original_bytes_and_member_digests_are_closed(packet, damage):
    profile = PROFILE
    if damage == 'omitted': packet.rows.pop(0)
    elif damage == 'extra': packet.rows.append(copy.deepcopy(packet.rows[0]))
    elif damage == 'wrong-bytes': packet.rows[0]['bytes'] += 1
    elif damage == 'boolean-bytes': packet.rows[0]['bytes'] = True
    elif damage == 'wrong-sha': packet.rows[0]['sha256'] = 'not-a-sha'
    else: profile = 'unknown-expanded-profile'
    reseal(packet)
    with pytest.raises(ValueError): fixed.select_manifest(profile, packet.raw)


def test_resolver_admits_exact_members_and_lock_parents_without_cold_work_only_restriction(scope):
    resolver = fixed.StrictResolver(scope.plan['members'])
    assert resolver('memory_service/chroma_db/chroma.sqlite3') == fixed.ROOT + r'\memory_service\chroma_db\chroma.sqlite3'
    assert resolver('memory_service/chroma_db') == fixed.ROOT + r'\memory_service\chroma_db'
    assert resolver('work/middlewares/kafka-data/events') == fixed.ROOT + r'\work\middlewares\kafka-data\events'
    with pytest.raises(ValueError, match='OUTSIDE_FIXED'): resolver('memory_service/chroma_db/unknown.sqlite3')
    with pytest.raises(ValueError, match='OUTSIDE_FIXED'): resolver('best_stg2.pth')


def test_fixed_chroma_or_kafka_root_itself_can_be_held_as_parent_without_admitting_siblings():
    resolver = fixed.StrictResolver([{'path': 'work/middlewares/chroma/chroma.sqlite3'},
                                     {'path': 'work/middlewares/kafka-data/meta.properties'}])
    assert resolver('work/middlewares/chroma') == fixed.ROOT + r'\work\middlewares\chroma'
    assert resolver('work/middlewares/kafka-data') == fixed.ROOT + r'\work\middlewares\kafka-data'
    with pytest.raises(ValueError): resolver('work/middlewares/mysql')


@pytest.mark.parametrize('damage', ['fingerprint-omitted', 'zero-id', 'duplicate-id', 'size', 'hardlink', 'reparse', 'directory',
                                  'metadata-type', 'member-path', 'member-sha', 'row-extra'])
def test_plan_cannot_change_selected_files_or_invent_permissive_identity(scope, damage):
    rows = copy.deepcopy(scope.plan['members'])
    if damage == 'fingerprint-omitted': rows[0].pop('fingerprint')
    elif damage == 'zero-id': rows[0]['fingerprint'][1] = 0
    elif damage == 'duplicate-id': rows[1]['fingerprint'][:2] = rows[0]['fingerprint'][:2]
    elif damage == 'size': rows[0]['fingerprint'][2] += 1
    elif damage == 'hardlink': rows[0]['fingerprint'][5] = 2
    elif damage == 'reparse': rows[0]['fingerprint'][7] |= 0x400
    elif damage == 'directory': rows[0]['fingerprint'][6] = 0o40700
    elif damage == 'metadata-type': rows[0]['fingerprint'][3] = True
    elif damage == 'member-path': rows[0]['path'] = 'uploads/unknown.jpg'
    elif damage == 'member-sha': rows[0]['sha256'] = 'e' * 64
    else: rows[0]['allowMissing'] = True
    with pytest.raises(ValueError): fixed.validate_observations(scope.selected, rows)


def test_all_fresh_hashes_and_live_proof_precede_first_delete_and_no_directory_is_removed(scope):
    def hold(value):
        assert value['directories'] == []
        assert all(not str(r['path']).lower().startswith('c:') for r in value['members'])
        return FakeBackend.hold(scope.backend, value)
    scope.backend.hold = hold
    result = apply(scope)
    first = next(i for i, event in enumerate(scope.events) if event[0] == 'delete-held')
    assert len([e for e in scope.events[:first] if e[0] == 'hash']) == 2
    assert len([e for e in scope.events[:first] if e[0] == 'live-ssh-proof']) == 1
    assert scope.events[first - 2][0:2] == ('audit', 'FILE_DELETE_INTENT') and scope.events[first - 1][0] == 'verify'
    assert result['filesDeleted'] == 2 and result['directoriesRemoved'] == 0 and result['allDirectoriesRetained']
    assert result['retained'] == scope.plan['retained']
    assert not any(e[0] == 'empty-dir-held' for e in scope.events)


@pytest.mark.parametrize('damage', ['hash', 'tracked', 'active', 'open-owner', 'identity', 'missing-current', 'missing-custody', 'ssh', 'proof'])
def test_preflight_failure_never_deletes_any_original(scope, damage):
    if damage == 'hash': scope.backend.fail_hash = scope.plan['members'][-1]['path']
    elif damage == 'tracked': scope.backend.tracked.add(scope.plan['members'][0]['path'].lower())
    elif damage == 'active': scope.backend.active_references = lambda _: fixed.need(False, 'ACTIVE_OWNER')
    elif damage == 'open-owner': scope.backend.hold = lambda _: fixed.need(False, 'ACTIVE_HANDLE')
    elif damage == 'identity': scope.backend.fail_verify = scope.plan['members'][0]['path']
    elif damage == 'missing-current': scope.plan['current'] = None
    elif damage == 'missing-custody': scope.plan['custody'] = None
    elif damage == 'ssh': scope.attestor.failure = True
    else: scope.attestor.damage = True
    with pytest.raises(ValueError): apply(scope)
    assert not any(e[0] in ('delete-held', 'empty-dir-held') for e in scope.events)


def test_owned_partial_disposition_retains_remaining_files_and_prohibits_replay(scope):
    scope.backend.fail_delete = scope.plan['members'][1]['path']
    with pytest.raises(ValueError): apply(scope)
    event = [e[2] for e in scope.events if e[0:2] == ('audit', 'PARTIAL_OR_REFUSED')][-1]
    assert event['confirmedFilesDeleted'] == 1 and event['fileDispositionAttempts'] == 2
    assert event['unconfirmedFileDispositions'] == 1 and not event['automaticResumeAllowed']
    assert not scope.backend.held


def test_plan_observes_all_identities_and_hashes_but_never_deletes_or_fetches_cloud(scope, packet, tmp_path, monkeypatch):
    manifest = tmp_path / 'synthetic-manifest.json'; manifest.write_bytes(packet.raw)
    monkeypatch.setattr(core, 'canonical_control', lambda path: Path(path))
    monkeypatch.setattr(fixed, 'observed_members', lambda *args: scope.plan['members'])
    monkeypatch.setattr(fixed, 'code_bindings', lambda *args: {'executorSha256': 'e' * 64})
    cold = SimpleNamespace(); proof = SimpleNamespace()
    plan = fixed.make_plan(PROFILE, manifest, None, None, core, cold, proof, lambda resolver: scope.backend)
    assert plan['status'] == 'PLAN_ONLY' and plan['originalFilesDeleted'] == 0 and plan['directoriesRemoved'] == 0
    assert len([event for event in scope.events if event[0] == 'hash']) == 2
    assert not any(event[0] in ('delete-held', 'empty-dir-held', 'live-ssh-proof') for event in scope.events)
    assert plan['current'] is None and plan['custody'] is None


@pytest.mark.parametrize('damage', ['plan-bytes', 'source-code', 'cloud-anchor', 'member-id'])
def test_apply_rechecks_reviewed_plan_source_and_cloud_bindings_before_native_backend(scope, packet, tmp_path, monkeypatch, damage):
    manifest = tmp_path / 'synthetic-manifest.json'; manifest.write_bytes(packet.raw)
    monkeypatch.setattr(core, 'canonical_control', lambda path: Path(path))
    monkeypatch.setattr(fixed, 'observed_members', lambda *args: scope.plan['members'])
    monkeypatch.setattr(fixed, 'code_bindings', lambda *args: {'executorSha256': 'e' * 64})
    monkeypatch.setattr(fixed, 'bindings', lambda *args: (scope.plan['current'], scope.plan['custody']))
    plan = fixed.make_plan(PROFILE, manifest, 'current', 'custody', core, SimpleNamespace(), SimpleNamespace(), lambda resolver: scope.backend)
    submitted = copy.deepcopy(plan)
    if damage == 'source-code': submitted['executorSha256'] = 'f' * 64
    elif damage == 'cloud-anchor': submitted['custody']['release'] = 'ci-1-' + 'd' * 12
    elif damage == 'member-id': submitted['members'][0]['fingerprint'][1] = 0
    monkeypatch.setattr(core, 'control', lambda _: (submitted, 'a' * 64))
    args = SimpleNamespace(plan='ignored', plan_sha256='b' * 64 if damage == 'plan-bytes' else 'a' * 64,
                           profile=PROFILE, manifest=manifest, current_receipt='current', custody_receipt='custody')
    with pytest.raises(ValueError): fixed.load_plan(args, core, SimpleNamespace(), SimpleNamespace())
    assert not any(event[0] == 'delete-held' for event in scope.events)


def test_refresh_after_intent_stall_preserves_fixed_bindings_and_remaining_exclusive_handles(scope, monkeypatch):
    origin = scope.proof.now; shifted = []
    monkeypatch.setattr(core.time, 'monotonic', lambda: (scope.proof.now - origin).total_seconds())
    def callback(event):
        if event == 'FILE_DELETE_INTENT' and not shifted:
            shifted.append(True); scope.proof.now += dt.timedelta(seconds=301)
    scope.audit.callback = callback
    assert apply(scope)['filesDeleted'] == 2
    assert len([e for e in scope.events if e[0] == 'live-ssh-proof']) == 2
    assert len([e for e in scope.events if e[0] == 'held-all']) == 1


def test_new_attestor_uses_fixed_original_helper_without_copying_ssh_transport(scope, tmp_path, monkeypatch):
    dummy = tmp_path / 'dummy'; dummy.write_bytes(b'not a key')
    profile = PROFILE; scope.proof.PROFILES = {profile: {'SNAPSHOT': 'legacy-source-snapshot'}}
    args = SimpleNamespace(profile=profile, ssh_host='192.0.2.10', ssh_user='ecs-user', ssh_port=22,
        ssh_key=dummy, known_hosts=dummy, remote_root='/home/ecs-user/doorhandle-ci')
    scope.plan['attestationHelperSha256'] = 'e' * 64; nonce = '9' * 64; calls = []
    from tests_python.test_local_cold_retirement import proof_for
    monkeypatch.setattr(core, 'canonical_control', lambda path: path)
    monkeypatch.setattr(core.shutil, 'which', lambda _: 'ssh')
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=core.encoded(proof_for(scope.plan, nonce, scope.proof.now)) + b'\n')
    monkeypatch.setattr(core.subprocess, 'run', run)
    result = core.LiveAttestor(scope.proof, args, helper_name='attest-fixed-originals.py').fetch(scope.plan, nonce)
    assert result['nonce'] == nonce and 'attest-fixed-originals.py' in calls[0][-1]
    assert scope.plan['attestationHelperSha256'] in calls[0][-1]
    assert 'StrictHostKeyChecking=yes' in calls[0] and 'GlobalKnownHostsFile=NUL' in calls[0]
    with pytest.raises(ValueError, match='FIXED_ATTESTATION_HELPER'): core.LiveAttestor(scope.proof, args, helper_name='../unreviewed.py')


def test_held_source_resolver_default_is_unchanged_and_custom_resolver_is_explicit():
    cold = fixed.load('preserve-cold-stores.py')
    assert cold.HeldSources({'members': []}).source_resolver is cold.safe_source
    resolver = lambda name: Path('/not-opened') / name
    assert cold.HeldSources({'members': []}, source_resolver=resolver).source_resolver is resolver
    with pytest.raises(Exception, match='EXPLICIT_SOURCE_RESOLVER'): cold.HeldSources({'members': []}, source_resolver=True)


def test_explicit_resolver_is_used_by_real_opaque_source_reader_on_ecs(tmp_path, monkeypatch):
    cold = fixed.load('preserve-cold-stores.py')
    source = tmp_path / 'opaque-original.bin'; body = b'opaque original bytes'; source.write_bytes(body)
    row = {'path': 'uploads/opaque-original.bin', 'bytes': len(body), 'sha256': fixed.sha(body),
           'fingerprint': cold.fingerprint(source.stat())}
    monkeypatch.setattr(cold, 'safe_source', lambda _: pytest.fail('A reviewed explicit resolver must be used'))
    resolver = lambda name: source if name == row['path'] else pytest.fail('Unknown source requested')
    with cold.HeldSources({'members': [row]}, source_resolver=resolver) as held:
        reader = held.reader(row['path']); assert reader.read(4096) == body and reader.read(4096) == b''
        held.verify_one(row)
        assert reader.bytes == len(body) and reader.checksum.hexdigest() == row['sha256']
    assert source.read_bytes() == body


def test_windows_backend_forwards_custom_resolver_and_delete_access_to_original_holder(tmp_path, monkeypatch):
    source = tmp_path / 'uploads/opaque.bin'; source.parent.mkdir(); source.write_bytes(b'opaque')
    fingerprint = fixed.load('preserve-cold-stores.py').fingerprint(source.stat())
    fingerprint[7] = 0  # Ordinary-file fixture without the read-only attribute.
    value = {'members': [{'path': 'uploads/opaque.bin', 'bytes': 6, 'sha256': fixed.sha(b'opaque'),
                          'fingerprint': fingerprint}], 'directories': []}
    resolver = lambda name: str(tmp_path / name)
    seen = []; closed = []
    @contextmanager
    def holder(actual, **options):
        seen.append((actual, options)); yield SimpleNamespace()
    backend = core.WindowsBackend.__new__(core.WindowsBackend)
    backend.cold = SimpleNamespace(HeldSources=holder)
    backend.source_resolver = resolver; backend.custom_source_resolver = True; backend.directories = {}
    backend.api = SimpleNamespace(CreateFileW=lambda *args: len(seen) + len(closed) + 123,
                                  CloseHandle=lambda handle: closed.append(handle) or 1)
    backend.final_path = lambda *args: None; backend.verify_file = lambda row: None
    monkeypatch.setattr(core, 'PROJECT_ROOT', str(tmp_path))
    with backend.hold(value): assert len(seen) == 1
    assert seen[0][0] is value and seen[0][1] == {'delete_access': True, 'source_resolver': resolver}
    assert closed and not backend.directories


def test_linux_cannot_enter_real_plan_or_apply_native_backend(capsys):
    assert fixed.os.name != 'nt'
    assert fixed.main(['--profile', PROFILE, '--manifest', 'not-opened', '--output', 'not-created']) == 1
    assert json.loads(capsys.readouterr().err)['status'] == 'REFUSED_OR_PARTIAL'


@pytest.fixture
def model_links(tmp_path, monkeypatch):
    root = tmp_path / 'project'; origin = root / fixed.MODEL_ORIGIN_MEMBER
    origin.parent.mkdir(parents=True); body = b'opaque fixed model fixture'; origin.write_bytes(body)
    alias = root / fixed.MODEL_ALIASES[0]; os.link(origin, alias)
    monkeypatch.setattr(fixed, 'ROOT', str(root))
    monkeypatch.setattr(fixed, 'MODEL_BYTES', len(body)); monkeypatch.setattr(fixed, 'MODEL_SHA256', fixed.sha(body))
    cold = fixed.load('preserve-cold-stores.py'); native_fingerprint = cold.fingerprint
    creation = origin.stat().st_ctime_ns
    def windows_creation_fingerprint(info):
        result = native_fingerprint(info)
        # Windows stores creation time at index 4. Linux ctime changes when a
        # link is removed; model only that Windows field in this ECS fixture.
        result[4] = creation
        return result
    monkeypatch.setattr(cold, 'fingerprint', windows_creation_fingerprint)
    resolver = lambda name: str(root / name)
    selected = [{'path': fixed.MODEL_ORIGIN_MEMBER, 'bytes': len(body), 'sha256': fixed.sha(body)}]
    profile = 'additional-originals-v1'
    members = fixed.observed_members(selected, cold, resolver, profile)
    group = fixed.observe_model_link_group(profile, members, cold, resolver)
    return SimpleNamespace(root=root, origin=origin, alias=alias, body=body, cold=cold, resolver=resolver,
                           profile=profile, selected=selected, members=members, group=group)


def test_fixed_model_group_binds_both_distinct_names_and_the_same_complete_two_link_identity(model_links):
    value = model_links
    fixed.validate_observations(value.selected, value.members, value.profile, value.group)
    assert value.group['source'] == fixed.MODEL_ORIGIN_MEMBER
    assert value.group['retained']['path'] == fixed.MODEL_ALIASES[0]
    assert value.group['retained']['fingerprint'] == value.members[0]['fingerprint']
    assert value.members[0]['fingerprint'][5] == 2 and value.origin.exists() and value.alias.exists()


@pytest.mark.parametrize('profile', [None, PROFILE, 'residual-project-originals-v1', 'pth-aliases-v1'])
def test_other_profiles_never_admit_the_model_two_link_source(model_links, profile):
    with pytest.raises(ValueError):
        fixed.observed_members(model_links.selected, model_links.cold, model_links.resolver, profile)


@pytest.mark.parametrize('damage', ['third-link', 'alias-replaced', 'alias-symlink', 'alias-missing', 'alias-renamed'])
def test_changed_or_unknown_model_link_topology_refuses_under_the_existing_hold_before_any_delete(model_links, damage):
    value = model_links
    if damage == 'third-link': os.link(value.origin, value.root / 'unknown.pth')
    elif damage == 'alias-renamed': value.alias.rename(value.root / 'unknown.pth')
    else:
        value.alias.unlink()
        if damage == 'alias-replaced': value.alias.write_bytes(value.body)
        elif damage == 'alias-symlink': value.alias.symlink_to(value.origin)
    events = []; backend = FakeBackend(events)
    with backend.hold(fixed.value_for(value.members)):
        with pytest.raises((ValueError, OSError)):
            fixed.verify_model_link_group(value.group, value.members, value.cold, value.resolver, backend)
    assert not any(row[0] == 'delete-held' for row in events)
    assert value.origin.exists()


@pytest.mark.parametrize('damage', ['missing-group', 'extra-key', 'wrong-source', 'wrong-retained-path',
                                  'retained-id', 'retained-hash', 'retained-count', 'source-count'])
def test_reviewed_group_cannot_admit_unbound_names_identity_or_unknown_links(model_links, damage):
    value = model_links; group = copy.deepcopy(value.group); members = copy.deepcopy(value.members)
    if damage == 'missing-group': group = None
    elif damage == 'extra-key': group['allowUnknownLinks'] = True
    elif damage == 'wrong-source': group['source'] = 'uploads/another.pth'
    elif damage == 'wrong-retained-path': group['retained']['path'] = fixed.MODEL_ALIASES[1]
    elif damage == 'retained-id': group['retained']['fingerprint'][1] += 1
    elif damage == 'retained-hash': group['retained']['sha256'] = 'e' * 64
    elif damage == 'retained-count': group['retained']['fingerprint'][5] = 3
    else: members[0]['fingerprint'][5] = 3
    with pytest.raises(ValueError):
        fixed.validate_observations(value.selected, members, value.profile, group)


def test_plan_records_live_closed_group_and_rechecks_it_while_sources_are_held(model_links, packet, tmp_path, monkeypatch):
    value = model_links
    raw = packet.seal([{'sourcePath': str(value.origin), 'bytes': len(value.body), 'sha256': fixed.sha(value.body)}])
    monkeypatch.setitem(fixed.RECIPES, value.profile, {'manifestSha256': fixed.sha(raw), 'members': 1,
        'selected': 1, 'bytes': len(value.body), 'retained': 0})
    manifest = tmp_path / 'model-manifest.json'; manifest.write_bytes(raw)
    monkeypatch.setattr(core, 'canonical_control', lambda path: Path(path))
    monkeypatch.setattr(fixed, 'StrictResolver', lambda *args: value.resolver)
    monkeypatch.setattr(fixed, 'code_bindings', lambda *args: {'executorSha256': 'e' * 64})
    events = []; backend = FakeBackend(events)
    plan = fixed.make_plan(value.profile, manifest, None, None, core, value.cold, SimpleNamespace(), lambda _: backend)
    assert plan['closedModelHardlinkGroup'] == value.group and plan['members'] == value.members
    assert plan['originalFilesDeleted'] == 0 and plan['retained'] == []
    assert len([row for row in events if row[0] == 'hash']) == 1
    assert not any(row[0] in ('delete-held', 'live-ssh-proof') for row in events)


def test_fixed_source_disposition_preserves_root_alias_as_one_link_before_separate_alias_retirement(model_links, scope, monkeypatch):
    value = model_links
    scope.plan.update(profile=value.profile, members=value.members, closedModelHardlinkGroup=value.group, retained=[])
    monkeypatch.setattr(fixed, 'StrictResolver', lambda *args: value.resolver)
    scope.backend.cold = value.cold
    original_delete = scope.backend.delete_file
    def remove_selected_name(row):
        original_delete(row); Path(value.resolver(row['path'])).unlink()
    scope.backend.delete_file = remove_selected_name
    result = apply(scope)
    assert result['filesDeleted'] == 1 and result['retainedModelLink'] == {'path': fixed.MODEL_ALIASES[0], 'remainingLinks': 1}
    assert not value.origin.exists() and value.alias.read_bytes() == value.body and value.alias.stat().st_nlink == 1
    first_delete = next(i for i, row in enumerate(scope.events) if row[0] == 'delete-held')
    assert any(row[0] == 'hash' for row in scope.events[:first_delete])
    assert any(row[0] == 'live-ssh-proof' for row in scope.events[:first_delete])
    assert any(row[0:2] == ('audit', 'MODEL_ALIAS_RETAINED') for row in scope.events)
    alias_rows = [{'path': fixed.MODEL_ALIASES[0], 'bytes': len(value.body), 'sha256': fixed.sha(value.body)}]
    assert fixed.observed_members(alias_rows, value.cold, value.resolver, 'pth-aliases-v1')[0]['fingerprint'][5] == 1


def test_group_metadata_delay_after_intent_requires_new_live_proof_before_any_disposition(model_links, scope, monkeypatch):
    value = model_links
    scope.plan.update(profile=value.profile, members=value.members, closedModelHardlinkGroup=value.group, retained=[])
    monkeypatch.setattr(fixed, 'StrictResolver', lambda *args: value.resolver)
    scope.backend.cold = value.cold; original = fixed.verify_model_link_group; calls = []
    def delayed(*args):
        original(*args); calls.append(True)
        if len(calls) == 4:
            scope.proof.now += dt.timedelta(seconds=301); scope.attestor.failure = True
    monkeypatch.setattr(fixed, 'verify_model_link_group', delayed)
    with pytest.raises(ValueError, match='AUTHENTICATED_LIVE_SERVER_ATTESTATION_REQUIRED'): apply(scope)
    partial = [event[2] for event in scope.events if event[:2] == ('audit', 'PARTIAL_OR_REFUSED')][-1]
    assert partial['confirmedFilesDeleted'] == partial['fileDispositionAttempts'] == 0
    assert not any(event[0] == 'delete-held' for event in scope.events)
    assert value.origin.exists() and value.alias.exists()


@pytest.mark.parametrize('damage', ['new-third-name', 'source-name-recreated'])
def test_post_disposition_uncertainty_reports_the_confirmed_source_name_and_keeps_remaining_names(model_links, scope, monkeypatch, damage):
    value = model_links
    scope.plan.update(profile=value.profile, members=value.members, closedModelHardlinkGroup=value.group, retained=[])
    monkeypatch.setattr(fixed, 'StrictResolver', lambda *args: value.resolver)
    scope.backend.cold = value.cold; original_delete = scope.backend.delete_file
    def remove_and_observe_change(row):
        original_delete(row); value.origin.unlink()
        if damage == 'new-third-name': os.link(value.alias, value.root / 'new-unknown.pth')
        else: value.origin.write_bytes(value.body)
    scope.backend.delete_file = remove_and_observe_change
    with pytest.raises(ValueError): apply(scope)
    partial = [event[2] for event in scope.events if event[:2] == ('audit', 'PARTIAL_OR_REFUSED')][-1]
    assert partial['confirmedFilesDeleted'] == partial['fileDispositionAttempts'] == 1
    assert partial['unconfirmedFileDispositions'] == 0 and partial['automaticResumeAllowed'] is False
    assert value.alias.read_bytes() == value.body
    assert not any(event[:2] == ('audit', 'COMPLETED') for event in scope.events)


def test_alias_profile_must_not_remove_root_link_before_the_additional_source(model_links):
    value = model_links
    aliases = [{'path': fixed.MODEL_ALIASES[0], 'bytes': len(value.body), 'sha256': fixed.sha(value.body)}]
    with pytest.raises(ValueError, match='RETIRE_ADDITIONAL_MODEL_ORIGIN_BEFORE_ALIASES'):
        fixed.observed_members(aliases, value.cold, value.resolver, 'pth-aliases-v1')
    assert value.origin.exists() and value.alias.exists()


def test_real_active_reference_scan_resolves_only_the_declared_retained_alias_without_adding_a_delete_member(model_links, monkeypatch):
    value = model_links; resolver = fixed.StrictResolver(value.members, value.group)
    backend = core.WindowsBackend.__new__(core.WindowsBackend); backend.source_resolver = resolver
    calls = []
    def process_scan(command, **options):
        calls.append((command, options)); return SimpleNamespace(returncode=0, stdout=b'[]')
    monkeypatch.setattr(core.subprocess, 'run', process_scan)
    backend.active_references(fixed.value_for(value.members + [value.group['retained']]))
    assert len(calls) == 1 and calls[0][0][0] == 'powershell.exe'
    assert fixed.MODEL_ALIASES[0] in resolver.retained and fixed.MODEL_ALIASES[0] not in resolver.members
    assert [row['path'] for row in value.members] == [fixed.MODEL_ORIGIN_MEMBER]
    with pytest.raises(ValueError, match='OUTSIDE_FIXED_SELECTED_FILES'): resolver('unknown.pth')


@pytest.mark.parametrize('error, code', [(ValueError('ORIGINAL_FILE_ID_OR_SIZE_NOT_ESTABLISHED'), 'ORIGINAL_FILE_ID_OR_SIZE_NOT_ESTABLISHED'),
    (ValueError('A' * 128), 'A' * 128), (ValueError('A' * 129), None),
    (ValueError(r'C:\private\secret.db'), None), (ValueError('lowercase detail'), None),
    (OSError('ORIGINAL_FILE_ID_OR_SIZE_NOT_ESTABLISHED'), None)])
def test_public_failure_exposes_only_bounded_authored_valueerror_codes(error, code):
    result = fixed.public_failure(error)
    assert result.get('errorCode') == code and result['errorType'] == type(error).__name__
    assert result['automaticResumeAllowed'] is False and result['scopeExpanded'] is False
    if code is None: assert 'errorCode' not in result and 'private' not in json.dumps(result)
