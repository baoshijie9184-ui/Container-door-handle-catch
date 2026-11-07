"""Tool recipe boundary checks; Jenkins executes this file only on admitted ECS."""
import hashlib
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest


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


if __name__ == '__main__':
    unittest.main()
