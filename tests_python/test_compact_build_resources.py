"""Pure boundary regressions; executed by Jenkins on ECS, never locally."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest


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
