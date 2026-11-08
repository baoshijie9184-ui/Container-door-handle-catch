"""Synthetic public OCI transport contracts; executed by Jenkins only on ECS."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'script/jenkins/transfer-candidate-build-tools.py'
SPEC = importlib.util.spec_from_file_location('candidate_build_input_transport', FILE)
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)
ATTEMPT = 'a' * 32


@pytest.fixture
def custody(tmp_path, monkeypatch):
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    (root / 'inbox').mkdir(mode=0o700)
    inbox = root / 'inbox/ci-12-aaaaaaaaaaaa'; inbox.mkdir(mode=0o700)
    context = {'release': inbox.name, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
               'identity': {'executionLocation': 'ECS', 'instanceId': 'i-fixture', 'machineId': 'c' * 32}}
    raw = b'public OCI fixture bytes'
    value = transport.binding(root, hashlib.sha256(raw).hexdigest(), len(raw))
    monkeypatch.setattr(transport.os, 'statvfs', lambda _path: SimpleNamespace(f_bavail=8 * 1024 ** 3, f_frsize=1))
    return root, inbox, context, raw, value


def stage(custody):
    root, inbox, context, raw, value = custody
    result = transport.probe(root, inbox, context, value, ATTEMPT)
    path = Path(result['stagingFile']); path.write_bytes(raw)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return path


def test_local_snapshot_uses_actual_bytes_and_a_stable_single_file(tmp_path):
    base = tmp_path / 'deps'; base.mkdir(); source = base / 'public.tar'; source.write_bytes(b'public')
    value = transport.local_snapshot(source, base)
    assert value['bytes'] == 6 and value['sha256'] == hashlib.sha256(b'public').hexdigest()
    assert len(value['fingerprintSha256']) == 64


@pytest.mark.parametrize('case', ['relative', 'outside', 'directory', 'symlink', 'hardlink', 'fifo', 'empty', 'oversize'])
def test_local_input_rejects_unadmitted_file_shapes(tmp_path, case):
    base = tmp_path / 'deps'; base.mkdir(); source = base / 'public.tar'; source.write_bytes(b'public')
    if case == 'relative': source = Path('public.tar')
    elif case == 'outside': source = tmp_path / 'outside.tar'; source.write_bytes(b'public')
    elif case == 'directory': source.unlink(); source.mkdir()
    elif case == 'symlink': source.unlink(); source.symlink_to(tmp_path / 'missing')
    elif case == 'hardlink': os.link(source, base / 'alias')
    elif case == 'fifo': source.unlink(); os.mkfifo(source)
    elif case == 'empty': source.write_bytes(b'')
    elif case == 'oversize':
        with source.open('wb') as output: output.truncate(transport.MAX_BYTES + 1)
    with pytest.raises((ValueError, OSError)):
        transport.local_snapshot(source, base)


def test_local_input_rejects_linked_parent(tmp_path):
    base = tmp_path / 'deps'; base.mkdir(); real = tmp_path / 'real'; real.mkdir()
    (real / 'public.tar').write_bytes(b'public'); (base / 'linked').symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match='LINKED_BUILD_INPUT_PATH'):
        transport.local_snapshot(base / 'linked/public.tar', base)


def test_local_same_fd_rejects_change_after_hash(tmp_path, monkeypatch):
    base = tmp_path / 'deps'; base.mkdir(); source = base / 'public.tar'; source.write_bytes(b'public')
    original = transport.hash_fd
    def changed(fd, size):
        result = original(fd, size); before = source.stat(); source.write_bytes(b'forged')
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000)); return result
    monkeypatch.setattr(transport, 'hash_fd', changed)
    with pytest.raises(ValueError, match='BUILD_INPUT_CHANGED'):
        transport.local_snapshot(source, base)


@pytest.mark.parametrize('size', [0, -1, transport.MAX_BYTES + 1, True])
def test_declared_input_byte_bound_is_strict(size, tmp_path):
    with pytest.raises(ValueError, match='BUILD_INPUT_BINDING_INVALID'):
        transport.binding(tmp_path, 'a' * 64, size)


def test_upload_budget_includes_real_input_once_and_preserves_reserve(custody, monkeypatch):
    root, inbox, context, raw, value = custody
    required = transport.FLOOR + len(raw) + 64 * 1024
    monkeypatch.setattr(transport.os, 'statvfs', lambda _path: SimpleNamespace(f_bavail=required - 1, f_frsize=1))
    with pytest.raises(ValueError, match='BUILD_INPUT_UPLOAD_DISK_RESERVE'):
        transport.probe(root, inbox, context, value, ATTEMPT)
    assert not transport.stage_path(inbox, ATTEMPT).exists()
    monkeypatch.setattr(transport.os, 'statvfs', lambda _path: SimpleNamespace(f_bavail=required, f_frsize=1))
    result = transport.probe(root, inbox, context, value, ATTEMPT)
    assert result['requiredAvailableBytes'] == required and result['diskReserveBytes'] == transport.FLOOR


def test_atomic_fd_publication_and_full_sha_cache_hit(custody):
    root, inbox, context, raw, value = custody; stage(custody)
    result = transport.publish(root, inbox, context, value, ATTEMPT)
    cache = Path(value['file'])
    assert result['status'] == 'AVAILABLE' and cache.read_bytes() == raw
    assert cache.stat().st_nlink == 1 and stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert not transport.stage_path(inbox, ATTEMPT).exists()
    assert transport.probe(root, inbox, context, value, 'd' * 32)['status'] == 'REUSED'
    assert not transport.stage_path(inbox, 'd' * 32).exists()


@pytest.mark.parametrize('case', ['different-bytes', 'hardlink', 'symlink', 'group-write'])
def test_existing_cache_is_never_replaced_or_deleted(custody, case):
    root, inbox, context, raw, value = custody; stage(custody)
    cache = Path(value['file']); cache.write_bytes(raw); cache.chmod(0o600)
    if case == 'different-bytes': cache.write_bytes(b'wrong')
    elif case == 'hardlink': os.link(cache, cache.parent / 'foreign-alias')
    elif case == 'symlink':
        cache.unlink(); target = cache.parent / 'foreign'; target.write_bytes(raw); cache.symlink_to(target)
    else: cache.chmod(0o660)
    before = cache.lstat()
    with pytest.raises(ValueError):
        transport.probe(root, inbox, context, value, 'd' * 32)
    after = cache.lstat(); assert (before.st_dev, before.st_ino, before.st_mode) == (after.st_dev, after.st_ino, after.st_mode)
    transport.cleanup(inbox, context, value, ATTEMPT)
    assert cache.exists()


def test_publication_conflict_does_not_overwrite_unknown_cache(custody):
    root, inbox, context, raw, value = custody; stage(custody)
    cache = Path(value['file']); cache.write_bytes(b'foreign'); cache.chmod(0o600)
    with pytest.raises(ValueError, match='EXISTING_BUILD_INPUT_DIFFERS'):
        transport.publish(root, inbox, context, value, ATTEMPT)
    assert cache.read_bytes() == b'foreign'


def test_publish_links_held_fd_even_if_staging_name_changes(custody, monkeypatch):
    root, inbox, context, raw, value = custody; source = stage(custody); original = transport.os.link
    def changed(src, dst, **kwargs):
        assert str(src).startswith('/proc/self/fd/')
        source.rename(source.with_name('unknown-original')); source.write_bytes(b'foreign')
        return original(src, dst, **kwargs)
    monkeypatch.setattr(transport.os, 'link', changed)
    with pytest.raises(ValueError, match='BUILD_INPUT_PUBLICATION_CHANGED'):
        transport.publish(root, inbox, context, value, ATTEMPT)
    assert Path(value['file']).read_bytes() == raw
    assert source.read_bytes() == b'foreign' and source.with_name('unknown-original').exists()


def test_partial_cleanup_is_limited_to_the_owned_upload(custody):
    root, inbox, context, raw, value = custody; path = stage(custody); path.write_bytes(b'partial')
    assert transport.cleanup(inbox, context, value, ATTEMPT)['status'] == 'REMOVED_OWNED_STAGING'
    assert not path.parent.exists() and not Path(value['file']).exists()
    assert transport.cleanup(inbox, context, value, ATTEMPT)['status'] == 'NO_STAGE'


def test_link_publication_interruption_recovers_only_the_proved_owned_alias(custody, monkeypatch):
    root, inbox, context, raw, value = custody; source = stage(custody); original = transport.os.unlink
    def interrupted(path, **kwargs):
        if Path(path) == source:
            raise OSError('Synthetic interruption after cache link publication')
        return original(path, **kwargs)
    monkeypatch.setattr(transport.os, 'unlink', interrupted)
    with pytest.raises(OSError): transport.publish(root, inbox, context, value, ATTEMPT)
    cache = Path(value['file']); assert cache.stat().st_nlink == source.stat().st_nlink == 2
    monkeypatch.setattr(transport.os, 'unlink', original)
    assert transport.cleanup(inbox, context, value, ATTEMPT)['status'] == 'REMOVED_OWNED_STAGING'
    assert cache.read_bytes() == raw and cache.stat().st_nlink == 1 and not source.parent.exists()
    assert transport.probe(root, inbox, context, value, 'd' * 32)['status'] == 'REUSED'


@pytest.mark.parametrize('case', ['unknown-entry', 'wrong-owner', 'linked-payload', 'writable-parent'])
def test_unknown_or_changed_staging_is_retained(custody, case):
    root, inbox, context, raw, value = custody; path = stage(custody)
    if case == 'unknown-entry': (path.parent / 'unknown').write_bytes(b'unknown')
    elif case == 'wrong-owner':
        owner = path.parent / 'owner.json'; data = json.loads(owner.read_bytes()); data['commit'] = 'd' * 40; owner.write_text(json.dumps(data))
    elif case == 'linked-payload': os.link(path, inbox / 'foreign-alias')
    else: path.parent.chmod(0o770)
    with pytest.raises(ValueError): transport.cleanup(inbox, context, value, ATTEMPT)
    assert path.exists() and (path.parent / 'owner.json').exists()


def test_foreign_uid_is_rejected_before_reading_input(tmp_path, monkeypatch):
    file = tmp_path / 'input'; file.write_bytes(b'public'); file.chmod(0o600); original = transport.os.fstat
    def foreign(fd):
        value = original(fd); fields = {name: getattr(value, name) for name in dir(value) if name.startswith('st_')}
        fields['st_uid'] = 999; return SimpleNamespace(**fields)
    monkeypatch.setattr(transport.os, 'fstat', foreign)
    with pytest.raises(ValueError, match='BUILD_INPUT_OWNER'):
        with transport.held(file, uid=1000, private=True): pytest.fail('Foreign source admitted')


def test_controller_wires_same_binding_to_initial_and_readback_without_archiving_tar():
    pipeline = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
    prepare = pipeline[pipeline.index("if ($Action -in @('PrepareTools', 'CleanupTools'))"):]
    assert '--buildkit-archive ' in prepare and '--buildkit-archive-sha256 ' in prepare and '--buildkit-archive-bytes ' in prepare
    assert '$prepareCommand --read-prepared' in prepare
    function = pipeline[pipeline.index('function Send-CandidateBuildToolsArchive'):pipeline.index("$tag = Require-Value")]
    assert "Get-PinnedSourceFile 'script/jenkins/fetch-buildkit-build-input.py'" in function
    assert "Get-PinnedSourceFile 'script/docker/compact-build-resources.py'" in function
    assert "'--resources-source'" in function and "'--output-dir'" in function
    assert "$record.rawArchiveArchived" not in function and 'rawArchiveArchived=$false' in function
    assert 'artifacts/candidate-build-tools-transport.json' in function
    assert "$guard cleanup $transferArguments" in function
    assert '134217728' in function and 'CANDIDATE_BUILD_INPUT_CACHE_ROOT' in function


def test_parameter_scope_and_global_node_cache_are_explicit():
    jenkins = (ROOT / 'Jenkinsfile.ecs-monolith').read_text(encoding='utf8')
    config = (ROOT / 'script/jenkins/configure-local.groovy').read_text(encoding='utf8')
    assert "string(name: 'CANDIDATE_BUILD_TOOLS_ARCHIVE', defaultValue: ''" in jenkins
    assert "env.CANDIDATE_BUILD_TOOLS_ARCHIVE && !(params.ACTION in ['verify-runtime', 'compact-cutover'])" in jenkins
    assert "new StringParameterDefinition('CANDIDATE_BUILD_TOOLS_ARCHIVE', ''" in config
    assert "'CANDIDATE_BUILD_INPUT_CACHE_ROOT': new File(project, 'work/jenkins/build-deps').path" in config
