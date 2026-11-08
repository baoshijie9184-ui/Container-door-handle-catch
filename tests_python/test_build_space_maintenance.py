"""Execute the fixed metadata controller against synthetic files on ECS only."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
from types import SimpleNamespace
import urllib.request

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != 'linux' or os.getuid() != 1000,
    reason='The maintenance metadata filesystem requires the real ECS Linux UID 1000')
ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'a' * 40
TAG = 'ci-9-' + COMMIT[:12]
CONTROL_BYTES = 99 * 1024 ** 2
RESERVE = 2 * 1024 ** 3
HELPERS = {
    'script/jenkins/cleanup-ecs-builds.py': b'raise RuntimeError("Opaque cleanup helper must not be imported")\n',
    'script/jenkins/verify-remote.py': b'raise RuntimeError("Opaque verifier must not be imported")\n',
}


def source_bytes(damage=None):
    output = io.BytesIO()
    entries = [*HELPERS.items(), ('README.md', b'Unrelated fixed source must remain inside the archive\n')]
    if damage == 'duplicate-helper':
        entries.append(entries[0])
    with tarfile.open(fileobj=output, mode='w:gz', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': 'b' * 40 if damage == 'commit' else COMMIT}) as package:
        for ordinal, (name, raw) in enumerate(entries):
            entry = tarfile.TarInfo(name); entry.size = len(raw); entry.mode = 0o600
            if damage == 'link-member' and ordinal == 1:
                entry.type = tarfile.SYMTYPE; entry.linkname = 'outside'; entry.size = 0
                package.addfile(entry)
            else:
                package.addfile(entry, io.BytesIO(raw))
    return output.getvalue()


def filesystem_state(root):
    result = {}
    for path in (root, *sorted(root.rglob('*'))):
        info = path.lstat()
        result[str(path.relative_to(root))] = (
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            path.read_bytes() if path.is_file() else None)
    return result


@pytest.fixture
def metadata_env(tmp_path, monkeypatch):
    script = (ROOT / 'script/jenkins/reclaim-build-outputs.ps1').read_text(encoding='utf8')
    program = script.split("$remoteProgram = @'\n", 1)[1].split("\n'@", 1)[0]
    root = tmp_path / 'ci'; root.mkdir(mode=0o700)
    (root / 'inbox').mkdir(mode=0o700); (root / 'verification').mkdir(mode=0o700)
    raw = source_bytes()
    context = {'root': str(root), 'tag': TAG, 'commit': COMMIT,
        'sourceSha256': hashlib.sha256(raw).hexdigest(), 'sourceBytes': len(raw), 'mode': 'Maintenance',
        'instanceId': 'i-synthetic', 'machineId': 'c' * 32,
        'helpers': {name: {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                    for name, content in HELPERS.items()}}
    value = SimpleNamespace(root=root, program=program, context=context, raw=raw,
                            machine=context['machineId'], instance=context['instanceId'], available=8 * 1024 ** 3)
    read_text = Path.read_text
    def machine_read(path, *args, **kwargs):
        if path == Path('/etc/machine-id'):
            return value.machine + '\n'
        return read_text(path, *args, **kwargs)
    class MetadataOpener:
        def open(self, request, timeout):
            assert timeout == 4
            if request.full_url.endswith('/api/token'):
                assert request.get_method() == 'PUT'
                return io.BytesIO(b'synthetic-metadata-token')
            assert request.full_url.endswith('/meta-data/instance-id')
            return io.BytesIO(value.instance.encode())
    monkeypatch.setattr(Path, 'read_text', machine_read)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: MetadataOpener())
    monkeypatch.setattr(os, 'statvfs', lambda path: SimpleNamespace(f_bavail=value.available, f_frsize=1))
    return value


def run_metadata(value, phase, monkeypatch):
    encoded = base64.b64encode(json.dumps(value.context).encode()).decode()
    monkeypatch.setattr(sys, 'argv', ['fixed-maintenance-metadata', encoded, phase])
    # This is the controller embedded in the versioned PS file. The two opaque
    # project helpers remain bytes and are never imported by this fixture.
    exec(compile(value.program, '<fixed-maintenance-metadata>', 'exec'), {'__name__': '__main__'})


def bootstrap(value, monkeypatch, capsys):
    with pytest.raises(SystemExit) as stopped:
        run_metadata(value, 'bootstrap', monkeypatch)
    assert stopped.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ''
    receipt = json.loads(captured.out)
    value.context['uploadIdentity'] = receipt['uploadIdentity']
    return receipt


@pytest.mark.parametrize('identity', ['uid', 'euid', 'machine', 'imds'])
def test_identity_must_match_before_any_maintenance_write(metadata_env, monkeypatch, capsys, identity):
    value = metadata_env
    if identity == 'uid': monkeypatch.setattr(os, 'getuid', lambda: 999)
    if identity == 'euid': monkeypatch.setattr(os, 'geteuid', lambda: 999)
    if identity == 'machine': value.machine = '0' * 32
    if identity == 'imds': value.instance = 'i-other'
    before = filesystem_state(value.root)
    with pytest.raises(ValueError, match='Fixed cleanup admission failed'):
        run_metadata(value, 'bootstrap', monkeypatch)
    assert filesystem_state(value.root) == before
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('failure', ['low-disk', 'existing-attempt'])
def test_bootstrap_refuses_without_overwriting_or_partial_directory_creation(metadata_env, monkeypatch, capsys, failure):
    value = metadata_env
    if failure == 'low-disk':
        value.available = RESERVE + len(value.raw) + CONTROL_BYTES - 1
    else:
        attempt = value.root / 'verification' / TAG; attempt.mkdir(mode=0o700)
        (attempt / 'keep').write_bytes(b'previous owner bytes')
    before = filesystem_state(value.root)
    with pytest.raises(ValueError, match='Fixed cleanup admission failed'):
        run_metadata(value, 'bootstrap', monkeypatch)
    assert filesystem_state(value.root) == before
    assert capsys.readouterr().out == ''


def test_bootstrap_creates_only_fresh_private_directories_and_one_exclusive_source(metadata_env, monkeypatch, capsys):
    value = metadata_env; receipt = bootstrap(value, monkeypatch, capsys)
    inbox = value.root / 'inbox' / TAG; attempt = value.root / 'verification' / TAG
    archive = inbox / 'cleanup-source.tar.gz'; info = archive.lstat()
    assert receipt['status'] == 'UPLOAD_REQUIRED' and receipt['file'] == str(archive)
    assert receipt['sourceSha256'] == value.context['sourceSha256'] and receipt['sourceBytes'] == len(value.raw)
    assert receipt['identity'] == {'instanceId': value.context['instanceId'],
        'machineId': value.context['machineId'], 'executionLocation': 'ECS'}
    assert receipt['requiredBytes'] == RESERVE + len(value.raw) + CONTROL_BYTES
    assert receipt['controlGrowthBytes'] == CONTROL_BYTES and receipt['reserveBytes'] == RESERVE
    assert receipt['uploadIdentity'] == {'device': info.st_dev, 'inode': info.st_ino}
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_uid == 1000 and info.st_nlink == 1 and info.st_size == 0
    assert stat.S_IMODE(inbox.stat().st_mode) == stat.S_IMODE(attempt.stat().st_mode) == 0o700
    assert {path.name for path in inbox.iterdir()} == {'cleanup-source.tar.gz'} and not list(attempt.iterdir())


def test_prepare_preserves_the_uploaded_inode_and_only_extracts_the_two_fixed_helpers(metadata_env, monkeypatch, capsys):
    value = metadata_env; receipt = bootstrap(value, monkeypatch, capsys)
    archive = Path(receipt['file']); archive.write_bytes(value.raw)
    run_metadata(value, 'prepare', monkeypatch)
    captured = capsys.readouterr(); assert captured.err == ''
    result = json.loads(captured.out)
    assert result == {'status': 'PREPARED', 'release': TAG,
                      'sourceSha256': value.context['sourceSha256'], 'mode': 'Maintenance'}
    info = archive.lstat()
    assert {'device': info.st_dev, 'inode': info.st_ino} == receipt['uploadIdentity']
    assert stat.S_IMODE(info.st_mode) == 0o600 and archive.read_bytes() == value.raw
    assert {path.name for path in archive.parent.iterdir()} == {'cleanup-source.tar.gz', *[Path(name).name for name in HELPERS]}
    for name, raw in HELPERS.items():
        path = archive.parent / Path(name).name
        assert path.read_bytes() == raw and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (value.root / 'verification' / TAG / 'verification-receipt.json').exists()


@pytest.mark.parametrize('damage', ['inode', 'bytes', 'sha', 'mode', 'commit', 'duplicate-helper', 'link-member'])
def test_prepare_requires_the_same_private_complete_source_and_closed_helper_members(metadata_env, monkeypatch, capsys, damage):
    value = metadata_env
    if damage in ('commit', 'duplicate-helper', 'link-member'):
        value.raw = source_bytes(damage)
        value.context.update(sourceBytes=len(value.raw), sourceSha256=hashlib.sha256(value.raw).hexdigest())
    receipt = bootstrap(value, monkeypatch, capsys); archive = Path(receipt['file'])
    if damage == 'inode':
        archive.rename(archive.with_name('retained-original'))
    archive.write_bytes(value.raw); archive.chmod(0o600)
    if damage == 'bytes': value.context['sourceBytes'] += 1
    if damage == 'sha': value.context['sourceSha256'] = '0' * 64
    if damage == 'mode': archive.chmod(0o644)
    with pytest.raises(ValueError, match='Fixed cleanup admission failed'):
        run_metadata(value, 'prepare', monkeypatch)
    assert capsys.readouterr().out == ''
    assert not any((archive.parent / Path(name).name).exists() for name in HELPERS)
    assert not (value.root / 'verification' / TAG / 'verification-receipt.json').exists()
