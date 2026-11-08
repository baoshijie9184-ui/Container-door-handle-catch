"""Public build-input custody only; no image execution, network download or shared deletion."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
from urllib.request import ProxyHandler, Request, build_opener

MAX_BYTES = 128 * 1024 ** 2
FLOOR = 2 * 1024 ** 3 + 256 * 1024 ** 2
LOCAL_BASE = Path('D:/AI/lunwen1/DoorHandleCatch/work/jenkins/build-deps')
RECIPE = 'script/jenkins/transfer-candidate-build-tools.py'
SHA = re.compile(r'[a-f0-9]{64}')


def need(value, code):
    if not value:
        raise ValueError(code)


def fingerprint(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def no_links(path):
    for item in (path, *path.parents):
        value = item.lstat()
        need(not stat.S_ISLNK(value.st_mode) and not getattr(value, 'st_file_attributes', 0) & 0x400,
             'LINKED_BUILD_INPUT_PATH')


@contextmanager
def held(path, *, uid=None, maximum=MAX_BYTES, empty=False, private=False, links=(1,)):
    path = Path(path); no_links(path); admitted = path.lstat()
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
                 | getattr(os, 'O_NONBLOCK', 0))
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink in links
             and (0 if empty else 1) <= before.st_size <= maximum, 'BUILD_INPUT_FILE_SHAPE')
        need(uid is None or before.st_uid == uid, 'BUILD_INPUT_OWNER')
        need(not private or stat.S_IMODE(before.st_mode) == 0o600, 'BUILD_INPUT_NOT_PRIVATE')
        need(fingerprint(admitted) == fingerprint(before), 'BUILD_INPUT_OPEN_CHANGED')
        yield fd, before
    finally:
        os.close(fd)


def hash_fd(fd, size):
    os.lseek(fd, 0, os.SEEK_SET); digest = hashlib.sha256(); total = 0
    while True:
        raw = os.read(fd, min(1024 ** 2, size - total + 1))
        if not raw:
            break
        total += len(raw); need(total <= size, 'BUILD_INPUT_GREW'); digest.update(raw)
    need(total == size, 'BUILD_INPUT_TRUNCATED')
    return digest.hexdigest()


def stable(fd, path, before):
    no_links(Path(path))
    need(fingerprint(before) == fingerprint(os.fstat(fd)) == fingerprint(Path(path).lstat()),
         'BUILD_INPUT_CHANGED')


def local_snapshot(path, base):
    path, base = Path(path), Path(base)
    need(path.is_absolute() and base.is_absolute() and '..' not in path.parts
         and path != base and path.is_relative_to(base), 'LOCAL_BUILD_INPUT_OUTSIDE_CACHE')
    no_links(base)
    with held(path) as (fd, before):
        checksum = hash_fd(fd, before.st_size); stable(fd, path, before)
        return {'file': str(path), 'sha256': checksum, 'bytes': before.st_size,
                'fingerprintSha256': hashlib.sha256(json.dumps(fingerprint(before)).encode()).hexdigest()}


def owned_directories(path, root):
    path, root = Path(path), Path(root)
    need(path == root or path.is_relative_to(root), 'BUILD_INPUT_DIRECTORY_OUTSIDE_ROOT')
    while True:
        no_links(path); value = path.lstat()
        need(stat.S_ISDIR(value.st_mode) and value.st_uid == 1000 and not value.st_mode & 0o022,
             'BUILD_INPUT_DIRECTORY_OWNER')
        if path == root:
            return
        path = path.parent


def private_directory(path, *, create=False, root=None):
    path = Path(path)
    if root is not None:
        owned_directories(path.parent, root)
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    no_links(path); value = path.lstat()
    need(stat.S_ISDIR(value.st_mode) and value.st_uid == 1000
         and stat.S_IMODE(value.st_mode) == 0o700, 'BUILD_INPUT_DIRECTORY_NOT_PRIVATE')
    return path


def binding(root, checksum, size):
    need(SHA.fullmatch(checksum or '') and type(size) is int and 0 < size <= MAX_BYTES,
         'BUILD_INPUT_BINDING_INVALID')
    return {'file': str(Path(root) / 'build-inputs/buildkit-v0.34.2' / (checksum + '.tar')),
            'sha256': checksum, 'bytes': size}


def checked_cache(value):
    cache = Path(value['file']); root = cache.parents[2]
    private_directory(cache.parent.parent, root=root); private_directory(cache.parent, root=root)
    with held(value['file'], uid=1000, private=True) as (fd, before):
        need(before.st_size == value['bytes'] and hash_fd(fd, before.st_size) == value['sha256'],
             'EXISTING_BUILD_INPUT_DIFFERS')
        stable(fd, value['file'], before)
    return value


def stage_path(inbox, attempt):
    need(re.fullmatch(r'[a-f0-9]{32}', attempt or ''), 'BUILD_INPUT_ATTEMPT_INVALID')
    return Path(inbox) / ('.buildkit-upload-' + attempt)


def owner_record(context, value, attempt):
    return {'kind': 'doorhandle-public-build-input-upload', **context,
            'buildkitArchive': value, 'attempt': attempt}


def write_exclusive(path, value):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(json.dumps(value, sort_keys=True).encode() + b'\n'); output.flush(); os.fsync(output.fileno())


def probe(root, inbox, context, value, attempt):
    cache = Path(value['file']); parent = Path(root) / 'build-inputs'
    private_directory(inbox, root=root)
    if parent.exists():
        private_directory(parent, root=root)
        if cache.parent.exists():
            private_directory(cache.parent, root=root)
            if cache.exists() or cache.is_symlink():
                return {'status': 'REUSED', 'buildkitArchive': checked_cache(value), **context}
    disk = os.statvfs(root); available = disk.f_bavail * disk.f_frsize
    required = FLOOR + value['bytes'] + 64 * 1024
    need(available >= required, 'BUILD_INPUT_UPLOAD_DISK_RESERVE')
    private_directory(parent, create=True, root=root); private_directory(cache.parent, create=True, root=root)
    stage = stage_path(inbox, attempt); stage.mkdir(mode=0o700); private_directory(stage)
    write_exclusive(stage / 'owner.json', owner_record(context, value, attempt))
    fd = os.open(stage / 'archive.tar', os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600); os.close(fd)
    return {'status': 'UPLOAD_REQUIRED', 'buildkitArchive': value, **context,
            'stagingFile': str(stage / 'archive.tar'), 'availableBytes': available,
            'requiredAvailableBytes': required, 'diskReserveBytes': FLOOR}


def admitted_stage(inbox, context, value, attempt):
    stage = private_directory(stage_path(inbox, attempt), root=Path(inbox).parents[1])
    need({p.name for p in stage.iterdir()} <= {'owner.json', 'archive.tar'}, 'UNKNOWN_BUILD_INPUT_STAGING_ENTRY')
    with held(stage / 'owner.json', uid=1000, private=True, maximum=16384) as (fd, before):
        raw = os.read(fd, 16385); stable(fd, stage / 'owner.json', before)
    need(json.loads(raw) == owner_record(context, value, attempt), 'BUILD_INPUT_STAGING_OWNER_DIFFERS')
    return stage


def cleanup(inbox, context, value, attempt):
    stage = stage_path(inbox, attempt)
    if not stage.exists() and not stage.is_symlink():
        return {'status': 'NO_STAGE', **context}
    stage = admitted_stage(inbox, context, value, attempt)
    directory = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        file = stage / 'archive.tar'
        if file.exists() or file.is_symlink():
            with held(file, uid=1000, private=True, maximum=value['bytes'], empty=True, links=(1, 2)) as (fd, before):
                if before.st_nlink == 2:
                    # Only this proved owner's exact source alias may be removed
                    # after a crash between link publication and source unlink.
                    cache = Path(value['file']); private_directory(cache.parent, root=cache.parents[2])
                    need(cache.exists() and not cache.is_symlink(), 'BUILD_INPUT_PARTIAL_PUBLICATION_NOT_PROVED')
                    with held(cache, uid=1000, private=True, links=(2,)) as (cache_fd, cache_before):
                        need((before.st_dev, before.st_ino) == (cache_before.st_dev, cache_before.st_ino)
                             and before.st_size == cache_before.st_size == value['bytes']
                             and hash_fd(fd, before.st_size) == hash_fd(cache_fd, cache_before.st_size) == value['sha256'],
                             'BUILD_INPUT_PARTIAL_PUBLICATION_NOT_PROVED')
                        stable(cache_fd, cache, cache_before); stable(fd, file, before)
                        os.unlink('archive.tar', dir_fd=directory)
                    cachedir = os.open(cache.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try: os.fsync(cachedir)
                    finally: os.close(cachedir)
                    checked_cache(value)
                else:
                    stable(fd, file, before); os.unlink('archive.tar', dir_fd=directory)
                os.fsync(directory)
        with held(stage / 'owner.json', uid=1000, private=True, maximum=16384) as (fd, before):
            need(json.loads(os.read(fd, 16385)) == owner_record(context, value, attempt),
                 'BUILD_INPUT_STAGING_OWNER_DIFFERS')
            stable(fd, stage / 'owner.json', before); os.unlink('owner.json', dir_fd=directory)
        need(not list(stage.iterdir()), 'BUILD_INPUT_STAGING_NOT_EMPTY')
    finally:
        os.close(directory)
    stage.rmdir()
    return {'status': 'REMOVED_OWNED_STAGING', **context}


def publish(root, inbox, context, value, attempt):
    stage = admitted_stage(inbox, context, value, attempt); cache = Path(value['file'])
    private_directory(cache.parent.parent, root=root); private_directory(cache.parent, root=root)
    disk = os.statvfs(root); need(disk.f_bavail * disk.f_frsize >= FLOOR, 'BUILD_INPUT_PUBLICATION_DISK_RESERVE')
    with held(stage / 'archive.tar', uid=1000, private=True) as (fd, before):
        need(before.st_size == value['bytes'] and hash_fd(fd, before.st_size) == value['sha256'],
             'UPLOADED_BUILD_INPUT_DIFFERS')
        stable(fd, stage / 'archive.tar', before)
        os.fsync(fd)
        directory = os.open(cache.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                # linkat follows our own held FD, never a replaceable staging pathname.
                os.link('/proc/self/fd/' + str(fd), cache.name, dst_dir_fd=directory, follow_symlinks=True)
                linked = cache.lstat(); current = os.fstat(fd)
                need((linked.st_dev, linked.st_ino) == (before.st_dev, before.st_ino)
                     and current.st_nlink == 2 and (stage / 'archive.tar').lstat().st_ino == before.st_ino,
                     'BUILD_INPUT_PUBLICATION_CHANGED')
                os.unlink(stage / 'archive.tar'); os.fsync(directory)
            except FileExistsError:
                checked_cache(value)
        finally:
            os.close(directory)
    checked_cache(value); cleanup(inbox, context, value, attempt)
    return {'status': 'AVAILABLE', 'buildkitArchive': value, **context}


def remote_context(args):
    need(sys.platform == 'linux' and os.getuid() == 1000, 'BUILD_INPUT_REQUIRES_ECS_OWNER')
    root = Path(args.root)
    need(root.is_absolute() and len(root.parts) > 2 and root.parts[1] in ('home', 'srv', 'opt')
         and '..' not in root.parts and re.fullmatch(r'ci-[1-9][0-9]*-[a-f0-9]{12}', args.tag or '')
         and re.fullmatch(r'[a-f0-9]{40}', args.commit or '') and args.tag.endswith('-' + args.commit[:12])
         and SHA.fullmatch(args.source_sha256 or ''), 'BUILD_INPUT_CONTEXT_INVALID')
    no_links(root); base = root.stat(); need(base.st_uid == 1000 and not base.st_mode & 0o022, 'BUILD_INPUT_ROOT_OWNER')
    need(args.instance_id == 'i-2zeieuov2aum486jm1ek'
         and args.machine_id == '1ebe8f77e3104ab6a49a9386e38abd20'
         and Path('/etc/machine-id').read_text().strip() == args.machine_id, 'BUILD_INPUT_MACHINE_DIFFERS')
    opener = build_opener(ProxyHandler({})); url = 'http://100.100.100.200/latest/'
    with opener.open(Request(url + 'api/token', data=b'', method='PUT', headers={'X-aliyun-ecs-metadata-token-ttl-seconds': '60'}), timeout=3) as response:
        token = response.read(4096).decode()
    with opener.open(Request(url + 'meta-data/instance-id', headers={'X-aliyun-ecs-metadata-token': token}), timeout=3) as response:
        need(response.read(256).decode().strip() == args.instance_id, 'BUILD_INPUT_INSTANCE_DIFFERS')
    inbox = private_directory(root / 'inbox' / args.tag, root=root)
    with held(inbox / 'source.tar.gz', uid=1000, maximum=512 * 1024 ** 2) as (fd, before):
        need(hash_fd(fd, before.st_size) == args.source_sha256, 'BUILD_INPUT_SOURCE_SHA_DIFFERS')
        with os.fdopen(os.dup(fd), 'rb') as raw:
            raw.seek(0)
            with tarfile.open(fileobj=raw, mode='r:gz') as source:
                entry = source.getmember(RECIPE)
                need(source.pax_headers.get('comment') == args.commit and entry.isfile()
                     and 0 < entry.size <= 1024 ** 2, 'BUILD_INPUT_FIXED_RECIPE_MISSING')
                with held(Path(__file__), uid=1000, private=True, maximum=1024 ** 2) as (own, shape):
                    need(hash_fd(own, shape.st_size) == hashlib.sha256(source.extractfile(entry).read()).hexdigest(),
                         'BUILD_INPUT_FIXED_RECIPE_DIFFERS')
                    stable(own, Path(__file__), shape)
        stable(fd, inbox / 'source.tar.gz', before)
    return root, inbox, {'release': args.tag, 'commit': args.commit, 'sourceSha256': args.source_sha256,
                         'identity': {'instanceId': args.instance_id, 'machineId': args.machine_id, 'executionLocation': 'ECS'}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('phase', choices=('local', 'probe', 'publish', 'cleanup'))
    parser.add_argument('--archive'); parser.add_argument('--local-root'); parser.add_argument('--root'); parser.add_argument('--tag')
    parser.add_argument('--commit'); parser.add_argument('--source-sha256'); parser.add_argument('--instance-id'); parser.add_argument('--machine-id')
    parser.add_argument('--archive-sha256'); parser.add_argument('--archive-bytes', type=int); parser.add_argument('--attempt')
    args = parser.parse_args(argv)
    if args.phase == 'local':
        need(os.name == 'nt' and Path(args.local_root or '') == LOCAL_BASE, 'LOCAL_BUILD_INPUT_ROOT_INVALID')
        result = local_snapshot(args.archive, LOCAL_BASE)
    else:
        root, inbox, context = remote_context(args); value = binding(root, args.archive_sha256, args.archive_bytes)
        result = {'probe': probe, 'publish': publish, 'cleanup': lambda _root, *rest: cleanup(*rest)}[args.phase](
            root, inbox, context, value, args.attempt)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        print(json.dumps({'status': 'REFUSED', 'errorType': type(error).__name__,
                          'code': str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z0-9_]+', str(error)) else 'BUILD_INPUT_OPERATION_FAILED'}), file=sys.stderr)
        raise SystemExit(2)
