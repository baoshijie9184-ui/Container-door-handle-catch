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
    def builder_input_args(self, root='/home/owned'):
        checksum = 'c' * 64
        return SimpleNamespace(root=str(root), prepare_candidate_builder=True,
            buildkit_archive=str(root) + '/build-inputs/buildkit-v0.34.2/' + checksum + '.tar',
            buildkit_archive_sha256=checksum, buildkit_archive_bytes=120000000)

    def test_optional_buildkit_request_requires_all_three_arguments_and_builder_mode(self):
        self.assertIsNone(tools.validate_builder_input_arguments(SimpleNamespace()))
        args = self.builder_input_args()
        expected = {'file': args.buildkit_archive, 'sha256': args.buildkit_archive_sha256,
                    'bytes': args.buildkit_archive_bytes}
        self.assertEqual(expected, tools.validate_builder_input_arguments(args))
        fields = ('buildkit_archive', 'buildkit_archive_sha256', 'buildkit_archive_bytes')
        for omitted in fields:
            changed = deepcopy(args); delattr(changed, omitted)
            with self.subTest(omitted=omitted), self.assertRaises(ValueError):
                tools.validate_builder_input_arguments(changed)
        args.prepare_candidate_builder = False
        with self.assertRaisesRegex(ValueError, 'candidate builder'):
            tools.validate_builder_input_arguments(args)

    def test_buildkit_input_rejects_unbounded_sizes_hash_aliases_and_cache_path_changes(self):
        mutations = [('buildkit_archive_bytes', size) for size in
                     (True, 0, -1, 128 * MIB + 1, '120000000')]
        mutations += [('buildkit_archive_sha256', checksum) for checksum in
                      ('C' * 64, 'c' * 63, 'sha256:' + 'c' * 64)]
        mutations += [('buildkit_archive', path) for path in
                      ('relative.tar', '/home/owned/archive.tar',
                       '/home/owned/build-inputs/buildkit-v0.34.2/' + 'd' * 64 + '.tar',
                       '/home/owned/build-inputs/../buildkit-v0.34.2/' + 'c' * 64 + '.tar')]
        mutations += [('root', root) for root in ('relative', '/home/owned/../owned', '/home//owned')]
        for name, replacement in mutations:
            args = self.builder_input_args(); setattr(args, name, replacement)
            with self.subTest(field=name, replacement=replacement), self.assertRaises(ValueError):
                tools.validate_builder_input_arguments(args)
        args = self.builder_input_args(); args.buildkit_archive_bytes = 128 * MIB
        self.assertEqual(128 * MIB, tools.validate_builder_input_arguments(args)['bytes'])

    def test_invalid_buildkit_request_is_rejected_before_identity_or_resource_creation(self):
        args = self.builder_input_args(); args.buildkit_archive_bytes = 128 * MIB + 1
        for constructor in (tools.Preparation, tools.PreparedReadback):
            with self.subTest(constructor=constructor.__name__), mock.patch.object(tools, 'identity') as identity, \
                    mock.patch.object(tools, 'canonical') as canonical, \
                    mock.patch.object(tools.Path, 'mkdir') as mkdir:
                with self.assertRaises(ValueError): constructor(args)
                identity.assert_not_called(); canonical.assert_not_called(); mkdir.assert_not_called()

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

    def package(self, root, *, commit=COMMIT, recipe=b'reviewed source', extra=None, runtime=None):
        path = root / 'source.tar.gz'
        with tarfile.open(path, 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': commit}) as archive:
            values = {tools.RECIPE: recipe, tools.REQUIREMENTS: b'pytest==8.4.2\n', 'README.md': b'not extracted'}
            if runtime is not None:
                values[tools.MEM0_REQUIREMENTS] = runtime
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

    def test_current_runtime_source_is_a_bound_third_input_without_changing_legacy_extraction_contract(self):
        runtime=(FILE.parents[2] / tools.MEM0_REQUIREMENTS).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            archive, own, output=self.package(Path(directory),runtime=runtime)
            result=tools.archive_inputs(archive,output,COMMIT,tools.digest(archive),own,include_mem0_runtime=True)
            self.assertEqual({tools.RECIPE,tools.REQUIREMENTS,tools.MEM0_REQUIREMENTS},set(result))
            self.assertEqual(runtime,(output / 'requirements.txt').read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            archive, own, output=self.package(Path(directory))
            with self.assertRaisesRegex(ValueError,'missing'):
                tools.archive_inputs(archive,output,COMMIT,tools.digest(archive),own,include_mem0_runtime=True)
            self.assertEqual([],list(output.iterdir()))

    def test_current_tool_pins_include_exact_runtime_closure_and_never_reuse_old_nine_pin_proof(self):
        current=tools.requirements(FILE.parent / 'python-test-requirements.txt')
        runtime=tools.requirements(FILE.parents[2] / tools.MEM0_REQUIREMENTS)
        self.assertEqual(22,len(current));self.assertEqual(13,len(runtime))
        self.assertEqual(runtime,tools.validate_mem0_requirements(current,runtime))
        for missing in runtime:
            changed=dict(current);changed.pop(missing)
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                tools.validate_mem0_requirements(changed,runtime)
        for package in runtime:
            changed=dict(current);changed[package]='0.0.0'
            with self.subTest(drift=package),self.assertRaises(ValueError):
                tools.validate_mem0_requirements(changed,runtime)
        value=tools.Preparation.__new__(tools.Preparation)
        value.call=mock.Mock(side_effect=AssertionError('new requirements must not inspect historical image'))
        self.assertIsNone(value.inspect_pinned_dependencies(current))
        self.assertIsNone(value.reuse_pinned_dependencies({tools.MEM0_REQUIREMENTS:'c'*64},current,{}))
        value.call.assert_not_called()

    def test_runtime_closure_does_not_allow_missing_or_unreviewed_runtime_package(self):
        current=tools.requirements(FILE.parent / 'python-test-requirements.txt')
        runtime=tools.requirements(FILE.parents[2] / tools.MEM0_REQUIREMENTS)
        for changed in (dict(runtime,unreviewed='1.0'),{key:value for key,value in runtime.items() if key!='qdrant-client'}):
            with self.assertRaisesRegex(ValueError,'13 admitted'):
                tools.validate_mem0_requirements(current,changed)

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


    def completed_readback(self, root, *, include_scipy=True, include_runtime=False):
        value = object.__new__(tools.PreparedReadback)
        value.root = root; value.inbox = root / 'inbox' / ('ci-1-' + COMMIT[:12])
        value.inbox.mkdir(parents=True)
        value.folder = value.inbox / 'python-tools'; value.folder.mkdir(mode=0o700)
        value.reports = value.folder / 'reports'; value.reports.mkdir(mode=0o700)
        value.archive = value.inbox / 'source.tar.gz'
        pins_raw = ((FILE.parent / 'python-test-requirements.txt').read_bytes() if include_runtime else
                    ''.join(name + '==' + version + '\n' for name, version in tools.CACHED_PINS.items()).encode())
        if not include_scipy:
            pins_raw = b'\n'.join(line for line in pins_raw.splitlines() if not line.startswith(b'scipy==')) + b'\n'
        recipe = Path(tools.__file__).read_bytes()
        value.found = {tools.RECIPE: recipe, tools.REQUIREMENTS: pins_raw}
        if include_runtime:
            value.found[tools.MEM0_REQUIREMENTS]=(FILE.parents[2] / tools.MEM0_REQUIREMENTS).read_bytes()
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
                installed = json.loads((value.reports / 'installed-versions.json').read_text())
                self.assertEqual(9 if scipy else 8, len(installed))
                self.assertNotIn(tools.MEM0_REQUIREMENTS, result['sourceFiles'])
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

    def test_completed_current_runtime_readback_binds_all_22_versions_and_third_source_original(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,_,_=self.completed_readback(Path(directory),include_runtime=True)
            result=value.read_prepared()
            self.assertTrue(result['readbackValidated'])
            self.assertIn(tools.MEM0_REQUIREMENTS,result['sourceFiles'])
            complete=json.loads((value.folder / 'completion.json').read_text())
            self.assertIn('requirements.txt',complete['proofs'])
            installed=json.loads((value.reports / 'installed-versions.json').read_text())
            self.assertEqual(22,len(installed))
            self.assertEqual('1.20.0',installed['qdrant-client'])
            self.assertEqual('1.45.2',installed['opentelemetry-exporter-otlp-proto-http'])
            self.assertFalse(result['testsExecuted'])

    def test_current_runtime_original_cannot_be_changed_after_preparation_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            value,_,_,_=self.completed_readback(Path(directory),include_runtime=True)
            original=value.folder / 'requirements.txt'
            original.write_text(original.read_text().replace('qdrant-client==1.20.0','qdrant-client==1.19.0'))
            with self.assertRaisesRegex(ValueError,'requirements differ'):
                value.read_prepared()

    def complete_with_builder_input(self, value):
        request = self.builder_input_args(value.root)
        for key, content in vars(request).items(): setattr(value.args, key, content)
        path = value.folder / 'completion.json'; complete = json.loads(path.read_text())
        result = {**complete['result'], 'candidateBuilderTools': {'file': 'bound-tools-reference'}}
        path.unlink(); published = tools.complete_preparation(value, result)
        return json.loads(path.read_text()), request, published

    def test_completion_keeps_legacy_schema_and_binds_explicit_buildkit_input(self):
        with tempfile.TemporaryDirectory() as directory:
            value, _, _, _ = self.completed_readback(Path(directory))
            legacy = json.loads((value.folder / 'completion.json').read_text())
            self.assertNotIn('buildkitArchive', legacy)
            complete, request, published = self.complete_with_builder_input(value)
            self.assertEqual(set(legacy) | {'buildkitArchive'}, set(complete))
            expected = tools.validate_builder_input_arguments(request)
            self.assertEqual(expected, complete['buildkitArchive'])
            self.assertEqual(expected, complete['result']['buildkitArchive'])
            self.assertEqual(expected, published['buildkitArchive'])
            with mock.patch.object(value, 'validate_builder') as validate:
                result = value.read_prepared()
            self.assertTrue(result['readbackValidated'])
            self.assertEqual(expected, result['buildkitArchive'])
            validate.assert_called_once_with(complete['result']['candidateBuilderTools'])

    def test_readback_rejects_removed_rebound_or_unexpected_buildkit_request(self):
        for mutation in ('missing-field', 'bytes', 'sha-path', 'no-cli', 'unexpected-field', 'boolean-bytes',
                         'result-missing', 'result-bytes', 'result-extra', 'result-boolean'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                value, _, _, calls = self.completed_readback(Path(directory))
                complete, _, _ = self.complete_with_builder_input(value)
                if mutation == 'missing-field': complete.pop('buildkitArchive')
                if mutation == 'bytes': value.args.buildkit_archive_bytes += 1
                if mutation == 'sha-path':
                    value.args.buildkit_archive_sha256 = 'd' * 64
                    value.args.buildkit_archive = str(value.root / 'build-inputs' / 'buildkit-v0.34.2' / ('d' * 64 + '.tar'))
                if mutation == 'no-cli':
                    for name in ('buildkit_archive', 'buildkit_archive_sha256', 'buildkit_archive_bytes'):
                        delattr(value.args, name)
                if mutation == 'unexpected-field': complete['unexpectedBuildInput'] = complete['buildkitArchive']
                if mutation == 'boolean-bytes': complete['buildkitArchive']['bytes'] = True
                if mutation == 'result-missing': complete['result'].pop('buildkitArchive')
                if mutation == 'result-bytes': complete['result']['buildkitArchive']['bytes'] += 1
                if mutation == 'result-extra': complete['result']['buildkitArchive']['foreign'] = True
                if mutation == 'result-boolean': complete['result']['buildkitArchive']['bytes'] = True
                (value.folder / 'completion.json').write_text(json.dumps(complete))
                with self.assertRaisesRegex(ValueError, 'request mode|result archive binding'): value.read_prepared()
                self.assertEqual([], calls)

    def test_builder_readback_requires_same_archive_and_checks_current_original_before_docker(self):
        for mode in ('changed-original', 'changed-binding', 'unrequested-binding'):
            with self.subTest(mode=mode):
                value = object.__new__(tools.PreparedReadback)
                value.args = self.builder_input_args(); value.root = Path(value.args.root)
                value.inbox = value.root / 'inbox' / ('ci-1-' + COMMIT[:12])
                value.folder = value.inbox / 'python-tools'; value.owner = {}
                binding = tools.validate_builder_input_arguments(value.args)
                document = {'buildkitArchive': dict(binding)}
                if mode == 'changed-binding': document['buildkitArchive']['bytes'] += 1
                if mode == 'unrequested-binding':
                    for name in ('buildkit_archive', 'buildkit_archive_sha256', 'buildkit_archive_bytes'):
                        delattr(value.args, name)
                    binding = None
                helper = SimpleNamespace(IMAGE_ID='sha256:' + 'd' * 64,
                    admit_tools=mock.Mock(return_value={'file': 'tools.json', 'sha256': 'e' * 64}),
                    buildkit_input=mock.Mock(return_value=binding),
                    validate_buildkit_archive=mock.Mock(side_effect=ValueError('current original changed')))
                spec = SimpleNamespace(loader=SimpleNamespace(exec_module=mock.Mock()))
                reference = {**helper.admit_tools.return_value, 'imageId': helper.IMAGE_ID, 'status': 'PREPARED'}
                with mock.patch.object(tools.importlib.util, 'spec_from_file_location', return_value=spec), \
                        mock.patch.object(tools.importlib.util, 'module_from_spec', return_value=helper), \
                        mock.patch.object(tools, 'control_bytes', return_value=json.dumps(document).encode()), \
                        mock.patch.object(value, 'call') as docker:
                    with self.assertRaisesRegex(ValueError, 'current original changed' if mode == 'changed-original' else 'archive binding'):
                        value.validate_builder(reference)
                    docker.assert_not_called()
                if mode == 'changed-original': helper.validate_buildkit_archive.assert_called_once_with(value.root, binding)
                else: helper.validate_buildkit_archive.assert_not_called()

    def completed_builder_readback(self, native=True):
        value = object.__new__(tools.PreparedReadback)
        value.args = SimpleNamespace(root='/home/owned', tag='ci-1-' + COMMIT[:12], source_sha256=SOURCE_SHA)
        value.root = Path(value.args.root); value.inbox = value.root / 'inbox' / value.args.tag
        value.folder = value.inbox / 'python-tools'; value.owner = {}
        config = 'sha256:' + 'd' * 64; descriptor = {'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                                  'digest': 'sha256:' + '1' * 64, 'size': 1192}
        engine = {'engineImageId': descriptor['digest'] if native else config, 'configDigest': config,
                  'loadDescriptor': descriptor, 'diffIds': ['sha256:' + '2' * 64], 'os': 'linux', 'architecture': 'amd64'}
        profile = {'profile': 'rootlesskit', 'file': '/etc/apparmor.d/rootlesskit',
                   'sha256': 'a6a1a760d88312275d64f195e6b2f51627e8cabfdf4e355262c86f0578c66d80',
                   'loadedMode': 'unconfined', 'localOverrideRulesAbsent': True}
        directory = value.inbox / 'candidate-build-tools'; log = b'v0.34.2\n'; license_raw = b'approved-license'
        helper = SimpleNamespace(IMAGE_ID=config, LABEL='io.doorhandle.candidate-builder', VERSION='v0.34.2',
            ROOTLESS_PROFILE='rootlesskit', admit_rootless_profile=mock.Mock(return_value=profile),
            BUILDER_MEMORY=2 * GIB, LICENSE_SHA=hashlib.sha256(license_raw).hexdigest(),
            admit_tools=mock.Mock(return_value={'file': 'tools.json', 'sha256': 'e' * 64}),
            buildkit_input=mock.Mock(return_value=None), tool_engine_identity=mock.Mock(return_value=engine),
            validate_engine_identity=mock.Mock(return_value=engine), rootless_security_options=mock.Mock(return_value=True))
        document = {'licenseFile': str(directory / 'LICENSE'), 'engineIdentity': engine, 'rootlessProfile': profile,
                    'versions': {name: {'file': name + '-version.log', 'sha256': hashlib.sha256(log).hexdigest()}
                                 for name in ('buildctl', 'buildkitd')}}
        cid = 'c' * 64; token = 'f' * 24
        summary = {'ownerToken': token, 'cleanup': {'builderContainerId': cid, 'builderExitCode': 0}}
        image = {'Id': engine['engineImageId'], 'Os': 'linux', 'Architecture': 'amd64', 'Config': {'User': '1000:1000'}}
        container = {'Id': cid, 'Image': engine['engineImageId'], 'AppArmorProfile': 'rootlesskit',
            'Config': {'User': '1000:1000', 'Labels': {helper.LABEL: token, 'io.doorhandle.release': value.args.tag,
                                                       'io.doorhandle.source': SOURCE_SHA}},
            'HostConfig': {'Privileged': False, 'Memory': 2 * GIB, 'MemorySwap': 2 * GIB, 'RestartPolicy': {'Name': 'no'},
                           'NetworkMode': 'bridge', 'NanoCpus': 2 * 10 ** 9, 'PidsLimit': 1024,
                           'SecurityOpt': ['seccomp=unconfined', 'apparmor=rootlesskit'] + ([] if native else ['systempaths=unconfined']),
                           'MaskedPaths': [], 'ReadonlyPaths': []},
            'State': {'Status': 'exited', 'Running': False, 'Restarting': False, 'Paused': False, 'OOMKilled': False,
                      'StartedAt': '2026-11-08T00:00:00Z', 'Pid': 0, 'ExitCode': 0}}
        def read(path, **_kwargs):
            if path == directory / 'tools.json': return json.dumps(document).encode()
            if path == directory / 'LICENSE': return license_raw
            if path.name in ('buildctl-version.log', 'buildkitd-version.log'): return log
            if path == directory / 'resource-summary.json': return json.dumps(summary).encode()
            raise AssertionError('Unexpected control read')
        def docker(*args):
            if args == ('image', 'inspect', engine['engineImageId']): return json.dumps([image]).encode()
            if args == ('inspect', cid): return json.dumps([container]).encode()
            raise AssertionError('Readback used an unbound image or Docker mutation')
        value.call = mock.Mock(side_effect=docker)
        reference = {**helper.admit_tools.return_value, 'imageId': helper.IMAGE_ID, 'status': 'PREPARED'}
        return value, helper, reference, read, image, container, engine

    def test_completed_builder_readback_uses_bound_engine_id_for_both_stores(self):
        for native in (False, True):
            with self.subTest(native=native):
                value, helper, reference, read, image, container, engine = self.completed_builder_readback(native)
                spec = SimpleNamespace(loader=SimpleNamespace(exec_module=mock.Mock()))
                with mock.patch.object(tools.importlib.util, 'spec_from_file_location', return_value=spec), \
                        mock.patch.object(tools.importlib.util, 'module_from_spec', return_value=helper), \
                        mock.patch.object(tools, 'control_bytes', side_effect=read):
                    value.validate_builder(reference)
                helper.validate_engine_identity.assert_called_once_with(image, engine)
                helper.admit_rootless_profile.assert_called_once_with()
                helper.rootless_security_options.assert_called_once_with(container['HostConfig'])
                self.assertEqual([mock.call('image', 'inspect', engine['engineImageId']), mock.call('inspect', container['Id'])],
                                 value.call.call_args_list)
                if native: self.assertNotEqual(helper.IMAGE_ID, engine['engineImageId'])

    def test_builder_readback_rejects_engine_drift_and_wrong_container_image(self):
        for change in ('identity-drift', 'root-user', 'container-config-id', 'sandbox-drift', 'profile-drift', 'applied-profile-drift', 'profile-boolean'):
            with self.subTest(change=change):
                value, helper, reference, read, image, container, engine = self.completed_builder_readback()
                if change == 'identity-drift': helper.validate_engine_identity.side_effect = ValueError('engine identity drift')
                if change == 'root-user': image['Config']['User'] = '0'
                if change == 'container-config-id': container['Image'] = helper.IMAGE_ID
                if change == 'sandbox-drift': helper.rootless_security_options.return_value = False
                if change == 'profile-drift':
                    helper.admit_rootless_profile.return_value = {**helper.admit_rootless_profile.return_value, 'profile': 'unconfined'}
                if change == 'applied-profile-drift': container['AppArmorProfile'] = 'unconfined'
                if change == 'profile-boolean':
                    original_read = read
                    def read(path, **kwargs):
                        raw = original_read(path, **kwargs)
                        if path.name == 'tools.json':
                            stored = json.loads(raw); stored['rootlessProfile']['localOverrideRulesAbsent'] = 1
                            return json.dumps(stored).encode()
                        return raw
                spec = SimpleNamespace(loader=SimpleNamespace(exec_module=mock.Mock()))
                with mock.patch.object(tools.importlib.util, 'spec_from_file_location', return_value=spec), \
                        mock.patch.object(tools.importlib.util, 'module_from_spec', return_value=helper), \
                        mock.patch.object(tools, 'control_bytes', side_effect=read), self.assertRaises(ValueError):
                    value.validate_builder(reference)
                expected = 0 if change in ('profile-drift', 'profile-boolean') else 2 if change in ('container-config-id', 'sandbox-drift', 'applied-profile-drift') else 1
                self.assertEqual(expected, value.call.call_count)

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

    def test_main_rejects_incomplete_archive_before_dispatching_prepare_or_readback(self):
        arguments = ['--root', '/home/owned', '--tag', 'ci-1-' + COMMIT[:12], '--commit', COMMIT,
                     '--source-sha256', SOURCE_SHA, '--instance-id', tools.INSTANCE, '--machine-id', tools.MACHINE,
                     '--prepare-candidate-builder', '--buildkit-archive-bytes', '120000000']
        for mode in ([], ['--read-prepared']):
            with self.subTest(mode=mode), mock.patch.object(tools, 'Preparation') as prepare, \
                    mock.patch.object(tools, 'PreparedReadback') as readback, \
                    mock.patch.object(tools.signal, 'signal'), mock.patch('sys.stderr', io.StringIO()):
                self.assertEqual(2, tools.main(arguments + mode))
                prepare.assert_not_called(); readback.assert_not_called()


class CompletedRuntimeDependencyReuseTests(unittest.TestCase):
    """Current 22-pin reuse is separate from the immutable historical 9-pin route."""
    owned_preparation = ToolPreparationTests.owned_preparation
    completed_readback = ToolPreparationTests.completed_readback
    reseal_readback = ToolPreparationTests.reseal_readback

    def completed_runtime_producer(self, root):
        value, producer, image, calls = self.completed_readback(root, include_runtime=True)
        owner = json.loads((value.folder / 'owner.json').read_text())
        producer['State'].update(StartedAt='2026-11-14T00:00:00Z', Paused=False)
        image['Config']['Labels'].update({tools.LABEL: owner['ownerToken'], 'io.doorhandle.release': value.args.tag})
        return value, producer, image, calls, owner

    def current_consumer(self, source, producer, image, calls):
        value = object.__new__(tools.Preparation)
        value.root, value.identity, value.docker = source.root, dict(source.identity), source.docker
        value.args = SimpleNamespace(tag='ci-2-' + 'f' * 12, commit='f' * 40, source_sha256='e' * 64,
                                     prepare_candidate_builder=False)
        value.inbox = value.root / 'inbox' / value.args.tag
        value.folder = value.inbox / 'python-tools'; value.reports = value.folder / 'reports'
        sources = {name: hashlib.sha256(raw).hexdigest() for name, raw in source.found.items()}
        sources[tools.RECIPE] = 'a' * 64  # Current reviewed recipe can differ; dependency pins cannot.
        pinned = tools.requirements(source.folder / 'python-test-requirements.txt')
        def call(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('image', 'ls'):
                return b'' if 'label=io.doorhandle.ci-tool-preparation-role=metadata-only' in args else (image['Id'] + '\n').encode()
            if args[:2] == ('image', 'inspect'):
                return json.dumps([image if args[2] == image['Id'] else {'Id': args[2], 'Os': 'linux',
                    'Config': {'Volumes': None, 'Env': []}, 'RootFS': {'Layers': ['base']}}]).encode()
            if args[0] == 'inspect' and args[-1] in (producer['Id'], producer['Name'].lstrip('/')):
                return json.dumps([producer]).encode()
            raise AssertionError('Reuse admission must inspect only, not change an old producer: ' + repr(args))
        value.call = mock.Mock(side_effect=call)
        return value, sources, pinned

    def test_current_metadata_recipe_can_name_an_admitted_image_without_rebinding_legacy_defaults(self):
        current = 'sha256:' + 'e' * 64
        args = tools.metadata_arguments('owned-current-metadata', 'c' * 24, 'ci-2-' + COMMIT[:12],
            SOURCE_SHA, uid=1000, gid=1000, image=current)
        self.assertEqual([current, '--version'], args[-2:])
        self.assertEqual('none', args[args.index('--network') + 1]); self.assertIn('--read-only', args)
        self.assertNotIn('--mount', args); self.assertNotIn('--volume', args)
        self.assertEqual(str(512 * MIB), args[args.index('--memory') + 1])
        legacy = tools.metadata_arguments('owned-legacy-metadata', 'd' * 24, 'ci-2-' + COMMIT[:12],
            SOURCE_SHA, uid=1000, gid=1000)
        self.assertEqual([tools.CACHED_PYTHON, '--version'], legacy[-2:])

    def test_current_22_pin_producer_is_reused_across_build_and_recipe_changes_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            source, producer, image, calls, owner = self.completed_runtime_producer(Path(directory))
            value, sources, pinned = self.current_consumer(source, producer, image, calls)
            # An unrelated later pipeline failure is not Python install evidence.
            failed = source.root / 'verification' / source.args.tag / 'verification-receipt.json'
            failed.parent.mkdir(parents=True); tools.write_json(failed, {'status': 'FAILED', 'errorType': 'URLError'})
            before = {str(p.relative_to(source.root)): p.read_bytes() for p in source.root.rglob('*') if p.is_file()}
            original_container = deepcopy(producer)
            result_image, original, result_producer, descriptor = value.inspect_completed_dependencies(sources, pinned)
            self.assertEqual(22, len(pinned)); self.assertEqual(image, result_image)
            self.assertEqual(original_container, result_producer)
            complete = json.loads((source.folder / 'completion.json').read_text())
            self.assertEqual(set(complete['proofs']), set(original))
            self.assertEqual(2, descriptor['schemaVersion'])
            self.assertEqual(image['Id'], descriptor['sourceImageId'])
            self.assertEqual(owner['release'], descriptor['producerRelease'])
            self.assertEqual(owner['commit'], descriptor['producerCommit'])
            self.assertEqual(owner['sourceSha256'], descriptor['producerSourceSha256'])
            self.assertEqual(complete['proofs'], descriptor['producerProofs'])
            self.assertEqual(tools.digest(source.folder / 'completion.json'), descriptor['producerCompletionSha256'])
            self.assertTrue(descriptor['producerContainerInspectedOnly'])
            self.assertNotEqual(owner['sourceFiles'][tools.RECIPE], sources[tools.RECIPE])
            self.assertEqual(before, {str(p.relative_to(source.root)): p.read_bytes() for p in source.root.rglob('*') if p.is_file()})
            self.assertTrue(calls and all(call[0] in ('image', 'inspect') for call in calls))
            self.assertIsNone(getattr(value, 'container', None))

    def test_same_versions_allow_current_requirements_comments_without_a_new_pip_install(self):
        with tempfile.TemporaryDirectory() as directory:
            source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
            value, sources, pinned = self.current_consumer(source, producer, image, calls)
            sources[tools.REQUIREMENTS] = hashlib.sha256(b'# current reviewed comment\n' + source.found[tools.REQUIREMENTS]).hexdigest()
            proof = value.inspect_completed_dependencies(sources, pinned)
            self.assertEqual(image['Id'], proof[3]['sourceImageId'])
            listing = next(call for call in calls if call[:2] == ('image', 'ls'))
            self.assertIn('label=io.doorhandle.ci-tools-requirements-sha256', listing)
            self.assertNotIn('label=io.doorhandle.ci-tools-requirements-sha256=' + sources[tools.REQUIREMENTS], listing)
            self.assertTrue(all(call[0] in ('image', 'inspect') for call in calls))

    def test_discovery_is_bounded_to_unique_immutable_ids_before_inspecting_any_candidate(self):
        for ids in (['mysql:8.4'], ['sha256:' + format(index, '064x') for index in range(129)]):
            with self.subTest(inventory=len(ids)):
                value = object.__new__(tools.Preparation)
                value.call = mock.Mock(side_effect=[('\n'.join(ids) + '\n').encode(), b''])
                value._completed_producer = mock.Mock()
                with self.assertRaises(ValueError): value.inspect_completed_dependencies({tools.MEM0_REQUIREMENTS: 'a' * 64}, {})
                value._completed_producer.assert_not_called()
        value = object.__new__(tools.Preparation); image = 'sha256:' + 'e' * 64
        value.call = mock.Mock(side_effect=[(image + '\n' + image + '\n').encode(), b''])
        value._completed_producer = mock.Mock(return_value=None)
        self.assertIsNone(value.inspect_completed_dependencies({tools.MEM0_REQUIREMENTS: 'a' * 64}, {}))
        value._completed_producer.assert_called_once()

    def dependency_discovery(self, images, metadata):
        value = object.__new__(tools.Preparation)
        scope = ('image', 'ls', '-q', '--no-trunc', '--filter', 'label=io.doorhandle.ci-tools=python-v1',
                 '--filter', 'label=io.doorhandle.ci-tools-requirements-sha256')
        metadata_scope = scope + ('--filter', 'label=io.doorhandle.ci-tool-preparation-role=metadata-only')
        def inspect(*arguments, **_kwargs):
            if arguments == scope: return images
            if arguments == metadata_scope: return metadata
            raise AssertionError('Discovery must use the same exact bounded tool/requirements label scope')
        value.call = mock.Mock(side_effect=inspect)
        value._completed_producer = mock.Mock(return_value=None)
        return value, {tools.MEM0_REQUIREMENTS: 'a' * 64}, {}, scope, metadata_scope

    def test_metadata_history_does_not_consume_the_128_completed_installer_candidate_limit(self):
        images = ['sha256:' + format(index, '064x') for index in range(1, 158)]
        raw = lambda ids: ('\n'.join(ids) + '\n').encode()
        value, sources, pinned, scope, metadata_scope = self.dependency_discovery(raw(images), raw(images[:155]))
        admitted = ('only-a-real-completed-installer-can-return-this-proof',)
        value._completed_producer.side_effect = [None, admitted]
        self.assertIs(admitted, value.inspect_completed_dependencies(sources, pinned))
        self.assertEqual([mock.call(*scope), mock.call(*metadata_scope)], value.call.call_args_list)
        self.assertEqual([mock.call(image, sources, pinned) for image in images[155:]], value._completed_producer.call_args_list)

    def test_129_actual_installers_still_fail_even_with_more_metadata_history_excluded(self):
        images = ['sha256:' + format(index, '064x') for index in range(1, 285)]
        raw = lambda ids: ('\n'.join(ids) + '\n').encode()
        value, sources, pinned, _, _ = self.dependency_discovery(raw(images), raw(images[:155]))
        with self.assertRaisesRegex(ValueError, 'bounded scope'): value.inspect_completed_dependencies(sources, pinned)
        value._completed_producer.assert_not_called(); self.assertEqual(2, value.call.call_count)

    def test_metadata_exclusion_requires_a_subset_of_the_same_strict_immutable_inventory(self):
        image = 'sha256:' + 'a' * 64; foreign = 'sha256:' + 'b' * 64
        for metadata in ((foreign + '\n').encode(), b'mysql:8.4\n', b'unknown Docker output\n',
                         (image + ' ' + foreign + '\n').encode()):
            with self.subTest(metadata=metadata):
                value, sources, pinned, _, _ = self.dependency_discovery((image + '\n').encode(), metadata)
                with self.assertRaises(ValueError): value.inspect_completed_dependencies(sources, pinned)
                value._completed_producer.assert_not_called()

    def test_metadata_duplicates_and_empty_filtered_inventory_never_trigger_producer_inspection(self):
        image = 'sha256:' + 'a' * 64
        for all_images, metadata in ((b'', b''), ((image + '\n' + image + '\n').encode(), (image + '\n' + image + '\n').encode())):
            with self.subTest(inventory=all_images):
                value, sources, pinned, _, _ = self.dependency_discovery(all_images, metadata)
                self.assertIsNone(value.inspect_completed_dependencies(sources, pinned)); value._completed_producer.assert_not_called()

    def test_docker_id_parser_keeps_only_complete_per_line_ids_and_the_exact_evidenced_notice(self):
        notice = 'Flag --pause has been deprecated, and enabled by default.'
        for kind, identifiers in (('image', ['sha256:' + 'a' * 64, 'sha256:' + 'b' * 64]),
                                  ('container', ['a' * 64, 'b' * 64])):
            text = '\n' + identifiers[0] + '\n' + notice + '\n\n' + identifiers[1] + '\n'
            for output in (text, text.encode()):
                with self.subTest(kind=kind, output_type=type(output).__name__):
                    self.assertEqual(identifiers, tools.docker_ids(output, kind))
            self.assertEqual([], tools.docker_ids(notice + '\n\n', kind))
            self.assertEqual([identifiers[0], identifiers[0]], tools.docker_ids((identifiers[0] + '\n') * 2, kind))

    def test_docker_id_parser_rejects_unknown_notices_garbage_and_mixed_id_kinds(self):
        notice = 'Flag --pause has been deprecated, and enabled by default.'
        for kind, actual, other in (('image', 'sha256:' + 'a' * 64, 'b' * 64),
                                    ('container', 'a' * 64, 'sha256:' + 'b' * 64)):
            for bad in ('WARNING: ignore this output\n', notice.replace('default.', 'default!') + '\n',
                        notice + ' extra\n', actual + ' garbage\n', actual + ' ' + actual + '\n',
                        other + '\n', actual.upper() + '\n', actual[:-1] + '\n'):
                with self.subTest(kind=kind, bad=bad), self.assertRaises(ValueError):
                    tools.docker_ids(notice + '\n' + actual + '\n' + bad, kind)
        for output, kind in ((b'\xff\xfe', 'image'), (None, 'image'), (['sha256:' + 'a' * 64], 'image'), ('', 'volume')):
            with self.subTest(output=output, kind=kind), self.assertRaises(ValueError): tools.docker_ids(output, kind)

    def test_historical_179_byte_commit_stdout_retains_its_original_unique_image_id_contract(self):
        # Reproduce #297's preserved stdout; inventory parsing has a separate contract.
        actual = 'sha256:0873bbdec32c00adb14c33a1a32de2ea8fe5acde0163088bd879318b2213f901'
        original = ('Flag --pause has been deprecated, and enabled by default. '
                    'Use --no-pause to disable pausing during commit.\n' + actual + '\n')
        self.assertEqual(179, len(original.encode()))
        self.assertEqual(actual, tools.commit_image_id(original))

    def test_original_commit_extraction_does_not_add_an_inventory_notice_whitelist(self):
        actual = 'sha256:' + 'a' * 64
        for notice in ('Historical Docker CLI notice from a different revision.',
                       'Flag --pause has been deprecated, and enabled by default. Use --no-pause to disable pausing during commit.',
                       'WARNING: this retained historical message is bound by the producer completion.',
                       'sha256:short\nAnother non-ID historical output line.'):
            for output in (notice + '\n' + actual + '\n', actual + '\n' + notice + '\n'):
                with self.subTest(notice=notice, position=output.startswith(actual)):
                    self.assertEqual(actual, tools.commit_image_id(output))

    def test_original_commit_extraction_still_requires_exactly_one_complete_image_id_line(self):
        actual = 'sha256:' + 'a' * 64; another = 'sha256:' + 'b' * 64
        for bad in ('', 'historical notice only', 'sha256:short', actual + ' trailing bytes',
                    'prefix ' + actual, actual + ' ' + another, actual + '\n' + actual,
                    'historical notice\n' + actual + '\n' + another):
            with self.subTest(output=bad), self.assertRaises(ValueError): tools.commit_image_id(bad)

    def test_completed_producer_with_bound_historical_long_commit_notice_remains_reusable_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
            original = ('Flag --pause has been deprecated, and enabled by default. '
                        'Use --no-pause to disable pausing during commit.\n' + image['Id'] + '\n')
            (source.folder / 'commit.stdout').write_text(original)
            self.reseal_readback(source)
            value, sources, pinned = self.current_consumer(source, producer, image, calls)
            before = {str(path.relative_to(source.inbox)): path.read_bytes() for path in source.inbox.rglob('*') if path.is_file()}
            proof = value.inspect_completed_dependencies(sources, pinned)
            self.assertEqual(image['Id'], proof[0]['Id'])
            self.assertEqual(tools.digest(source.folder / 'commit.stdout'), proof[3]['producerCommitReceiptSha256'])
            self.assertEqual(tools.digest(source.folder / 'completion.json'), proof[3]['producerCompletionSha256'])
            self.assertEqual(before, {str(path.relative_to(source.inbox)): path.read_bytes() for path in source.inbox.rglob('*') if path.is_file()})
            self.assertTrue(calls and all(call[0] in ('image', 'inspect') for call in calls))

    def test_exact_docker_notice_is_not_counted_or_inspected_in_either_discovery_inventory(self):
        notice = b'Flag --pause has been deprecated, and enabled by default.\n'
        image = 'sha256:' + 'a' * 64; metadata = 'sha256:' + 'b' * 64
        value, sources, pinned, _, _ = self.dependency_discovery(
            notice + (image + '\n' + metadata + '\n').encode(), (metadata + '\n').encode() + notice)
        self.assertIsNone(value.inspect_completed_dependencies(sources, pinned))
        value._completed_producer.assert_called_once_with(image, sources, pinned)

    def test_unknown_output_in_either_inventory_cannot_be_hidden_by_metadata_exclusion(self):
        notice = b'Flag --pause has been deprecated, and enabled by default.\n'
        image = ('sha256:' + 'a' * 64 + '\n').encode()
        for bad in (b'WARNING: Docker maybe succeeded\n', image.rstrip() + b' trailing bytes\n',
                    b'Flag --pause has been deprecated, and enabled by default!\n', b'sha256:bad\n'):
            for metadata_bad in (False, True):
                with self.subTest(bad=bad, metadata=metadata_bad):
                    value, sources, pinned, _, _ = self.dependency_discovery(
                        notice + image + (b'' if metadata_bad else bad), notice + (bad if metadata_bad else b''))
                    with self.assertRaises(ValueError): value.inspect_completed_dependencies(sources, pinned)
                    value._completed_producer.assert_not_called()

    def test_explicit_dependency_id_still_requires_the_full_valid_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
            value, sources, pinned = self.current_consumer(source, producer, image, calls)
            image['Config']['Labels'].pop('io.doorhandle.ci-tools-requirements-sha256')
            with self.assertRaises(ValueError): value.inspect_completed_dependencies(sources, pinned, image_id=image['Id'])
            self.assertFalse(any(call[:2] == ('image', 'ls') for call in calls))
            self.assertTrue(all(call[0] in ('image', 'inspect') for call in calls))

    def test_completed_reuse_refuses_foreign_identity_nonce_commands_layers_or_producer_state(self):
        damages = ('ecs', 'image-nonce', 'image-command', 'image-sensitive-env', 'image-base',
                   'producer-command', 'producer-live', 'producer-oom', 'producer-pid', 'producer-exit',
                   'producer-never-started', 'producer-owner', 'producer-mount')
        for damage in damages:
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
                value, sources, pinned = self.current_consumer(source, producer, image, calls)
                if damage == 'ecs': value.identity = {**value.identity, 'machineId': 'd' * 32}
                if damage == 'image-nonce': image['Config']['Labels'][tools.LABEL] = 'f' * 24
                if damage == 'image-command': image['Config']['Cmd'] = tools.installer_command(pinned)
                if damage == 'image-sensitive-env': image['Config']['Env'] = ['API_KEY=synthetic-must-not-inherit']
                if damage == 'image-base': image['RootFS']['Layers'][0] = 'different-base'
                if damage == 'producer-command': producer['Config']['Cmd'] = ['--version']
                if damage == 'producer-live': producer['State'].update(Running=True, Status='running', Pid=123)
                if damage == 'producer-oom': producer['State']['OOMKilled'] = True
                if damage == 'producer-pid': producer['State']['Pid'] = 123
                if damage == 'producer-exit': producer['State']['ExitCode'] = 1
                if damage == 'producer-never-started': producer['State']['StartedAt'] = '0001-01-01T00:00:00Z'
                if damage == 'producer-owner': producer['Config']['Labels'][tools.LABEL] = 'foreign'
                if damage == 'producer-mount': producer['Mounts'][1]['Source'] = '/production/data'
                with self.assertRaises(ValueError): value.inspect_completed_dependencies(sources, pinned, image_id=image['Id'])
                self.assertTrue(all(call[0] in ('image', 'inspect') for call in calls))

    def test_completed_reuse_rejects_changed_original_control_bytes_and_missing_completion(self):
        names = ('owner.json', 'preparation.json', 'completion.json', 'reports/pip-install.json',
                 'reports/installed-versions.json', 'pip.log', 'commit.stdout', 'requirements.txt')
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
                value, sources, pinned = self.current_consumer(source, producer, image, calls)
                path = source.folder / name
                if name == 'completion.json': path.unlink()
                else: path.write_bytes(path.read_bytes() + b'changed original')
                with self.assertRaises((ValueError, OSError)):
                    value.inspect_completed_dependencies(sources, pinned, image_id=image['Id'])
                self.assertTrue(all(call[0] in ('image', 'inspect') for call in calls))

    def test_actual_installed_versions_and_pip_check_are_semantic_guards_even_if_reports_are_resealed(self):
        for damage in ('versions', 'pip-check', 'resource-growth'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
                value, sources, pinned = self.current_consumer(source, producer, image, calls)
                receipt_file = source.folder / 'preparation.json'; receipt = json.loads(receipt_file.read_text())
                if damage == 'versions':
                    file = source.reports / 'installed-versions.json'; installed = json.loads(file.read_text())
                    installed['qdrant-client'] = '1.19.0'; file.write_text(json.dumps(installed))
                    receipt['installedVersionsSha256'] = tools.digest(file)
                elif damage == 'pip-check':
                    (source.folder / 'pip.log').write_bytes(b'pip check did not finish successfully\n')
                else:
                    file = source.folder / 'resource-samples.jsonl'; rows = [json.loads(row) for row in file.read_text().splitlines()]
                    rows[0]['hostDiskGrowthBytes'] += 1; file.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
                    receipt['resourceSamplesSha256'] = tools.digest(file)
                receipt_file.write_text(json.dumps(receipt)); self.reseal_readback(source)
                with self.assertRaises(ValueError): value.inspect_completed_dependencies(sources, pinned, image_id=image['Id'])
                self.assertTrue(all(call[0] in ('image', 'inspect') for call in calls))

    def test_producer_restart_between_readback_and_final_inspection_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
            value, sources, pinned = self.current_consumer(source, producer, image, calls)
            original = value.call.side_effect; inspected = []
            def racing(*args, **kwargs):
                if args == ('inspect', producer['Id']):
                    inspected.append(True)
                    if len(inspected) == 2: producer['State'].update(Status='running', Running=True, Pid=123)
                return original(*args, **kwargs)
            value.call.side_effect = racing
            with self.assertRaises(ValueError): value.inspect_completed_dependencies(sources, pinned, image_id=image['Id'])
            self.assertEqual(2, len(inspected)); self.assertTrue(all(call[0] in ('image', 'inspect') for call in calls))

    def test_metadata_custody_and_cleanup_bind_the_new_dependency_id_not_the_legacy_default(self):
        value, row, calls = ToolPreparationTests.metadata_preparation(self)
        value.dependency_image = row['Image'] = 'sha256:' + 'a' * 64
        result = value.cleanup_metadata()
        self.assertEqual(value.dependency_image, result['containers'][0]['sourceImageId'])
        self.assertIn(('rm', value.metadata_container), calls)
        self.assertTrue(all(call[0] not in ('start', 'stop', 'run', 'exec') for call in calls))
        value, row, calls = ToolPreparationTests.metadata_preparation(self)
        value.dependency_image = 'sha256:' + 'a' * 64
        with self.assertRaises(ValueError): value.cleanup_metadata()
        self.assertFalse(any(call[0] == 'rm' for call in calls))

    def reuse_attempt(self, source, producer, image, calls):
        """Use the real reuse writer and readback; replace only the Docker repair."""
        value, _, pinned = self.current_consumer(source, producer, image, calls)
        value.folder.mkdir(parents=True, mode=0o700); value.reports.mkdir(mode=0o700)
        value.archive = value.inbox / 'source.tar.gz'
        value.found = {**source.found, tools.RECIPE: source.found[tools.RECIPE] + b'\n# Reviewed metadata-only revision.\n',
                       tools.REQUIREMENTS: b'# Same admitted pins, new reviewed source.\n' + source.found[tools.REQUIREMENTS]}
        with tarfile.open(value.archive, 'w:gz', pax_headers={'comment': value.args.commit}) as archive:
            for name, raw in value.found.items():
                entry = tarfile.TarInfo(name); entry.size = len(raw); archive.addfile(entry, io.BytesIO(raw))
        value.archive.chmod(0o600); value.args.source_sha256 = tools.digest(value.archive)
        sources = {name: hashlib.sha256(raw).hexdigest() for name, raw in value.found.items()}
        for name, raw in value.found.items():
            path = value.folder / Path(name).name; path.write_bytes(raw)
            path.chmod(0o444 if name == tools.REQUIREMENTS else 0o600)
        value.token = 'b' * 24; value.name = 'doorhandle-ci-python-' + value.token
        value.baseline = 8 * GIB; value.image = None; value.snapshot = value.folder / 'resource-samples.jsonl'
        owner = {'release': value.args.tag, 'commit': value.args.commit, 'sourceSha256': value.args.source_sha256,
                 'identity': value.identity, 'ownerToken': value.token, 'containerName': value.name, 'baseImageId': tools.BASE,
                 'diskReserveBytes': tools.RESERVE, 'diskOvershootBytes': tools.OVERSHOOT,
                 'maximumGrowthBytes': tools.MAX_GROWTH, 'baselineAvailableBytes': value.baseline, 'sourceFiles': sources}
        tools.write_json(value.folder / 'owner.json', owner)
        for name in ('installed-versions.json', 'pip-install.json'):
            path = value.reports / name; path.touch(mode=0o600)
        image['Size'] = 4 * MIB
        repaired = deepcopy(image); repaired['Id'] = 'sha256:' + 'f' * 64
        repaired['Config']['Labels'].update({tools.LABEL: value.token, 'io.doorhandle.release': value.args.tag,
            'io.doorhandle.commit': value.args.commit, 'io.doorhandle.source': value.args.source_sha256,
            'io.doorhandle.ci-tools-recipe-sha256': sources[tools.RECIPE],
            'io.doorhandle.ci-tools-requirements-sha256': sources[tools.REQUIREMENTS]})
        metadata_id = 'a' * 64
        cleanup = {'status': 'STOPPED', 'containersCreated': [metadata_id], 'remaining': [],
            'containers': [{'containerId': metadata_id, 'sourceImageId': image['Id'], 'started': False, 'pid': 0, 'removed': True}]}
        old_call = value.call.side_effect
        def inspect(*args, **kwargs):
            if args == ('image', 'inspect', repaired['Id']):
                calls.append(args); return json.dumps([repaired]).encode()
            if args == ('ps', '-aq', '--no-trunc', '--filter', 'id=' + metadata_id):
                calls.append(args); return b''
            return old_call(*args, **kwargs)
        value.call.side_effect = inspect
        value.available = mock.Mock(return_value=value.baseline - 1024)
        def repair(current_sources, cached):
            self.assertEqual(sources, current_sources); self.assertEqual(image['Id'], cached['Id'])
            self.assertEqual(image['RootFS'], repaired['RootFS'])
            value.dependency_image = cached['Id']; value.image = repaired['Id']
            sample = {'elapsedSeconds': 1.0, 'availableDiskBytes': value.baseline - 1024, 'hostDiskGrowthBytes': 1024,
                      'ownedWritableBytes': 0, 'ownedMemoryPeakBytes': 3000, 'oomKilled': False}
            value.snapshot.write_text(json.dumps(sample) + '\n'); value.snapshot.chmod(0o600)
            value.observed = {'hostDiskGrowthPeakBytes': 1024, 'containerWritablePeakBytes': 0,
                              'memoryPeakBytes': 3000, 'oomKilled': False, 'samples': 1}
            for name, raw in [('config-commit.stdout', (repaired['Id'] + '\n').encode()), ('config-commit.stderr', b'')]:
                path = value.folder / name; path.write_bytes(raw); path.chmod(0o600)
            return deepcopy(cleanup)
        value.repair_cached_image = mock.Mock(side_effect=repair)
        return value, sources, pinned, owner, repaired, cleanup

    def completed_reuse(self, root):
        source, producer, image, calls, _ = self.completed_runtime_producer(root)
        value, sources, pinned, owner, repaired, cleanup = self.reuse_attempt(source, producer, image, calls)
        before = {str(path.relative_to(source.inbox)): path.read_bytes() for path in source.inbox.rglob('*') if path.is_file()}
        result = value.reuse_completed_dependencies(sources, pinned, owner)
        published = tools.complete_preparation(value, result)
        readback = object.__new__(tools.PreparedReadback)
        readback.__dict__.update(value.__dict__)
        return source, producer, image, readback, repaired, cleanup, before, calls, published

    def test_real_reuse_completion_and_readback_preserve_originals_and_bind_current_metadata_without_pip(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(tools, 'create_arguments') as install:
            source, producer, image, value, repaired, cleanup, before, calls, published = self.completed_reuse(Path(directory))
            result = value.read_prepared()
            self.assertTrue(result['readbackValidated']); self.assertEqual('PREPARED', result['status'])
            self.assertEqual('REUSED_IMMUTABLE_IMAGE_CONFIG_REPAIRED', result['dependencyPreparation'])
            self.assertFalse(result['pipExecutedThisAttempt']); self.assertFalse(result['testsExecuted'])
            self.assertEqual(image['Id'], result['dependencyImageId']); self.assertEqual(repaired['Id'], result['pythonImageId'])
            self.assertEqual(published['completionSha256'], result['completionSha256']); self.assertEqual(cleanup, result['cleanup'])
            reuse = json.loads((value.folder / 'reuse.json').read_text())
            self.assertEqual(2, reuse['schemaVersion']); self.assertEqual(source.args.tag, reuse['producerRelease'])
            self.assertEqual(tools.digest(source.folder / 'completion.json'), reuse['producerCompletionSha256'])
            self.assertNotEqual(reuse['producerCommit'], result['commit'])
            self.assertNotEqual(reuse['producerSourceSha256'], result['sourceSha256'])
            self.assertNotEqual(reuse['producerProofs']['python-test-requirements.txt'], reuse['currentSourceFiles'][tools.REQUIREMENTS])
            self.assertEqual(22, len(json.loads((value.reports / 'installed-versions.json').read_text())))
            for name in ('pip-install.json', 'installed-versions.json'):
                self.assertEqual((source.reports / name).read_bytes(), (value.reports / name).read_bytes())
            complete = json.loads((value.folder / 'completion.json').read_text())
            self.assertEqual(set(tools.completion_files(result)), set(complete['proofs']))
            self.assertIn('requirements.txt', complete['proofs']); self.assertIn('reuse.json', complete['proofs'])
            self.assertIn('config-commit.stdout', complete['proofs']); self.assertNotIn('pip.log', complete['proofs'])
            self.assertEqual(before, {str(path.relative_to(source.inbox)): path.read_bytes() for path in source.inbox.rglob('*') if path.is_file()})
            self.assertEqual('exited', producer['State']['Status']); self.assertFalse(producer['State']['Running'])
            value.repair_cached_image.assert_called_once(); install.assert_not_called()
            self.assertTrue(calls and all(call[0] in ('image', 'inspect', 'ps') for call in calls))

    def test_resealed_reuse_descriptors_cannot_rebind_the_original_producer_or_current_source(self):
        for damage in ('producer-completion', 'producer-release', 'producer-owner', 'producer-proof', 'source-image',
                       'current-source', 'unexpected-field', 'disk-bound'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                _, _, _, value, _, _, _, _, _ = self.completed_reuse(Path(directory))
                path = value.folder / 'reuse.json'; reuse = json.loads(path.read_text())
                if damage == 'producer-completion': reuse['producerCompletionSha256'] = '0' * 64
                if damage == 'producer-release': reuse['producerRelease'] = 'ci-999-' + COMMIT[:12]
                if damage == 'producer-owner': reuse['producerOwnerSha256'] = '0' * 64
                if damage == 'producer-proof': reuse['producerProofs']['reports/pip-install.json'] = '0' * 64
                if damage == 'source-image': reuse['sourceImageId'] = tools.CACHED_PYTHON
                if damage == 'current-source': reuse['currentSourceFiles'][tools.RECIPE] = '0' * 64
                if damage == 'unexpected-field': reuse['notAdmitted'] = True
                if damage == 'disk-bound': reuse['observedGrowthBytes'] += 1
                path.write_text(json.dumps(reuse))
                receipt_path = value.folder / 'preparation.json'; receipt = json.loads(receipt_path.read_text())
                receipt['reuseEvidenceSha256'] = tools.digest(path); receipt_path.write_text(json.dumps(receipt))
                self.reseal_readback(value)
                with self.assertRaisesRegex(ValueError, 'Config-only producer evidence'): value.read_prepared()

    def test_repaired_readback_rejects_started_or_remaining_metadata_and_changed_dependency_layers(self):
        for damage in ('started', 'pid', 'source-image', 'not-removed', 'remaining', 'live-container', 'layers'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                _, _, _, value, repaired, cleanup, _, _, _ = self.completed_reuse(Path(directory))
                path = value.folder / 'preparation.json'; receipt = json.loads(path.read_text())
                if damage == 'started': receipt['cleanup']['containers'][0]['started'] = True
                if damage == 'pid': receipt['cleanup']['containers'][0]['pid'] = 123
                if damage == 'source-image': receipt['cleanup']['containers'][0]['sourceImageId'] = tools.CACHED_PYTHON
                if damage == 'not-removed': receipt['cleanup']['containers'][0]['removed'] = False
                if damage == 'remaining': receipt['cleanup']['remaining'] = cleanup['containersCreated']
                if damage == 'layers': repaired['RootFS']['Layers'].append('unexpected-write')
                if damage == 'live-container':
                    original = value.call.side_effect
                    def still_exists(*args, **kwargs):
                        if args[0] == 'ps': return (cleanup['containersCreated'][0] + '\n').encode()
                        return original(*args, **kwargs)
                    value.call.side_effect = still_exists
                path.write_text(json.dumps(receipt)); self.reseal_readback(value)
                with self.assertRaises(ValueError): value.read_prepared()

    def test_current_report_slots_cannot_overwrite_existing_or_linked_files_during_reuse(self):
        for damage in ('nonempty', 'symlink', 'hardlink'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
                value, sources, pinned, owner, _, _ = self.reuse_attempt(source, producer, image, calls)
                path = value.reports / 'installed-versions.json'
                if damage == 'nonempty': path.write_text('do not replace')
                elif damage == 'symlink': path.unlink(); path.symlink_to(source.reports / 'installed-versions.json')
                else:
                    path.unlink(); victim = value.folder / 'another-owned-report-slot'
                    victim.touch(mode=0o600); os.link(victim, path)
                original = (source.reports / 'installed-versions.json').read_bytes()
                with self.assertRaisesRegex(ValueError, 'report slot was replaced'):
                    value.reuse_completed_dependencies(sources, pinned, owner)
                self.assertEqual(original, (source.reports / 'installed-versions.json').read_bytes())
                value.repair_cached_image.assert_not_called()
                self.assertFalse((value.folder / 'preparation.json').exists())

    def test_different_pins_and_repaired_images_are_not_recursive_dependency_producers(self):
        for damage in ('pins', 'repaired'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                source, producer, image, calls, _ = self.completed_runtime_producer(Path(directory))
                value, sources, pinned = self.current_consumer(source, producer, image, calls)
                if damage == 'pins': pinned = {**pinned, 'qdrant-client': '1.19.0'}
                else:
                    path = source.folder / 'preparation.json'; receipt = json.loads(path.read_text())
                    receipt['dependencyPreparation'] = 'REUSED_IMMUTABLE_IMAGE_CONFIG_REPAIRED'; path.write_text(json.dumps(receipt))
                with mock.patch.object(value, 'repair_cached_image') as repair:
                    self.assertIsNone(value.reuse_completed_dependencies(sources, pinned, {})); repair.assert_not_called()
                self.assertFalse(value.folder.exists())
                self.assertTrue(all(call[0] in ('image', 'inspect') for call in calls))


if __name__ == '__main__':
    unittest.main()
