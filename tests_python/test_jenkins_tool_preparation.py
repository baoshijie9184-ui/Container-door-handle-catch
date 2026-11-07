"""Tool recipe boundary checks; Jenkins executes this file only on admitted ECS."""
import hashlib
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


FILE = Path(__file__).resolve().parents[1] / 'script' / 'jenkins' / 'prepare-ecs-tools.py'
SPEC = importlib.util.spec_from_file_location('ecs_tool_preparation', FILE)
tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tools)
GIB, MIB = tools.GIB, tools.MIB
COMMIT = 'a' * 40
SOURCE_SHA = 'b' * 64


class ToolPreparationTests(unittest.TestCase):
    def test_config_size_may_shrink_only_when_all_dependency_diffids_are_identical(self):
        old = {'RootFS': {'Layers': ['base', 'dependencies']}, 'Size': 1017481845}
        new = {'RootFS': {'Layers': ['base', 'dependencies']}, 'Size': 1017481042}
        tools.validate_dependency_layers(old, new)
        for layers in (['base'], ['base', 'replacement'], ['base', 'dependencies', 'extra']):
            with self.subTest(layers=layers), self.assertRaises(ValueError):
                tools.validate_dependency_layers(old, {**new, 'RootFS': {'Layers': layers}})

    def test_final_defaults_are_explicit_and_cannot_repeat_the_installation(self):
        sources = {tools.RECIPE: 'c' * 64, tools.REQUIREMENTS: tools.CACHED_REQUIREMENTS}
        changes = tools.tool_changes(sources, uid=1000, gid=1000, commit=COMMIT, source_sha=SOURCE_SHA)
        self.assertIn('ENTRYPOINT ["/usr/local/bin/python"]', changes)
        self.assertIn('CMD ["--version"]', changes)
        self.assertNotIn('ENTRYPOINT []', changes)
        self.assertNotIn('CMD []', changes)
        self.assertNotIn(tools.INSTALL, '\n'.join(changes))
        cfg = {'User': '1000:1000', 'Entrypoint': [tools.PYTHON], 'Cmd': ['--version'],
               'WorkingDir': '/', 'Healthcheck': {'Test': ['NONE']}, 'Volumes': None,
               'Labels': {'io.doorhandle.ci-tools': 'python-v1', 'io.doorhandle.commit': COMMIT,
                          'io.doorhandle.source': SOURCE_SHA,
                          'io.doorhandle.ci-tools-recipe-sha256': sources[tools.RECIPE],
                          'io.doorhandle.ci-tools-requirements-sha256': tools.CACHED_REQUIREMENTS}}
        tools.validate_tool_config(cfg, sources, uid=1000, gid=1000, commit=COMMIT, source_sha=SOURCE_SHA)
        for changed in ({'Cmd': tools.installer_command({'pytest': '8.4.2'})}, {'Cmd': []},
                        {'Entrypoint': []}, {'User': '0:0'}, {'Healthcheck': {'Test': ['CMD', 'start-app']}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                tools.validate_tool_config(dict(cfg, **changed), sources,
                    uid=1000, gid=1000, commit=COMMIT, source_sha=SOURCE_SHA)

    def test_metadata_create_is_inert_bounded_and_has_no_external_mounts(self):
        args = tools.metadata_arguments('current-owned-metadata', 'owner-token', 'ci-1-' + COMMIT[:12],
                                        SOURCE_SHA, uid=1000, gid=1000)
        self.assertEqual('create', args[0])
        self.assertEqual([tools.CACHED_PYTHON, '--version'], args[-2:])
        self.assertEqual('none', args[args.index('--network') + 1])
        self.assertEqual(str(512 * MIB), args[args.index('--memory') + 1])
        self.assertEqual(str(512 * MIB), args[args.index('--memory-swap') + 1])
        self.assertEqual('1000:1000', args[args.index('--user') + 1])
        self.assertIn('--read-only', args)
        self.assertIn('--no-healthcheck', args)
        self.assertNotIn('--mount', args)
        self.assertNotIn('--volume', args)
        self.assertNotIn('--privileged', args)
        self.assertNotIn(tools.INSTALL, args)

    def test_docker_stdout_notice_does_not_replace_the_immutable_image_receipt(self):
        actual = 'sha256:' + 'd' * 64
        output = 'Flag --pause has been deprecated, and enabled by default.\n' + actual + '\n'
        self.assertEqual(actual, tools.commit_image_id(output))
        for bad in ('notice only', actual + '\n' + actual, 'sha256:short'):
            with self.subTest(output=bad), self.assertRaises(ValueError):
                tools.commit_image_id(bad)

    def package(self, root, *, commit=COMMIT, recipe=b'reviewed source', extra=None):
        path = root / 'source.tar.gz'
        with tarfile.open(path, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': commit}) as archive:
            values = {tools.RECIPE: recipe, tools.REQUIREMENTS: b'pytest==8.4.2\n', 'README.md': b'not extracted'}
            for name, content in values.items():
                member = tarfile.TarInfo(name); member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            if extra is not None:
                archive.addfile(extra)
        own = root / 'uploaded.py'; own.write_bytes(b'reviewed source')
        output = root / 'extract'; output.mkdir()
        return path, own, output

    def test_only_pinned_recipe_and_requirements_are_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            archive, own, output = self.package(Path(directory))
            result = tools.archive_inputs(archive, output, COMMIT, tools.digest(archive), own)
            self.assertEqual({tools.RECIPE, tools.REQUIREMENTS}, set(result))
            self.assertEqual({'prepare-ecs-tools.py', 'python-test-requirements.txt'}, {p.name for p in output.iterdir()})
            self.assertEqual(hashlib.sha256(b'reviewed source').hexdigest(), result[tools.RECIPE])

    def test_wrong_commit_source_digest_or_uploaded_recipe_cannot_prepare(self):
        for mode in ('commit', 'archive', 'recipe'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                archive, own, output = self.package(Path(directory),
                    commit='c' * 40 if mode == 'commit' else COMMIT,
                    recipe=b'other source' if mode == 'recipe' else b'reviewed source')
                with self.assertRaises(ValueError):
                    tools.archive_inputs(archive, output, COMMIT,
                        SOURCE_SHA if mode == 'archive' else tools.digest(archive), own)
                self.assertEqual([], list(output.iterdir()))

    def test_archive_traversal_links_and_duplicate_recipe_are_rejected(self):
        entries = [tarfile.TarInfo('../escape'), tarfile.TarInfo('/absolute'),
                   tarfile.TarInfo('windows\\escape'), tarfile.TarInfo(tools.RECIPE),
                   tarfile.TarInfo('link')]
        entries[-1].type = tarfile.SYMTYPE; entries[-1].linkname = '/etc/passwd'
        for entry in entries:
            with self.subTest(name=entry.name), tempfile.TemporaryDirectory() as directory:
                archive, own, output = self.package(Path(directory), extra=entry)
                with self.assertRaises(ValueError):
                    tools.archive_inputs(archive, output, COMMIT, tools.digest(archive), own)
                self.assertEqual([], list(output.iterdir()))

    def test_only_version_pins_no_urls_options_or_duplicate_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            path.write_text('# public dependencies\nPyMySQL==1.1.2\npytest==8.4.2\n')
            self.assertEqual({'pymysql': '1.1.2', 'pytest': '8.4.2'}, tools.requirements(path))
            for invalid in ('pytest>=8.4.2', '--extra-index-url https://example.invalid',
                            'https://example.invalid/a.whl', 'pkg-name==1.0\npkg_name==1.1', ''):
                path.write_text(invalid)
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    tools.requirements(path)

    def test_build_container_is_bounded_and_mounts_only_public_input_and_owned_reports(self):
        args = tools.create_arguments('owned', 'token', 'ci-1-' + COMMIT[:12], SOURCE_SHA,
                                      Path('/owned/requirements.txt'), Path('/owned/reports'), {'pytest': '8.4.2'})
        self.assertEqual('never', args[args.index('--pull') + 1])
        self.assertEqual(str(2 * GIB), args[args.index('--memory') + 1])
        self.assertEqual(str(2 * GIB), args[args.index('--memory-swap') + 1])
        self.assertEqual('2', args[args.index('--cpus') + 1])
        self.assertEqual('ALL', args[args.index('--cap-drop') + 1])
        self.assertIn('--no-healthcheck', args)
        self.assertNotIn('--privileged', args)
        self.assertNotIn('/var/run/docker.sock', ' '.join(args))
        self.assertNotIn('--network host', ' '.join(args))
        mounts = [args[i + 1] for i, value in enumerate(args) if value == '--mount']
        self.assertEqual(2, len(mounts))
        self.assertIn('readonly', mounts[0])
        self.assertIn(tools.BASE, args)
        self.assertNotIn('pytest', tools.INSTALL)

    def test_fresh_install_uses_only_existing_https_mirror_and_keeps_provenance(self):
        pinned = tools.requirements(FILE.parent / 'python-test-requirements.txt')
        with mock.patch('subprocess.call', return_value=0) as call, \
                mock.patch('importlib.metadata.version', side_effect=pinned.__getitem__), \
                mock.patch('pathlib.Path.write_text') as write, \
                mock.patch.object(sys, 'argv', ['-c', json.dumps(pinned)]):
            exec(compile(tools.INSTALL, '<owned-pip-recipe>', 'exec'), {})
        install, check = [entry.args[0] for entry in call.call_args_list]
        prefix = [sys.executable, '-I', '-m', 'pip', '--isolated',
                  '--disable-pip-version-check', '--no-input']
        self.assertEqual(prefix, install[:len(prefix)])
        options = install[len(prefix):]
        self.assertEqual('install', options[0])
        self.assertEqual('https://mirrors.aliyun.com/pypi/simple',
                         options[options.index('--index-url') + 1])
        self.assertEqual(1, options.count('--index-url'))
        self.assertIn('--no-cache-dir', options)
        self.assertIn('--no-compile', options)
        self.assertEqual(str(Path('/ci-report') / 'pip-install.json'),
                         options[options.index('--report') + 1])
        self.assertEqual('/ci-input/requirements.txt', options[options.index('-r') + 1])
        self.assertTrue(all(option not in options for option in
                            ('--trusted-host', '--extra-index-url', '--no-deps')))
        self.assertEqual(prefix + ['check'], check)
        write.assert_called_once()
        self.assertEqual(pinned, json.loads(write.call_args.args[0]))

    def test_growth_and_real_disk_reserve_are_independent_bounds(self):
        self.assertEqual(GIB, tools.resource_check(8 * GIB, 7 * GIB, MIB))
        with self.assertRaises(ValueError):
            tools.resource_check(8 * GIB, 8 * GIB - tools.MAX_GROWTH - 1, 0)
        with self.assertRaises(ValueError):
            tools.resource_check(3 * GIB, tools.RESERVE + tools.OVERSHOOT - 1, 0)
        with self.assertRaises(ValueError):
            tools.resource_check(8 * GIB, 7 * GIB, tools.MAX_GROWTH + 1)
        with self.assertRaises(ValueError):
            tools.resource_check(8 * GIB, 7 * GIB, GIB, required_growth=GIB + 1)

    def test_fresh_install_counts_existing_metadata_once_and_keeps_both_bounds(self):
        metadata = 64 * 1024
        self.assertEqual(tools.MAX_GROWTH - metadata,
                         tools.admit_fresh_install(8 * GIB, 8 * GIB - metadata))
        # At the exact admission boundary, metadata consumes the total envelope
        # once; it cannot require a second, complete installation allowance.
        baseline = tools.RESERVE + tools.OVERSHOOT + tools.MAX_GROWTH
        self.assertEqual(tools.MAX_GROWTH - metadata,
                         tools.admit_fresh_install(baseline, baseline - metadata))
        with self.assertRaises(ValueError):
            tools.admit_fresh_install(baseline - 1, baseline - metadata - 1)
        for spent in (tools.MAX_GROWTH, tools.MAX_GROWTH + 1):
            with self.subTest(spent=spent), self.assertRaises(ValueError):
                tools.admit_fresh_install(8 * GIB, 8 * GIB - spent)
        with self.assertRaises(ValueError):
            tools.admit_fresh_install(8 * GIB, tools.RESERVE + tools.OVERSHOOT - 1)

    def owned_preparation(self):
        value = tools.Preparation.__new__(tools.Preparation)
        value.token = 'c' * 24; value.name = 'doorhandle-ci-python-' + value.token
        value.container = 'd' * 64
        value.args = SimpleNamespace(tag='ci-1-' + COMMIT[:12], source_sha256=SOURCE_SHA)
        value.folder = Path('/owned/python-tools'); value.reports = value.folder / 'reports'
        row = {'Id': value.container, 'Name': '/' + value.name, 'Image': tools.BASE,
               'Config': {'User': '0:0', 'Entrypoint': ['/usr/local/bin/python'],
                          'Healthcheck': {'Test': ['NONE']},
                          'Labels': {tools.LABEL: value.token, 'io.doorhandle.release': value.args.tag,
                                     'io.doorhandle.source': SOURCE_SHA}},
               'HostConfig': {'RestartPolicy': {'Name': 'no'}, 'Privileged': False,
                              'Memory': 2 * GIB, 'MemorySwap': 2 * GIB, 'NanoCpus': 2 * 10 ** 9,
                              'PidsLimit': 256, 'NetworkMode': 'bridge', 'CapDrop': ['ALL'],
                              'SecurityOpt': ['no-new-privileges:true']},
               'Mounts': [{'Type': 'bind', 'Source': str(value.folder / 'python-test-requirements.txt'),
                           'Destination': '/ci-input/requirements.txt', 'RW': False},
                          {'Type': 'bind', 'Source': str(value.reports), 'Destination': '/ci-report', 'RW': True}],
               'State': {'Running': False, 'Pid': 0, 'ExitCode': 0, 'Restarting': False}}
        value.call = lambda *_args, **_kwargs: json.dumps([row]).encode()
        return value, row

    def metadata_preparation(self):
        value = tools.Preparation.__new__(tools.Preparation)
        value.token = 'e' * 24
        value.metadata_name = 'doorhandle-ci-python-' + value.token + '-metadata'
        value.metadata_container = 'f' * 64
        value.args = SimpleNamespace(tag='ci-1-' + COMMIT[:12], source_sha256=SOURCE_SHA)
        row = {'Id': value.metadata_container, 'Name': '/' + value.metadata_name,
               'Image': tools.CACHED_PYTHON,
               'Config': {'User': str(os.getuid()) + ':' + str(os.getgid()),
                          'Entrypoint': [tools.PYTHON], 'Cmd': ['--version'], 'WorkingDir': '/',
                          'Healthcheck': {'Test': ['NONE']},
                          'Labels': {tools.LABEL: value.token, 'io.doorhandle.release': value.args.tag,
                                     'io.doorhandle.source': SOURCE_SHA,
                                     'io.doorhandle.ci-tool-preparation-role': 'metadata-only'}},
               'HostConfig': {'RestartPolicy': {'Name': 'no'}, 'ReadonlyRootfs': True,
                              'Privileged': False, 'Memory': 512 * MIB, 'MemorySwap': 512 * MIB,
                              'NanoCpus': 10 ** 9, 'PidsLimit': 16, 'NetworkMode': 'none',
                              'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true']},
               'Mounts': [], 'State': {'Status': 'created', 'Running': False, 'Pid': 0,
                                      'ExitCode': 0, 'Restarting': False, 'Paused': False,
                                      'OOMKilled': False, 'StartedAt': '0001-01-01T00:00:00Z'}}
        calls = []
        def call(*arguments, **_kwargs):
            calls.append(arguments)
            if arguments[0] == 'inspect':
                return json.dumps([row]).encode()
            if arguments[0] in ('diff', 'ps'):
                return b''
            if arguments == ('rm', value.metadata_container):
                return value.metadata_container.encode()
            raise AssertionError('Metadata cleanup must never start or stop any container')
        value.call = call
        return value, row, calls

    def test_metadata_cleanup_removes_only_the_never_started_current_container(self):
        value, _, calls = self.metadata_preparation()
        result = value.cleanup_metadata()
        self.assertEqual('STOPPED', result['status'])
        self.assertEqual([value.metadata_container], result['containersCreated'])
        self.assertFalse(result['containers'][0]['started'])
        self.assertEqual([], result['remaining'])
        self.assertIn(('rm', value.metadata_container), calls)
        self.assertTrue(all(arguments[0] not in ('start', 'stop', 'run', 'exec') for arguments in calls))

    def test_metadata_cleanup_rejects_old_or_started_or_writable_or_mounted_containers(self):
        variants = [('old-owner', lambda row: row['Config']['Labels'].update({tools.LABEL: 'old-producer'})),
                    ('another-image', lambda row: row.update(Image=tools.BASE)),
                    ('already-started', lambda row: row['State'].update(StartedAt='2026-11-07T00:00:00Z')),
                    ('running', lambda row: row['State'].update(Status='running', Running=True, Pid=123)),
                    ('writable', lambda row: row['HostConfig'].update(ReadonlyRootfs=False)),
                    ('unexpected-network', lambda row: row['HostConfig'].update(NetworkMode='bridge')),
                    ('mount', lambda row: row.update(Mounts=[{'Type': 'bind', 'Source': '/production'}])),
                    ('installer-command', lambda row: row['Config'].update(Cmd=tools.installer_command({'pytest': '8.4.2'})))]
        for name, mutate in variants:
            value, row, calls = self.metadata_preparation()
            mutate(row)
            with self.subTest(name=name), self.assertRaises(ValueError):
                value.cleanup_metadata()
            self.assertFalse(any(arguments[0] == 'rm' for arguments in calls))

    def test_pinned_reuse_refuses_unexpected_old_command_before_creating_any_container(self):
        value = tools.Preparation.__new__(tools.Preparation)
        cfg = {'User': str(os.getuid()) + ':' + str(os.getgid()), 'Entrypoint': [tools.PYTHON],
               'Cmd': ['-c', 'unexpected'], 'WorkingDir': '/', 'Healthcheck': {'Test': ['NONE']},
               'Labels': {'io.doorhandle.ci-tools-requirements-sha256': tools.CACHED_REQUIREMENTS,
                          'io.doorhandle.ci-tools-recipe-sha256': tools.CACHED_RECIPE}}
        calls = []
        value.call = lambda *args, **_kwargs: calls.append(args) or tools.CACHED_PYTHON.encode()
        value.image_row = lambda _image: {'Id': tools.CACHED_PYTHON, 'Config': deepcopy(cfg)}
        with self.assertRaises(ValueError):
            value.reuse_pinned_dependencies({tools.REQUIREMENTS: tools.CACHED_REQUIREMENTS}, dict(tools.CACHED_PINS), {})
        self.assertFalse(any(args[0] in ('create', 'commit', 'rm', 'start', 'stop') for args in calls))

    def test_cleanup_requires_exact_owner_image_limits_and_mounts(self):
        value, row = self.owned_preparation()
        self.assertEqual(value.container, value.stop_owned()['containerId'])
        row['Config']['Labels'][tools.LABEL] = 'other-owner'
        with self.assertRaises(ValueError):
            value.stop_owned()
        value, row = self.owned_preparation()
        row['HostConfig']['Memory'] = 0
        with self.assertRaises(ValueError):
            value.stop_owned()
        value, row = self.owned_preparation()
        row['Mounts'][1]['Source'] = '/production/data'
        with self.assertRaises(ValueError):
            value.stop_owned()


    def completed_readback(self, root, *, include_scipy=True):
        value = object.__new__(tools.PreparedReadback)
        value.root = root; value.inbox = root / 'inbox' / ('ci-1-' + COMMIT[:12])
        value.inbox.mkdir(parents=True)
        value.folder = value.inbox / 'python-tools'; value.folder.mkdir(mode=0o700)
        value.reports = value.folder / 'reports'; value.reports.mkdir(mode=0o700)
        value.archive = value.inbox / 'source.tar.gz'
        pins_raw = (FILE.parent / 'python-test-requirements.txt').read_bytes()
        if not include_scipy:
            pins_raw = b'\n'.join(line for line in pins_raw.splitlines() if not line.startswith(b'scipy==')) + b'\n'
        recipe = Path(tools.__file__).read_bytes()
        value.found = {tools.RECIPE: recipe, tools.REQUIREMENTS: pins_raw}
        with tarfile.open(value.archive, 'w:gz', pax_headers={'comment': COMMIT}) as archive:
            for name, raw in value.found.items():
                entry = tarfile.TarInfo(name); entry.size = len(raw); archive.addfile(entry, io.BytesIO(raw))
        value.archive.chmod(0o600)
        source_sha = tools.digest(value.archive)
        value.args = SimpleNamespace(tag=value.inbox.name, commit=COMMIT, source_sha256=source_sha,
                                     prepare_candidate_builder=False)
        value.identity = {'instanceId': tools.INSTANCE, 'machineId': tools.MACHINE, 'executionLocation': 'ECS'}
        value.docker = Path('/usr/bin/docker'); token = 'c' * 24
        sources = {name: hashlib.sha256(raw).hexdigest() for name, raw in value.found.items()}
        for name, raw in value.found.items():
            file = value.folder / Path(name).name; file.write_bytes(raw)
            file.chmod(0o444 if name == tools.REQUIREMENTS else 0o600)
        pinned = tools.requirements(value.folder / 'python-test-requirements.txt')
        owner = {'release': value.args.tag, 'commit': COMMIT, 'sourceSha256': source_sha, 'identity': value.identity,
                 'ownerToken': token, 'containerName': 'doorhandle-ci-python-' + token, 'baseImageId': tools.BASE,
                 'diskReserveBytes': tools.RESERVE, 'diskOvershootBytes': tools.OVERSHOOT,
                 'maximumGrowthBytes': tools.MAX_GROWTH, 'baselineAvailableBytes': 8 * GIB, 'sourceFiles': sources}
        tools.write_json(value.folder / 'owner.json', owner)
        tools.write_json(value.reports / 'pip-install.json', {'version': '1', 'install': []})
        tools.write_json(value.reports / 'installed-versions.json', pinned)
        sample = {'elapsedSeconds': 1.0, 'availableDiskBytes': 8 * GIB - 1234, 'hostDiskGrowthBytes': 1234,
                  'ownedWritableBytes': 2000, 'ownedMemoryPeakBytes': 3000, 'oomKilled': False}
        watchdog = {'kind': 'disk-watchdog', 'elapsedSeconds': 0.999,
                    'availableDiskBytes': 8 * GIB - 1200, 'hostDiskGrowthBytes': 1200}
        file = value.folder / 'resource-samples.jsonl'
        file.write_text(json.dumps(sample) + '\n' + json.dumps(watchdog) + '\n'); file.chmod(0o600)
        tools.write_json(value.folder / 'fresh-install-admission.json', {
            'kind': 'doorhandle-fresh-tool-admission', 'release': value.args.tag, 'commit': COMMIT,
            'sourceSha256': source_sha, 'baselineAvailableBytes': 8 * GIB, 'availableBytes': 8 * GIB - 64 * 1024,
            'observedHostGrowthUpperBoundBytes': 64 * 1024, 'remainingGrowthBytes': tools.MAX_GROWTH - 64 * 1024,
            'maximumGrowthBytes': tools.MAX_GROWTH, 'reserveBytes': tools.RESERVE, 'overshootBytes': tools.OVERSHOOT})
        image_id = 'sha256:' + 'e' * 64
        for name, raw in [('pip.log', b'No broken requirements found.\n'), ('commit.stdout', (image_id + '\n').encode()), ('commit.stderr', b'')]:
            file = value.folder / name; file.write_bytes(raw); file.chmod(0o600)
        receipt = {**owner, 'status': 'PREPARED', 'kind': 'doorhandle-ecs-tool-preparation',
                   'dependencyPreparation': 'INSTALLED_CURRENT_SOURCE', 'pipExecutedThisAttempt': True,
                   'testsExecuted': False, 'pythonImageId': image_id, 'mavenImageId': tools.MAVEN, 'nodeImageId': tools.NODE,
                   'pipReportSha256': tools.digest(value.reports / 'pip-install.json'),
                   'reportSha': tools.digest(value.reports / 'pip-install.json'),
                   'installedVersionsSha256': tools.digest(value.reports / 'installed-versions.json'),
                   'resourceSamplesSha256': tools.digest(value.folder / 'resource-samples.jsonl'),
                   'observed': {'hostDiskGrowthPeakBytes': 1234, 'containerWritablePeakBytes': 2000,
                                'memoryPeakBytes': 3000, 'oomKilled': False, 'samples': 2},
                   'cleanup': {'containerId': 'd' * 64, 'pid': 0, 'exitCode': 0, 'retained': True}}
        tools.write_json(value.folder / 'preparation.json', receipt)
        result = {**receipt, 'preparation': str(value.folder / 'preparation.json'),
                  'preparationSha256': tools.digest(value.folder / 'preparation.json')}
        tools.complete_preparation(value, result)
        _, producer = self.owned_preparation()
        producer['Name'] = '/' + owner['containerName']
        producer['Config']['Labels'].update({'io.doorhandle.release': value.args.tag, 'io.doorhandle.source': source_sha})
        producer['Config']['Cmd'] = tools.installer_command(pinned)
        producer['Mounts'][0]['Source'] = str(value.folder / 'python-test-requirements.txt')
        producer['Mounts'][1]['Source'] = str(value.reports)
        producer['State'].update(Status='exited', OOMKilled=False)
        config = {'User': str(os.getuid()) + ':' + str(os.getgid()), 'Entrypoint': [tools.PYTHON],
                  'Cmd': ['--version'], 'WorkingDir': '/', 'Healthcheck': {'Test': ['NONE']}, 'Volumes': None,
                  'Env': [], 'Labels': {'io.doorhandle.ci-tools': 'python-v1', 'io.doorhandle.source': source_sha,
                    'io.doorhandle.commit': COMMIT, 'io.doorhandle.ci-tools-recipe-sha256': sources[tools.RECIPE],
                    'io.doorhandle.ci-tools-requirements-sha256': sources[tools.REQUIREMENTS]}}
        image = {'Id': image_id, 'Os': 'linux', 'Config': config, 'RootFS': {'Layers': ['base', 'installed']}}
        calls = []
        def call(*args, **kwargs):
            calls.append(args)
            if args == ('inspect', 'd' * 64): return json.dumps([producer]).encode()
            if args[:2] == ('image', 'inspect'):
                row = image if args[2] == image_id else {'Id': args[2], 'Os': 'linux',
                    'Config': {'Volumes': None, 'Env': []}, 'RootFS': {'Layers': ['base']}}
                return json.dumps([row]).encode()
            raise AssertionError('Readback may not create, install, commit, start or stop')
        value.call = call
        return value, producer, image, calls

    def reseal_readback(self, value):
        receipt = json.loads((value.folder / 'preparation.json').read_text())
        (value.folder / 'completion.json').unlink()
        tools.complete_preparation(value, {**receipt, 'preparation': str(value.folder / 'preparation.json'),
            'preparationSha256': tools.digest(value.folder / 'preparation.json')})

    def cached_producer(self, root):
        """Reuse the complete synthetic producer; image defaults stay passive."""
        value, producer, image, calls = self.completed_readback(root)
        owner = json.loads((value.folder / 'owner.json').read_text())
        producer['State'].update(StartedAt='2026-11-07T00:00:00Z', Paused=False)
        image['Config']['Labels'].update({tools.LABEL: owner['ownerToken'],
                                         'io.doorhandle.release': value.args.tag})
        original_call = value.call
        def call(*args, **kwargs):
            if args == ('image', 'ls', '-q', '--no-trunc', '--filter', 'label=io.doorhandle.ci-tools=python-v1'):
                calls.append(args); return (image['Id'] + '\n').encode()
            if args == ('inspect', owner['containerName']):
                calls.append(args); return json.dumps([producer]).encode()
            return original_call(*args, **kwargs)
        value.call = call
        facts = {'CACHED_PYTHON': image['Id'], 'CACHED_RELEASE': owner['release'],
                 'CACHED_COMMIT': owner['commit'], 'CACHED_SOURCE': owner['sourceSha256'],
                 'CACHED_RECIPE': owner['sourceFiles'][tools.RECIPE],
                 'CACHED_REQUIREMENTS': owner['sourceFiles'][tools.REQUIREMENTS],
                 'CACHED_PINS': tools.requirements(value.folder / 'python-test-requirements.txt'),
                 'CACHED_PROOFS': {name: tools.digest(value.folder / name) for name in tools.CACHED_PROOFS}}
        return value, producer, image, calls, facts

    def test_pinned_cache_accepts_passive_image_only_with_original_successful_installer_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            value, producer, image, calls, facts = self.cached_producer(Path(directory))
            before = {str(p.relative_to(value.root)): (p.read_bytes(), p.stat().st_mode)
                      for p in value.root.rglob('*') if p.is_file()}
            original_producer = deepcopy(producer)
            with mock.patch.multiple(tools, **facts):
                result_image, original, result_producer = value.inspect_pinned_dependencies(dict(facts['CACHED_PINS']))
            self.assertEqual(image, result_image)
            self.assertEqual(set(facts['CACHED_PROOFS']), set(original))
            self.assertEqual(original_producer, result_producer)
            self.assertEqual(['--version'], result_image['Config']['Cmd'])
            self.assertEqual(tools.installer_command(facts['CACHED_PINS']), result_producer['Config']['Cmd'])
            self.assertEqual(before, {str(p.relative_to(value.root)): (p.read_bytes(), p.stat().st_mode)
                                     for p in value.root.rglob('*') if p.is_file()})
            self.assertTrue(calls and all(args[0] in ('image', 'inspect') for args in calls))

    def test_pinned_cache_refuses_image_installer_empty_and_unexpected_commands(self):
        for command in ('installer', [], ['-c', 'unexpected'], None):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                value, _, image, calls, facts = self.cached_producer(Path(directory))
                image['Config']['Cmd'] = tools.installer_command(facts['CACHED_PINS']) if command == 'installer' else command
                with mock.patch.multiple(tools, **facts), self.assertRaisesRegex(ValueError, 'image configuration differs'):
                    value.inspect_pinned_dependencies(dict(facts['CACHED_PINS']))
                self.assertTrue(calls and all(args[0] in ('image', 'inspect') for args in calls))

    def test_pinned_cache_still_refuses_passive_or_unexpected_original_producer_commands(self):
        for command in (['--version'], ['-c', 'unexpected'], [], None):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                value, producer, _, calls, facts = self.cached_producer(Path(directory))
                producer['Config']['Cmd'] = command
                with mock.patch.multiple(tools, **facts), self.assertRaisesRegex(ValueError, 'producer did not finish successfully'):
                    value.inspect_pinned_dependencies(dict(facts['CACHED_PINS']))
                self.assertTrue(calls and all(args[0] in ('image', 'inspect') for args in calls))

    def test_completed_readback_verifies_eight_or_nine_pins_without_any_mutation(self):
        for scipy in (False, True):
            with self.subTest(scipy=scipy), tempfile.TemporaryDirectory() as directory:
                value, _, _, calls = self.completed_readback(Path(directory), include_scipy=scipy)
                before = {str(p.relative_to(value.root)): p.read_bytes() for p in value.root.rglob('*') if p.is_file()}
                result = value.read_prepared()
                self.assertTrue(result['readbackValidated'])
                self.assertEqual('PREPARED', result['status'])
                self.assertEqual(before, {str(p.relative_to(value.root)): p.read_bytes() for p in value.root.rglob('*') if p.is_file()})
                self.assertTrue(all(args[0] in ('inspect', 'image') for args in calls))

    def test_readback_rejects_original_control_byte_drift(self):
        for name in ('owner.json', 'preparation.json', 'python-test-requirements.txt', 'reports/pip-install.json',
                     'reports/installed-versions.json', 'resource-samples.jsonl', 'commit.stdout', 'pip.log'):
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                value, _, _, _ = self.completed_readback(Path(directory))
                path = value.folder / name; mode = path.stat().st_mode & 0o777
                path.chmod(0o600); path.write_bytes(path.read_bytes() + b'changed'); path.chmod(mode)
                with self.assertRaises((ValueError, json.JSONDecodeError)): value.read_prepared()

    def test_readback_refuses_live_or_changed_producer_and_image_configuration(self):
        for mutation in ('running', 'oom', 'pid', 'exit', 'owner', 'mount', 'installer', 'image-command', 'image-source'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                value, producer, image, _ = self.completed_readback(Path(directory))
                if mutation == 'running': producer['State']['Running'] = True
                if mutation == 'oom': producer['State']['OOMKilled'] = True
                if mutation == 'pid': producer['State']['Pid'] = 123
                if mutation == 'exit': producer['State']['ExitCode'] = 1
                if mutation == 'owner': producer['Config']['Labels'][tools.LABEL] = 'another-owner'
                if mutation == 'mount': producer['Mounts'][1]['Source'] = '/production/data'
                if mutation == 'installer': producer['Config']['Cmd'] = ['--version']
                if mutation == 'image-command': image['Config']['Cmd'] = ['-c', 'start-business']
                if mutation == 'image-source': image['Config']['Labels']['io.doorhandle.source'] = 'f' * 64
                with self.assertRaises(ValueError): value.read_prepared()

    def test_readback_recomputes_resource_samples_even_when_sidecars_are_resealed(self):
        for mutation in ('peak', 'reserve', 'growth', 'oom', 'admission'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                value, _, _, _ = self.completed_readback(Path(directory))
                file = value.folder / ('fresh-install-admission.json' if mutation == 'admission' else 'resource-samples.jsonl')
                rows = [json.loads(line) for line in file.read_text().splitlines()] if mutation != 'admission' else [json.loads(file.read_text())]
                if mutation == 'peak': rows[0]['ownedMemoryPeakBytes'] += 1
                if mutation == 'reserve': rows[0]['availableDiskBytes'] = tools.RESERVE - 1
                if mutation == 'growth': rows[0]['hostDiskGrowthBytes'] += 1
                if mutation == 'oom': rows[0]['oomKilled'] = True
                if mutation == 'admission': rows[0]['remainingGrowthBytes'] += 1
                file.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
                receipt_file = value.folder / 'preparation.json'; receipt = json.loads(receipt_file.read_text())
                receipt['resourceSamplesSha256'] = tools.digest(value.folder / 'resource-samples.jsonl')
                receipt_file.write_text(json.dumps(receipt)); self.reseal_readback(value)
                with self.assertRaises(ValueError): value.read_prepared()

    def test_readback_requires_final_completion_and_same_builder_request(self):
        with tempfile.TemporaryDirectory() as directory:
            value, _, _, calls = self.completed_readback(Path(directory))
            value.args.prepare_candidate_builder = True
            with self.assertRaisesRegex(ValueError, 'request mode'): value.read_prepared()
            value.args.prepare_candidate_builder = False
            (value.folder / 'completion.json').unlink()
            with self.assertRaises(tools.PreparationPending): value.read_prepared()
            self.assertEqual([], calls)
            tools.write_json(value.folder / 'completion-failure.json', {'status': 'FAILED_OR_UNKNOWN'})
            with self.assertRaisesRegex(ValueError, 'terminal failure'): value.read_prepared()

    def test_atomic_completion_never_overwrites_success_or_leaves_pending_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'completion.json'
            tools.atomic_completion(path, {'original': True}); before = path.read_bytes()
            with self.assertRaises(FileExistsError): tools.atomic_completion(path, {'replacement': True})
            self.assertEqual(before, path.read_bytes())
            self.assertEqual([path], list(path.parent.iterdir()))

    def test_read_prepared_main_routes_pending_and_semantic_failures_without_preparation(self):
        arguments = ['--root', '/home/owned', '--tag', 'ci-1-' + COMMIT[:12], '--commit', COMMIT,
                     '--source-sha256', SOURCE_SHA, '--instance-id', tools.INSTANCE, '--machine-id', tools.MACHINE, '--read-prepared']
        for error, code in [(tools.PreparationPending('incomplete'), 75), (tools.PreparationError('changed'), 2)]:
            with self.subTest(code=code), mock.patch.object(tools, 'Preparation') as prepare, \
                    mock.patch.object(tools, 'PreparedReadback', side_effect=error), \
                    mock.patch.object(tools.signal, 'signal'), mock.patch('sys.stderr', io.StringIO()):
                self.assertEqual(code, tools.main(arguments)); prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
