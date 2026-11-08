"""Bounded byte-only Docker-save/BuildKit-export inspection and OCI inputs.

Layers are hashed and optionally gzip-decoded for their DiffID, never extracted
or executed. This preserves an existing immutable worker dependency image when
the isolated BuildKit daemon cannot access the host daemon's image store.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile


MIB = 1024 ** 2
SHA = re.compile(r'sha256:[a-f0-9]{64}')
MANIFEST_TYPES = {'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'}
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json'}
CONFIG_TYPES = {'application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json'}
LAYER_TYPES = {'application/vnd.oci.image.layer.v1.tar': 'application/vnd.oci.image.layer.v1.tar',
               'application/vnd.oci.image.layer.v1.tar+gzip': 'application/vnd.oci.image.layer.v1.tar+gzip',
               'application/vnd.docker.image.rootfs.diff.tar': 'application/vnd.oci.image.layer.v1.tar',
               'application/vnd.docker.image.rootfs.diff.tar.gzip': 'application/vnd.oci.image.layer.v1.tar+gzip'}


def require(value, message):
    if not value:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(MIB), b''): h.update(block)
    return 'sha256:' + h.hexdigest()


def decoded(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate image metadata key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def image_descriptor(value, media_types, metadata=True):
    keys = {'mediaType', 'digest', 'size'}
    require(type(value) is dict and keys <= value.keys()
            and value.keys() <= keys | ({'annotations', 'platform'} if metadata else set())
            and type(value['mediaType']) is str and value['mediaType'] in media_types
            and type(value['digest']) is str and SHA.fullmatch(value['digest'])
            and type(value['size']) is int and value['size'] > 0, 'Invalid typed image descriptor')
    if 'annotations' in value:
        require(type(value['annotations']) is dict and all(type(k) is str and type(v) is str for k, v in value['annotations'].items()),
                'Invalid image descriptor annotations')
    if 'platform' in value:
        platform = value['platform']
        require(type(platform) is dict and {'os', 'architecture'} <= platform.keys()
                and platform.keys() <= {'os', 'architecture', 'variant', 'os.version', 'os.features'}
                and platform['os'] == 'linux' and platform['architecture'] == 'amd64'
                and all(type(platform[k]) is str for k in ('os', 'architecture', 'variant', 'os.version') if k in platform)
                and ('os.features' not in platform or type(platform['os.features']) is list
                     and all(type(v) is str for v in platform['os.features'])), 'Unsupported image descriptor platform')
    return {key: value[key] for key in ('mediaType', 'digest', 'size')}


def oci_source(members, small):
    """Verify the original single-platform graph, retaining its load identity."""
    require('index.json' in members and 'oci-layout' in members
            and decoded(small('oci-layout')) == {'imageLayoutVersion': '1.0.0'}, 'Incomplete engine OCI metadata')
    value = decoded(small('index.json')); allowed = {'index.json', 'oci-layout'}; root = None; expected_media = None
    for depth in range(4):
        require(type(value) is dict and type(value.get('schemaVersion')) is int and value['schemaVersion'] == 2,
                'Unsupported engine OCI graph')
        if expected_media is not None:
            require(value.get('mediaType') == expected_media, 'Engine descriptor media type differs from its raw graph')
        if 'annotations' in value:
            require(type(value['annotations']) is dict and all(type(k) is str and type(v) is str for k, v in value['annotations'].items()),
                    'Invalid engine graph annotations')
        if 'manifests' not in value:
            require(value.keys() <= {'schemaVersion', 'mediaType', 'config', 'layers', 'annotations'}
                    and value.get('mediaType') in MANIFEST_TYPES and type(value.get('layers')) is list
                    and len(value['layers']) <= 256 and root is not None, 'Unsupported engine image manifest')
            config = image_descriptor(value.get('config'), CONFIG_TYPES)
            layers = [image_descriptor(row, LAYER_TYPES) for row in value['layers']]
            for descriptor in [config, *layers]:
                name = 'blobs/sha256/' + descriptor['digest'][7:]; item = members.get(name)
                size = item.size if isinstance(item, tarfile.TarInfo) and item.isfile() else item.get('size') if type(item) is dict else None
                require(size == descriptor['size'], 'Engine OCI config/layer size differs')
                allowed.add(name)
            return root, value, allowed
        require(depth < 3 and value.keys() <= {'schemaVersion', 'mediaType', 'manifests', 'annotations'}
                and ('mediaType' not in value or value['mediaType'] in INDEX_TYPES)
                and type(value['manifests']) is list and len(value['manifests']) == 1, 'Engine export contains another image/platform')
        descriptor = image_descriptor(value['manifests'][0], MANIFEST_TYPES | INDEX_TYPES)
        if root is None: root = descriptor
        name = 'blobs/sha256/' + descriptor['digest'][7:]; raw = small(name)
        require(len(raw) == descriptor['size'] and 'sha256:' + hashlib.sha256(raw).hexdigest() == descriptor['digest'],
                'Engine OCI metadata bytes differ')
        allowed.add(name); value = decoded(raw); expected_media = descriptor['mediaType']
    raise ValueError('Unsupported engine OCI graph depth')


def archive_catalog(package, maximum):
    catalog = {}; size = 0
    for entry in package:
        name = PurePosixPath(entry.name)
        require(name.parts and not name.is_absolute() and '..' not in name.parts and '\\' not in entry.name
                and entry.name not in catalog and (entry.isfile() or entry.isdir())
                and not entry.issparse() and not any('sparse' in key.lower() for key in entry.pax_headers),
                'Unsafe or duplicate image archive member')
        size += entry.size
        require(len(catalog) < 16384 and size <= maximum, 'Image archive exceeds its declared byte/member bound')
        catalog[entry.name] = entry
    return catalog


def source_closure(members, small, source, config_id, layer_digests, layer_media_types=None):
    """Close both legacy save metadata and the engine's content-addressed graph."""
    allowed = {'manifest.json', source['Config'], *source['Layers']}
    for name in source['Layers']:
        if name.endswith('/layer.tar'):
            folder = name.rsplit('/', 1)[0]
            for suffix in ('VERSION', 'json'):
                metadata = folder + '/' + suffix
                if metadata in members:
                    raw = small(metadata)
                    require(raw.strip() == b'1.0' if suffix == 'VERSION' else isinstance(json.loads(raw), dict), 'Unsupported legacy layer metadata')
                    allowed.add(metadata)
    if 'repositories' in members:
        require(isinstance(json.loads(small('repositories')), dict), 'Invalid legacy repository metadata'); allowed.add('repositories')
    load_descriptor = None
    if 'index.json' in members or 'oci-layout' in members:
        load_descriptor, manifest, graph = oci_source(members, small); allowed.update(graph)
        require(manifest['config']['digest'] == config_id
                and [row['digest'] for row in manifest['layers']] == layer_digests
                and source['Config'] == 'blobs/sha256/' + config_id[7:]
                and source['Layers'] == ['blobs/sha256/' + digest[7:] for digest in layer_digests],
                'Legacy and OCI compatibility graphs differ')
        if layer_media_types is not None:
            require([LAYER_TYPES[row['mediaType']] for row in manifest['layers']] == layer_media_types,
                    'Engine OCI layer media type differs from its bytes')
    for name, item in members.items():
        directory = item is None or isinstance(item, tarfile.TarInfo) and item.isdir()
        require(directory or name in allowed, 'Unreferenced image export member is refused')
    return load_descriptor


