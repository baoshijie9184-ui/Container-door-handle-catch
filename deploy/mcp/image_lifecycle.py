"""Fixed reviewed Fetch image retirement. No arbitrary image, command, mount or path is accepted."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import socket
import tarfile
import time
import uuid
import anyio


class ImageLifecycle:
    def __init__(self, executor, version, package_sha):
        self.executor, self.store = executor, executor.store
        self.version, self.package_sha = version, package_sha
        self.root = self.store.path.parent / 'image-legal'

    async def production_owner(self):
        # Rehearsals share the host daemon but not the production reference database.
        # Their private copied journal must never authorize deletion of a production image.
        hostname = socket.gethostname()
        if not re.fullmatch('[a-f0-9]{12,64}', hostname) or self.store.path != Path('/var/lib/doorhandle-mcp/executions.sqlite3'):
            return False
        code, data = await self.command(['inspect', '--type', 'container', hostname])
        values = json.loads(data) if code == 0 else []
        if len(values) != 1:
            return False
        row = values[0]; labels = row.get('Config', {}).get('Labels') or {}
        mounts = [value for value in row.get('Mounts', []) if value.get('Destination') == '/var/lib/doorhandle-mcp']
        return bool(re.fullmatch('[a-f0-9]{64}', row.get('Id', '')) and row['Id'].startswith(hostname) and row.get('Image') == self.executor.image and row.get('State', {}).get('Running') is True and labels.get('com.docker.compose.project') == 'doorhandlecatch-monolith' and labels.get('com.docker.compose.service') == 'mcp-runner' and len(mounts) == 1 and mounts[0].get('Type') == 'volume' and mounts[0].get('Name') == 'doorhandlecatch-monolith_doorhandle-mcp-executions')

    async def command(self, args, limit=1048576):
        # Bound output while reading, not after accumulating an arbitrary tar stream.
        process = await anyio.open_process(['docker', *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), 'DOCKER_HOST': 'unix:///var/run/docker.sock', 'HOME': '/tmp'})
        data = bytearray()
        try:
            with anyio.fail_after(30):
                while True:
                    try:
                        block = await process.stdout.receive(65536)
                    except anyio.EndOfStream:
                        break
                    data.extend(block)
                    if len(data) > limit:
                        raise ValueError('Docker metadata limit')
                code = await process.wait()
            return code, bytes(data)
        finally:
            with anyio.CancelScope(shield=True):
                if process.returncode is None:
                    process.kill()
                    with anyio.move_on_after(3):
                        await process.wait()
                with anyio.move_on_after(3):
                    await process.aclose()

    async def absent(self, image):
        code, data = await self.command(['image', 'inspect', image])
        if code == 0:
            return False
        code, data = await self.command(['image', 'ls', '-aq', '--no-trunc'])
        if code != 0:
            raise ValueError('Daemon image absence unavailable')
        values = data.decode('ascii').split()
        if any(not re.fullmatch('sha256:[a-f0-9]{64}', value) for value in values):
            raise ValueError('Daemon image inventory invalid')
        return image not in values

    async def inspect(self, image):
        if image not in self.executor.approved_images:
            raise ValueError('Unreviewed image')
        code, data = await self.command(['image', 'inspect', image])
        if code != 0:
            if await self.absent(image):
                return None
            raise ValueError('Image unavailable')
        values = json.loads(data)
        if len(values) != 1 or values[0].get('Id') != image:
            raise ValueError('Image identity')
        value = values[0]; config = value.get('Config') or {}; labels = config.get('Labels') or {}
        if labels.get('doorhandle.mcp.fetch') != 'true' or labels.get('doorhandle.mcp.version') != self.version or labels.get('doorhandle.mcp.package-sha256') != self.package_sha or config.get('Volumes'):
            raise ValueError('Reviewed image metadata')
        return value

    def row(self, image):
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM image_retirement WHERE image=?', (image,)).fetchone()
            return dict(row) if row else None

    def state(self, image, request, state, *, digest=None, absent=False):
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM image_retirement WHERE image=? AND request=?', (image, request)).fetchone()
            if row is None:
                raise ValueError('Retirement identity')
            if row['state'] == 'REMOVED':
                return
            db.execute('UPDATE image_retirement SET state=?,archive_sha256=COALESCE(?,archive_sha256),image_absent=?,updated_at=? WHERE image=? AND request=?', (state, digest, int(absent), int(time.time()), image, request))
            db.execute('INSERT INTO image_retirement_event(image,request,state,created_at) VALUES(?,?,?,?)', (image, request, state, int(time.time())))

    def receipt(self, identity):
        row = self.row(identity['image'])
        if row is None or row['request'] != identity['nonce'] or row['owner'] != identity['owner']:
            raise ValueError('Retirement receipt identity')
        return {'poolId': self.store.pool_id, 'image': row['image'], 'request': row['request'], 'owner': row['owner'],
                'state': row['state'], 'archiveSha256': row['archive_sha256'], 'imageAbsent': bool(row['image_absent'])}

    async def inventory(self):
        items = []
        for image in sorted(self.executor.approved_images):
            row = self.row(image)
            try:
                value = await self.inspect(image)
                size = value.get('Size') if value else None
                if size is not None and (type(size) is not int or size < 0):
                    raise ValueError('Image size')
                items.append({'image': image, 'current': image == self.executor.image, 'present': value is not None,
                              'imageBytes': size, 'state': row['state'] if row else 'ACTIVE'})
            except Exception:
                items.append({'image': image, 'current': image == self.executor.image, 'present': None, 'imageBytes': None, 'state': 'UNKNOWN'})
        legal_bytes, legal_files = self.archive_usage()
        return {'poolId': self.store.pool_id, 'currentImage': self.executor.image, 'protocol': 2, 'items': items, 'legalArchiveBytes': legal_bytes, 'legalArchiveFiles': legal_files, 'cleanupAllowed': await self.production_owner()}

    async def prepare(self, identity):
        if not await self.production_owner():
            raise ValueError('Only the fixed production runner can retire shared daemon images')
        image, request, owner = identity['image'], identity['nonce'], identity['owner']
        if image == self.executor.image or await self.inspect(image) is None:
            raise ValueError('Current or missing image cannot enter a new retirement')
        with self.store.transaction() as db:
            db.execute("INSERT INTO metadata(key,value) VALUES('required_image_policy','4') ON CONFLICT(key) DO UPDATE SET value='4'")
            row = db.execute('SELECT * FROM image_retirement WHERE image=?', (image,)).fetchone()
            if row is None:
                if db.execute('SELECT COUNT(*) FROM image_retirement').fetchone()[0] >= 128:
                    raise ValueError('Retirement history capacity requires explicit archival governance')
                db.execute("INSERT INTO image_retirement(image,request,owner,state,updated_at) VALUES(?,?,?,'FENCED',?)", (image, request, owner, int(time.time())))
                db.execute("INSERT INTO image_retirement_event(image,request,state,created_at) VALUES(?,?,'FENCED',?)", (image, request, int(time.time())))
            elif row['request'] != request or row['owner'] != owner:
                raise ValueError('Image already fenced by another request')
            if row is not None and row['state'] not in ('FENCED', 'PREPARED'):
                return self.receipt_after_transaction(identity, row)
            pending = db.execute("SELECT COUNT(*) FROM execution WHERE image=? AND status<>'REMOVED'", (image,)).fetchone()[0]
            state = 'PREPARED' if pending == 0 else 'FENCED'
            db.execute('UPDATE image_retirement SET state=?,updated_at=? WHERE image=?', (state, int(time.time()), image))
        return self.receipt(identity)

    def receipt_after_transaction(self, identity, row):
        # Build from the row already held by this transaction; do not open a nested SQLite writer.
        return {'poolId': self.store.pool_id, 'image': row['image'], 'request': row['request'], 'owner': row['owner'],
                'state': row['state'], 'archiveSha256': row['archive_sha256'], 'imageAbsent': bool(row['image_absent'])}

    @staticmethod
    def tar_files(data, *, max_file=262144, max_files=600):
        result = {}
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
            for entry in archive:
                path = Path(entry.name)
                if path.is_absolute() or '..' in path.parts or '\\' in entry.name or not (entry.isfile() or entry.isdir()):
                    raise ValueError('Legal archive entry')
                if entry.isdir():
                    continue
                if entry.size < 0 or entry.size > max_file or len(result) >= max_files or entry.name in result:
                    raise ValueError('Legal archive limit')
                stream = archive.extractfile(entry); value = stream.read(max_file + 1)
                if len(value) != entry.size:
                    raise ValueError('Legal archive bytes')
                result[entry.name] = value
        return result

    def archive_path(self, image):
        for path in (self.root, *self.root.parents):
            if path.is_symlink() or path.exists() and path.resolve() != path:
                raise ValueError('Legal archive redirects')
        self.root.mkdir(mode=0o700, exist_ok=True)
        mode = self.root.stat()
        if mode.st_uid != os.geteuid() or mode.st_mode & 0o077:
            raise ValueError('Private legal archive required')
        path = self.root / (image.removeprefix('sha256:') + '.json')
        if path.is_symlink():
            raise ValueError('Legal archive redirect')
        return path

    def archive_usage(self):
        for path in (self.root, *self.root.parents):
            if path.is_symlink() or path.exists() and path.resolve() != path:
                raise ValueError('Legal archive storage redirected')
        if not self.root.exists():
            return 0, 0
        count, total = 0, 0
        for path in self.root.iterdir():
            value = path.lstat()
            if not re.fullmatch('[a-f0-9]{64}\\.json', path.name) or not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_uid != os.geteuid() or value.st_mode & 0o077 or value.st_size > 16 * 1024 * 1024:
                raise ValueError('Legal archive storage unverified')
            count += 1; total += value.st_size
            if count > 128:
                raise ValueError('Legal archive history capacity')
        return total, count

    def verified_archive(self, image, digest):
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            return False
        path = self.archive_path(image)
        if not path.exists():
            return False
        value = path.stat()
        return stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and value.st_uid == os.geteuid() and not value.st_mode & 0o077 and value.st_size <= 16 * 1024 * 1024 and hashlib.sha256(path.read_bytes()).hexdigest() == digest

    async def archive(self, image, request, owner):
        name = 'dh-mcp-legal-' + uuid.UUID(request).hex
        code, data = await self.command(['create', '--pull', 'never', '--name', name, '--network', 'none', '--read-only', '--cap-drop=ALL', '--label', 'doorhandle.mcp.legal=true', '--label', 'doorhandle.mcp.pool='+self.store.pool_id,
            '--label', 'doorhandle.mcp.request='+request, '--label', 'doorhandle.mcp.owner='+str(owner), '--entrypoint', '/bin/false', image])
        if code != 0 or not re.fullmatch('[a-f0-9]{64}', data.decode('ascii').strip()):
            raise ValueError('Legal snapshot container unavailable')
        container = data.decode('ascii').strip()
        code, data = await self.command(['inspect', '--type', 'container', container])
        values = json.loads(data) if code == 0 else []
        if len(values) != 1 or values[0].get('Image') != image or values[0].get('Name') != '/'+name or values[0].get('State', {}).get('Running') is not False or values[0].get('Mounts'):
            raise ValueError('Legal snapshot identity')
        documents = {}
        for source, limit in [('manifest.json', 1048576), ('requirements.lock', 262144), ('licenses', 8 * 1024 * 1024)]:
            code, data = await self.command(['cp', container+':/opt/fetch/'+source, '-'], limit)
            if code != 0:
                raise ValueError('Legal snapshot missing')
            files = self.tar_files(data, max_file=524288 if source == 'manifest.json' else 262144)
            if source == 'licenses':
                if not files or any(not re.fullmatch(r'licenses/[0-9]+-[0-9]+\.txt', key) for key in files):
                    raise ValueError('Legal directory scope')
            elif set(files) != {source}:
                raise ValueError('Legal document scope')
            if set(files) & set(documents):
                raise ValueError('Repeated legal document')
            documents.update(files)
        manifest = json.loads(documents['manifest.json'])
        if manifest.get('version') != self.version or manifest.get('packageSha256') != self.package_sha or not documents.get('requirements.lock'):
            raise ValueError('Legal snapshot release')
        licenses = manifest.get('licenses')
        if not isinstance(licenses, list) or not 1 <= len(licenses) <= 500:
            raise ValueError('Legal snapshot metadata')
        expected = {'manifest.json', 'requirements.lock'}
        for item in licenses:
            path = item.get('path', '')
            if not re.fullmatch(r'licenses/[0-9]+-[0-9]+\.txt', path) or path in expected or path not in documents or hashlib.sha256(documents[path]).hexdigest() != item.get('sha256'):
                raise ValueError('Legal snapshot hash')
            expected.add(path)
        if set(documents) != expected:
            raise ValueError('Legal snapshot completeness')
        body = json.dumps({'protocol': 1, 'image': image, 'version': self.version, 'packageSha256': self.package_sha,
                           'files': {key: base64.b64encode(value).decode('ascii') for key, value in sorted(documents.items())}}, sort_keys=True, separators=(',', ':')).encode()
        if len(body) > 16 * 1024 * 1024:
            raise ValueError('Legal snapshot size')
        path = self.archive_path(image)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        digest = hashlib.sha256(body).hexdigest()
        self.state(image, request, 'ARCHIVING', digest=digest)
        if not self.verified_archive(image, digest):
            raise ValueError('Legal snapshot durability')
        # This stopped container was created by this one request. No force or name-only deletion.
        code, _ = await self.command(['rm', container])
        if code != 0 or not await self.executor.absent(container, 'id'):
            raise ValueError('Legal snapshot cleanup unverified')
        return digest

    async def delete(self, identity):
        if not await self.production_owner():
            raise ValueError('Only the fixed production runner can delete shared daemon images')
        image, request = identity['image'], identity['nonce']
        if image == self.executor.image or image not in self.executor.approved_images:
            raise ValueError('Reviewed retired image required')
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM image_retirement WHERE image=?', (image,)).fetchone()
            if row is None or row['request'] != request or row['owner'] != identity['owner']:
                raise ValueError('Retirement approval identity')
            if row['state'] != 'PREPARED':
                return self.receipt_after_transaction(identity, row)
            if db.execute("SELECT COUNT(*) FROM execution WHERE image=? AND status<>'REMOVED'", (image,)).fetchone()[0]:
                raise ValueError('Unreleased image executions')
            db.execute("UPDATE image_retirement SET state='ARCHIVING',updated_at=? WHERE image=?", (int(time.time()), image))
            db.execute("INSERT INTO image_retirement_event(image,request,state,created_at) VALUES(?,?,'ARCHIVING',?)", (image, request, int(time.time())))
        try:
            if await self.inspect(image) is None:
                raise ValueError('Image disappeared before legal preservation')
            digest = await self.archive(image, request, identity['owner'])
            code, containers = await self.command(['ps', '-aq', '--no-trunc', '--filter', 'ancestor='+image])
            if code != 0 or containers.strip():
                raise ValueError('Image still referenced by a container')
            self.state(image, request, 'REMOVING', digest=digest)
            await self.command(['image', 'rm', '--no-prune', image])  # Never force; do not remove parent images.
            if not await self.absent(image) or not self.verified_archive(image, digest):
                raise ValueError('Image removal unverified')
            self.state(image, request, 'REMOVED', digest=digest, absent=True)
        except BaseException:
            self.state(image, request, 'NEEDS_REVIEW')
            raise
        return self.receipt(identity)

    async def reconcile(self, identity):
        row = self.row(identity['image'])
        if row is None or row['request'] != identity['nonce'] or row['owner'] != identity['owner']:
            raise ValueError('Retirement receipt identity')
        # Observation only. Never recreate a legal container, re-copy data or resend image rm.
        if row['state'] != 'REMOVED' and self.verified_archive(row['image'], row['archive_sha256']):
            legal = 'dh-mcp-legal-' + uuid.UUID(row['request']).hex
            if await self.executor.absent(legal) and await self.absent(row['image']):
                self.state(row['image'], row['request'], 'REMOVED', digest=row['archive_sha256'], absent=True)
        return self.receipt(identity)
