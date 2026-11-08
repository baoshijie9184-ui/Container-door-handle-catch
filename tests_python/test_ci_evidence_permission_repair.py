"""Synthetic ECS filesystem contracts; no cloud, application or database access."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


repair = load('registered_ci_permissions_contract', ROOT / 'script/jenkins/repair-ci-evidence-permissions.py')
support = load('registered_ci_permissions_fixture_support', ROOT / 'tests_python/test_jenkins_ecs_build_cleanup.py')


@pytest.fixture
def state(tmp_path, monkeypatch):
    value = support.state.__wrapped__(tmp_path, monkeypatch)
    helpers = {'script/jenkins/' + name: (ROOT / 'script/jenkins' / name).read_bytes() for name in repair.OLD_CLOSURE}
    support.package(value.inbox / 'source.tar.gz', helpers, value.record['commit'])
    for name, raw in helpers.items(): support.put(value.checkout / name, raw)
    source_sha = support.cleanup.digest(value.inbox / 'source.tar.gz')
    value.record.update(status='PASS', verificationExitCode=0, sourceSha256=source_sha)
    inner_path = value.evidence / 'receipt.json'; inner = json.loads(inner_path.read_bytes())
    inner['status'] = 'PASS'; inner['commands'][0]['exitCode'] = 0; support.put_json(inner_path, inner)
    for path in (value.manifest, value.evidence / 'tool-runtime.json', value.attempt / '.verification-claimed/claim.json'):
        body = json.loads(path.read_bytes()); body['sourceSha256'] = source_sha; support.put_json(path, body)
    tools_path = value.evidence / 'tool-runtime.json'; tools = json.loads(tools_path.read_bytes())
    tools['manifestSha256'] = tools['cleanup']['manifestSha256'] = support.cleanup.digest(value.manifest)
    support.put_json(tools_path, tools)
    support.seal(value)
    # Isolate this fixture from the runner's umask. The only permission defects
    # are the explicit registered leaf and two Java ancestors below.
    for parent, dirs, files in os.walk(value.root):
        Path(parent).chmod(0o700)
        for name in files: (Path(parent) / name).chmod(0o600)
    value.xml = value.evidence / value.reports[-1][8:]; value.xml.chmod(0o644)
    targets = [inner_path, value.evidence / 'java', value.xml.parent.parent]
    value.changes = []
    for path in targets:
        directory = path.is_dir(); path.chmod(0o775 if directory else 0o664)
        value.changes.append(dict(path=path.relative_to(value.root).as_posix(), directory=directory,
                                  beforeMode=0o775 if directory else 0o664,
                                  afterMode=0o700 if directory else 0o600, nlink=path.stat().st_nlink))
    value.entry = {k: copy.deepcopy(value.record[k]) for k in ('release', 'commit', 'sourceSha256', 'attempt', 'identity', 'reportFiles')}
    value.entry.update(verificationReceiptSha256=support.cleanup.digest(value.attempt / 'verification-receipt.json'),
                       toolManifestSha256=support.cleanup.digest(value.manifest),
                       evidenceArchiveSha256=support.cleanup.digest(value.archive), evidenceArchiveBytes=value.archive.stat().st_size,
                       changes=value.changes)
    monkeypatch.setattr(support.cleanup, 'docker_snapshot', lambda: [])
    monkeypatch.setattr(support.cleanup, 'process_references', lambda checkout: None)
    return value


def execute(state, *, apply=False, audit=None):
    return repair.repair_entry(state.root, state.entry, support.IDENTITY, support.remote,
                               support.cleanup, apply=apply, audit=audit)


def modes(state):
    return {row['path']: (state.root / row['path']).stat().st_mode & 0o7777 for row in state.changes}


def test_default_plan_reads_complete_original_proofs_and_changes_nothing(state):
    before = support.preserved_bytes(state); permissions = modes(state); audit = {}
    result = execute(state, audit=audit)
    assert result == {'status': 'PLANNED', 'changedPaths': [row['path'] for row in state.changes]}
    assert audit['preflight'] == 'PASS' and audit['originalReportFiles'] == len(state.reports)
    assert support.preserved_bytes(state) == before and modes(state) == permissions
    assert state.xml.stat().st_mode & 0o777 == 0o644


def test_apply_tightens_only_registered_paths_preserves_all_bytes_and_is_idempotent(state):
    before = support.preserved_bytes(state); audit = {}
    result = execute(state, apply=True, audit=audit)
    assert result['status'] == 'REPAIRED' and len(result['changedPaths']) == 3
    assert modes(state) == {r['path']: r['afterMode'] for r in state.changes}
    assert support.preserved_bytes(state) == before and state.xml.stat().st_mode & 0o777 == 0o644
    assert all(row['after'] and (row['sha256Before'] is None or row['sha256Before'] == row['sha256After'])
               for row in audit['targets'])
    assert execute(state, apply=True) == {'status': 'NO_ACTION', 'changedPaths': []}


@pytest.mark.parametrize('which', ['receipt', 'report', 'archive', 'source', 'claim', 'manifest', 'helper'])
def test_any_original_byte_drift_refuses_before_the_first_chmod(state, which, monkeypatch):
    path = {'receipt': state.attempt / 'verification-receipt.json', 'report': state.xml,
            'archive': state.archive, 'source': state.inbox / 'source.tar.gz',
            'claim': state.attempt / '.verification-claimed/claim.json', 'manifest': state.manifest,
            'helper': state.checkout / 'script/jenkins/preserve-cold-stores.py'}[which]
    path.write_bytes(path.read_bytes() + b'changed')
    before = modes(state)
    monkeypatch.setattr(repair.os, 'fchmod', lambda *unused: pytest.fail('chmod before full admission'))
    with pytest.raises(Exception): execute(state, apply=True)
    assert modes(state) == before


@pytest.mark.parametrize('damage', ['symlink-leaf', 'hardlink-leaf', 'symlink-directory', 'unknown-mode', 'unregistered-writable', 'directory-membership'])
def test_metadata_links_and_unknown_writable_paths_are_rejected(state, damage, monkeypatch):
    leaf = state.evidence / 'receipt.json'
    if damage == 'symlink-leaf':
        saved = state.root / 'saved-receipt'; leaf.rename(saved); leaf.symlink_to(saved)
    elif damage == 'hardlink-leaf': os.link(leaf, state.root / 'unregistered-link')
    elif damage == 'symlink-directory':
        saved = state.evidence / 'saved-java'; (state.evidence / 'java').rename(saved); (state.evidence / 'java').symlink_to(saved, target_is_directory=True)
    elif damage == 'unknown-mode': leaf.chmod(0o666)
    elif damage == 'unregistered-writable': state.xml.chmod(0o664)
    else: (state.evidence / 'java/unreviewed-child').mkdir()
    monkeypatch.setattr(repair.os, 'fchmod', lambda *unused: pytest.fail('chmod before metadata admission'))
    with pytest.raises(Exception): execute(state, apply=True)


def test_foreign_uid_refused_on_held_descriptor(state, monkeypatch):
    original = repair.os.fstat; target = (state.evidence / 'receipt.json').stat().st_ino
    def fstat(fd):
        info = original(fd)
        if info.st_ino != target: return info
        fields = list(info); fields[4] = os.getuid() + 1
        return os.stat_result(fields)
    monkeypatch.setattr(repair.os, 'fstat', fstat)
    with pytest.raises(ValueError, match='UID_CHANGED'): execute(state, apply=True)


@pytest.mark.parametrize('owner', ['release', 'token', 'bind-mount', 'process'])
def test_live_producer_or_container_owner_blocks_every_change(state, owner, monkeypatch):
    if owner == 'process':
        def active(unused): raise ValueError('ACTIVE_PROCESS_REFERENCES_OLD_CHECKOUT')
        monkeypatch.setattr(support.cleanup, 'process_references', active)
    else:
        row = ['fixture', True, False, 20, None, None, []]
        if owner == 'release': row[4] = state.entry['release']
        elif owner == 'token': row[5] = 'b' * 24
        else: row[6] = [{'Type': 'bind', 'Source': str(state.checkout)}]
        monkeypatch.setattr(support.cleanup, 'docker_snapshot', lambda: [row])
    before = modes(state)
    with pytest.raises(ValueError): execute(state, apply=True)
    assert modes(state) == before


@pytest.mark.parametrize('field', ['identity', 'attempt', 'verificationReceiptSha256', 'toolManifestSha256', 'reportFiles'])
def test_registered_context_and_full_catalog_cannot_be_substituted(state, field):
    if field == 'identity': state.entry[field] = {**support.IDENTITY, 'instanceId': 'i-other'}
    elif field == 'reportFiles': state.entry[field] = state.entry[field][:-1]
    else: state.entry[field] = '0' * len(state.entry[field])
    before = modes(state)
    with pytest.raises(Exception): execute(state, apply=True)
    assert modes(state) == before


def test_path_replacement_after_all_preflight_rejected_without_chmod(state, monkeypatch):
    original = repair.old_preflight
    def replace(*args):
        result = original(*args)
        path = state.evidence / 'receipt.json'; raw = path.read_bytes()
        saved = state.evidence / 'replacement'; support.put(saved, raw); saved.chmod(0o664); saved.replace(path)
        return result
    monkeypatch.setattr(repair, 'old_preflight', replace)
    monkeypatch.setattr(repair.os, 'fchmod', lambda *unused: pytest.fail('chmod after path replacement'))
    # Replacement also changes ancestor metadata, which may be rejected first.
    with pytest.raises(ValueError, match=r'^HELD_(?:METADATA_CHANGED|PATH_REPLACED)$'): execute(state, apply=True)


def test_last_preflight_failure_cannot_partially_tighten_earlier_targets(state, monkeypatch):
    original = support.cleanup.quiescent; calls = 0
    def quiescent(*args):
        nonlocal calls
        calls += 1
        if calls == 2: raise ValueError('LATE_ACTIVE_PRODUCER')
        return original(*args)
    monkeypatch.setattr(support.cleanup, 'quiescent', quiescent)
    before = modes(state)
    with pytest.raises(ValueError, match='LATE_ACTIVE'): execute(state, apply=True)
    assert modes(state) == before


def test_source_commit_and_recipe_closure_checked_against_original_archive(state):
    with repair.HeldTree(state.root, state.changes) as tree:
        with pytest.raises(ValueError, match='CLOSURE_INCOMPLETE'):
            repair.source_closure(tree, state.entry['release'], 'f' * 40, state.entry['sourceSha256'], repair.OLD_CLOSURE)


def test_versioned_registration_is_exactly_the_reviewed_97_inventory():
    value = json.loads((ROOT / 'script/jenkins' / repair.REGISTRY).read_bytes())
    entry = repair.validate_registry(value)
    assert entry['release'] == 'ci-97-abedbf81a73d' and len(entry['reportFiles']) == 223
    assert sum(not row['directory'] for row in entry['changes']) == 9
    assert sum(row['directory'] for row in entry['changes']) == 12
    assert entry['verificationReceiptSha256'] == 'c0f8f89f48516c3e5346f6c0aee6721cf2a8cccd6c2235ffcf4e5f9e6f948c70'


@pytest.mark.parametrize('damage', ['missing-report', 'unknown-path', 'widened-mode', 'duplicate-target'])
def test_registration_cannot_widen_the_reviewed_scope(damage):
    value = json.loads((ROOT / 'script/jenkins' / repair.REGISTRY).read_bytes()); entry = value['releases'][0]
    if damage == 'missing-report': entry['reportFiles'].pop()
    elif damage == 'unknown-path': entry['changes'][0]['path'] = 'verification/ci-other/checkout/work/data'
    elif damage == 'widened-mode': entry['changes'][0]['afterMode'] = 0o644
    else: entry['changes'][-1] = entry['changes'][0]
    with pytest.raises(ValueError): repair.validate_registry(value)


@pytest.fixture
def invocation(state, monkeypatch):
    current = state.root / 'verification' / support.CURRENT / 'checkout'; work = current / 'work'
    work.mkdir(parents=True, mode=0o700)
    for path in (current.parent, current, work): path.chmod(0o700)
    args = SimpleNamespace(tag=support.CURRENT, commit='c' * 40, source_sha256='d' * 64,
        verification_receipt_sha256='e' * 64, output=str(work / 'old-evidence-permissions'),
        prior_tag=[state.entry['release']], apply=False)
    monkeypatch.setattr(repair, 'current_context', lambda args: (state.root, current, support.IDENTITY,
        support.remote, support.cleanup, state.entry))
    return args


def test_public_raw_sha_is_detached_and_audit_is_private(state, invocation):
    result = repair.run(invocation); output = Path(invocation.output)
    public = json.loads((output / 'public.json').read_bytes()); audit = json.loads((output / 'audit.json').read_bytes())
    assert 'reportSha256' not in public and result['reportSha256'] == repair.sha((output / 'public.json').read_bytes())
    assert public['auditSha256'] == repair.sha((output / 'audit.json').read_bytes())
    assert result['status'] == audit['status'] == 'PLANNED' and result['originalReportBytesChanged'] is False
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())


def test_unregistered_prior_is_no_action_and_does_not_probe_97(state, invocation, monkeypatch):
    invocation.prior_tag = ['ci-71-' + 'f' * 12]
    monkeypatch.setattr(repair, 'repair_entry', lambda *a, **kw: pytest.fail('unregistered tag probed'))
    result = repair.run(invocation)
    assert result['status'] == 'NO_ACTION' and result['changedPaths'] == [] and result['reason'] == 'UNREGISTERED_PRIOR_TAG'


def test_reused_output_never_overwrites_audit(state, invocation):
    repair.run(invocation); output = Path(invocation.output); raw = (output / 'audit.json').read_bytes()
    with pytest.raises(ValueError, match='FRESH_CURRENT'): repair.run(invocation)
    assert (output / 'audit.json').read_bytes() == raw


def test_failed_preflight_writes_failure_audit_and_leaves_report_modes(state, invocation):
    state.xml.write_bytes(b'drift'); invocation.apply = True; before = modes(state)
    with pytest.raises(ValueError): repair.run(invocation)
    audit = json.loads((Path(invocation.output) / 'audit.json').read_bytes())
    assert audit['status'] == 'FAILED' and audit['changedPaths'] == [] and modes(state) == before
    assert not (Path(invocation.output) / 'public.json').exists()


@pytest.fixture
def current_checkout(state, monkeypatch):
    tag = support.CURRENT; checkout = state.root / 'verification' / tag / 'checkout'
    helpers = {'script/jenkins/' + name: (ROOT / 'script/jenkins' / name).read_bytes() for name in repair.CLOSURE}
    for name, raw in helpers.items(): support.put(checkout / name, raw)
    source = state.root / 'inbox' / tag / 'source.tar.gz'; support.package(source, helpers, 'c' * 40)
    raw_receipt = support.put_json(checkout.parent / 'verification-receipt.json', {'synthetic': 'current raw marker'})
    for tree_root in (checkout.parent, source.parent):
        for parent, dirs, files in os.walk(tree_root): Path(parent).chmod(0o700)
    args = SimpleNamespace(root=str(state.root), tag=tag, commit='c' * 40,
        source_sha256=support.cleanup.digest(source), instance_id=support.IDENTITY['instanceId'],
        machine_id=support.IDENTITY['machineId'], verification_receipt_sha256=support.cleanup.digest(raw_receipt),
        plan=str(checkout / 'script/jenkins' / repair.REGISTRY))
    record = dict(scope='source', commit=args.commit, sourceSha256=args.source_sha256)
    def stopped(root, tag, observed, verifier, cleanup, current):
        assert current and root == state.root and tag == args.tag and observed == support.IDENTITY
        return record, support.cleanup.digest(raw_receipt)
    cold = SimpleNamespace(fixed_modules=lambda args: (SimpleNamespace(identity=lambda instance, machine: support.IDENTITY),
        support.remote, support.cleanup, checkout), stopped_receipt=stopped)
    monkeypatch.setattr(repair, 'SELF', checkout / 'script/jenkins/repair-ci-evidence-permissions.py')
    monkeypatch.setattr(repair, 'load', lambda name: cold)
    return SimpleNamespace(args=args, checkout=checkout, record=record, raw_receipt=raw_receipt, source=source)


@pytest.mark.skipif(os.getuid() != 1000, reason='actual ECS executor UID is required for current CLI admission')
@pytest.mark.parametrize('scope', ['source', 'mysql'])
def test_current_fixed_source_closure_is_admitted_before_trusted_module_load(current_checkout, scope):
    current_checkout.record['scope'] = scope
    result = repair.current_context(current_checkout.args)
    assert result[1] == current_checkout.checkout and result[2] == support.IDENTITY


@pytest.mark.skipif(os.getuid() != 1000, reason='actual ECS executor UID is required for current CLI admission')
@pytest.mark.parametrize('damage', ['registry', 'helper', 'raw-sha', 'raw-mode', 'current-commit', 'current-source', 'current-scope'])
def test_current_closure_and_actual_pass_binding_cannot_be_substituted(current_checkout, damage):
    value = current_checkout
    if damage in ('registry', 'helper'):
        path = value.checkout / 'script/jenkins' / (repair.REGISTRY if damage == 'registry' else 'repair-ci-evidence-permissions.py')
        path.write_bytes(path.read_bytes() + b'changed')
    elif damage == 'raw-sha': value.args.verification_receipt_sha256 = '0' * 64
    elif damage == 'raw-mode': value.raw_receipt.chmod(0o644)
    else: value.record[{'current-commit': 'commit', 'current-source': 'sourceSha256', 'current-scope': 'scope'}[damage]] = 'wrong'
    with pytest.raises(ValueError): repair.current_context(value.args)


@pytest.mark.parametrize('prior', [support.CURRENT, 'ci-99-' + 'f' * 12])
def test_equal_or_newer_build_is_never_an_old_repair_target(state, invocation, prior, monkeypatch):
    invocation.prior_tag = [prior]
    monkeypatch.setattr(repair, 'repair_entry', lambda *a, **kw: pytest.fail('non-prior repair attempted'))
    with pytest.raises(ValueError, match='EARLIER_PRIOR'): repair.run(invocation)
    assert not (Path(invocation.output) / 'public.json').exists()


def test_every_chmod_has_a_durable_intent_and_final_audit_binds_journal(state, invocation, monkeypatch):
    invocation.apply = True; output = Path(invocation.output)
    original_chmod, original_sync = repair.os.fchmod, repair.os.fsync
    last_synced_inode = None; intents = []
    def fsync(fd):
        nonlocal last_synced_inode
        original_sync(fd); last_synced_inode = os.fstat(fd).st_ino
    def fchmod(fd, mode):
        journal = output / 'audit.jsonl'; events = [json.loads(line) for line in journal.read_bytes().splitlines()]
        assert events[0]['phase'] == 'PREFLIGHT' and events[-1]['phase'] == 'INTENT'
        assert last_synced_inode == journal.stat().st_ino
        intents.append(events[-1]['path']); original_chmod(fd, mode)
    monkeypatch.setattr(repair.os, 'fsync', fsync); monkeypatch.setattr(repair.os, 'fchmod', fchmod)
    result = repair.run(invocation); audit = json.loads((output / 'audit.json').read_bytes())
    events = [json.loads(line) for line in (output / 'audit.jsonl').read_bytes().splitlines()]
    assert result['status'] == 'REPAIRED' and intents == result['changedPaths']
    assert len([row for row in events if row['phase'] == 'AFTER']) == len(state.changes)
    assert events[-1]['phase'] == 'FINISHED' and audit['journalSha256'] == repair.sha((output / 'audit.jsonl').read_bytes())


def test_interruption_after_chmod_retains_intent_and_next_explicit_attempt_revalidates(state, invocation, monkeypatch):
    invocation.apply = True; original = repair.os.fchmod
    def interrupted(fd, mode):
        original(fd, mode)
        raise KeyboardInterrupt('synthetic interruption immediately after syscall')
    monkeypatch.setattr(repair.os, 'fchmod', interrupted)
    with pytest.raises(KeyboardInterrupt): repair.run(invocation)
    output = Path(invocation.output); audit = json.loads((output / 'audit.json').read_bytes())
    events = [json.loads(line) for line in (output / 'audit.jsonl').read_bytes().splitlines()]
    first = state.changes[0]['path']
    assert audit['status'] == 'FAILED' and audit['pendingIntent'] == first
    assert [row['path'] for row in events if row['phase'] == 'INTENT'] == [first]
    assert not any(row['phase'] == 'AFTER' for row in events)
    assert not (output / 'public.json').exists() and (state.root / first).stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(repair.os, 'fchmod', original)
    invocation.output = str(output.with_name('old-evidence-permissions-next'))
    result = repair.run(invocation)
    assert result['status'] == 'REPAIRED' and first not in result['changedPaths']
    assert modes(state) == {row['path']: row['afterMode'] for row in state.changes}


def test_replacement_while_durable_intent_is_written_refuses_before_chmod(state, monkeypatch):
    def journal(event):
        if event['phase'] != 'INTENT': return
        path = state.root / event['path']; saved = state.root / 'replacement-during-intent'
        support.put(saved, path.read_bytes()); saved.chmod(0o664); saved.replace(path)
    monkeypatch.setattr(repair.os, 'fchmod', lambda *unused: pytest.fail('chmod after INTENT path replacement'))
    with pytest.raises(ValueError, match=r'^HELD_(?:METADATA_CHANGED|PATH_REPLACED)$'):
        repair.repair_entry(state.root, state.entry, support.IDENTITY, support.remote, support.cleanup,
                            apply=True, journal=journal)


def run_controller_registry_reader(tmp_path, registry, *, damage=None):
    """Run the exact source-byte reader embedded in the controller, only on ECS."""
    script = (ROOT / 'script/jenkins/repair-ci-evidence-permissions.ps1').read_text(encoding='utf8')
    reader = script.split("$reader = @'\n", 1)[1].split("\n'@", 1)[0]
    commit = 'c' * 40; helper = b'raise RuntimeError("Project helpers must not be imported by a metadata reader")\n'
    raw = json.dumps(registry, sort_keys=True).encode() if type(registry) is dict else registry
    members = [('script/jenkins/repair-ci-evidence-permissions.py', helper),
               ('script/jenkins/ci-evidence-permission-repairs.json', raw)]
    if damage == 'missing-helper': members.pop(0)
    if damage == 'missing-registry': members.pop()
    if damage == 'duplicate-helper': members.append(members[0])
    if damage == 'duplicate-registry': members.append(members[1])
    if damage == 'oversize-registry': members[1] = (members[1][0], raw + b' ' * (1024 * 1024 + 1 - len(raw)))
    archive = tmp_path / 'source.tar.gz'
    with tarfile.open(archive, 'x:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={} if damage == 'missing-commit' else {'comment': 'd' * 40 if damage == 'wrong-commit' else commit}) as package:
        for name, body in members:
            row = tarfile.TarInfo(name); row.size = len(body)
            if damage in ('symlink-registry', 'hardlink-registry', 'contiguous-registry') and name.endswith('.json'):
                row.type = {'symlink-registry': tarfile.SYMTYPE, 'hardlink-registry': tarfile.LNKTYPE,
                            'contiguous-registry': tarfile.CONTTYPE}[damage]
                row.linkname = 'script/jenkins/repair-ci-evidence-permissions.py'
            package.addfile(row, io.BytesIO(body))
    result = subprocess.run([sys.executable, '-I', '-B', '-c', reader, str(archive), commit],
                            env={}, capture_output=True, timeout=10)
    return result, helper, raw


def selector_registry():
    return {'schema': 1, 'kind': 'doorhandle-registered-ci-permission-repairs', 'releases': [
        {'release': 'ci-97-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64}]}


@pytest.mark.parametrize('source', ['closed-metadata', 'actual-fixed-registry'])
def test_controller_reader_only_projects_fixed_registry_tags_and_source_member_hashes(tmp_path, source):
    registry = selector_registry() if source == 'closed-metadata' else json.loads((ROOT / 'script/jenkins/ci-evidence-permission-repairs.json').read_bytes())
    result, helper, raw = run_controller_registry_reader(tmp_path, registry)
    assert result.returncode == 0 and not result.stderr
    value = json.loads(result.stdout)
    assert set(value) == {'sha256', 'registrySha256', 'registeredTags'}
    assert value['sha256'] == hashlib.sha256(helper).hexdigest() and value['registrySha256'] == hashlib.sha256(raw).hexdigest()
    assert value['registeredTags'] == [entry['release'] for entry in registry['releases']]
    # Native references to a newer private source are not permission exceptions.
    assert not set(value['registeredTags']).intersection({'ci-110-' + 'b' * 12})
    assert set(value['registeredTags']).intersection({registry['releases'][0]['release']})
    assert len(result.stdout) < 8192 and b'Project helpers must not be imported' not in result.stdout


@pytest.mark.parametrize('damage', ['missing-helper', 'missing-registry', 'duplicate-helper', 'duplicate-registry',
    'oversize-registry', 'symlink-registry', 'hardlink-registry', 'contiguous-registry', 'missing-commit', 'wrong-commit'])
def test_controller_reader_refuses_nonunique_nonregular_unbounded_or_foreign_source_members(tmp_path, damage):
    result, _, _ = run_controller_registry_reader(tmp_path, selector_registry(), damage=damage)
    assert result.returncode != 0 and not result.stdout
    expected = b'Fixed repair members or commit missing' if damage in ('missing-helper', 'missing-registry', 'missing-commit', 'wrong-commit') else b'Unique regular bounded repair members required'
    assert expected in result.stderr


@pytest.mark.parametrize('damage', ['duplicate-root-key', 'duplicate-entry-key', 'schema-bool', 'schema-string', 'kind',
    'extra-root-key', 'missing-releases', 'releases-object', 'empty-releases', 'duplicate-release', 'release-type',
    'tag', 'commit-type', 'commit', 'prefix', 'source-sha', 'nonfinite'])
def test_controller_selector_rejects_ambiguous_or_untyped_registry_identity_before_skipping(tmp_path, damage):
    value = selector_registry()
    if damage == 'schema-bool': value['schema'] = True
    if damage == 'schema-string': value['schema'] = '1'
    if damage == 'kind': value['kind'] = 'another-registry'
    if damage == 'extra-root-key': value['unknown'] = True
    if damage == 'missing-releases': del value['releases']
    if damage == 'releases-object': value['releases'] = {}
    if damage == 'empty-releases': value['releases'] = []
    if damage == 'duplicate-release': value['releases'].append(copy.deepcopy(value['releases'][0]))
    if damage == 'release-type': value['releases'][0] = 'not-an-entry'
    if damage == 'tag': value['releases'][0]['release'] = 'ci-97-' + 'A' * 12
    if damage == 'commit-type': value['releases'][0]['commit'] = None
    if damage == 'commit': value['releases'][0]['commit'] = 'a' * 39
    if damage == 'prefix': value['releases'][0]['commit'] = 'f' * 40
    if damage == 'source-sha': value['releases'][0]['sourceSha256'] = 'not-a-digest'
    if damage == 'nonfinite': value['releases'][0]['unknown'] = float('nan')
    raw = json.dumps(value, sort_keys=True).encode()
    if damage == 'duplicate-root-key': raw = raw.replace(b'"schema": 1', b'"schema": 1, "schema": 1')
    if damage == 'duplicate-entry-key': raw = raw.replace(b'"commit": "', b'"commit": "' + b'a' * 40 + b'", "commit": "', 1)
    result, _, _ = run_controller_registry_reader(tmp_path, raw)
    assert result.returncode != 0 and not result.stdout
    if damage in ('duplicate-root-key', 'duplicate-entry-key'):
        assert b'Repeated registry JSON key' in result.stderr
