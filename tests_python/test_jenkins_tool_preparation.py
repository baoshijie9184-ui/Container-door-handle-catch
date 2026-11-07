"""Tool recipe boundary checks; Jenkins executes this file only on admitted ECS."""
import hashlib
import importlib.util
import io
import json
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
