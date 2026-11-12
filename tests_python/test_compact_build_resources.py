"""Pure boundary regressions; executed by Jenkins on ECS, never locally."""
import copy
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
import stat
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
STOCK_ROOTLESS_PROFILE = b'''# This profile allows everything and only exists to give the
# application a name instead of having the label "unconfined"

abi <abi/4.0>,
include <tunables/global>

profile rootlesskit /usr/bin/rootlesskit flags=(unconfined) {
  userns,

  # Site-specific additions and overrides. See local/README for details.
  include if exists <local/rootlesskit>
}
'''


@contextlib.contextmanager
def profile_policy_fixture(local=None):
    """Actual bytes/FD identities, with root ownership simulated for CI UID1000."""
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / 'etc/apparmor.d'; directory.mkdir(parents=True)
        path = directory / 'rootlesskit'; path.write_bytes(STOCK_ROOTLESS_PROFILE); path.chmod(0o644)
        local_directory = directory / 'local'; local_directory.mkdir()
        local_path = local_directory / 'rootlesskit'
        if local is not None: local_path.write_bytes(local); local_path.chmod(0o600)
        state = SimpleNamespace(path=path, local=local_path, directory=directory, fault=None)
        actual_lstat, actual_fstat = os.lstat, os.fstat
        def metadata(info, item=None):
            values = {name: getattr(info, name) for name in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            values['st_uid'] = 0
            if stat.S_ISDIR(info.st_mode): values['st_mode'] &= ~0o022
            if state.fault == 'foreign-file' and stat.S_ISREG(info.st_mode): values['st_uid'] = 1
            if state.fault == 'writable-parent' and item == directory: values['st_mode'] |= 0o002
            return SimpleNamespace(**values)
        result = SimpleNamespace(returncode=0, stdout=b'other-profile (enforce)\nrootlesskit (unconfined)\n', stderr=b'')
        with mock.patch.object(RES, 'ROOTLESS_PROFILE_FILE', path), mock.patch.object(RES.os, 'getuid', return_value=1000), \
                mock.patch.object(RES.os, 'lstat', side_effect=lambda item: metadata(actual_lstat(item), Path(item))), \
                mock.patch.object(RES.os, 'fstat', side_effect=lambda fd: metadata(actual_fstat(fd))), \
                mock.patch.object(RES.subprocess, 'run', return_value=result) as command:
            state.command = command; state.result = result
            yield state


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
    actor = SimpleNamespace(directory=directory, phases=[], checks=0, calls=[], builder=None, finishes=[],
                            context={**CONTEXT, 'ownerToken': 'e' * 24}, input_measurements=[])
    actor.begin = lambda name, growth, measured, memory: actor.phases.append((name, growth, measured, memory))
    actor.check = lambda: setattr(actor, 'checks', actor.checks + 1)
    actor.finish = lambda status: actor.finishes.append(status) or {'status': status}
    def run(args, name, **_kwargs):
        actor.calls.append((name, args)); log = directory / (name + '.log'); log.write_text(RES.VERSION); return log
    actor.run = run
    return actor


def identity_fixture(config=None, *, native=False, diff_ids=None):
    config = config or RES.IMAGE_ID
    diff_ids = diff_ids or ['sha256:' + '5' * 64]
    descriptor = {'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': 'sha256:' + '8' * 64, 'size': 1192}
    measurement = {'imageId': config, 'configDigest': config, 'manifestDigest': 'sha256:' + '9' * 64,
                   'layers': [{'diffId': value} for value in diff_ids]}
    row = {'Id': descriptor['digest'] if native else config, 'Os': 'linux', 'Architecture': 'amd64',
           'RootFS': {'Type': 'layers', 'Layers': diff_ids}, 'Config': {'User': '1000:1000', 'Env': []}, 'Size': 1}
    if native: row['Descriptor'] = copy.deepcopy(descriptor)
    binding = {'engineImageId': row['Id'], 'configDigest': config, 'loadDescriptor': descriptor if native else None,
               'diffIds': diff_ids, 'os': 'linux', 'architecture': 'amd64'}
    return row, measurement, binding


def evidence(directory):
    baseline = {'monotonic': 1.0, 'diskAvailableBytes': 16 * RES.GIB, 'memoryAvailableBytes': 8 * RES.GIB, 'filesystemBlockBytes': 4096}
    phases = []
    probes = []
    engine = identity_fixture()[2]
    builder = {'id': 'd' * 64, 'image': engine['engineImageId'], 'running': True, 'pid': 1234, 'memoryLimitBytes': RES.BUILDER_MEMORY,
               'currentBytes': RES.MIB, 'peakBytes': 2 * RES.MIB, 'oomKills': 0, 'writeRateLimitBytesPerSecond': 64 * RES.MIB}
    names = ['source-extraction', 'stage-contexts', 'builder-bootstrap', *['build-' + service for service in RES.SERVICES],
             *['load-' + service for service in RES.SERVICES], 'candidate-jar-readback']
    for index, phase in enumerate(names, 1):
        name = phase + '-%03d' % index
        measured = {'actualInputBytes': 1024}
        if phase == 'builder-bootstrap': measured.update(engineIdentity=engine, rootlessProfile=RES.rootless_profile_proof())
        plan = RES.phase_plan({**CONTEXT, 'ownerToken': 'e' * 24}, name, baseline, RES.GIB, RES.BUILDER_MEMORY, measured)
        path = directory / ('phase-%02d.json' % index); path.write_bytes(RES.encoded(plan))
        phases.append({'file': path.name, 'sha256': RES.digest(path)})
        probes.append({**baseline, 'monotonic': 1.0 + index * .05, 'phase': name, 'builder': builder})
    raw = b''.join(RES.encoded(row) + b'\n' for row in probes); (directory / 'resource-probes.jsonl').write_bytes(raw)
    image = {'imageId': 'sha256:' + '1' * 64, 'ociArchiveSha256': '2' * 64, 'ociArchiveBytes': 20480,
             'controlledDockerfileSha256': '3' * 64, 'inputContext': {'sha256': '4' * 64},
             'layers': [{'diffId': 'sha256:' + '5' * 64, 'blobDigest': 'sha256:' + '6' * 64, 'allocationUpperBoundBytes': 8192}]}
    image.update(configDigest=image['imageId'], manifestDigest='sha256:' + '9' * 64, loadDescriptor=None,
                 engineIdentity=identity_fixture(image['imageId'])[2])
    summary = {'version': 1, 'kind': 'doorhandle-candidate-build-resources', **CONTEXT, 'ownerToken': 'e' * 24,
               'status': 'PASS', 'capacityVerdict': 'CONTROLLED_MEASUREMENT', 'productionCapacityVerified': False, 'engineIdentity': engine,
               'rootlessProfile': RES.rootless_profile_proof(),
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
        for backend, failure in [(backend, failure) for backend in ('classic', 'containerd') for failure in (None, 'load', 'version', 'original-drift')]:
            with self.subTest(backend=backend, failure=failure), tempfile.TemporaryDirectory() as temporary, \
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
                def docker(*arguments):
                    if arguments[0] == 'info': return json.dumps([['driver-type', 'io.containerd.snapshotter.v1']] if backend == 'containerd' else []).encode()
                    proof = json.loads((actor.directory / 'official-layer-measurements.json').read_bytes())
                    row = {'Id': proof['loadDescriptor']['digest'] if backend == 'containerd' else image,
                           'Os': 'linux', 'Architecture': 'amd64', 'Size': 1,
                           'RootFS': {'Type': 'layers', 'Layers': [_diff]}, 'Config': {'User': '1000:1000', 'Env': []}}
                    if backend == 'containerd': row['Descriptor'] = proof['loadDescriptor']
                    self.assertEqual(('image', 'inspect', row['Id']), arguments)
                    return json.dumps([row]).encode()
                actor.docker = docker
                def bootstrap(value, *, image_identity):
                    self.assertTrue(any(name == 'official-image-load' for name, _args in value.calls))
                    self.assertEqual(image, image_identity['configDigest']); self.assertEqual([_diff], image_identity['diffIds'])
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
                        self.assertEqual(value['engineIdentity'], RES.measured_tool_identity(actor.directory, value))
                        self.assertEqual(image, value['imageId']); self.assertEqual(image, value['engineIdentity']['configDigest'])
                        self.assertTrue(value['ociImageLoadVerified']); self.assertEqual(['PASS'], actor.finishes)
                        self.assertEqual(['official-image-load', 'buildctl-version', 'buildkitd-version'], [name for name, _args in actor.calls])

    def test_classic_and_manifest_engine_handles_keep_the_original_config_identity(self):
        for native in (False, True):
            row, measurement, binding = identity_fixture(native=native)
            with self.subTest(native=native):
                self.assertEqual(binding, RES.engine_identity(row, measurement, binding['loadDescriptor']))
                self.assertEqual(binding, RES.validate_engine_identity(row, binding))
                self.assertEqual(RES.IMAGE_ID, binding['configDigest'])
                if native: self.assertNotEqual(measurement['manifestDigest'], binding['engineImageId'])

    def test_engine_target_descriptor_accepts_only_typed_standard_metadata(self):
        row, measurement, binding = identity_fixture(native=True)
        row['Descriptor'].update(annotations={'org.opencontainers.image.ref.name': 'fixture'},
            platform={'os': 'linux', 'architecture': 'amd64', 'variant': '', 'os.version': '', 'os.features': ['fixture']})
        self.assertEqual(binding, RES.engine_identity(row, measurement, binding['loadDescriptor']))
        for change in ({'url': 'unbound'}, {'annotations': {'key': 3}}, {'platform': {'os': 'linux', 'architecture': 'arm64'}},
                       {'platform': {'os': 'linux', 'architecture': 'amd64', 'os.features': 'feature'}}, {'size': True}):
            damaged = copy.deepcopy(row); damaged['Descriptor'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                RES.engine_identity(damaged, measurement, binding['loadDescriptor'])

    def test_engine_identity_rejects_unrelated_config_layers_platform_and_descriptor(self):
        row, measurement, binding = identity_fixture(native=True, diff_ids=['sha256:' + '5' * 64, 'sha256:' + '6' * 64])
        for change in ('id', 'descriptor', 'missing-descriptor', 'ordered-layers', 'os', 'architecture', 'rootfs-type', 'config', 'binding-extra'):
            damaged = copy.deepcopy(row); proof = copy.deepcopy(measurement); expected = copy.deepcopy(binding)
            if change == 'id': damaged['Id'] = 'sha256:' + '7' * 64
            if change == 'descriptor': damaged['Descriptor']['digest'] = 'sha256:' + '7' * 64
            if change == 'missing-descriptor': del damaged['Descriptor']
            if change == 'ordered-layers': damaged['RootFS']['Layers'].reverse()
            if change == 'os': damaged['Os'] = 'windows'
            if change == 'architecture': damaged['Architecture'] = 'arm64'
            if change == 'rootfs-type': damaged['RootFS']['Type'] = 'unknown'
            if change == 'config': proof['imageId'] = 'sha256:' + '7' * 64
            if change == 'binding-extra': expected['unbound'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                if change == 'binding-extra': RES.validate_engine_identity(damaged, expected)
                else: RES.engine_identity(damaged, proof, binding['loadDescriptor'])

    def test_engine_lookup_selects_the_proven_store_without_inspect_error_fallback(self):
        _row, measurement, binding = identity_fixture(native=True)
        for driver, expected in (([], RES.IMAGE_ID), ([['driver-type', 'io.containerd.snapshotter.v1']], binding['engineImageId'])):
            actor = SimpleNamespace(docker=mock.Mock(return_value=json.dumps(driver).encode()))
            self.assertEqual(expected, RES.engine_lookup_id(actor, measurement, binding['loadDescriptor']))
            actor.docker.assert_called_once_with('info', '--format', '{{json .DriverStatus}}')
        for driver, descriptor in (([['driver-type', 'unknown']], binding['loadDescriptor']),
                ([['driver-type', 'io.containerd.snapshotter.v1']] * 2, binding['loadDescriptor']),
                ([['driver-type', 'io.containerd.snapshotter.v1']], None), ({'driver-type': 'io.containerd.snapshotter.v1'}, binding['loadDescriptor'])):
            with self.subTest(driver=driver, descriptor=descriptor), self.assertRaises(ValueError):
                RES.engine_lookup_id(SimpleNamespace(docker=lambda *_: json.dumps(driver).encode()), measurement, descriptor)

    def test_local_save_stream_uses_the_verified_original_manifest_not_the_engine_as_config(self):
        members, config, diff, _manifest, _size = official_oci_fixture()
        descriptor = json.loads(members['index.json'])['manifests'][0]
        row = {'Id': descriptor['digest'], 'Descriptor': dict(descriptor, annotations={'fixture': 'retained'}),
               'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Env': []}, 'RootFS': {'Layers': [diff]}, 'Size': 1}
        with tempfile.TemporaryDirectory() as temporary:
            actor = archive_actor(Path(temporary) / 'attempt'); actor.docker = lambda *_: json.dumps([row]).encode()
            def process(*_args, **_kwargs):
                return SimpleNamespace(stdout=io.BytesIO(tar_bytes(list(members.items()))), wait=lambda **_: 0, poll=lambda: 0)
            with mock.patch.object(RES.subprocess, 'Popen', side_effect=process) as save, \
                    mock.patch.object(OCI, 'export_stream_to_oci', wraps=OCI.export_stream_to_oci) as export:
                proof = RES.local_layout(actor, row['Id'], actor.directory / 'base0', OCI)
            self.assertIsNone(export.call_args.args[2]); self.assertEqual(descriptor, export.call_args.kwargs['expected_engine_descriptor'])
            self.assertEqual(config, proof['imageId']); self.assertEqual(config, proof['configDigest'])
            self.assertEqual(descriptor, proof['loadDescriptor']); self.assertIsNone(actor.process)
            self.assertEqual(2, save.call_count)
            self.assertEqual(1, len(actor.input_measurements))
            record = json.loads((actor.directory / 'base0-measurement.json').read_bytes())
            self.assertEqual(proof['layers'], record['measurement']['layers'])
            self.assertEqual(actor.context['ownerToken'], record['ownerToken'])
            summary = {'ownerToken': actor.context['ownerToken'], 'inputMeasurements': actor.input_measurements}
            RES.validate_input_measurements(actor.directory, summary, CONTEXT)
            # The controller's established --directory artifacts/... is relative.
            with mock.patch.object(RES.os, 'getcwd', return_value=str(actor.directory.parent)):
                RES.validate_input_measurements(Path(actor.directory.name), summary, CONTEXT)

    def test_complete_local_measurement_survives_budget_refusal_without_materializing_layers(self):
        raw, image, diff = image_bytes()
        row = {'Id': image, 'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Env': []},
               'RootFS': {'Layers': [diff]}, 'Size': 1}
        with tempfile.TemporaryDirectory() as temporary:
            actor = archive_actor(Path(temporary) / 'attempt'); actor.docker = lambda *_: json.dumps([row]).encode()
            begin = actor.begin
            def admission(name, growth, measured, memory):
                begin(name, growth, measured, memory)
                if name.startswith('export-'): raise RES.BuildResourceError('Synthetic real disk admission refusal')
            actor.begin = admission
            process = SimpleNamespace(stdout=io.BytesIO(raw), wait=lambda **_: 0, poll=lambda: 0)
            with mock.patch.object(RES.subprocess, 'Popen', return_value=process) as save:
                with self.assertRaisesRegex(ValueError, 'real disk admission refusal'):
                    RES.local_layout(actor, image, actor.directory / 'base0', OCI)
            self.assertEqual(1, save.call_count); self.assertFalse((actor.directory / 'base0').exists())
            self.assertTrue((actor.directory / 'base0-measurement.json').is_file())
            self.assertEqual(len(raw) + 8 * RES.MIB, actor.phases[-1][1])
            self.assertIsNone(actor.process)

    def test_local_materialization_cannot_replace_the_measured_blob_catalogue(self):
        raw, image, diff = image_bytes()
        row = {'Id': image, 'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Env': []},
               'RootFS': {'Layers': [diff]}, 'Size': 1}
        with tempfile.TemporaryDirectory() as temporary:
            actor = archive_actor(Path(temporary) / 'attempt'); actor.docker = lambda *_: json.dumps([row]).encode()
            def process(*_args, **_kwargs):
                return SimpleNamespace(stdout=io.BytesIO(raw), wait=lambda **_: 0, poll=lambda: 0)
            original = OCI.export_stream_to_oci
            def changed(origin, destination, *args, **kwargs):
                proof = original(origin, destination, *args, **kwargs)
                if destination is not None: proof['layers'][0]['blobDigest'] = 'sha256:' + 'f' * 64
                return proof
            with mock.patch.object(RES.subprocess, 'Popen', side_effect=process), \
                    mock.patch.object(OCI, 'export_stream_to_oci', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'differs from its complete byte measurement'):
                    RES.local_layout(actor, image, actor.directory / 'base0', OCI)
            self.assertTrue((actor.directory / 'base0-measurement.json').is_file()); self.assertIsNone(actor.process)

    def test_measurement_collection_stays_in_the_existing_success_and_failure_receiver(self):
        pipeline = (ROOT / 'script/jenkins/pipeline.ps1').read_text(encoding='utf8')
        receiver = pipeline[pipeline.index('function Receive-OwnedBuildResources'):pipeline.index('function Receive-RuntimeResource')]
        for required in ('inputMeasurements', '$measurementCatalog = @()',
                         '$measurementCatalog = @($summary.inputMeasurements)', '^base[0-3]-measurement\\.json$', '1048576',
                         '$measurement.ownerToken -cne $summary.ownerToken', '$measurement.identity.executionLocation',
                         "'doorhandle-complete-image-input-measurement'"):
            self.assertIn(required, receiver)
        self.assertIn('finally { $candidateResources = Receive-CandidateResources }', pipeline)
        self.assertIn("'artifacts/candidate-build-resources'", pipeline)

    def test_measurement_reference_requires_exact_owner_name_bytes_and_complete_layer_identity(self):
        raw, image, diff = image_bytes()
        measured = OCI.inspect_docker_stream(io.BytesIO(raw), image, [diff], RES.MIB, lambda: None)
        row = {'Id': image, 'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Layers': [diff]}}
        original = {'version': 1, 'kind': 'doorhandle-complete-image-input-measurement', **CONTEXT, 'ownerToken': 'e' * 24,
                    'engineIdentity': RES.engine_identity(row, measured, measured['loadDescriptor']), 'measurement': measured}
        for damage in ('name', 'bytes', 'sha', 'owner', 'commit', 'blob', 'layer-bytes', 'bool-bytes', 'duplicate', 'link'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary); path = directory / 'base0-measurement.json'; value = copy.deepcopy(original)
                if damage == 'owner': value['ownerToken'] = 'f' * 24
                if damage == 'commit': value['commit'] = 'f' * 40
                if damage == 'blob': value['measurement']['layers'][0]['blobDigest'] = 'invalid'
                if damage == 'layer-bytes': value['measurement']['compressedBytes'] += 1
                path.write_bytes(RES.encoded(value))
                reference = {'file': path.name, 'sha256': RES.digest(path), 'bytes': path.stat().st_size}
                if damage == 'name': reference['file'] = '../base0-measurement.json'
                if damage == 'bytes': reference['bytes'] += 1
                if damage == 'sha': reference['sha256'] = 'f' * 64
                if damage == 'bool-bytes': reference['bytes'] = True
                if damage == 'link': os.link(path, directory / 'foreign-alias')
                references = [reference, reference] if damage == 'duplicate' else [reference]
                with self.assertRaises(ValueError):
                    RES.validate_input_measurements(directory, {'ownerToken': 'e' * 24, 'inputMeasurements': references}, CONTEXT)

    def test_rehashed_tool_measurements_still_require_the_pinned_config_and_ordered_diffids(self):
        _row, measurement, engine = identity_fixture(native=True)
        measurement.update(compressedBytes=RES.BUILDKIT_LAYER_BYTES, manifestDigest=engine['loadDescriptor']['digest'], loadDescriptor=engine['loadDescriptor'])
        for damage in (None, 'config', 'layers', 'manifest', 'measurement-sha', 'binding-pin'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary); proof = copy.deepcopy(measurement); binding = copy.deepcopy(engine)
                if damage == 'config': proof['configDigest'] = 'sha256:' + '7' * 64
                if damage == 'layers': proof['layers'][0]['diffId'] = 'sha256:' + '7' * 64
                if damage == 'manifest': proof['manifestDigest'] = 'sha256:' + '7' * 64
                if damage == 'binding-pin': binding['configDigest'] = 'sha256:' + '7' * 64
                path = directory / 'official-layer-measurements.json'; path.write_bytes(RES.encoded(proof)); path.chmod(0o600)
                value = {'engineIdentity': binding, 'imageMeasurementSha256': RES.digest(path)}
                if damage == 'measurement-sha': value['imageMeasurementSha256'] = '0' * 64
                if damage is None: self.assertEqual(engine, RES.measured_tool_identity(directory, value))
                else:
                    with self.assertRaises(ValueError): RES.measured_tool_identity(directory, value)

    def test_owned_container_requires_the_bound_engine_handle_and_all_existing_resource_guards(self):
        engine = identity_fixture(native=True)[2]; actor = RES.Supervisor.__new__(RES.Supervisor)
        actor.token = 'e' * 24; actor.context = CONTEXT
        actor.builder = {'id': 'd' * 64, 'engineIdentity': engine, 'ioDevice': '/dev/vda', 'mounts': []}
        row = {'Id': actor.builder['id'], 'Image': engine['engineImageId'],
            'State': {'StartedAt': '0001-01-01T00:00:00Z', 'Running': False, 'Pid': 0},
            'Config': {'User': '1000:1000', 'Labels': {RES.LABEL: actor.token, 'io.doorhandle.release': CONTEXT['release'], 'io.doorhandle.source': CONTEXT['sourceSha256']}},
            'HostConfig': {'Privileged': False, 'Memory': RES.BUILDER_MEMORY, 'MemorySwap': RES.BUILDER_MEMORY,
                'BlkioDeviceWriteBps': [{'Path': '/dev/vda', 'Rate': 64 * RES.MIB}],
                'SecurityOpt': ['seccomp=unconfined', 'apparmor=' + RES.ROOTLESS_PROFILE, 'systempaths=unconfined'],
                'MaskedPaths': [], 'ReadonlyPaths': [], 'Tmpfs': {'/tmp': '', '/run/user/1000': ''}}, 'Mounts': []}
        actor.docker = lambda *_: json.dumps([row]).encode()
        self.assertEqual(row, actor.owned_builder())
        row['HostConfig']['SecurityOpt'].remove('systempaths=unconfined')
        self.assertEqual(row, actor.owned_builder())
        row['State'].update(StartedAt='2026-11-08T03:00:00Z', Running=True, Pid=1234)
        row['AppArmorProfile'] = RES.ROOTLESS_PROFILE
        self.assertEqual(row, actor.owned_builder())
        for profile in ('unconfined', '', None, 'other-profile'):
            damaged = dict(row, AppArmorProfile=profile); actor.docker = lambda *_: json.dumps([damaged]).encode()
            with self.subTest(profile=profile), self.assertRaises(ValueError): actor.owned_builder()
        for key in ('MaskedPaths', 'ReadonlyPaths'):
            damaged = copy.deepcopy(row); damaged['HostConfig'][key] = ['/proc/kcore']
            actor.docker = lambda *_: json.dumps([damaged]).encode()
            with self.subTest(key=key), self.assertRaises(ValueError): actor.owned_builder()
        for field, value in (('Image', RES.IMAGE_ID), ('Id', '7' * 64)):
            damaged = dict(row, **{field: value}); actor.docker = lambda *_: json.dumps([damaged]).encode()
            with self.subTest(field=field), self.assertRaises(ValueError): actor.owned_builder()

    def test_rootless_security_normalization_requires_exact_options_and_explicit_empty_path_masks(self):
        base = ['seccomp=unconfined', 'apparmor=' + RES.ROOTLESS_PROFILE]
        for options in (base, list(reversed(base)), base + ['systempaths=unconfined']):
            host = {'SecurityOpt': options, 'MaskedPaths': [], 'ReadonlyPaths': []}
            with self.subTest(options=options): self.assertIs(True, RES.rootless_security_options(host))
            for key, value in (('MaskedPaths', ['/proc/kcore']), ('ReadonlyPaths', ['/proc/sys']),
                               ('MaskedPaths', None), ('ReadonlyPaths', ()), ('MaskedPaths', {})):
                damaged = copy.deepcopy(host); damaged[key] = value
                with self.subTest(options=options, key=key, value=value):
                    self.assertIs(False, RES.rootless_security_options(damaged))
            for key in ('MaskedPaths', 'ReadonlyPaths'):
                damaged = dict(host); del damaged[key]
                with self.subTest(missing=key, options=options): self.assertIs(False, RES.rootless_security_options(damaged))
        for options in (None, 'seccomp=unconfined', tuple(base), [], [base[0]], [base[1]],
                        [base[0], 'systempaths=unconfined'], [base[1], 'systempaths=unconfined'],
                        base + [base[0]], base + ['systempaths=unconfined'] * 2, base + ['label=disable'], base + [3],
                        ['seccomp=unconfined', 'apparmor=unconfined']):
            with self.subTest(options=options):
                self.assertIs(False, RES.rootless_security_options({'SecurityOpt': options, 'MaskedPaths': [], 'ReadonlyPaths': []}))
        for host in (None, [], {}, {'MaskedPaths': [], 'ReadonlyPaths': []}):
            with self.subTest(host=host): self.assertIs(False, RES.rootless_security_options(host))

    def test_existing_stock_profile_is_read_only_admitted_with_no_effective_local_override(self):
        self.assertEqual('rootlesskit', RES.ROOTLESS_PROFILE)
        self.assertEqual('/etc/apparmor.d/rootlesskit', str(RES.ROOTLESS_PROFILE_FILE))
        self.assertEqual(RES.ROOTLESS_PROFILE_SHA256, hashlib.sha256(STOCK_ROOTLESS_PROFILE).hexdigest())
        for local in (None, b'', b'# Site-specific notes only\n  # ordinary UTF8 comment \xe4\xb8\xad\xe6\x96\x87\n\n'):
            with self.subTest(local=local), profile_policy_fixture(local) as fixture:
                before = fixture.path.read_bytes()
                self.assertEqual(RES.rootless_profile_proof(), RES.admit_rootless_profile())
                self.assertEqual(before, fixture.path.read_bytes())
                fixture.command.assert_called_once()
                self.assertEqual(['/usr/bin/sudo', '-n', '/usr/bin/cat', '/sys/kernel/security/apparmor/profiles'], fixture.command.call_args.args[0])
                self.assertEqual({'capture_output', 'timeout', 'env'}, set(fixture.command.call_args.kwargs))
                self.assertLessEqual(set(fixture.command.call_args.kwargs['env']), {'PATH', 'LANG', 'LC_ALL'})

    def test_profile_owner_bytes_loaded_name_and_local_policy_are_checked_before_any_builder_mutation(self):
        for damage in ('stock-bytes', 'stock-owner', 'stock-mode', 'stock-link', 'stock-symlink', 'parent-mode',
                'local-rule', 'local-include', 'local-include-prefix', 'local-spaced-include', 'local-size', 'local-mode',
                'local-hardlink', 'local-invalid-utf8', 'local-nul', 'local-dir-link', 'loaded-mode', 'loaded-missing',
                'loaded-duplicate', 'sudo-failure', 'stock-race', 'local-race', 'wrong-actor'):
            with self.subTest(damage=damage), profile_policy_fixture() as fixture:
                if damage == 'stock-bytes': fixture.path.write_bytes(STOCK_ROOTLESS_PROFILE + b'# changed\n')
                if damage == 'stock-owner': fixture.fault = 'foreign-file'
                if damage == 'stock-mode': fixture.path.chmod(0o666)
                if damage == 'stock-link': os.link(fixture.path, fixture.directory / 'alias')
                if damage == 'stock-symlink':
                    target = fixture.directory / 'actual'; fixture.path.rename(target); fixture.path.symlink_to(target)
                if damage == 'parent-mode': fixture.fault = 'writable-parent'
                local_bytes = {'local-rule': b'userns,\n', 'local-include': b'#include <rules>\n',
                    'local-include-prefix': b'#includeanything\n', 'local-spaced-include': b'# include <rules>\n',
                    'local-size': b'#' * (8 * 1024 + 1), 'local-mode': b'# comment\n', 'local-hardlink': b'# comment\n',
                    'local-invalid-utf8': b'#\xff\n', 'local-nul': b'#\0\n'}
                if damage in local_bytes:
                    fixture.local.write_bytes(local_bytes[damage]); fixture.local.chmod(0o666 if damage == 'local-mode' else 0o600)
                if damage == 'local-hardlink': os.link(fixture.local, fixture.directory / 'local-alias')
                if damage == 'local-dir-link':
                    parent = fixture.local.parent; target = fixture.directory / 'other-local'; parent.rename(target); parent.symlink_to(target, target_is_directory=True)
                if damage == 'loaded-mode': fixture.result.stdout = b'rootlesskit (enforce)\n'
                if damage == 'loaded-missing': fixture.result.stdout = b'other-profile (unconfined)\n'
                if damage == 'loaded-duplicate': fixture.result.stdout *= 2
                if damage == 'sudo-failure': fixture.result.returncode = 1
                if damage in ('stock-race', 'local-race'):
                    def mutate(*_args, **_kwargs):
                        if damage == 'stock-race': fixture.path.write_bytes(STOCK_ROOTLESS_PROFILE + b'# after-read\n')
                        else: fixture.local.write_bytes(b'userns,\n')
                        return fixture.result
                    fixture.command.side_effect = mutate
                actor = SimpleNamespace(begin=mock.Mock(), docker=mock.Mock())
                with mock.patch.object(RES.os, 'getuid', return_value=0 if damage == 'wrong-actor' else 1000):
                    with self.assertRaises((ValueError, OSError)): RES.bootstrap_builder(actor, image_identity=identity_fixture()[2])
                actor.begin.assert_not_called(); actor.docker.assert_not_called()

    def test_resource_validator_rejects_rehashed_engine_and_bootstrap_binding_drift(self):
        for damage in ('missing-engine', 'builder-probe', 'bootstrap', 'candidate-config', 'candidate-engine', 'profile-bool', 'bootstrap-profile-bool'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary); summary, probes = evidence(directory)
                if damage == 'missing-engine': del summary['engineIdentity']
                if damage == 'profile-bool': summary['rootlessProfile']['localOverrideRulesAbsent'] = 1
                if damage == 'builder-probe': probes[0]['builder']['image'] = 'sha256:' + '7' * 64
                if damage == 'bootstrap':
                    reference = summary['phases'][2]; path = directory / reference['file']; phase = json.loads(path.read_bytes())
                    phase['measuredInputs']['engineIdentity']['configDigest'] = 'sha256:' + '7' * 64
                    path.write_bytes(RES.encoded(phase)); reference['sha256'] = RES.digest(path)
                if damage == 'bootstrap-profile-bool':
                    reference = summary['phases'][2]; path = directory / reference['file']; phase = json.loads(path.read_bytes())
                    phase['measuredInputs']['rootlessProfile']['localOverrideRulesAbsent'] = 1
                    path.write_bytes(RES.encoded(phase)); reference['sha256'] = RES.digest(path)
                if damage == 'candidate-config': summary['build']['images']['backend']['configDigest'] = 'sha256:' + '7' * 64
                if damage == 'candidate-engine': summary['build']['images']['backend']['engineIdentity']['engineImageId'] = 'sha256:' + '7' * 64
                raw = b''.join(RES.encoded(row) + b'\n' for row in probes); (directory / 'resource-probes.jsonl').write_bytes(raw)
                summary['probeSha256'] = hashlib.sha256(raw).hexdigest(); (directory / 'resource-summary.json').write_bytes(RES.encoded(summary))
                with self.assertRaises(ValueError): RES.validate_files(directory, CONTEXT)

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