def inspect_docker_archive(archive, expected_image_id=None, expected_diff_ids=None,
                           maximum_uncompressed_bytes=8 * 1024 ** 3, destination=None, check=None):
    """Inspect one linux/amd64 image; optional destination receives OCI blobs.

    Docker 29 may store Config/Layers under blobs/sha256 and compress layers;
    the compatibility manifest.json remains the explicit one-image identity.
    """
    archive = Path(archive)
    require(archive.is_file() and not archive.is_symlink() and archive.stat().st_nlink == 1,
            'An owned regular image archive is required')
    require(type(maximum_uncompressed_bytes) is int and maximum_uncompressed_bytes > 0,
            'An explicit image expansion bound is required')
    require(archive.stat().st_size <= maximum_uncompressed_bytes + 16 * MIB, 'Image archive transport exceeds its bound')
    if destination is not None:
        destination = Path(destination)
        require(not destination.exists() and not destination.is_symlink(), 'OCI materialization must be fresh')
        destination.mkdir(mode=0o700); (destination / 'blobs/sha256').mkdir(mode=0o700, parents=True)
    def write_blob(raw):
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        if destination is not None:
            path = destination / 'blobs/sha256' / digest[7:]
            if not path.exists():
                with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream: stream.write(raw)
            require(checksum(path) == digest, 'OCI metadata blob changed')
        return {'digest': digest, 'size': len(raw)}
    with tarfile.open(archive, 'r:') as package:
        catalog = archive_catalog(package, maximum_uncompressed_bytes + 16 * MIB)
        with archive.open('rb') as tail:
            tail.seek(package.offset)
            for block in iter(lambda: tail.read(MIB), b''):
                require(not block.strip(b'\0'), 'Nonzero bytes follow the image archive end')
                if check is not None: check()
        def small(name):
            require(name in catalog and catalog[name].isfile() and catalog[name].size <= 4 * MIB,
                    'Required bounded image metadata is missing')
            with package.extractfile(catalog[name]) as stream: return stream.read(4 * MIB + 1)
        if 'manifest.json' in catalog:
            manifest = decoded(small('manifest.json'))
            require(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict),
                    'Only one explicit image may be exported/imported')
            source = manifest[0]
        else:
            _load_descriptor, manifest, _graph = oci_source(catalog, small)
            digests = [manifest['config']['digest'], *[row['digest'] for row in manifest['layers']]]
            require(all(SHA.fullmatch(value) for value in digests), 'OCI content digest is invalid')
            source = {'Config': 'blobs/sha256/' + digests[0][7:],
                      'Layers': ['blobs/sha256/' + value[7:] for value in digests[1:]]}
        require(type(source.get('Config')) is str and type(source.get('Layers')) is list
                and all(type(name) is str for name in source['Layers']), 'Invalid image Config/Layers metadata')
        config_raw = small(source['Config']); config = decoded(config_raw)
        config_id = 'sha256:' + hashlib.sha256(config_raw).hexdigest()
        if source['Config'].startswith('blobs/sha256/'):
            require(source['Config'].split('/')[-1] == config_id[7:], 'Content-addressed image config differs')
        require(type(config) is dict and type(config.get('rootfs')) is dict
                and SHA.fullmatch(config_id) and (expected_image_id is None or config_id == expected_image_id)
                and config.get('os') == 'linux' and config.get('architecture') == 'amd64'
                and config.get('rootfs', {}).get('type') == 'layers', 'Image config identity/platform differs')
        diff_ids = config['rootfs']['diff_ids']; names = source['Layers']
        require(isinstance(names, list) and isinstance(diff_ids, list) and len(names) == len(diff_ids)
                and len(set(names)) == len(names) and len(names) <= 256
                and all(type(x) is str and SHA.fullmatch(x) for x in diff_ids)
                and (expected_diff_ids is None or diff_ids == expected_diff_ids), 'Image layer/DiffID catalog differs')
        layers = []; descriptors = []; expanded_total = 0
        for name, diff_id in zip(names, diff_ids):
            require(name in catalog and catalog[name].isfile(), 'Image layer is not a regular archive member')
            blob = hashlib.sha256(); length = 0; target = None
            temporary = destination / ('layer-' + str(len(layers)) + '.partial') if destination is not None else None
            try:
                if temporary is not None: target = temporary.open('xb'); os.chmod(temporary, 0o600)
                with package.extractfile(catalog[name]) as stream:
                    prefix = stream.read(2); compression = prefix == b'\x1f\x8b'
                    blob.update(prefix); length += len(prefix)
                    if target is not None: target.write(prefix)
                    for chunk in iter(lambda: stream.read(MIB), b''):
                        blob.update(chunk); length += len(chunk)
                        if target is not None: target.write(chunk)
                        if check is not None: check()
                if target is not None: target.flush(); os.fsync(target.fileno()); target.close(); target = None
                digest = 'sha256:' + blob.hexdigest(); expanded = hashlib.sha256(); unpacked = 0
                if name.startswith('blobs/sha256/'):
                    require(name.split('/')[-1] == digest[7:], 'Content-addressed layer bytes differ')
                with package.extractfile(catalog[name]) as raw:
                    stream = gzip.GzipFile(fileobj=raw) if compression else raw
                    for chunk in iter(lambda: stream.read(MIB), b''):
                        unpacked += len(chunk)
                        require(expanded_total + unpacked <= maximum_uncompressed_bytes, 'Image layer expansion exceeds its enforced bound')
                        expanded.update(chunk)
                        if check is not None: check()
                    if compression: stream.close()
                require('sha256:' + expanded.hexdigest() == diff_id and length == catalog[name].size,
                        'Original image layer bytes/DiffID differ')
                expanded_total += unpacked
                # Measure allocation from actual layer headers without applying
                # any path/link. One extra block per entry bounds directory and
                # inode bookkeeping; shared/overwritten entries are not credited.
                allocated, entries = 4096, 0
                with package.extractfile(catalog[name]) as raw:
                    stream = gzip.GzipFile(fileobj=raw) if compression else raw
                    with tarfile.open(fileobj=stream, mode='r|') as layer:
                        for entry in layer:
                            entries += 1
                            require(entries <= 200000 and entry.size >= 0 and not entry.issparse(),
                                    'Layer filesystem metadata exceeds its bound')
                            allocated += ((entry.size + 4095) // 4096) * 4096 + 4096
                            if check is not None: check()
                    if compression: stream.close()
                if temporary is not None:
                    final = destination / 'blobs/sha256' / digest[7:]
                    if final.exists():
                        require(checksum(final) == digest, 'Duplicate OCI layer differs'); temporary.unlink()
                    else: temporary.rename(final)
                media = 'application/vnd.oci.image.layer.v1.tar' + ('+gzip' if compression else '')
                descriptors.append({'mediaType': media, 'digest': digest, 'size': length})
                layers.append({'blobDigest': digest, 'diffId': diff_id, 'bytes': length,
                               'uncompressedBytes': unpacked, 'allocationUpperBoundBytes': allocated,
                               'filesystemEntries': entries, 'mediaType': media})
            finally:
                if target is not None: target.close()
        load_descriptor = source_closure(catalog, small, source, config_id,
                                         [row['blobDigest'] for row in layers], [row['mediaType'] for row in layers])
        config_ref = write_blob(config_raw)
        oci_manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', **config_ref}, 'layers': descriptors}
        descriptor = write_blob(encoded(oci_manifest)); descriptor.update(mediaType=oci_manifest['mediaType'])
        if destination is not None:
            for name, value in [('oci-layout', {'imageLayoutVersion': '1.0.0'}),
                                ('index.json', {'schemaVersion': 2, 'manifests': [descriptor]})]:
                with os.fdopen(os.open(destination / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                    stream.write(encoded(value))
        return {'imageId': config_id, 'manifestDigest': descriptor['digest'], 'configDigest': config_id, 'loadDescriptor': load_descriptor,
                'archiveBytes': archive.stat().st_size, 'archiveSha256': checksum(archive)[7:],
                'compressedBytes': sum(x['bytes'] for x in layers), 'uncompressedLayerBytes': expanded_total,
                'layers': layers, 'layerCount': len(layers), 'config': config}


def export_to_oci(archive, destination, expected_image_id, expected_diff_ids, maximum_uncompressed_bytes, check=None):
    return inspect_docker_archive(archive, expected_image_id, expected_diff_ids,
                                  maximum_uncompressed_bytes, destination, check)


def export_stream_to_oci(origin, destination, expected_image_id, expected_diff_ids,
                         maximum_uncompressed_bytes, before_member, check, *, expected_engine_descriptor=None):
    """Save directly into OCI blobs: no second full Torch TAR on this disk.

    Every next member's real declared bytes are admitted before they are
    written. A complete manifest/config/DiffID verification closes the stream.
    The host dependency image remains untouched and can recreate these inputs.
    """
    if expected_engine_descriptor is not None:
        expected_engine_descriptor = image_descriptor(expected_engine_descriptor, MANIFEST_TYPES | INDEX_TYPES, metadata=False)
    require((type(expected_image_id) is str and SHA.fullmatch(expected_image_id))
            or expected_image_id is None and expected_engine_descriptor is not None,
            'A pinned config or complete engine descriptor is required')
    require(type(expected_diff_ids) is list and len(expected_diff_ids) <= 256
            and all(type(value) is str and SHA.fullmatch(value) for value in expected_diff_ids)
            and type(maximum_uncompressed_bytes) is int and maximum_uncompressed_bytes > 0,
            'Typed image DiffIDs and expansion bound are required')
    destination = Path(destination); require(not destination.exists(), 'Fresh OCI stream destination required')
    (destination / 'blobs/sha256').mkdir(mode=0o700, parents=True)
    members = {}; total = 0; stream_sha = hashlib.sha256(); stream_bytes = 0
    class Observed:
        def read(self, size=-1):
            nonlocal stream_bytes
            block = origin.read(size); stream_sha.update(block); stream_bytes += len(block)
            require(stream_bytes <= maximum_uncompressed_bytes + 16 * MIB, 'Image source stream exceeds its bound')
            return block
    observed = Observed()
    with tarfile.open(fileobj=observed, mode='r|') as package:
        for entry in package:
            name = PurePosixPath(entry.name)
            require(name.parts and not name.is_absolute() and '..' not in name.parts and '\\' not in entry.name
                    and entry.name not in members and (entry.isfile() or entry.isdir()) and not entry.issparse()
                    and not any('sparse' in key.lower() for key in entry.pax_headers), 'Unsafe image source member')
            require(len(members) < 16384 and total + entry.size <= maximum_uncompressed_bytes,
                    'Image source member/byte bound exceeded')
            before_member(entry.name, entry.size); total += entry.size
            if entry.isdir(): members[entry.name] = None; continue
            temporary = destination / ('member-%05d.partial' % len(members)); h = hashlib.sha256(); copied = 0
            with package.extractfile(entry) as source, temporary.open('xb') as output:
                os.chmod(temporary, 0o600)
                for block in iter(lambda: source.read(MIB), b''):
                    copied += len(block); h.update(block); output.write(block); check()
                output.flush(); os.fsync(output.fileno())
            require(copied == entry.size, 'Truncated image source member')
            blob = destination / 'blobs/sha256' / h.hexdigest()
            if blob.exists(): require(checksum(blob) == 'sha256:' + h.hexdigest(), 'Repeated image blob differs'); temporary.unlink()
            else: temporary.rename(blob)
            members[entry.name] = {'path': blob, 'size': copied, 'digest': 'sha256:' + h.hexdigest()}
        for block in iter(lambda: package.fileobj.read(MIB), b''):
            require(not block.strip(b'\0'), 'Nonzero bytes follow the image source archive end'); check()
    for block in iter(lambda: observed.read(MIB), b''):
        require(not block.strip(b'\0'), 'Nonzero bytes follow the image source stream'); check()
    def small(name):
        item = members.get(name)
        require(item is not None and item['size'] <= 4 * MIB, 'Bounded Docker export metadata missing')
        return item['path'].read_bytes()
    if 'manifest.json' in members:
        manifest = decoded(small('manifest.json'))
        require(isinstance(manifest, list) and len(manifest) == 1 and type(manifest[0]) is dict,
                'Docker export must contain exactly one image')
        row = manifest[0]
    else:
        _load_descriptor, value, _graph = oci_source(members, small)
        row = {'Config': 'blobs/sha256/' + value['config']['digest'][7:],
               'Layers': ['blobs/sha256/' + item['digest'][7:] for item in value['layers']]}
    require(type(row.get('Config')) is str and type(row.get('Layers')) is list
            and all(type(name) is str for name in row['Layers']), 'Invalid image Config/Layers metadata')
    # Validate the original raw graph before deriving a config identity from
    # an engine manifest/index handle. The handle never replaces that digest.
    if expected_engine_descriptor is not None:
        require('index.json' in members and oci_source(members, small)[0] == expected_engine_descriptor,
                'Original engine load descriptor differs')
    config_raw = small(row['Config']); config = decoded(config_raw)
    config_id = 'sha256:' + hashlib.sha256(config_raw).hexdigest()
    require(type(config) is dict and type(config.get('rootfs')) is dict
            and (expected_image_id is None or config_id == expected_image_id)
            and config.get('architecture') == 'amd64' and config.get('os') == 'linux'
            and config.get('rootfs', {}).get('type') == 'layers'
            and config.get('rootfs', {}).get('diff_ids') == expected_diff_ids
            and type(row['Layers']) is list and len(row['Layers']) == len(expected_diff_ids)
            and all(type(name) is str for name in row['Layers']) and len(set(row['Layers'])) == len(row['Layers']),
            'Exported dependency image config differs')
    if row['Config'].startswith('blobs/sha256/'):
        require(row['Config'] == 'blobs/sha256/' + config_id[7:], 'Content-addressed image config differs')
    layers = []; descriptors = []; unpacked_total = 0
    keep = {config_id[7:]}
    for name, expected in zip(row['Layers'], expected_diff_ids):
        item = members.get(name); require(item is not None, 'Exported dependency layer missing')
        if name.startswith('blobs/sha256/'):
            require(name == 'blobs/sha256/' + item['digest'][7:], 'Content-addressed layer bytes differ')
        path = item['path']; keep.add(item['digest'][7:])
        with path.open('rb') as raw: compressed = raw.read(2) == b'\x1f\x8b'
        h = hashlib.sha256(); unpacked = 0
        with path.open('rb') as raw:
            source = gzip.GzipFile(fileobj=raw) if compressed else raw
            for block in iter(lambda: source.read(MIB), b''):
                unpacked += len(block); require(unpacked_total + unpacked <= maximum_uncompressed_bytes, 'Dependency expansion exceeds its bound')
                h.update(block); check()
            if compressed: source.close()
        require('sha256:' + h.hexdigest() == expected, 'Dependency DiffID changed')
        allocated, entries = 4096, 0
        with path.open('rb') as raw:
            source = gzip.GzipFile(fileobj=raw) if compressed else raw
            with tarfile.open(fileobj=source, mode='r|') as contents:
                for entry in contents:
                    entries += 1; require(entries <= 200000 and not entry.issparse(), 'Dependency filesystem metadata bound exceeded')
                    allocated += ((entry.size + 4095) // 4096) * 4096 + 4096; check()
            if compressed: source.close()
        unpacked_total += unpacked
        media = 'application/vnd.oci.image.layer.v1.tar' + ('+gzip' if compressed else '')
        descriptors.append({'mediaType': media, 'digest': item['digest'], 'size': item['size']})
        layers.append({'blobDigest': item['digest'], 'diffId': expected, 'bytes': item['size'],
                       'uncompressedBytes': unpacked, 'allocationUpperBoundBytes': allocated,
                       'filesystemEntries': entries, 'mediaType': media})
    load_descriptor = source_closure(members, small, row, config_id,
                                     [item['blobDigest'] for item in layers], [item['mediaType'] for item in layers])
    value = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
             'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'digest': config_id, 'size': len(config_raw)},
             'layers': descriptors}
    raw = encoded(value); manifest_digest = 'sha256:' + hashlib.sha256(raw).hexdigest(); keep.add(manifest_digest[7:])
    target = destination / 'blobs/sha256' / manifest_digest[7:]
    if not target.exists(): target.write_bytes(raw); os.chmod(target, 0o600)
    for target in (destination / 'blobs/sha256').iterdir():
        if target.name not in keep: target.unlink()  # only redundant source metadata we just created
    for name, content in [('oci-layout', {'imageLayoutVersion': '1.0.0'}), ('index.json', {'schemaVersion': 2,
            'manifests': [{'mediaType': value['mediaType'], 'digest': manifest_digest, 'size': len(raw)}]})]:
        with os.fdopen(os.open(destination / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as output: output.write(encoded(content))
    return {'imageId': config_id, 'manifestDigest': manifest_digest, 'configDigest': config_id, 'loadDescriptor': load_descriptor,
            'dockerSaveStreamSha256': stream_sha.hexdigest(), 'dockerSaveStreamBytes': stream_bytes,
            'compressedBytes': sum(item['bytes'] for item in layers), 'uncompressedLayerBytes': unpacked_total,
            'layers': layers, 'layerCount': len(layers)}
