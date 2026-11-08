"""Pure boundary regressions; executed by Jenkins on ECS, never locally."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


RES = load('build_resources_under_test', 'script/docker/compact-build-resources.py')
OCI = load('image_inputs_under_test', 'script/docker/compact-image-inputs.py')
CONTEXT = {'release': 'ci-123-' + 'a' * 12, 'commit': 'a' * 40, 'sourceSha256': 'b' * 64,
           'identity': {'instanceId': 'i-fixture', 'machineId': 'c' * 32, 'executionLocation': 'ECS'}}


def tar_bytes(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as package:
        for name, raw in members:
            entry = tarfile.TarInfo(name); entry.size = len(raw); package.addfile(entry, io.BytesIO(raw))
    return output.getvalue()


def image_bytes():
    layer = tar_bytes([('app/source.txt', b'actual dependency bytes\n')])
    diff = 'sha256:' + hashlib.sha256(layer).hexdigest()
    config = OCI.encoded({'architecture': 'amd64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': [diff]}, 'config': {'Env': ['MODE=fixture']}})
    image = 'sha256:' + hashlib.sha256(config).hexdigest()
    manifest = json.dumps([{'Config': image[7:] + '.json', 'Layers': ['dependency/layer.tar'], 'RepoTags': ['fixture:unused']}]).encode()
    return tar_bytes([('manifest.json', manifest), (image[7:] + '.json', config), ('dependency/layer.tar', layer)]), image, diff


def official_oci_fixture():
    layer = gzip.compress(tar_bytes([('app/source.txt', b'immutable upstream bytes\n')]), mtime=0)
    diff = 'sha256:' + hashlib.sha256(gzip.decompress(layer)).hexdigest()
    config = OCI.encoded({'architecture': 'amd64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': [diff]},
                          'config': {'User': '1000:1000', 'Env': []}})
    image = 'sha256:' + hashlib.sha256(config).hexdigest(); blob = 'sha256:' + hashlib.sha256(layer).hexdigest()
    manifest = OCI.encoded({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'digest': image, 'size': len(config)},
        'layers': [{'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip', 'digest': blob, 'size': len(layer)}]})
    checksum = 'sha256:' + hashlib.sha256(manifest).hexdigest()
    descriptor = {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': checksum, 'size': len(manifest)}
    members = {'oci-layout': OCI.encoded({'imageLayoutVersion': '1.0.0'}),
        'index.json': OCI.encoded({'schemaVersion': 2, 'manifests': [descriptor]}),
        'blobs/sha256/' + checksum[7:]: manifest, 'blobs/sha256/' + image[7:]: config,
        'blobs/sha256/' + blob[7:]: layer}
    return members, image, diff, checksum, len(layer)


def cache_archive(root, raw):
    checksum = hashlib.sha256(raw).hexdigest(); folder = root / 'build-inputs' / ('buildkit-' + RES.VERSION)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.parent.chmod(0o700); folder.chmod(0o700)
    path = folder / (checksum + '.tar'); path.write_bytes(raw); path.chmod(0o600)
    return {'file': str(path), 'sha256': checksum, 'bytes': len(raw)}


def archive_actor(directory):
    directory.mkdir(mode=0o700)
    actor = SimpleNamespace(directory=directory, phases=[], checks=0, calls=[], builder=None, finishes=[])
    actor.begin = lambda name, growth, measured, memory: actor.phases.append((name, growth, measured, memory))
    actor.check = lambda: setattr(actor, 'checks', actor.checks + 1)
    actor.finish = lambda status: actor.finishes.append(status) or {'status': status}
    def run(args, name, **_kwargs):
        actor.calls.append((name, args)); log = directory / (name + '.log'); log.write_text(RES.VERSION); return log
    actor.run = run
    return actor


def evidence(directory):
    baseline = {'monotonic': 1.0, 'diskAvailableBytes': 16 * RES.GIB, 'memoryAvailableBytes': 8 * RES.GIB, 'filesystemBlockBytes': 4096}
    phases = []
    probes = []
    builder = {'id': 'd' * 64, 'image': RES.IMAGE_ID, 'running': True, 'pid': 1234, 'memoryLimitBytes': RES.BUILDER_MEMORY,
               'currentBytes': RES.MIB, 'peakBytes': 2 * RES.MIB, 'oomKills': 0, 'writeRateLimitBytesPerSecond': 64 * RES.MIB}
    names = ['source-extraction', 'stage-contexts', *['build-' + service for service in RES.SERVICES],
             *['load-' + service for service in RES.SERVICES], 'candidate-jar-readback']
    for index, phase in enumerate(names, 1):
        name = phase + '-%03d' % index
        plan = RES.phase_plan({**CONTEXT, 'ownerToken': 'e' * 24}, name, baseline, RES.GIB, RES.BUILDER_MEMORY, {'actualInputBytes': 1024})
        path = directory / ('phase-%02d.json' % index); path.write_bytes(RES.encoded(plan))
        phases.append({'file': path.name, 'sha256': RES.digest(path)})
        probes.append({**baseline, 'monotonic': 1.0 + index * .05, 'phase': name, 'builder': builder})
    raw = b''.join(RES.encoded(row) + b'\n' for row in probes); (directory / 'resource-probes.jsonl').write_bytes(raw)
    image = {'imageId': 'sha256:' + '1' * 64, 'ociArchiveSha256': '2' * 64, 'ociArchiveBytes': 20480,
             'controlledDockerfileSha256': '3' * 64, 'inputContext': {'sha256': '4' * 64},
             'layers': [{'diffId': 'sha256:' + '5' * 64, 'blobDigest': 'sha256:' + '6' * 64, 'allocationUpperBoundBytes': 8192}]}
    summary = {'version': 1, 'kind': 'doorhandle-candidate-build-resources', **CONTEXT, 'ownerToken': 'e' * 24,
               'status': 'PASS', 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False,
               'baselineProbe': baseline, 'finalProbe': {**baseline, 'monotonic': probes[-1]['monotonic'] + .05}, 'phases': phases, 'probeFile': 'resource-probes.jsonl',
               'probeSha256': hashlib.sha256(raw).hexdigest(), 'monitorFailure': None, 'originalDataChanged': False,
               'cleanup': {'creatorStopped': True, 'builderStopped': True, 'daemonImportTerminated': True, 'builderContainerId': 'd' * 64},
               'build': {'images': {name: copy.deepcopy(image) for name in RES.SERVICES}},
               'applicationJar': {'sha256': '7' * 64, 'bytes': 4096}}
    (directory / 'resource-summary.json').write_bytes(RES.encoded(summary))
    return summary, probes


class CompactBuildResourceTests(unittest.TestCase):
    def test_optional_archive_arguments_keep_the_original_default_and_exact_cache_contract(self):
        args = SimpleNamespace(root='/home/ecs-user/ci', prepare_candidate_builder=False)
        self.assertIsNone(RES.buildkit_input(args))
        fields = dict(buildkit_archive='/home/ecs-user/ci/build-inputs/buildkit-' + RES.VERSION + '/' + 'a' * 64 + '.tar',
                      buildkit_archive_sha256='a' * 64, buildkit_archive_bytes=10240)
        args.prepare_candidate_builder = True
        self.assertEqual({'file': fields['buildkit_archive'], 'sha256': 'a' * 64, 'bytes': 10240},
                         RES.buildkit_input(SimpleNamespace(**vars(args), **fields)))
        for change in ({'buildkit_archive': None}, {'buildkit_archive_sha256': ''}, {'buildkit_archive_bytes': True},
                       {'buildkit_archive_bytes': RES.BUILDKIT_ARCHIVE_MAX + 1}, {'buildkit_archive': fields['buildkit_archive'] + '/other'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                RES.buildkit_input(SimpleNamespace(**vars(args), **dict(fields, **change)))
        args.prepare_candidate_builder = False
        invalid = SimpleNamespace(**vars(args), **fields)
        with self.assertRaises(ValueError): RES.buildkit_input(invalid)
        with mock.patch.object(RES, 'Supervisor') as supervisor, mock.patch.object(RES.subprocess, 'run') as docker:
            with self.assertRaises(ValueError): RES.prepare_tools(invalid, CONTEXT['identity'], ROOT / 'deploy/buildkit')
            supervisor.assert_not_called(); docker.assert_not_called()

    def test_official_archive_preserves_raw_manifest_config_blobs_and_real_diffid_measurement(self):
        members, image, diff, checksum, size = official_oci_fixture()
        with tempfile.TemporaryDirectory() as temporary, mock.patch.multiple(RES, REFERENCE='docker.io/moby/buildkit@' + checksum,
                IMAGE_ID=image, BUILDKIT_LAYER_BYTES=size):
            root = Path(temporary); binding = cache_archive(root, tar_bytes(list(members.items())))
            actor = archive_actor(root / 'output'); destination = actor.directory / 'official-oci'
            proof = RES.archive_layout(actor, root, binding, destination, OCI)
            self.assertEqual(image, proof['imageId']); self.assertEqual(size, proof['compressedBytes'])
            self.assertEqual(diff, proof['layers'][0]['diffId']); self.assertGreater(actor.checks, 0)
            self.assertEqual({'official-archive-validation', 'copy-official-oci', 'measure-official-oci'}, {row[0] for row in actor.phases})
            self.assertEqual(proof['manifestDigest'], json.loads((destination / 'index.json').read_bytes())['manifests'][0]['digest'])
            self.assertEqual(binding, RES.validate_buildkit_archive(root, binding))

    def test_archive_rejects_wrong_pins_extra_graph_metadata_types_and_blob_changes(self):
        members, image, _diff, checksum, size = official_oci_fixture()
        for change in ('wrong-pin', 'wrong-config', 'extra-index', 'index-bool', 'size-bool', 'duplicate-json',
                       'extra-blob', 'missing-blob', 'corrupt-blob', 'short-blob', 'duplicate-member'):
            altered = copy.deepcopy(members); index = json.loads(altered['index.json']); layers = json.loads(altered['blobs/sha256/' + checksum[7:]])['layers']
            layer = 'blobs/sha256/' + layers[0]['digest'][7:]
            if change == 'extra-index': index['manifests'].append(copy.deepcopy(index['manifests'][0]))
            if change == 'index-bool': index['schemaVersion'] = True
            if change == 'size-bool': index['manifests'][0]['size'] = True
            altered['index.json'] = OCI.encoded(index)
            if change == 'duplicate-json': altered['index.json'] = altered['index.json'].replace(b'"schemaVersion":2', b'"schemaVersion":2,"schemaVersion":2')
            if change == 'extra-blob': altered['blobs/sha256/' + 'f' * 64] = b'foreign'
            if change == 'missing-blob': del altered[layer]
            if change == 'corrupt-blob': altered[layer] = b'x' + altered[layer][1:]
            if change == 'short-blob': altered[layer] = altered[layer][:-1]
            entries = list(altered.items())
            if change == 'duplicate-member': entries.append(('oci-layout', altered['oci-layout']))
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary, \
                    mock.patch.multiple(RES, REFERENCE='docker.io/moby/buildkit@' + ('sha256:' + 'f' * 64 if change == 'wrong-pin' else checksum),
                                        IMAGE_ID='sha256:' + 'f' * 64 if change == 'wrong-config' else image, BUILDKIT_LAYER_BYTES=size):
                root = Path(temporary); binding = cache_archive(root, tar_bytes(entries)); actor = archive_actor(root / 'output')
                with self.assertRaises(ValueError): RES.archive_layout(actor, root, binding, actor.directory / 'official-oci', OCI)

    def test_raw_archive_header_gate_precedes_pax_sparse_and_link_dispatch(self):
        for kind in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_SPARSE, tarfile.SYMTYPE, tarfile.LNKTYPE):
            header = tarfile.TarInfo('index.json'); header.type = kind; header.size = 2 * RES.GIB
            raw = header.tobuf(format=tarfile.USTAR_FORMAT) + b'\0' * 1024
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); binding = cache_archive(root, raw); actor = archive_actor(root / 'output')
                with mock.patch.object(tarfile.TarInfo, '_proc_pax', side_effect=AssertionError('PAX must not allocate')), \
                        mock.patch.object(tarfile.TarInfo, '_proc_gnusparse_00', side_effect=AssertionError('Sparse must not dispatch')):
                    with self.assertRaises(ValueError): RES.archive_layout(actor, root, binding, actor.directory / 'official-oci', OCI)

    def test_archive_transport_and_owned_cache_freshness_are_independent(self):
        members, _image, _diff, _checksum, _size = official_oci_fixture(); raw = tar_bytes(list(members.items()))
        for change in ('sha', 'size', 'mode', 'hardlink', 'symlink', 'parent-write', 'fifo', 'held-metadata'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); binding = cache_archive(root, raw); path = Path(binding['file'])
                if change == 'sha': path.write_bytes(b'x' + raw[1:])
                if change == 'size': path.write_bytes(raw[:-1])
                if change == 'mode': path.chmod(0o644)
                if change == 'hardlink': os.link(path, path.with_suffix('.alias'))
                if change == 'symlink': path.rename(path.with_suffix('.original')); path.symlink_to(path.with_suffix('.original'))
                if change == 'parent-write': path.parent.chmod(0o777)
                if change == 'fifo': path.unlink(); os.mkfifo(path, 0o600)
                with self.assertRaises(ValueError):
                    if change == 'held-metadata':
                        with RES.buildkit_archive_source(root, binding, lambda: None):
                            before = path.stat(); os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
                    else: RES.validate_buildkit_archive(root, binding)

    def test_archive_rejects_nonzero_tail_and_missing_tar_terminator(self):
        members, image, _diff, checksum, size = official_oci_fixture(); raw = tar_bytes(list(members.items()))
        end = sum(512 + ((len(value) + 511) // 512) * 512 for value in members.values())
        for changed in (raw + b'nonzero-tail', raw[:end]):
            with self.subTest(size=len(changed)), tempfile.TemporaryDirectory() as temporary, \
                    mock.patch.multiple(RES, REFERENCE='docker.io/moby/buildkit@' + checksum, IMAGE_ID=image, BUILDKIT_LAYER_BYTES=size):
                root = Path(temporary); binding = cache_archive(root, changed); actor = archive_actor(root / 'output')
                with self.assertRaises(ValueError): RES.archive_layout(actor, root, binding, actor.directory / 'official-oci', OCI)

    def test_offline_preparation_keeps_real_load_bootstrap_version_stop_and_current_original_checks(self):
        members, image, _diff, checksum, size = official_oci_fixture()
        for failure in (None, 'load', 'version', 'original-drift'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary, \
                    mock.patch.multiple(RES, REFERENCE='docker.io/moby/buildkit@' + checksum, IMAGE_ID=image, BUILDKIT_LAYER_BYTES=size):
                root = Path(temporary); binding = cache_archive(root, tar_bytes(list(members.items())))
                inbox = root / 'inbox' / CONTEXT['release']; inbox.mkdir(mode=0o700, parents=True)
                recipe = root / 'recipe'; recipe.mkdir(mode=0o700)
                for name, source in [('LICENSE', ROOT / 'deploy/buildkit/LICENSE'),
                                     *[(Path(relative).name, ROOT / relative) for relative in RES.RECIPES]]:
                    (recipe / name).write_bytes(source.read_bytes())
                actor = archive_actor(inbox / 'candidate-build-tools'); real_run = actor.run
                def run(arguments, name, **kwargs):
                    if failure == 'load' and name == 'official-image-load': raise ValueError('Fixture load failed')
                    path = real_run(arguments, name, **kwargs)
                    if failure == 'version' and name == 'buildctl-version': path.write_text('wrong-version')
                    return path
                actor.run = run
                actor.docker = lambda *args: json.dumps([{'Id': image, 'Os': 'linux', 'Architecture': 'amd64', 'Size': 1,
                    'RootFS': {'Layers': []}, 'Config': {'User': '1000:1000', 'Env': []}}]).encode()
                def bootstrap(value):
                    self.assertTrue(any(name == 'official-image-load' for name, _args in value.calls))
                    value.builder = {'id': 'd' * 64}
                    if failure == 'original-drift': Path(binding['file']).write_bytes(b'changed')
                args = SimpleNamespace(root=str(root), tag=CONTEXT['release'], commit=CONTEXT['commit'],
                    source_sha256=CONTEXT['sourceSha256'], prepare_candidate_builder=True,
                    buildkit_archive=binding['file'], buildkit_archive_sha256=binding['sha256'], buildkit_archive_bytes=binding['bytes'])
                with mock.patch.object(RES, 'Supervisor', return_value=actor), mock.patch.object(RES, 'load_module', return_value=OCI), \
                        mock.patch.object(RES.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), \
                        mock.patch.object(RES, 'host_diff_ids', return_value=set()), mock.patch.object(RES, 'bootstrap_builder', side_effect=bootstrap), \
                        mock.patch.object(RES, 'registry_layout', side_effect=AssertionError('Offline input may not fetch the network')):
                    if failure is not None:
                        with self.assertRaises(ValueError): RES.prepare_tools(args, CONTEXT['identity'], recipe)
                        self.assertFalse((actor.directory / 'tools.json').exists()); self.assertEqual(['FAILED'], actor.finishes)
                    else:
                        result = RES.prepare_tools(args, CONTEXT['identity'], recipe)
                        value = json.loads((actor.directory / 'tools.json').read_bytes())
                        self.assertEqual('PREPARED', result['status']); self.assertEqual(binding, value['buildkitArchive'])
                        self.assertTrue(value['ociImageLoadVerified']); self.assertEqual(['PASS'], actor.finishes)
                        self.assertEqual(['official-image-load', 'buildctl-version', 'buildkitd-version'], [name for name, _args in actor.calls])

    def test_actual_floor_and_memory_admission_are_independent(self):
        baseline = {'diskAvailableBytes': RES.DISK_FLOOR + RES.MIB, 'memoryAvailableBytes': RES.BUILDER_MEMORY + RES.MEMORY_FLOOR}
        self.assertEqual('MEASUREMENT_ADMITTED', RES.phase_plan(CONTEXT, 'fixture', baseline, RES.MIB, RES.BUILDER_MEMORY, {'bytes': 1})['status'])
        for field in ('diskAvailableBytes', 'memoryAvailableBytes'):
            with self.subTest(field=field):
                smaller = dict(baseline); smaller[field] -= 1
                self.assertEqual('FAIL_CLOSED', RES.phase_plan(CONTEXT, 'fixture', smaller, RES.MIB, RES.BUILDER_MEMORY, {'bytes': 1})['status'])

    def test_image_tags_do_not_double_count_shared_image_identity(self):
        row = {'Id': 'sha256:' + '1' * 64, 'Os': 'linux', 'Architecture': 'amd64', 'Size': 987654321,
               'Config': {'Env': ['MODE=normal']}, 'RootFS': {'Layers': ['sha256:' + '2' * 64]}}
        result = RES.unique_image_inputs([row, copy.deepcopy(row)])
        self.assertEqual(1, len(result)); self.assertEqual(row['RootFS']['Layers'], result[row['Id']]['diffIds'])
        row['Config']['Env'] = ['API_KEY=never-export-this']
        with self.assertRaises(ValueError): RES.unique_image_inputs([row])

    def test_builtin_frontend_replaces_only_unique_reviewed_from(self):
        body = '# syntax=docker/dockerfile:1\nFROM sha256:' + 'a' * 64 + '\nCOPY source.py /app/source.py\nUSER app\n'
        actual = RES.effective_dockerfile(body, 'sha256:' + 'a' * 64, 'dh_base_worker')
        self.assertNotIn('syntax=', actual); self.assertIn('COPY source.py /app/source.py\nUSER app', actual)
        with self.assertRaises(ValueError): RES.effective_dockerfile(body + 'FROM other\n', 'sha256:' + 'a' * 64, 'dh_base_worker')

    def test_docker_stream_to_oci_preserves_image_diffid_and_all_bytes(self):
        raw, image, diff = image_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'oci'; admitted = []
            result = OCI.export_stream_to_oci(io.BytesIO(raw), directory, image, [diff], RES.MIB,
                lambda name, size: admitted.append((name, size)), lambda: None)
            self.assertEqual(image, result['imageId']); self.assertEqual(diff, result['layers'][0]['diffId'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), result['dockerSaveStreamSha256'])
            archive = Path(temporary) / 'output.tar'
            with tarfile.open(archive, 'w') as package:
                for path in sorted(directory.rglob('*')):
                    if path.is_file(): package.add(path, arcname=path.relative_to(directory).as_posix())
            checked = OCI.inspect_docker_archive(archive, image, [diff], RES.MIB)
            self.assertEqual(result['manifestDigest'], checked['manifestDigest']); self.assertEqual(3, len(admitted))
            self.assertGreater(checked['layers'][0]['allocationUpperBoundBytes'], len(b'actual dependency bytes\n'))

    def test_layer_corruption_and_expansion_are_rejected(self):
        raw, image, diff = image_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'image.tar'; archive.write_bytes(raw)
            with self.assertRaises(ValueError): OCI.inspect_docker_archive(archive, image, ['sha256:' + 'f' * 64], RES.MIB)
            with self.assertRaises(ValueError): OCI.inspect_docker_archive(archive, image, [diff], 10)
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as package:
                members = [(row.name, package.extractfile(row).read()) for row in package]
            compressed = [(name, gzip.compress(value) if name == 'dependency/layer.tar' else value) for name, value in members]
            archive.write_bytes(tar_bytes(compressed))
            proof = OCI.inspect_docker_archive(archive, image, [diff], RES.MIB)
            self.assertEqual(diff, proof['layers'][0]['diffId']); self.assertTrue(proof['layers'][0]['mediaType'].endswith('+gzip'))
            with self.assertRaises(ValueError): OCI.inspect_docker_archive(archive, image, [diff], 10239)

    def test_engine_oci_only_save_stream_has_same_pinned_identity(self):
        raw, image, diff = image_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); first = root / 'first'
            OCI.export_stream_to_oci(io.BytesIO(raw), first, image, [diff], RES.MIB, lambda *_: None, lambda: None)
            members = [(path.relative_to(first).as_posix(), path.read_bytes()) for path in sorted(first.rglob('*')) if path.is_file()]
            stream = tar_bytes(members)
            proof = OCI.export_stream_to_oci(io.BytesIO(stream), root / 'second', image, [diff], RES.MIB, lambda *_: None, lambda: None)
            self.assertEqual(image, proof['imageId']); self.assertEqual(diff, proof['layers'][0]['diffId'])
            self.assertEqual(hashlib.sha256(stream).hexdigest(), proof['dockerSaveStreamSha256'])

    def test_unreferenced_regular_member_is_not_silently_imported(self):
        raw, image, diff = image_bytes(); extra = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as package:
            members = [(row.name, package.extractfile(row).read()) for row in package]
        members.append(('unreviewed-private-file', b'not part of the image'))
        extra.write(tar_bytes(members))
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'image.tar'; archive.write_bytes(extra.getvalue())
            with self.assertRaises(ValueError): OCI.inspect_docker_archive(archive, image, [diff], RES.MIB)
            with self.assertRaises(ValueError): OCI.export_stream_to_oci(io.BytesIO(extra.getvalue()), Path(temporary) / 'oci',
                image, [diff], RES.MIB, lambda *_: None, lambda: None)
            archive.write_bytes(raw + b'not-zero-trailing-content')
            with self.assertRaises(ValueError): OCI.inspect_docker_archive(archive, image, [diff], RES.MIB)
            with self.assertRaises(ValueError): OCI.export_stream_to_oci(io.BytesIO(archive.read_bytes()), Path(temporary) / 'tail-oci',
                image, [diff], RES.MIB, lambda *_: None, lambda: None)

    def test_archive_never_extracts_links_or_paths(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE), ('link', tarfile.SYMTYPE), ('hardlink', tarfile.LNKTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / 'bad.tar'
                with tarfile.open(archive, 'w') as package:
                    entry = tarfile.TarInfo(name); entry.type = kind; entry.linkname = 'outside'; package.addfile(entry)
                with self.assertRaises(ValueError): OCI.inspect_docker_archive(archive, maximum_uncompressed_bytes=RES.MIB)

    def test_complete_resource_files_are_recomputed_and_bound_to_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary); directory = source / 'work/candidate-build-resources'; directory.mkdir(parents=True)
            summary, _ = evidence(directory)
            reference = RES.validate_files(directory, CONTEXT)
            build = {'buildResourceEvidence': reference, 'images': {name: item['imageId'] for name, item in summary['build']['images'].items()},
                     'applicationJarSha256': '7' * 64, 'applicationJarBytes': 4096}
            self.assertEqual(reference, RES.validate_candidate(build, source, CONTEXT))
            build['images']['backend'] = 'sha256:' + '9' * 64
            with self.assertRaises(ValueError): RES.validate_candidate(build, source, CONTEXT)

    def test_rehashed_raw_pressure_oom_sampling_and_cleanup_do_not_pass(self):
        for kind in ('disk', 'memory', 'oom', 'late', 'growth', 'cleanup', 'source', 'phase'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary); summary, probes = evidence(directory)
                if kind == 'disk': probes[0]['diskAvailableBytes'] = RES.DISK_FLOOR - 1
                if kind == 'memory': probes[0]['memoryAvailableBytes'] = RES.MEMORY_FLOOR - 1
                if kind == 'oom': probes[0]['builder']['oomKills'] = 1
                if kind == 'late': probes[1]['monotonic'] += 3
                if kind == 'growth': probes[0]['diskAvailableBytes'] = 14 * RES.GIB
                if kind == 'cleanup': summary['cleanup']['daemonImportTerminated'] = False
                if kind == 'source': summary['sourceSha256'] = 'f' * 64
                if kind == 'phase': (directory / 'phase-01.json').write_bytes(b'{}')
                raw = b''.join(RES.encoded(row) + b'\n' for row in probes); (directory / 'resource-probes.jsonl').write_bytes(raw)
                summary['probeSha256'] = hashlib.sha256(raw).hexdigest(); (directory / 'resource-summary.json').write_bytes(RES.encoded(summary))
                with self.assertRaises(ValueError): RES.validate_files(directory, CONTEXT)

    def test_emergency_stop_targets_only_inspected_owned_builder(self):
        actor = RES.Supervisor.__new__(RES.Supervisor)
        actor.process = None; actor.builder = {'id': 'a' * 64}; actor.builder_stopping = False; actor.daemon_import_unknown = False
        rows = [{'Id': 'a' * 64, 'State': {'Running': True}}, {'Id': 'a' * 64, 'State': {'Running': False, 'Pid': 0, 'ExitCode': 137}}]
        calls = []
        actor.owned_builder = lambda: rows.pop(0)
        actor.docker = lambda *args, **kwargs: calls.append(args)
        result = actor._stop_owned(emergency=True)
        self.assertTrue(result['builderStopped']); self.assertEqual([('kill', '--signal', 'KILL', 'a' * 64)], calls)

    def test_runtime_fixture_cannot_build_external_context(self):
        args = type('Args', (), {'tag': CONTEXT['release']})()
        with self.assertRaises(ValueError): RES.runtime_image(Path('/owned'), Path('/owned/releases') / args.tag,
            args, CONTEXT['identity'], Path('/business/source'), 'anything', 'model', 'doorhandle-rehearsal-' + 'a' * 12)


if __name__ == '__main__':
    unittest.main()
