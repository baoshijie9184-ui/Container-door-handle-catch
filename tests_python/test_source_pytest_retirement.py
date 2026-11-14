"""Direct contracts for retiring the sixteen explicitly authorized pytest roots.

These cases use only pytest-owned synthetic filesystem objects on ECS. They do
not start an application, a container, a cloud operation, or another test run.
"""
import ast
import builtins
import copy
import errno
import importlib.util
import io
import os
from pathlib import Path
import re
import socket
import stat
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'source_pytest_retirement_direct_contract', ROOT / 'script/jenkins/retire-source-pytest.py')
retirement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retirement)

APPROVED_BUILDS = (100, 102, 103, 104, 105, 107, 109, 110,
                   114, 120, 122, 150, 178, 180, 215, 217)


def put(path, raw=b'synthetic pytest temporary data', mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    path.chmod(mode)
    return path


def target_for(root, release=None):
    release = release or retirement.EXACT_RELEASES[0]
    return root / 'verification' / release / 'checkout/work/ci-evidence/tmp/pytest'


def remove(root, target, planned, events, unlinks=None):
    return retirement.remove_owned_tree(root, target.relative_to(root).as_posix(),
                                        planned, events.append, unlinks)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / 'synthetic-ci'
    target = target_for(root)
    target.mkdir(parents=True, mode=0o700)
    return SimpleNamespace(root=root, target=target)


@pytest.fixture
def readonly_directory():
    """Retain fixture-only directory FDs so even a failed assertion can restore cleanup access."""
    descriptors = []
    fchmod = os.fchmod
    def restrict(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        assert info.st_uid == os.getuid() and stat.S_ISDIR(info.st_mode)
        descriptors.append((descriptor, stat.S_IMODE(info.st_mode)))
        fchmod(descriptor, stat.S_IMODE(info.st_mode) & ~stat.S_IWUSR)
    try:
        yield restrict
    finally:
        for descriptor, mode in reversed(descriptors):
            try: fchmod(descriptor, mode | stat.S_IWUSR)
            finally: os.close(descriptor)


def metadata_rows(path):
    paths = [path] + list(path.rglob('*'))
    return {item.relative_to(path).as_posix(): item.lstat() for item in paths}


def fake_stat(monkeypatch, victim, **changes):
    """Change metadata for one real fixture inode without requiring root/mounts."""
    wanted = victim.lstat()
    def wrap(function):
        def changed(*args, **kwargs):
            info = function(*args, **kwargs)
            if (info.st_dev, info.st_ino) == (wanted.st_dev, wanted.st_ino):
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
                fields.update(changes)
                return SimpleNamespace(**fields)
            return info
        return changed
    for name in ('stat', 'lstat', 'fstat'):
        monkeypatch.setattr(retirement.os, name, wrap(getattr(os, name)))


def deny_data_reads(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Temporary object contents must never be read')
    monkeypatch.setattr(builtins, 'open', forbidden)
    monkeypatch.setattr(io, 'open', forbidden)
    monkeypatch.setattr(retirement.os, 'read', forbidden)
    monkeypatch.setattr(retirement.os, 'pread', forbidden)


def test_exact_release_set_is_the_sixteen_user_approved_builds():
    assert type(retirement.EXACT_RELEASES) is tuple
    assert len(retirement.EXACT_RELEASES) == len(set(retirement.EXACT_RELEASES)) == 16
    assert tuple(int(value.split('-')[1]) for value in retirement.EXACT_RELEASES) == APPROVED_BUILDS
    assert not {225, 229, 266} & set(APPROVED_BUILDS)


def test_metadata_preserves_original_nine_field_contract(tree):
    info = put(tree.target / 'fixture').lstat()
    assert retirement.metadata(info) == [info.st_mode, info.st_uid, info.st_gid, info.st_size,
        info.st_mtime_ns, info.st_ino, info.st_dev, info.st_ctime_ns, info.st_nlink]


def test_inventory_covers_regular_sparse_hardlinks_links_fifo_socket_and_readonly_directory(
        tree, tmp_path, readonly_directory):
    external = put(tmp_path / 'outside-original', b'outside original', 0o400)
    os.link(external, tree.target / 'hardlink-one')
    os.link(external, tree.target / 'hardlink-two')
    regular = put(tree.target / 'readonly/regular', b'owned data', 0o400)
    with (tree.target / 'sparse').open('wb') as stream:
        stream.seek(64 * 1024 ** 2)
        stream.write(b'x')
    (tree.target / 'outside-link').symlink_to(external)
    (tree.target / 'dangling-link').symlink_to(tmp_path / 'missing-outside')
    os.mkfifo(tree.target / 'fifo', 0o600)
    descriptor = os.open(tree.target, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
            # /proc/self/fd avoids the AF_UNIX path-length limit of pytest roots.
            endpoint.bind('/proc/self/fd/' + str(descriptor) + '/socket')
            readonly_directory(regular.parent)
            expected = metadata_rows(tree.target)
            value = retirement.inventory(tree.target)
    finally:
        os.close(descriptor)
    rows = {row['path']: row['metadata'] for row in value['entries']}
    assert value['rootMetadata'] == retirement.metadata(expected['.'])
    assert rows == {name: retirement.metadata(info) for name, info in expected.items() if name != '.'}
    assert value['entryCount'] == len(rows)
    unique = {(info.st_dev, info.st_ino): info for info in expected.values()}
    assert value['allocatedBytes'] == sum(info.st_blocks * 512 for info in unique.values())
    assert len(unique) == len(expected) - 1
    assert (tree.target / 'sparse').stat().st_size > (tree.target / 'sparse').stat().st_blocks * 512
    assert external.read_bytes() == b'outside original'


def test_inventory_and_removal_never_read_temporary_object_bodies(tree, monkeypatch):
    put(tree.target / 'file')
    with (tree.target / 'sparse').open('wb') as stream:
        stream.seek(64 * 1024 ** 2)
        stream.write(b'x')
    os.mkfifo(tree.target / 'fifo', 0o600)
    (tree.target / 'dangling-link').symlink_to(tree.root / 'missing')
    descriptor = os.open(tree.target, os.O_RDONLY | os.O_DIRECTORY)
    events = []
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
            endpoint.bind('/proc/self/fd/' + str(descriptor) + '/socket')
            with monkeypatch.context() as context:
                deny_data_reads(context)
                planned = retirement.inventory(tree.target)
                remove(tree.root, tree.target, planned, events)
    finally:
        os.close(descriptor)
    assert not tree.target.exists()
    assert any(row['phase'] == 'UNLINK' for row in events)


def test_removal_adds_write_only_to_owned_target_directories_and_preserves_external_links(
        tree, tmp_path, monkeypatch, readonly_directory):
    external_dir = tmp_path / 'outside'
    external = put(external_dir / 'original', b'preserved external bytes', 0o400)
    readonly_directory(external_dir)
    owned = put(tree.target / 'readonly/owned-file', mode=0o400)
    os.link(external, owned.parent / 'outside-hardlink')
    (tree.target / 'outside-link').symlink_to(external_dir, target_is_directory=True)
    readonly_directory(owned.parent)
    readonly_directory(tree.target)
    external_before = external.lstat()
    external_dir_before = external_dir.lstat()
    parent_before = tree.target.parent.lstat()
    allowed = {(path.stat().st_dev, path.stat().st_ino) for path in (tree.target, owned.parent)}
    original_chmod, original_fchmod, original_stat = os.chmod, os.fchmod, os.stat
    changed = []
    def check(info):
        assert stat.S_ISDIR(info.st_mode), 'Retirement must not change file permissions'
        assert (info.st_dev, info.st_ino) in allowed, 'Only target directories may gain owner write'
        changed.append((info.st_dev, info.st_ino))
    def chmod(path, mode, *args, **kwargs):
        if isinstance(path, int):
            check(os.fstat(path))
        else:
            check(original_stat(path, dir_fd=kwargs.get('dir_fd'), follow_symlinks=False))
        return original_chmod(path, mode, *args, **kwargs)
    def fchmod(descriptor, mode):
        check(os.fstat(descriptor))
        return original_fchmod(descriptor, mode)
    planned = retirement.inventory(tree.target)
    events = []
    with monkeypatch.context() as context:
        context.setattr(retirement.os, 'chmod', chmod)
        context.setattr(retirement.os, 'fchmod', fchmod)
        remove(tree.root, tree.target, planned, events)
    assert not tree.target.exists()
    assert changed and set(changed) == allowed
    assert external.read_bytes() == b'preserved external bytes'
    after = external.lstat()
    for name in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns'):
        assert getattr(after, name) == getattr(external_before, name)
    assert after.st_nlink == external_before.st_nlink - 1
    assert retirement.metadata(external_dir.lstat()) == retirement.metadata(external_dir_before)
    assert stat.S_IMODE(tree.target.parent.stat().st_mode) == stat.S_IMODE(parent_before.st_mode)
    assert any(row['phase'] == 'OWNER_WRITE_ADDED' for row in events)


def test_shared_unlink_ledger_allows_original_plan_across_two_exact_roots(tree, tmp_path):
    second = target_for(tree.root, retirement.EXACT_RELEASES[1])
    second.mkdir(parents=True, mode=0o700)
    external = put(tmp_path / 'hardlink-original', b'unchanged external original', 0o400)
    os.link(external, tree.target / 'one')
    os.link(external, second / 'two')
    os.link(external, second / 'three')
    first_plan = retirement.inventory(tree.target)
    second_plan = retirement.inventory(second)
    before = external.lstat()
    unlinks, events = {}, []
    remove(tree.root, tree.target, first_plan, events, unlinks)
    remove(tree.root, second, second_plan, events, unlinks)
    assert not tree.target.exists() and not second.exists()
    assert external.read_bytes() == b'unchanged external original'
    assert external.stat().st_mode == before.st_mode
    assert external.stat().st_nlink == before.st_nlink - 3
    assert unlinks[(before.st_dev, before.st_ino)]['count'] == 3
    assert unlinks[(before.st_dev, before.st_ino)]['metadata'] == retirement.metadata(external.lstat())


@pytest.mark.parametrize('change', ['foreign-owner', 'cross-filesystem', 'character-device', 'block-device'])
@pytest.mark.parametrize('victim_kind', ['root', 'child'])
def test_inventory_refuses_foreign_owner_cross_device_and_device_nodes(tree, monkeypatch, change, victim_kind):
    child = put(tree.target / 'file')
    victim = tree.target if victim_kind == 'root' else child
    info = victim.lstat()
    changes = {'foreign-owner': {'st_uid': os.getuid() + 1},
        'cross-filesystem': {'st_dev': info.st_dev + 1},
        'character-device': {'st_mode': stat.S_IFCHR | 0o600},
        'block-device': {'st_mode': stat.S_IFBLK | 0o600}}[change]
    with monkeypatch.context() as context:
        fake_stat(context, victim, **changes)
        with pytest.raises(ValueError):
            retirement.inventory(tree.target)
    assert child.read_bytes() == b'synthetic pytest temporary data'


@pytest.mark.parametrize('mutation', ['new-entry', 'content', 'mode', 'inode', 'root-swap', 'root-symlink'])
def test_changed_inventory_or_replaced_root_refuses_before_any_unlink(tree, mutation):
    payload = put(tree.target / 'payload', b'original bytes')
    planned = retirement.inventory(tree.target)
    if mutation == 'new-entry':
        put(tree.target / 'unexpected')
    elif mutation == 'content':
        before = payload.stat()
        payload.write_bytes(b'modified bytes')
        os.utime(payload, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    elif mutation == 'mode':
        payload.chmod(0o400)
    elif mutation == 'inode':
        replacement = put(tree.target / 'replacement', b'original bytes')
        replacement.replace(payload)
    elif mutation == 'root-swap':
        tree.target.rename(tree.target.with_name('original-pytest'))
        payload = put(tree.target / 'new-root-payload')
    else:
        tree.target.rename(tree.target.with_name('original-pytest'))
        payload = put(tree.root / 'outside-root/preserved')
        tree.target.symlink_to(payload.parent, target_is_directory=True)
    events = []
    with pytest.raises(ValueError):
        remove(tree.root, tree.target, planned, events)
    assert payload.exists()
    assert not any(row['phase'] in ('UNLINK', 'RMDIR') for row in events)


@pytest.mark.parametrize('relative', [
    'verification/ci-225-aaaaaaaaaaaa/checkout/work/ci-evidence/tmp/pytest',
    'verification/ci-229-aaaaaaaaaaaa/checkout/work/ci-evidence/tmp/pytest',
    'verification/ci-266-aaaaaaaaaaaa/checkout/work/ci-evidence/tmp/pytest',
    'verification/ci-999-aaaaaaaaaaaa/checkout/work/ci-evidence/tmp/pytest',
    'checkout/work/ci-evidence/tmp/pytest', 'arbitrary-directory',
])
def test_protected_or_unapproved_releases_and_arbitrary_directories_are_not_targets(tmp_path, relative):
    root = tmp_path / 'synthetic-ci'
    target = root / relative
    payload = put(target / 'keep', b'not authorized')
    planned = retirement.inventory(target)
    events = []
    with pytest.raises(ValueError):
        retirement.remove_owned_tree(root, relative, planned, events.append)
    assert payload.read_bytes() == b'not authorized'
    assert events == []


@pytest.mark.parametrize('location', ['root', 'checkout', 'work', 'evidence', 'tmp', 'case', 'sibling'])
def test_exact_release_does_not_authorize_ancestors_descendants_or_siblings(tree, location):
    paths = {'root': tree.root, 'checkout': tree.target.parents[3],
        'work': tree.target.parents[2], 'evidence': tree.target.parents[1],
        'tmp': tree.target.parent, 'case': tree.target / 'test_case',
        'sibling': tree.target.with_name('pytest-other')}
    target = paths[location]
    payload = put(target / 'keep')
    planned = retirement.inventory(target)
    events = []
    with pytest.raises(ValueError):
        remove(tree.root, target, planned, events)
    assert payload.exists()
    assert events == []


@pytest.mark.parametrize('alteration', ['absolute', 'leading-dot', 'double-slash', 'parent', 'trailing-slash'])
def test_noncanonical_target_spelling_cannot_expand_exact_path_authorization(tree, alteration):
    payload = put(tree.target / 'keep')
    planned = retirement.inventory(tree.target)
    relative = tree.target.relative_to(tree.root).as_posix()
    target = {'absolute': str(tree.target), 'leading-dot': './' + relative,
        'double-slash': relative.replace('/checkout/', '//checkout/'),
        'parent': relative + '/../pytest', 'trailing-slash': relative + '/'}[alteration]
    events = []
    with pytest.raises(ValueError):
        retirement.remove_owned_tree(tree.root, target, planned, events.append)
    assert payload.exists()
    assert events == []


def test_inventory_refuses_a_symbolic_link_as_its_root(tree):
    payload = put(tree.root / 'outside/preserved', b'outside data')
    tree.target.rmdir()
    tree.target.symlink_to(payload.parent, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        retirement.inventory(tree.target)
    assert payload.read_bytes() == b'outside data'


def test_partial_deletion_keeps_success_journal_and_restores_remaining_directory_modes(
        tree, monkeypatch, readonly_directory):
    first = put(tree.target / 'readonly/a', mode=0o400)
    second = put(tree.target / 'readonly/b', mode=0o400)
    readonly_directory(first.parent)
    readonly_directory(tree.target)
    modes = {path: stat.S_IMODE(path.stat().st_mode) for path in (tree.target, first.parent)}
    planned = retirement.inventory(tree.target)
    original_unlink = os.unlink
    calls, events = [], []
    def fail_second(path, *args, **kwargs):
        calls.append(str(path))
        if len(calls) == 2:
            raise OSError(errno.EIO, 'synthetic partial unlink failure')
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(retirement.os, 'unlink', fail_second)
        with pytest.raises(OSError, match='synthetic partial unlink failure'):
            remove(tree.root, tree.target, planned, events)
    assert len(calls) == 2
    assert sum(path.exists() for path in (first, second)) == 1
    assert tree.target.exists()
    assert {path: stat.S_IMODE(path.stat().st_mode) for path in modes} == modes
    assert len([row for row in events if row['phase'] == 'UNLINK']) == 1
    assert any(row['phase'] == 'OWNER_MODE_RESTORED' for row in events)


@pytest.mark.parametrize('changed_index', [0, 1, 2, 3, 4, 5, 6])
def test_own_hardlink_unlinks_do_not_excuse_other_metadata_changes(changed_index):
    expected = [stat.S_IFREG | 0o400, os.getuid(), os.getgid(), 100, 200, 300, 400, 500, 3]
    observed = expected.copy()
    observed[7], observed[8] = 501, 2
    actual = observed.copy()
    actual[changed_index] += 1
    ledger = {(400, 300): {'count': 1, 'metadata': observed}}
    assert not retirement.same_metadata(actual, expected, ledger)


@pytest.mark.parametrize('links,ctime,owned_unlinks,observed_ctime,accepted', [
    (3, 500, 0, 500, True), (2, 501, 1, 501, True), (1, 502, 2, 502, True),
    (2, 501, 0, 500, False), (1, 502, 1, 501, False), (3, 501, 0, 500, False),
    (3, 501, 1, 501, False), (4, 501, 1, 501, False),
    (2, 502, 1, 501, False),
])
def test_hardlink_metadata_accepts_only_exact_post_unlink_metadata(
        links, ctime, owned_unlinks, observed_ctime, accepted):
    expected = [stat.S_IFREG | 0o400, os.getuid(), os.getgid(), 100, 200, 300, 400, 500, 3]
    actual = expected.copy()
    actual[7], actual[8] = ctime, links
    observed = expected.copy()
    observed[7], observed[8] = observed_ctime, expected[8] - owned_unlinks
    ledger = {(400, 300): {'count': owned_unlinks, 'metadata': observed}} if owned_unlinks else {}
    assert bool(retirement.same_metadata(actual, expected, ledger)) is accepted


def test_count_only_ledger_cannot_authorize_a_hardlink_ctime_change():
    expected = [stat.S_IFREG | 0o400, os.getuid(), os.getgid(), 100, 200, 300, 400, 500, 3]
    actual = expected.copy()
    actual[7], actual[8] = 501, 2
    assert not retirement.same_metadata(actual, expected, {(400, 300): 1})


@pytest.fixture
def authorization():
    return {'schemaVersion': 1,
        'kind': 'doorhandle-exact-source-pytest-temporary-retirement-authorization',
        'source': 'USER_EXPLICIT_MESSAGE', 'answer': retirement.USER_ANSWER,
        'branch': 'java-cloud', 'job': 'doorhandle-java', 'root': str(retirement.ROOT),
        'identity': copy.deepcopy(retirement.IDENTITY), 'actorUid': 1000,
        'exactBuilds': list(retirement.EXACT_BUILDS),
        'entries': copy.deepcopy(retirement.APPROVED_ENTRIES), 'excludedBuilds': [225, 229, 266],
        'allowArbitraryPath': False, 'allowFutureBuilds': False, 'allowDiskExpansion': False,
        'allowRootTargetMutations': False, 'allowOwnerWriteForOwnedTargetDirectories': True,
        'authorizationEndsWhenExactTargetsConsumed': True,
        'requiredConditions': copy.deepcopy(retirement.REQUIRED_CONDITIONS),
        'alwaysPreserve': copy.deepcopy(retirement.ALWAYS_PRESERVE),
        'grantedAtUtc': '2026-11-14T04:00:00+00:00'}


def test_authorization_accepts_the_static_exact_user_scope_without_private_files(authorization):
    assert retirement.validate_authorization(authorization) == authorization['entries']


@pytest.mark.parametrize('field,value', [
    ('schemaVersion', 2), ('kind', 'ordinary-cleanup-request'), ('source', 'ASSUMED_CONSENT'),
    ('answer', 'different answer'), ('branch', 'other-branch'), ('job', 'other-job'),
    ('root', '/unapproved-ci-root'), ('identity', {}), ('actorUid', 1001),
    ('excludedBuilds', [225, 229]), ('allowArbitraryPath', True), ('allowFutureBuilds', True),
    ('allowDiskExpansion', True), ('allowRootTargetMutations', True),
    ('allowOwnerWriteForOwnedTargetDirectories', False),
    ('authorizationEndsWhenExactTargetsConsumed', False),
    ('requiredConditions', []), ('alwaysPreserve', []), ('grantedAtUtc', ''),
])
def test_authorization_refuses_changed_identity_expanded_powers_or_lost_conditions(authorization, field, value):
    authorization[field] = value
    with pytest.raises(ValueError):
        retirement.validate_authorization(authorization)


@pytest.mark.parametrize('mutation', ['missing-build', 'extra-build', 'missing-entry', 'extra-entry',
                                     'release', 'path', 'source-proof'])
def test_authorization_requires_the_code_bound_exact_builds_paths_and_original_source_proofs(
        authorization, mutation):
    if mutation == 'missing-build':
        authorization['exactBuilds'].pop()
    elif mutation == 'extra-build':
        authorization['exactBuilds'].append(225)
    elif mutation == 'missing-entry':
        authorization['entries'].pop()
    elif mutation == 'extra-entry':
        authorization['entries'].append(copy.deepcopy(authorization['entries'][0]))
    elif mutation == 'release':
        authorization['entries'][0]['release'] = 'ci-266-aaaaaaaaaaaa'
    elif mutation == 'path':
        authorization['entries'][0]['path'] = 'verification/unapproved/checkout/work'
    else:
        authorization['entries'][0]['sourceProof'] = {}
    with pytest.raises(ValueError):
        retirement.validate_authorization(authorization)


@pytest.fixture
def status_attempt(tmp_path, monkeypatch):
    args = SimpleNamespace(tag='ci-301-' + 'a' * 12, commit='a' * 40,
        source_sha256='b' * 64, authorization_sha256='c' * 64, plan_sha256='e' * 64)
    folder = tmp_path / 'owned-retirement-status'
    folder.mkdir(mode=0o700)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Status must not issue/replay work, write controls, or invoke a process')
    for name in ('write_json', 'make_plan', 'apply'):
        monkeypatch.setattr(retirement, name, forbidden)
    monkeypatch.setattr(retirement.subprocess, 'run', forbidden)
    return SimpleNamespace(args=args, folder=folder, current=retirement.context(args))


def control(attempt, name, value):
    return put(attempt.folder / name, retirement.encoded(value))


def process_identity(monkeypatch, state, pid=7654321):
    calls = []
    def start(actual):
        assert actual == pid, 'Only the original claimed PID may be checked'
        calls.append(actual)
        if state == 'gone':
            raise ProcessLookupError('synthetic original process has ended')
        return 'original-ticks' if state == 'same' else 'different-ticks'
    monkeypatch.setattr(retirement, 'process_start', start)
    return calls


def test_status_context_binds_fixed_source_authorization_identity_and_preservation(status_attempt):
    args = status_attempt.args
    assert status_attempt.current == {'batch': retirement.BATCH, 'release': args.tag,
        'commit': args.commit, 'sourceSha256': args.source_sha256,
        'authorizationSha256': args.authorization_sha256, 'identity': retirement.IDENTITY,
        'sourceSqlAndReportsRetained': True, 'businessDatabaseUntouched': True,
        'excludedBuilds': [225, 229, 266], 'testsExecuted': False}


@pytest.mark.parametrize('outcome', ['COMPLETE', 'PARTIAL_FAILURE'])
def test_status_accepts_only_original_context_bound_terminal_receipt(status_attempt, monkeypatch, outcome):
    control(status_attempt, 'receipt.json', {**status_attempt.current, 'status': outcome})
    def unexpected_pid_probe(_pid):
        raise AssertionError('A sealed terminal receipt does not need a live process probe')
    monkeypatch.setattr(retirement, 'process_start', unexpected_pid_probe)
    result = retirement.status(status_attempt.args, status_attempt.folder)
    assert all(result[key] == value for key, value in status_attempt.current.items())
    assert result['status'] == outcome and result['terminal'] is True


@pytest.mark.parametrize('field,value', [
    ('batch', 'another-batch'), ('release', 'ci-302-' + 'd' * 12), ('commit', 'd' * 40),
    ('sourceSha256', 'd' * 64), ('authorizationSha256', 'd' * 64), ('identity', {}),
    ('sourceSqlAndReportsRetained', False), ('businessDatabaseUntouched', False),
    ('excludedBuilds', [225, 229]), ('testsExecuted', True),
])
def test_status_rejects_receipt_from_another_context_or_with_weakened_preservation(
        status_attempt, field, value):
    receipt = {**status_attempt.current, 'status': 'COMPLETE', field: value}
    control(status_attempt, 'receipt.json', receipt)
    with pytest.raises(ValueError, match='TERMINAL_RECEIPT_CONTEXT_CHANGED'):
        retirement.status(status_attempt.args, status_attempt.folder)


@pytest.mark.parametrize('state', ['same', 'reused', 'gone'])
def test_apply_claim_without_receipt_never_becomes_success_or_replays(status_attempt, monkeypatch, state):
    control(status_attempt, 'claim.json', {**status_attempt.current, 'pid': 7654321,
                                         'startTicks': 'original-ticks'})
    calls = process_identity(monkeypatch, state)
    result = retirement.status(status_attempt.args, status_attempt.folder)
    assert result['status'] == ('RUNNING' if state == 'same' else 'UNKNOWN_WITHOUT_RECEIPT')
    assert result['terminal'] is False
    assert calls == [7654321]
    assert not (status_attempt.folder / 'receipt.json').exists()


def planning_controls(attempt):
    control(attempt, 'planning-claim.json', {**attempt.current, 'pid': 7654321,
                                           'startTicks': 'original-ticks'})
    control(attempt, 'plan.json', {**attempt.current, 'status': 'PLANNED', 'targets': []})
    control(attempt, 'plan-complete.json', {**attempt.current, 'planSha256': 'e' * 64})


@pytest.mark.parametrize('state', ['same', 'reused', 'gone'])
def test_planning_disconnect_is_settled_only_after_original_planner_ends_with_sealed_plan(
        status_attempt, monkeypatch, state):
    planning_controls(status_attempt)
    process_identity(monkeypatch, state)
    def plan_digest(path):
        assert path == status_attempt.folder / 'plan.json'
        return 'e' * 64
    monkeypatch.setattr(retirement, 'digest', plan_digest)
    result = retirement.status(status_attempt.args, status_attempt.folder)
    assert result['terminal'] is False, 'Planning completion must not claim deletion completed'
    assert result['planTerminal'] is (state != 'same')
    assert result['status'] == ('PLANNING' if state == 'same' else 'PLANNED')
    assert result['planSha256'] == 'e' * 64
    assert not (status_attempt.folder / 'claim.json').exists()


@pytest.mark.parametrize('damage', ['completion-context', 'planner-context', 'plan-sha'])
def test_planning_completion_requires_original_context_and_exact_sealed_plan(status_attempt, monkeypatch, damage):
    planning_controls(status_attempt)
    if damage == 'completion-context':
        control(status_attempt, 'plan-complete.json', {**status_attempt.current,
            'authorizationSha256': 'f' * 64, 'planSha256': 'e' * 64})
    elif damage == 'planner-context':
        control(status_attempt, 'planning-claim.json', {**status_attempt.current,
            'release': 'ci-302-' + 'f' * 12, 'pid': 7654321, 'startTicks': 'original-ticks'})
    monkeypatch.setattr(retirement, 'digest', lambda _path: ('f' if damage == 'plan-sha' else 'e') * 64)
    process_identity(monkeypatch, 'gone')
    with pytest.raises(ValueError, match='ORIGINAL_PLAN_COMPLETION_CHANGED'):
        retirement.status(status_attempt.args, status_attempt.folder)


def test_planning_claim_without_completion_is_nonterminal_and_never_reissued(status_attempt, monkeypatch):
    control(status_attempt, 'planning-claim.json', {**status_attempt.current,
        'pid': 7654321, 'startTicks': 'original-ticks'})
    process_identity(monkeypatch, 'same')
    result = retirement.status(status_attempt.args, status_attempt.folder)
    assert result['terminal'] is False and result['planTerminal'] is False
    assert not (status_attempt.folder / 'plan-complete.json').exists()
    assert not (status_attempt.folder / 'claim.json').exists()


def test_status_cli_returns_pollable_success_for_a_live_original_planner(status_attempt, monkeypatch, capsys):
    args = status_attempt.args
    cleanup = SimpleNamespace(owned_chain=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(retirement, 'fixed_modules', lambda _args: (status_attempt.folder, cleanup, None))
    monkeypatch.setattr(retirement.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(retirement, 'status', lambda _args, _folder: {**status_attempt.current,
        'status': 'PLANNING', 'terminal': False, 'planTerminal': False})
    monkeypatch.setattr(retirement.sys, 'argv', ['retire-source-pytest.py', 'status',
        '--tag', args.tag, '--commit', args.commit, '--source-sha256', args.source_sha256,
        '--authorization-sha256', args.authorization_sha256])
    assert retirement.main() == 0
    assert 'PLANNING' in capsys.readouterr().out


@pytest.mark.parametrize('damage', ['non-root', 'unapproved-release', 'extra-field', 'missing-field',
                                   'empty-keys', 'negative-key', 'boolean-key', 'invalid-nonce',
                                   'socket-not-in-keys', 'malformed-socket-keys', 'missing-socket-keys'])
def test_root_process_metadata_probe_refuses_unclosed_or_unapproved_request_before_scanning(
        tmp_path, monkeypatch, damage):
    request = {'release': retirement.EXACT_RELEASES[0], 'keys': [[1, 2]], 'socketKeys': [], 'nonce': 'a' * 32}
    uid = 1000 if damage == 'non-root' else 0
    monkeypatch.setattr(retirement.os, 'getuid', lambda: uid)
    monkeypatch.setattr(retirement.os, 'geteuid', lambda: uid)
    def machine_id(path, *_args, **_kwargs):
        assert path == Path('/etc/machine-id'), 'No process or target payload may be read'
        return retirement.IDENTITY['machineId'] + '\n'
    monkeypatch.setattr(Path, 'read_text', machine_id)
    def unexpected_scan(*_args, **_kwargs):
        raise AssertionError('A rejected root request must not enumerate any process')
    monkeypatch.setattr(retirement.os, 'scandir', unexpected_scan)
    if damage == 'unapproved-release': request['release'] = 'ci-266-' + 'a' * 12
    elif damage == 'extra-field': request['path'] = '/unapproved'
    elif damage == 'missing-field': request.pop('nonce')
    elif damage == 'empty-keys': request['keys'] = []
    elif damage == 'negative-key': request['keys'] = [[1, -1]]
    elif damage == 'boolean-key': request['keys'] = [[True, 2]]
    elif damage == 'invalid-nonce': request['nonce'] = 'z' * 32
    elif damage == 'socket-not-in-keys': request['socketKeys'] = [[1, 3]]
    elif damage == 'malformed-socket-keys': request['socketKeys'] = [[True, 2]]
    elif damage == 'missing-socket-keys': request.pop('socketKeys')
    with pytest.raises(ValueError):
        retirement.probe_processes(request, proc=tmp_path / 'synthetic-proc')


def test_root_process_metadata_probe_can_check_only_an_explicit_synthetic_proc_tree(tmp_path, monkeypatch):
    proc = tmp_path / 'synthetic-empty-proc'
    proc.mkdir(mode=0o700)
    request = {'release': retirement.EXACT_RELEASES[0], 'keys': [[1, 2]], 'socketKeys': [], 'nonce': 'a' * 32}
    monkeypatch.setattr(retirement.os, 'getuid', lambda: 0)
    monkeypatch.setattr(retirement.os, 'geteuid', lambda: 0)
    def machine_id(path, *_args, **_kwargs):
        assert path == Path('/etc/machine-id')
        return retirement.IDENTITY['machineId']
    monkeypatch.setattr(Path, 'read_text', machine_id)
    original_scandir = os.scandir
    def owned_scan(path):
        assert Path(path) == proc, 'The real process namespace is not part of this case'
        return original_scandir(path)
    monkeypatch.setattr(retirement.os, 'scandir', owned_scan)
    result = retirement.probe_processes(request, proc=proc)
    assert result['status'] == 'QUIESCENT'
    assert result['scope'] == 'ALL_UIDS_EXACT_SOURCE_PYTEST_ROOT'
    assert result['release'] == request['release'] and result['nonce'] == request['nonce']
    assert result['processesChecked'] == 0 and result['uidsChecked'] == []
    assert result['socketNamespacesChecked'] == 0
    assert result['socketKeysSha256'] == retirement.hashlib.sha256(retirement.encoded([])).hexdigest()


@pytest.mark.parametrize('reference', ['release-label', 'same-bind', 'ancestor-bind', 'descendant-bind', 'held-lock'])
def test_container_label_bind_and_held_inode_references_reject_before_any_sudo(tree, monkeypatch, reference):
    release = retirement.EXACT_RELEASES[0]
    target = retirement.ROOT / 'verification' / release / 'checkout'
    mounts = {'same-bind': target, 'ancestor-bind': target.parent,
              'descendant-bind': target / 'work/ci-evidence/tmp/pytest'}
    container_release = release if reference == 'release-label' else 'another-release'
    binds = [{'Type': 'bind', 'Source': str(mounts[reference])}] if reference in mounts else []
    snapshot = [('f' * 64, False, False, 0, container_release, 'synthetic-token', binds)]
    metadata = retirement.inventory(tree.target)
    root_info = metadata['rootMetadata']
    locks = {(root_info[6], root_info[5])} if reference == 'held-lock' else set()
    cleanup = SimpleNamespace(docker_snapshot=lambda: snapshot, locked_inodes=lambda: locks)
    def no_sudo(*_args, **_kwargs):
        raise AssertionError('Known active references must refuse before the privileged metadata probe')
    monkeypatch.setattr(retirement.subprocess, 'run', no_sudo)
    with pytest.raises(ValueError, match=(
            'OLD_RELEASE_CONTAINER_STILL_PRESENT|CONTAINER_REFERENCES_APPROVED_TEST_ROOT|TARGET_HAS_HELD_FILE_LOCK')):
        retirement.reference_probe(release, metadata, cleanup)


def current_namespace_proc(tmp_path):
    proc = tmp_path / 'synthetic-proc'
    namespace = proc / 'self/ns/net'
    namespace.parent.mkdir(parents=True, mode=0o700)
    namespace.symlink_to('/proc/self/ns/net')
    return proc


@pytest.mark.parametrize('binding', ['proc-fd', 'relative', 'absolute', 'renamed'])
def test_live_unix_socket_is_rejected_by_vfs_identity_after_bind_directory_and_cwd_are_gone(
        tmp_path, monkeypatch, binding):
    bound = tmp_path / 'bound'
    outside = tmp_path / 'outside'
    bound.mkdir(mode=0o700)
    outside.mkdir(mode=0o700)
    proc = current_namespace_proc(tmp_path)
    original_cwd = Path.cwd()
    path = bound / 'live.sock'
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
            if binding in ('relative', 'absolute'):
                os.chdir(bound)
                # A short absolute spelling works even in the long, read-only
                # control-container mount; it becomes stale after chdir.
                endpoint.bind('live.sock' if binding == 'relative' else '/proc/self/cwd/live.sock')
            else:
                descriptor = os.open(bound, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    endpoint.bind('/proc/self/fd/' + str(descriptor) + '/live.sock')
                finally:
                    os.close(descriptor)
                with pytest.raises(OSError):
                    os.fstat(descriptor)
            os.chdir(outside)
            if binding == 'renamed':
                path.rename(bound / 'renamed.sock')
                path = bound / 'renamed.sock'
            info = path.lstat()
            key = (info.st_dev, info.st_ino)
            snapshot = retirement.unix_socket_vfs()
            assert key in snapshot
            assert Path.cwd() == outside and endpoint.fileno() >= 0
            monkeypatch.setattr(retirement, 'unix_socket_vfs', lambda: snapshot)
            def unnecessary_setns(_descriptor):
                raise AssertionError('The current namespace must not require privilege or setns')
            monkeypatch.setattr(retirement, 'enter_net_namespace', unnecessary_setns)
            with pytest.raises(ValueError, match='ACTIVE_UNIX_SOCKET_VFS_REFERENCE'):
                retirement.socket_references({key}, proc=proc)
    finally:
        os.chdir(original_cwd)


def test_closed_unix_socket_residue_is_absent_from_vfs_dump_and_may_be_retired(tmp_path, monkeypatch):
    bound = tmp_path / 'closed-socket'
    bound.mkdir(mode=0o700)
    proc = current_namespace_proc(tmp_path)
    descriptor = os.open(bound, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as endpoint:
            endpoint.bind('/proc/self/fd/' + str(descriptor) + '/closed.sock')
    finally:
        os.close(descriptor)
    path = bound / 'closed.sock'
    info = path.lstat()
    key = (info.st_dev, info.st_ino)
    snapshot = retirement.unix_socket_vfs()
    assert stat.S_ISSOCK(info.st_mode) and key not in snapshot
    monkeypatch.setattr(retirement, 'unix_socket_vfs', lambda: snapshot)
    def unnecessary_setns(_descriptor):
        raise AssertionError('The current namespace must not require setns')
    monkeypatch.setattr(retirement, 'enter_net_namespace', unnecessary_setns)
    assert retirement.socket_references({key}, proc=proc) == 1
    assert retirement.metadata(path.lstat()) == retirement.metadata(info)


def test_no_socket_candidates_skip_all_namespace_and_diagnostic_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('An empty socket set must not inspect process or network namespaces')
    monkeypatch.setattr(retirement, 'unix_socket_vfs', forbidden)
    monkeypatch.setattr(retirement, 'enter_net_namespace', forbidden)
    monkeypatch.setattr(retirement.os, 'scandir', forbidden)
    assert retirement.socket_references(set(), proc=Path('/must-not-be-opened')) == 0


@pytest.mark.parametrize('failure', ['empty', 'truncated', 'interrupted', 'kernel-error'])
def test_incomplete_or_refused_unix_socket_diagnostics_never_mean_no_active_sockets(monkeypatch, failure):
    sequence = 123
    monkeypatch.setattr(retirement.secrets, 'randbits', lambda _bits: sequence)
    class DiagnosticChannel:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def settimeout(self, _timeout): pass
        def bind(self, address): assert address == (0, 0)
        def sendto(self, raw, address):
            assert address == (0, 0)
            return len(raw)
        def getsockname(self): return (777, 0)
        def recvmsg(self, _maximum):
            if failure == 'empty': return b'', [], 0, (0, 0)
            kind = 2 if failure == 'kernel-error' else 3
            body = retirement.struct.pack('=i', -errno.EPERM) if kind == 2 else b''
            flags = 0x10 if failure == 'interrupted' else 0
            raw = retirement.struct.pack('=IHHII', 16 + len(body), kind, flags, sequence, 777) + body
            return raw, [], socket.MSG_TRUNC if failure == 'truncated' else 0, (0, 0)
    def diagnostic_socket(family, kind, protocol):
        assert family == socket.AF_NETLINK and kind & socket.SOCK_RAW and protocol == 4
        return DiagnosticChannel()
    monkeypatch.setattr(retirement.socket, 'socket', diagnostic_socket)
    with pytest.raises(ValueError, match='UNIX_SOCKET_DIAGNOSTIC_'):
        retirement.unix_socket_vfs()


def process_stat(entry):
    fields = [b'S'] + [b'0'] * 19
    fields[19] = b'123456'
    return put(entry / 'stat', entry.name.encode() + b' (synthetic) ' + b' '.join(fields) + b'\n')


@pytest.mark.parametrize('outcome', ['clear', 'active', 'diagnostic-error', 'namespace-denied'])
def test_foreign_namespace_is_always_restored_after_inspection_or_refusal(tmp_path, monkeypatch, outcome):
    proc = tmp_path / 'synthetic-proc'
    origin = put(proc / 'self/ns/net')
    foreign = put(proc / '1234/ns/net')
    process_stat(proc / '1234')
    origin_key = (origin.stat().st_dev, origin.stat().st_ino)
    foreign_key = (foreign.stat().st_dev, foreign.stat().st_ino)
    current = [origin_key]
    transitions = []
    candidate = (1, 2)
    def enter(descriptor):
        info = os.fstat(descriptor)
        key = (info.st_dev, info.st_ino)
        transitions.append(key)
        if key == foreign_key and outcome == 'namespace-denied':
            raise PermissionError(errno.EPERM, 'synthetic namespace permission denied')
        current[0] = key
    def snapshot():
        if current[0] == foreign_key:
            if outcome == 'diagnostic-error':
                raise OSError(errno.EIO, 'synthetic socket diagnostic failure')
            if outcome == 'active': return {candidate}
        return set()
    monkeypatch.setattr(retirement, 'enter_net_namespace', enter)
    monkeypatch.setattr(retirement, 'unix_socket_vfs', snapshot)
    if outcome == 'clear':
        assert retirement.socket_references({candidate}, proc=proc) == 2
    else:
        with pytest.raises((ValueError, OSError)):
            retirement.socket_references({candidate}, proc=proc)
    assert transitions == [foreign_key, origin_key]
    assert current[0] == origin_key


def test_live_process_with_unknown_socket_namespace_refuses_instead_of_claiming_coverage(tmp_path, monkeypatch):
    proc = tmp_path / 'synthetic-proc'
    put(proc / 'self/ns/net')
    process_stat(proc / '1234')
    monkeypatch.setattr(retirement, 'unix_socket_vfs', lambda: set())
    with pytest.raises(ValueError, match='UNIX_SOCKET_NAMESPACE_COVERAGE_UNKNOWN'):
        retirement.socket_references({(1, 2)}, proc=proc)


@pytest.mark.parametrize('damage', ['none', 'socket-digest', 'namespace-count'])
def test_reference_probe_binds_exact_socket_subset_and_namespace_coverage_without_real_sudo(
        tree, monkeypatch, damage):
    metadata = retirement.inventory(tree.target)
    socket_info = metadata['rootMetadata'].copy()
    socket_info[0] = stat.S_IFSOCK | 0o600
    socket_info[5] += 1
    metadata['entries'] = [{'path': 'synthetic.sock', 'metadata': socket_info}]
    all_keys = sorted({(row[6], row[5]) for row in [metadata['rootMetadata'], socket_info]})
    socket_keys = [[socket_info[6], socket_info[5]]]
    release = retirement.EXACT_RELEASES[0]
    request = {'release': release, 'keys': [list(key) for key in all_keys],
               'socketKeys': socket_keys, 'nonce': 'a' * 32}
    monkeypatch.setattr(retirement, 'LOADED_SOURCE', b'# synthetic pinned helper\n')
    monkeypatch.setattr(retirement, 'read_bounded', lambda *_args: retirement.LOADED_SOURCE)
    monkeypatch.setattr(retirement.secrets, 'token_hex', lambda _size: 'a' * 32)
    cleanup = SimpleNamespace(docker_snapshot=lambda: [], locked_inodes=lambda: set())
    def response(_command, **kwargs):
        assert repr(retirement.encoded(request).decode()).encode() in kwargs['input']
        value = {'status': 'QUIESCENT', 'scope': 'ALL_UIDS_EXACT_SOURCE_PYTEST_ROOT',
            'release': release, 'nonce': 'a' * 32,
            'keysSha256': retirement.hashlib.sha256(retirement.encoded(request['keys'])).hexdigest(),
            'socketKeysSha256': retirement.hashlib.sha256(retirement.encoded(socket_keys)).hexdigest(),
            'socketNamespacesChecked': 1}
        if damage == 'socket-digest': value['socketKeysSha256'] = 'f' * 64
        elif damage == 'namespace-count': value['socketNamespacesChecked'] = 0
        return SimpleNamespace(returncode=0, stdout=retirement.encoded(value), stderr=b'')
    monkeypatch.setattr(retirement.subprocess, 'run', response)
    if damage == 'none':
        assert retirement.reference_probe(release, metadata, cleanup)['socketNamespacesChecked'] == 1
    else:
        with pytest.raises(ValueError, match='ALL_UID_PROCESS_RESPONSE_NOT_BOUND'):
            retirement.reference_probe(release, metadata, cleanup)


def test_source_pytest_policy_returns_before_ordinary_or_failed_native_maintenance():
    pipeline = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf-8')
    maintenance = pipeline.split(
        "if ($Action -ceq 'ReclaimBuildOutputs' -and $env:ACTION -ceq 'reclaim-build-outputs') {", 1
        )[1].split("if ($Action -eq 'Preflight')", 1)[0]
    selector = "if ($nativeRetentionPolicy -cin @('SourcePytest16','SourcePytest307308')) {"
    exact = maintenance.split(selector, 1)[1].split('\n    }', 1)[0]
    assert re.fullmatch(r'\s*& ./script/jenkins/retire-source-pytest\.ps1[^\n]+\n\s*return\s*', exact)
    # The independent generated-only branch also invokes this controller, but
    # returns before policy dispatch. Locate the ordinary maintenance call by
    # its complete switch boundary, not the prefix shared by both modes.
    ordinary = list(re.finditer(
        r'(?m)^    & ./script/jenkins/reclaim-build-outputs\.ps1 -Mode Maintenance -SshOptions [^\n]+$',
        maintenance))
    assert len(ordinary) == 1, 'There must be one ordinary maintenance fall-through'
    assert maintenance.index(selector) < ordinary[0].start()
    assert ordinary[0].end() < maintenance.index('-CanonicalBatch FailedNative -SshOptions')
    assert 'reclaim-build-outputs.ps1' not in exact and 'FailedNative' not in exact
    assert maintenance.count('retire-source-pytest.ps1') == 1


def test_pinned_source_helpers_and_original_plan_journals_are_bound_without_apply_replay():
    pipeline = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf-8')
    package = re.search(r"(?ms)^if \(\$Action -ceq 'PackageSourceOnly'\) \{\n(.*?)^\}\n", pipeline)
    assert package, 'The source-only archive must be produced by its standalone action block'
    package = package[1]
    assert "if ($nativeRetentionPolicy -cin @('SourcePytest16','SourcePytest307308')) { $maintenancePaths += 'script/jenkins/retire-source-pytest.py' }" in package
    assert "'--output=artifacts/source.tar.gz', $commit) + $maintenancePaths" in package
    controller = (ROOT / 'script/jenkins/retire-source-pytest.ps1').read_text(encoding='utf-8')
    assert "foreach($name in @('retire-source-pytest.py','cleanup-ecs-builds.py','verify-remote.py'))" in controller
    assert "$inputFile=Get-PinnedSourceFile ('script/jenkins/'+$name)" in controller
    assert "$helperSha=(Get-FileHash -LiteralPath $inputFile -Algorithm SHA256).Hash.ToLowerInvariant()" in controller
    guard = next(line for line in controller.splitlines() if line.lstrip().startswith('$guard='))
    assert "sha256sum '$helper'" in guard and "= '$helperSha' && python3 -I -B '$helper'" in guard
    phases = re.findall(r'"\$guard (plan|apply|status) \$binding[^"\n]*"', controller)
    assert phases == ['plan', 'status', 'apply', 'status']
    assert controller.count('$guard apply') == 1
    assert "--tag '$Tag' --commit '$Commit' --source-sha256 '$SourceSha256' --authorization-sha256 '$authSha'" in controller
    plan_observer = controller.split('if($planExit -eq 255){', 1)[1].split('} elseif($planExit', 1)[0]
    apply_observer = controller.split('if($applyExit -eq 255){', 1)[1].split('} elseif($applyExit', 1)[0]
    assert '$guard status $binding' in plan_observer and '$original.planTerminal -eq $true' in plan_observer
    assert "$original.status -cne 'PLANNED'" in plan_observer
    assert '$guard status $binding' in apply_observer and '$original.terminal -eq $true' in apply_observer
    assert "$original.status -cne 'COMPLETE'" in apply_observer
    assert "$plan=Copy-ExactEvidence 'plan.json'" in controller
    assert '$planSha=(Get-FileHash "$local/plan.json" -Algorithm SHA256).Hash.ToLowerInvariant()' in controller
    assert '$receipt.planSha256 -cne $planSha' in controller
    assert '(Get-FileHash "$local/$name" -Algorithm SHA256).Hash.ToLowerInvariant() -cne $row.sha256' in controller
    assert '(Get-FileHash "$local/$name" -Algorithm SHA256).Hash.ToLowerInvariant() -cne $done[0].journalSha256' in controller
    assert "$name -cne ('root-'+($row.release.Split('-')[1])+'.journal.jsonl')" in controller


def test_retirement_choices_and_archive_preserve_public_controls_but_not_private_authorization():
    workflow = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf-8')
    seed = (ROOT / 'script/jenkins/configure-local.groovy').read_text(encoding='utf-8')
    controller = (ROOT / 'script/jenkins/retire-source-pytest.ps1').read_text(encoding='utf-8')
    workflow_choices = re.search(r"choice\(name: 'NATIVE_RETENTION_POLICY', choices: (\[[^\]]+\])", workflow)
    seed_choices = re.search(r"ChoiceParameterDefinition\('NATIVE_RETENTION_POLICY', (\[[^\]]+\]) as String\[\]", seed)
    admitted_choices = re.search(r'env\.NATIVE_RETENTION_POLICY in (\[[^\]]+\])', workflow)
    assert workflow_choices and seed_choices and admitted_choices
    choices = ast.literal_eval(workflow_choices[1])
    assert choices == ast.literal_eval(seed_choices[1]) == ast.literal_eval(admitted_choices[1])
    assert choices[0] == 'FailedNative' and choices.count('SourcePytest16') == 1
    assert "env.NATIVE_RETENTION_POLICY != 'FailedNative' && params.ACTION != 'reclaim-build-outputs'" in workflow
    authorization = 'work/jenkins/data-residency-20261107/source-pytest16-retention-authorization-20261114.json'
    assert "'DOORHANDLE_SOURCE_PYTEST16_AUTHORIZATION_FILE': new File(project, '" + authorization + "').path" in seed
    archives = re.findall(r"archiveArtifacts\s+artifacts:\s*'([^']+)'", workflow)
    assert any('artifacts/source-pytest16/*' in paths.split(',') for paths in archives)
    assert all(authorization not in paths and 'source-pytest16-authorization.json' not in paths for paths in archives)
    assert '$local=\'artifacts/source-pytest16\'' in controller
    auth_transfers = [line for line in controller.splitlines() if 'scp.exe' in line and '$authorization' in line]
    assert len(auth_transfers) == 1
    assert '"${Destination}:$remote/$authorizationName"' in auth_transfers[0]
    assert "$authorizationName='source-pytest16-authorization.json'" in controller
    assert "$authorizationName='source-pytest307308-authorization.json'" in controller
    assert '$local' not in auth_transfers[0]
