"""Live fixture cgroup identity contracts; execute only on the admitted ECS."""
from contextlib import ExitStack
import importlib.util
import io
import os
import json
import subprocess
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


MODULE = Path(__file__).resolve().parents[1] / 'script/jenkins/prepare-compact-fixtures.py'
SPEC = importlib.util.spec_from_file_location('fixture_cgroup_preparer', MODULE)
preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparer)


class PrivateJsonPublicationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.file = self.temp / 'private.json'
        preparer.write_json(self.file, {'generation': 1})

    def test_ordinary_private_inputs_keep_owner_only_modes_and_json_shape(self):
        for mode in (0o400, 0o600, 0o700):
            with self.subTest(mode=mode):
                self.file.chmod(mode)
                self.assertEqual({'generation': 1}, preparer.private_json(self.file))

    def test_static_inputs_do_not_acquire_a_publication_lock(self):
        import fcntl
        self.temp.chmod(0o755)  # Existing static inputs never required a private parent.
        with patch.object(fcntl, 'flock', side_effect=AssertionError('static input must not lock')):
            preparer.write_json(self.file, {'generation': 2}, replace=True)
            self.assertEqual({'generation': 2}, preparer.private_json(self.file))

    def test_private_read_never_reopens_the_path_for_content(self):
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('path must not reopen')):
            self.assertEqual({'generation': 1}, preparer.private_json(self.file, publication_lock=True))

    def test_zero_link_inode_is_strictly_rejected_without_replacement_lookup_or_retry(self):
        original = os.fstat; calls = []
        def detached(descriptor):
            metadata = original(descriptor)
            if preparer.stat.S_ISREG(metadata.st_mode):
                calls.append(metadata); self.file.unlink()
                return original(descriptor)
            return metadata
        with patch.object(preparer.os, 'fstat', side_effect=detached):
            with self.assertRaises(preparer.PrivateJsonError) as failed:
                preparer.private_json(self.file, publication_lock=True)
        self.assertEqual(1, len(calls)); self.assertEqual(['links'], failed.exception.observation['fields'])
        self.assertEqual(['OPEN'], [row['stage'] for row in failed.exception.observation['observations']])

    def test_uncooperative_replace_during_read_is_not_an_accepted_zero_link_snapshot(self):
        original = os.fstat; changed = []
        def replace(descriptor):
            metadata = original(descriptor)
            if preparer.stat.S_ISREG(metadata.st_mode) and not changed:
                changed.append(True)
                preparer.write_json(self.file, {'generation': 2}, replace=True)  # Deliberately ignores the protocol.
            return metadata
        with patch.object(preparer.os, 'fstat', side_effect=replace):
            with self.assertRaises(preparer.PrivateJsonError) as failed:
                preparer.private_json(self.file, publication_lock=True)
        self.assertEqual(['links'], failed.exception.observation['fields'])
        self.assertEqual('READ', failed.exception.observation['observations'][-1]['stage'])

    def test_reader_waits_until_replace_and_directory_fsync_have_completed(self):
        import fcntl
        for boundary in ('replace', 'directory-fsync'):
            preparer.write_json(self.file, {'generation': 1}, replace=True)
            entered, release, contended = threading.Event(), threading.Event(), threading.Event()
            result, errors = [], []
            original_replace, original_sync, original_flock = os.replace, os.fsync, fcntl.flock
            def pause():
                entered.set()
                if not release.wait(2): raise AssertionError('publication gate was not released')
            def replace(*args, **kwargs):
                if boundary == 'replace': pause()
                return original_replace(*args, **kwargs)
            def sync(descriptor):
                if boundary == 'directory-fsync' and preparer.stat.S_ISDIR(os.fstat(descriptor).st_mode): pause()
                return original_sync(descriptor)
            def flock(descriptor, operation):
                try: return original_flock(descriptor, operation)
                except BlockingIOError:
                    if operation & fcntl.LOCK_SH: contended.set()
                    raise
            def run(function):
                try: function()
                except BaseException as error: errors.append(error)
            writer = threading.Thread(target=run, args=(lambda: preparer.write_json(
                self.file, {'generation': 2}, replace=True, publication_lock=True),))
            reader = threading.Thread(target=run, args=(lambda: result.append(
                preparer.private_json(self.file, publication_lock=True)),))
            with self.subTest(boundary=boundary), patch.object(preparer.os, 'replace', side_effect=replace), \
                 patch.object(preparer.os, 'fsync', side_effect=sync), patch.object(fcntl, 'flock', side_effect=flock):
                try:
                    writer.start(); self.assertTrue(entered.wait(2))
                    reader.start(); self.assertTrue(contended.wait(2)); self.assertEqual([], result)
                finally:
                    release.set(); writer.join(2)
                    if reader.ident is not None: reader.join(2)
            self.assertFalse(writer.is_alive()); self.assertFalse(reader.is_alive()); self.assertEqual([], errors)
            self.assertEqual([{'generation': 2}], result)

    def test_writer_waits_for_complete_reader_snapshot_on_the_same_directory_inode(self):
        import fcntl
        entered, release, contended = threading.Event(), threading.Event(), threading.Event()
        result, errors = [], []
        original_read, original_flock = preparer.read_private_json, fcntl.flock
        def read(path):
            entered.set()
            if not release.wait(2): raise AssertionError('reader gate was not released')
            return original_read(path)
        def flock(descriptor, operation):
            try: return original_flock(descriptor, operation)
            except BlockingIOError:
                if operation & fcntl.LOCK_EX: contended.set()
                raise
        def run(function):
            try: function()
            except BaseException as error: errors.append(error)
        reader = threading.Thread(target=run, args=(lambda: result.append(preparer.private_json(
            self.file, publication_lock=True)),))
        writer = threading.Thread(target=run, args=(lambda: preparer.write_json(
            self.file, {'generation': 2}, replace=True, publication_lock=True),))
        with patch.object(preparer, 'read_private_json', side_effect=read), patch.object(fcntl, 'flock', side_effect=flock):
            try:
                reader.start(); self.assertTrue(entered.wait(2))
                writer.start(); self.assertTrue(contended.wait(2))
            finally:
                release.set(); reader.join(2)
                if writer.ident is not None: writer.join(2)
        self.assertFalse(reader.is_alive()); self.assertFalse(writer.is_alive()); self.assertEqual([], errors)
        self.assertEqual([{'generation': 1}], result)
        self.assertEqual({'generation': 2}, preparer.private_json(self.file))

    def test_reader_lock_timeout_is_bounded_and_never_reads_json(self):
        import fcntl
        with patch.object(fcntl, 'flock', side_effect=BlockingIOError), \
             patch.object(preparer.time, 'monotonic', side_effect=[10.0, 10.0, 11.0]), \
             patch.object(preparer.time, 'sleep'), \
             patch.object(preparer, 'read_private_json') as read:
            with self.assertRaises(preparer.PrivateJsonError) as failed:
                preparer.private_json(self.file, publication_lock=True)
        read.assert_not_called()
        self.assertEqual('PUBLICATION_LOCK_TIMEOUT', failed.exception.observation['reason'])
        self.assertEqual('SHARED', failed.exception.observation['lockMode'])
        self.assertEqual(1, failed.exception.observation['waitLimitSeconds'])

    def test_writer_lock_timeout_never_replaces_the_existing_publication(self):
        import fcntl
        with patch.object(fcntl, 'flock', side_effect=BlockingIOError), \
             patch.object(preparer.time, 'monotonic', side_effect=[10.0, 10.0, 11.0]), \
             patch.object(preparer.time, 'sleep'), patch.object(preparer.os, 'replace') as replace:
            with self.assertRaises(preparer.PrivateJsonError) as failed:
                preparer.write_json(self.file, {'generation': 2}, replace=True, publication_lock=True)
        replace.assert_not_called(); self.assertEqual('EXCLUSIVE', failed.exception.observation['lockMode'])
        self.assertEqual({'generation': 1}, preparer.private_json(self.file))

    def test_lock_release_after_failure_allows_the_next_owned_writer(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
            with preparer.json_publication_lock(self.file, enabled=True): raise RuntimeError('synthetic failure')
        preparer.write_json(self.file, {'generation': 2}, replace=True, publication_lock=True)
        self.assertEqual({'generation': 2}, preparer.private_json(self.file, publication_lock=True))

    def test_publication_parent_must_be_owned_private_and_not_a_symlink(self):
        self.temp.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'publication directory'):
            preparer.private_json(self.file, publication_lock=True)
        self.temp.chmod(0o700)
        parent = self.temp / 'parent'; parent.symlink_to(self.temp, target_is_directory=True)
        with self.assertRaises(ValueError): preparer.private_json(parent / self.file.name, publication_lock=True)

    def test_nonregular_hardlinked_or_oversized_objects_still_fail_metadata(self):
        directory = self.temp / 'directory'; directory.mkdir()
        link = self.temp / 'link'; os.link(self.file, link)
        oversized = self.temp / 'oversized'
        with oversized.open('wb') as stream: stream.truncate(16 * 1024 * 1024 + 1)
        oversized.chmod(0o600)
        for path, field in ((directory, 'regularFile'), (link, 'links'), (oversized, 'size')):
            with self.subTest(field=field), self.assertRaises(preparer.PrivateJsonError) as failed:
                preparer.private_json(path, publication_lock=True)
            self.assertIn(field, failed.exception.observation['fields'])

    def test_wrong_uid_still_fails_before_read(self):
        with patch.object(preparer.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaises(preparer.PrivateJsonError) as failed: preparer.private_json(self.file)
        self.assertEqual(['uid'], failed.exception.observation['fields'])

    def test_unsafe_file_permissions_are_not_retried(self):
        self.file.chmod(0o640)
        with self.assertRaises(preparer.PrivateJsonError) as failed:
            preparer.private_json(self.file, publication_lock=True)
        self.assertEqual(['mode'], failed.exception.observation['fields'])
        self.assertEqual(1, len(failed.exception.observation['observations']))

    def test_symlink_leaf_parent_and_relative_paths_remain_rejected(self):
        leaf = self.temp / 'leaf'; leaf.symlink_to(self.file)
        parent = self.temp / 'parent'; parent.symlink_to(self.temp, target_is_directory=True)
        for path in (leaf, parent / self.file.name, Path('private.json')):
            with self.subTest(path=path), self.assertRaises(ValueError): preparer.private_json(path)

    def test_in_place_content_or_mode_changes_are_not_atomic_publications(self):
        original = os.fstat
        for damage in ('size', 'mode'):
            preparer.write_json(self.file, {'generation': 1}, replace=True)
            seen = []
            def mutate(descriptor):
                metadata = original(descriptor)
                if preparer.stat.S_ISREG(metadata.st_mode):
                    seen.append(metadata)
                    if len(seen) == 1:
                        if damage == 'size': self.file.write_bytes(b'{"generation":12345}')
                        else: self.file.chmod(0o640)
                return metadata
            with self.subTest(damage=damage), patch.object(preparer.os, 'fstat', side_effect=mutate):
                with self.assertRaises(preparer.PrivateJsonError): preparer.private_json(self.file, publication_lock=True)

    def test_json_errors_are_not_retried_or_exported_as_json_content(self):
        for body in (b'{"password":"synthetic-private",', b'{"same":1,"same":2}'):
            self.file.write_bytes(body)
            with self.subTest(body=body), self.assertRaises(ValueError):
                preparer.private_json(self.file, publication_lock=True)

    def test_reader_uses_the_existing_sixteen_mib_bound_not_unbounded_read(self):
        original = os.fdopen; sizes = []
        class Reader:
            def __init__(self, *args, **kwargs): self.stream = original(*args, **kwargs)
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def read(self, size): sizes.append(size); return self.stream.read(size)
        with patch.object(preparer.os, 'fdopen', side_effect=Reader):
            self.assertEqual({'generation': 1}, preparer.private_json(self.file))
        self.assertEqual([16 * 1024 * 1024 + 1], sizes)

    def test_every_watch_status_and_owner_publisher_uses_the_same_lock_protocol(self):
        import ast
        tree = ast.parse(MODULE.read_text('utf8'))
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        calls = []
        for name, target in (('start_fixture_watch', 'file'), ('run', 'self.status_file'), ('stop', 'self.status_file')):
            selected = [node for node in ast.walk(functions[name]) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == 'write_json'
                        and ast.unparse(node.args[0]) == target]
            self.assertEqual(2 if name != 'stop' else 1, len(selected))
            calls.extend(selected)
        for call in calls:
            self.assertTrue(next(keyword.value.value for keyword in call.keywords if keyword.arg == 'publication_lock'))
        for name, fragment in (('read_status', 'self.status_file'), ('main', 'fixture-watch-owner.json')):
            call = next(node for node in ast.walk(functions[name]) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == 'private_json'
                        and fragment in ast.unparse(node.args[0]))
            self.assertTrue(next(keyword.value.value for keyword in call.keywords if keyword.arg == 'publication_lock'))


class FixtureCgroupProbeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.proc = self.temp / 'proc'
        self.cgroups = self.temp / 'cgroups'
        self.relative = '/docker/fixture'
        self.group = self.cgroups / self.relative.lstrip('/')
        self.group.mkdir(parents=True)
        (self.proc / '31415').mkdir(parents=True)
        self.write('memory.max', str(preparer.MYSQL_MEMORY))
        self.write('memory.swap.max', '0')
        self.write('memory.current', '1024')
        self.write('memory.events', 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n')
        (self.proc / '31415/cgroup').write_text('0::' + self.relative + '\n')
        self.identity = {'pid': 31415, 'startTicks': 12345}
        self.journal = {'containerId': 'a' * 64, 'sourceContainerId': 'b' * 64,
            'image': 'sha256:' + 'c' * 64, 'token': 'fixture-token', 'containerName': 'fixture',
            'work': '/private/owned-work', 'dataDirectory': '/private/owned-work/data', 'port': 3307}
        self.row = {'Id': 'a' * 64, 'HostConfig': {'Memory': preparer.MYSQL_MEMORY,
            'MemorySwap': preparer.MYSQL_MEMORY}, 'State': {'Pid': 31415, 'OOMKilled': False}}
        self.inspect = Mock(side_effect=lambda: self.row)
        self.monitor = preparer.PreparationMonitor.__new__(preparer.PreparationMonitor)
        self.monitor.preparation = SimpleNamespace(journal=self.journal, inspect_owned=self.inspect)
        self.stack.enter_context(patch.object(preparer, 'Path', side_effect=self.mapped_path))
        self.stack.enter_context(patch.object(preparer, 'proc_identity',
            side_effect=lambda _pid: None if self.identity is None else dict(self.identity)))

    def mapped_path(self, value):
        text = str(value)
        if text.startswith('/proc/'):
            return self.proc / text[len('/proc/'):]
        if text == '/sys/fs/cgroup':
            return self.cgroups
        return Path(value)

    def write(self, name, value):
        (self.group / name).write_text(value + '\n', encoding='ascii')

    def seed(self):
        self.assertEqual((1024, 0), self.monitor.fixture_memory())

    def test_anonymous_admission_never_credits_file_cache_or_more_than_current(self):
        self.write('memory.stat', 'anon 256\nfile 768\nslab_reclaimable 128')
        self.monitor.fixture_memory(include_anonymous=True)
        self.assertEqual(256, self.monitor.fixture_observation['anonymousMemoryBytes'])
        self.write('memory.stat', 'anon 2048\nfile 4096')
        self.monitor.fixture_memory(include_anonymous=True)
        self.assertEqual(1024, self.monitor.fixture_observation['anonymousMemoryBytes'])

    def test_missing_or_malformed_anonymous_measurement_cannot_receive_credit(self):
        for body in ('file 1024', 'anon -1', 'anon 1\nanon 2', 'anon private-data', 'anon 1 extra'):
            with self.subTest(body=body):
                self.write('memory.stat', body)
                with self.assertRaises(ValueError): self.monitor.fixture_memory(include_anonymous=True)

    def test_registered_ancillary_fixture_reuses_actual_owned_kernel_limits(self):
        limit = 128 * preparer.MIB
        self.row['HostConfig'].update(Memory=limit, MemorySwap=limit)
        self.row['State'].update(Running=True, Restarting=False, Paused=False, Dead=False)
        self.write('memory.max', str(limit)); self.write('memory.stat', 'anon 256\nfile 768')
        watch = preparer.FixtureWatch.__new__(preparer.FixtureWatch)
        result = watch.container_memory('redis', self.inspect, limit)
        self.assertEqual(limit - 256, result['remainingMemoryBytes'])
        self.assertEqual(self.journal['containerId'], result['containerId'])
        self.assertEqual(self.relative, result['cgroup'])
        self.inspect.assert_called_once_with()
        self.write('memory.swap.max', '1')
        with self.assertRaisesRegex(ValueError, 'kernel memory limits'):
            watch.container_memory('redis', self.inspect, limit)

    def test_ancillary_owned_or_running_failure_precedes_kernel_credit(self):
        watch = preparer.FixtureWatch.__new__(preparer.FixtureWatch)
        with patch.object(preparer.PreparationMonitor, 'fixture_memory') as probe:
            with self.assertRaises(ValueError):
                watch.container_memory('redis', Mock(side_effect=ValueError('owner refused')), 128 * preparer.MIB)
            for field in ('Running', 'Restarting', 'Paused', 'Dead', 'OOMKilled'):
                self.row['State'].update(Running=True, Restarting=False, Paused=False, Dead=False, OOMKilled=False)
                self.row['State'][field] = field != 'Running'
                with self.assertRaises(ValueError): watch.container_memory('redis', self.inspect, 128 * preparer.MIB)
            probe.assert_not_called()

    def test_no_container_before_bootstrap_needs_no_docker_probe(self):
        self.journal.pop('containerId')
        self.assertEqual((0, 0), self.monitor.fixture_memory())
        self.inspect.assert_not_called()

    def test_not_started_bootstrap_keeps_oom_and_does_not_cache(self):
        self.row['State'].update(Pid=0, OOMKilled=True)
        self.assertEqual((0, 1), self.monitor.fixture_memory())
        self.assertEqual((0, 1), self.monitor.fixture_memory())
        self.assertEqual(2, self.inspect.call_count)
        self.assertFalse(hasattr(self.monitor, '_fixture_cgroup'))

    def test_live_second_probe_reads_current_values_without_docker(self):
        self.seed()
        self.write('memory.current', '8192')
        self.write('memory.events', 'oom_kill 2')
        self.assertEqual((8192, 2), self.monitor.fixture_memory())
        self.inspect.assert_called_once_with()

    def test_bootstrap_inspect_failure_cannot_be_bypassed(self):
        self.inspect.side_effect = ValueError('owned inspection refused')
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()
        self.assertFalse(hasattr(self.monitor, '_fixture_cgroup'))

    def test_bootstrap_memory_or_swap_configuration_mismatch_fails(self):
        for field in ('Memory', 'MemorySwap'):
            with self.subTest(field=field):
                self.row['HostConfig'][field] = preparer.MYSQL_MEMORY + 1
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()
                self.row['HostConfig'][field] = preparer.MYSQL_MEMORY
        self.assertFalse(hasattr(self.monitor, '_fixture_cgroup'))

    def test_bootstrap_pid_must_be_a_live_positive_integer(self):
        for pid in (True, -1, '31415'):
            with self.subTest(pid=pid):
                self.row['State']['Pid'] = pid
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()
        self.assertFalse(hasattr(self.monitor, '_fixture_cgroup'))

    def test_cached_journal_ownership_changes_are_rejected(self):
        self.seed()
        for key in self.journal:
            previous = self.journal[key]
            with self.subTest(key=key):
                self.journal[key] = 'changed'
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()
                self.journal[key] = previous
        self.inspect.assert_called_once_with()

    def test_cached_container_disappearance_cannot_return_zero(self):
        self.seed()
        self.journal.pop('containerId')
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_cached_process_disappearance_cannot_return_stale_values(self):
        self.seed()
        self.identity = None
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_cached_pid_reuse_is_rejected(self):
        self.seed()
        self.identity['startTicks'] += 1
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_cached_pid_identity_change_is_rejected(self):
        self.seed()
        self.identity['pid'] += 1
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_live_process_cgroup_movement_is_rejected(self):
        self.seed()
        (self.proc / '31415/cgroup').write_text('0::/docker/another\n')
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_missing_or_ambiguous_unified_cgroup_is_rejected(self):
        for value in ('1:memory:/docker/fixture\n', '0::/a\n0::/b\n', '0::/\n', '0::/a/../b\n'):
            with self.subTest(value=value):
                (self.proc / '31415/cgroup').write_text(value)
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()

    def test_replaced_cgroup_directory_is_rejected(self):
        self.seed()
        original = self.group.with_name('original')
        self.group.rename(original)
        self.group.mkdir()
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_cgroup_directory_symlink_is_rejected(self):
        self.seed()
        original = self.group.with_name('original')
        self.group.rename(original)
        self.group.symlink_to(original, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_actual_kernel_memory_limit_drift_is_rejected(self):
        self.seed()
        for value in ('max', '0', str(preparer.MYSQL_MEMORY + 4096)):
            with self.subTest(value=value):
                self.write('memory.max', value)
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()

    def test_actual_kernel_swap_limit_drift_is_rejected(self):
        self.seed()
        self.write('memory.swap.max', '4096')
        with self.assertRaises(ValueError):
            self.monitor.fixture_memory()

    def test_failed_first_pair_retains_both_values_without_retry_or_stale_success(self):
        self.seed(); previous = dict(self.monitor.fixture_observation)
        self.write('memory.max', 'max'); self.write('memory.swap.max', '4096')
        with patch.object(preparer.os, 'open', wraps=os.open) as opened:
            with self.assertRaises(ValueError) as caught: self.monitor.fixture_memory()
        error, value = self.monitor.fixture_limit_failure
        self.assertIs(caught.exception, error)
        self.assertEqual(['memory.max', 'memory.swap.max'], [Path(call.args[0]).name for call in opened.call_args_list])
        self.assertEqual('BEFORE_COUNTERS', value['phase'])
        self.assertEqual({'memory.max': {'status': 'READ', 'value': 'max'},
                          'memory.swap.max': {'status': 'READ', 'value': '4096'}}, value['controls'])
        self.assertTrue(value['identityVerifiedBeforeProbe'] and value['identityVerifiedAfterFailure'])
        self.assertEqual(31415, value['pid']); self.assertEqual(12345, value['startTicks'])
        self.assertEqual(preparer.MYSQL_MEMORY, value['expectedMemoryLimitBytes'])
        self.assertEqual(0, value['expectedSwapLimitBytes'])
        self.assertEqual(previous, self.monitor.fixture_observation)

    def test_failed_second_pair_retains_changed_values_and_phase(self):
        self.seed(); original_open = os.open
        def change(path, *args, **kwargs):
            result = original_open(path, *args, **kwargs)
            if Path(path).name == 'memory.events': self.write('memory.swap.max', 'max')
            return result
        with patch.object(preparer.os, 'open', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'limits changed'): self.monitor.fixture_memory()
        value = self.monitor.fixture_limit_failure[1]
        self.assertEqual('AFTER_COUNTERS', value['phase'])
        self.assertEqual({'status': 'READ', 'value': 'max'}, value['controls']['memory.swap.max'])
        self.assertEqual('0', str(self.monitor.fixture_observation['swapLimitBytes']))

    def test_limit_diagnostics_do_not_export_invalid_oversized_or_non_ascii_bytes(self):
        self.seed()
        for body in (b'MYSQL_PWD=private-value', b'1' * 4097, b'\xffprivate-value', b''):
            with self.subTest(body=body[:8]):
                (self.group / 'memory.max').write_bytes(body)
                with self.assertRaises(ValueError): self.monitor.fixture_memory()
                value = self.monitor.fixture_limit_failure[1]
                self.assertIn(value['controls']['memory.max']['status'], ('INVALID_VALUE', 'READ_FAILED'))
                self.assertEqual({'status': 'READ', 'value': '0'}, value['controls']['memory.swap.max'])
                raw = json.dumps(value)
                self.assertNotIn('private-value', raw); self.assertNotIn('11111111', raw)
                self.assertNotIn(str(self.temp), raw)

    def test_first_limit_io_failure_retains_original_error_and_still_reads_swap(self):
        self.seed(); original_open = os.open
        failure = OSError('synthetic-private-path')
        def unavailable(path, *args, **kwargs):
            if Path(path).name == 'memory.max': raise failure
            return original_open(path, *args, **kwargs)
        with patch.object(preparer.os, 'open', side_effect=unavailable):
            with self.assertRaises(OSError) as caught: self.monitor.fixture_memory()
        self.assertIs(failure, caught.exception)
        value = self.monitor.fixture_limit_failure[1]
        self.assertEqual({'status': 'READ_FAILED', 'errorType': 'OSError'}, value['controls']['memory.max'])
        self.assertEqual({'status': 'READ', 'value': '0'}, value['controls']['memory.swap.max'])
        self.assertNotIn('synthetic-private-path', json.dumps(value))

    def test_failed_limit_read_does_not_claim_identity_survived_replaced_process(self):
        self.seed(); original_open = os.open
        def changed(path, *args, **kwargs):
            if Path(path).name == 'memory.max':
                self.identity['startTicks'] += 1; self.write('memory.max', 'max')
            return original_open(path, *args, **kwargs)
        with patch.object(preparer.os, 'open', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'limits differ'): self.monitor.fixture_memory()
        self.assertFalse(self.monitor.fixture_limit_failure[1]['identityVerifiedAfterFailure'])

    def test_prior_limit_failure_cannot_be_attached_to_a_later_identity_failure(self):
        self.seed(); self.write('memory.swap.max', 'max')
        with self.assertRaises(ValueError): self.monitor.fixture_memory()
        self.assertIsNotNone(self.monitor.fixture_limit_failure)
        self.identity = None
        with self.assertRaises(ValueError): self.monitor.fixture_memory()
        self.assertIsNone(self.monitor.fixture_limit_failure)

    def test_failed_bootstrap_retains_limits_without_caching_success(self):
        self.write('memory.swap.max', 'max')
        with self.assertRaises(ValueError): self.monitor.fixture_memory()
        self.assertFalse(hasattr(self.monitor, '_fixture_cgroup'))
        self.assertFalse(hasattr(self.monitor, 'fixture_observation'))
        self.assertEqual('max', self.monitor.fixture_limit_failure[1]['controls']['memory.swap.max']['value'])

    def test_preparation_failure_receipt_retains_only_the_same_limit_failure(self):
        self.seed(); self.write('memory.swap.max', 'max')
        with self.assertRaises(ValueError) as caught: self.monitor.fixture_memory()
        preparation = preparer.Preparation.__new__(preparer.Preparation)
        preparation.resources = self.monitor; preparation.journal = {'phase': 'PREPARING'}
        preparation.work = self.temp
        preparation.args = SimpleNamespace(tag='ci-999-' + 'c' * 12, commit='c' * 40, source_sha256='d' * 64)
        value = preparation.retain_failure(caught.exception)
        self.assertEqual(self.monitor.fixture_limit_failure[1], value['kernelLimitFailure'])
        self.assertEqual(value['kernelLimitFailure'], json.loads((self.temp / 'failure.json').read_text())['kernelLimitFailure'])
        preparation.failure_origin = None
        value = preparation.retain_failure(ValueError('unrelated-private-error'))
        self.assertNotIn('kernelLimitFailure', value)
        self.assertNotIn('unrelated-private-error', json.dumps(value))

    def test_resource_failure_receipt_retains_the_failed_kernel_pair(self):
        self.seed(); self.write('memory.swap.max', 'max')
        with self.assertRaises(ValueError) as caught: self.monitor.fixture_memory()
        self.monitor.lock = threading.RLock(); self.monitor.failed = threading.Event()
        self.monitor.stop = threading.Event(); self.monitor.measured_at = time.monotonic()
        self.monitor.token = 'e' * 32; self.monitor.preparation.work = self.temp
        with patch.object(preparer.os, 'kill') as kill:
            self.monitor.fail(caught.exception, worker='collector')
        kill.assert_called_once()
        value = json.loads((self.temp / 'resource-failure.json').read_text())
        self.assertEqual(self.monitor.fixture_limit_failure[1], value['kernelLimitFailure'])
        self.assertEqual('OWNED_ATTEMPT_ONLY', value['stopScope'])

    def test_control_symlink_is_rejected(self):
        self.seed()
        current = self.group / 'memory.current'
        current.rename(self.group / 'other-current')
        current.symlink_to(self.group / 'other-current')
        with self.assertRaises(OSError):
            self.monitor.fixture_memory()

    def test_malformed_or_oversized_current_measurement_is_rejected(self):
        self.seed()
        for value in ('-1', 'NaN', '1' * 4097):
            with self.subTest(value=value[:8]):
                self.write('memory.current', value)
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()

    def test_missing_or_malformed_oom_counter_is_rejected(self):
        self.seed()
        for value in ('oom 0', 'oom_kill -1', 'oom_kill NaN'):
            with self.subTest(value=value):
                self.write('memory.events', value)
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()

    def test_process_drift_during_control_read_cannot_publish(self):
        self.seed()
        original_open = os.open
        def change_at_read(path, *args, **kwargs):
            result = original_open(path, *args, **kwargs)
            if Path(path).name == 'memory.events':
                self.identity['startTicks'] += 1
            return result
        with patch.object(preparer.os, 'open', side_effect=change_at_read):
            with self.assertRaises(ValueError):
                self.monitor.fixture_memory()

    def test_limit_drift_during_control_read_cannot_publish(self):
        self.seed()
        original_open = os.open
        def change_at_read(path, *args, **kwargs):
            result = original_open(path, *args, **kwargs)
            if Path(path).name == 'memory.events':
                self.write('memory.max', 'max')
            return result
        with patch.object(preparer.os, 'open', side_effect=change_at_read):
            with self.assertRaises(ValueError):
                self.monitor.fixture_memory()

    def test_ownership_drift_during_control_read_cannot_publish(self):
        self.seed()
        original_open = os.open
        def change_at_read(path, *args, **kwargs):
            result = original_open(path, *args, **kwargs)
            if Path(path).name == 'memory.events':
                self.journal['containerId'] = 'd' * 64
            return result
        with patch.object(preparer.os, 'open', side_effect=change_at_read):
            with self.assertRaises(ValueError):
                self.monitor.fixture_memory()

    def test_bootstrap_oom_flag_is_preserved_with_live_kernel_counter(self):
        self.row['State']['OOMKilled'] = True
        self.assertEqual((1024, 1), self.monitor.fixture_memory())
        self.assertEqual((1024, 1), self.monitor.fixture_memory())

    def test_kernel_peak_is_retained_when_available(self):
        self.write('memory.peak', '16384')
        self.seed()
        self.assertEqual(16384, self.monitor.fixture_observation['memoryPeakBytes'])
        self.assertEqual(1024, self.monitor.fixture_observation['memoryCurrentBytes'])
        self.assertEqual(0, self.monitor.fixture_observation['swapLimitBytes'])
        self.assertEqual(preparer.MYSQL_MEMORY, self.monitor.fixture_observation['memoryLimitBytes'])

    def test_older_kernel_without_peak_preserves_current_and_events(self):
        self.seed()
        self.assertIsNone(self.monitor.fixture_observation['memoryPeakBytes'])
        self.assertEqual(0, self.monitor.fixture_observation['events']['oom_kill'])

    def test_malformed_or_inconsistent_peak_is_rejected(self):
        for peak in ('NaN', '-1', '1023', '1' * 4097):
            with self.subTest(peak=peak[:8]):
                self.write('memory.peak', peak)
                with self.assertRaises(ValueError):
                    self.monitor.fixture_memory()


class FixtureWatchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.args = SimpleNamespace(tag='ci-999-' + 'c' * 12, commit='c' * 40, source_sha256='d' * 64)
        self.identity = {'instanceId': 'i-fixture', 'machineId': 'a' * 32, 'executionLocation': 'ECS'}
        self.process = {'pid': 6000, 'startTicks': 200, 'group': 6000, 'session': 6000}
        self.descriptor = {'version': 1, 'kind': 'doorhandle-fixture-watch-owner',
            'release': self.args.tag, 'commit': self.args.commit, 'sourceSha256': self.args.source_sha256,
            'identity': self.identity, 'containerId': 'a' * 64, 'ownerToken': 'e' * 32, 'groupToken': 'f' * 32,
            'process': self.process, 'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'kernelIdentity': {'pid': 31415, 'startTicks': 100, 'relative': '/docker/fixture', 'directory': [1, 2]},
            'memoryLimitBytes': preparer.MYSQL_MEMORY, 'swapLimitBytes': 0,
            'mysqlConfiguration': {'tableOpenCacheInstances': 1, 'bufferPoolBytes': 256 * preparer.MIB, 'maxConnections': 120}}
        self.file = self.temp / 'fixture-watch-owner.json'; preparer.write_json(self.file, self.descriptor)
        self.journal = {'containerId': 'a' * 64, 'fixtureWatch': {'file': str(self.file),
            'ownerToken': 'e' * 32, 'groupToken': 'f' * 32}, 'mysqlRuntimeConfiguration': self.descriptor['mysqlConfiguration']}
        self.preparation = SimpleNamespace(work=self.temp, args=self.args, identity=self.identity, journal=self.journal,
            inspect_owned=Mock())
        self.watch = preparer.FixtureWatch(self.preparation)

    def status(self, status='RUNNING', **changes):
        value = {key: item for key, item in self.descriptor.items() if key not in ('kind', 'groupToken', 'kernelIdentity')}
        value.update(kind='doorhandle-fixture-runtime', status=status, capturedMonotonic=time.monotonic(),
            watchStopped=False, probeCount=1)
        value.update(changes)
        preparer.write_json(self.watch.status_file, value, replace=self.watch.status_file.exists(), publication_lock=True)
        return value

    def probe(self):
        return {'memoryCurrentBytes': 1024, 'memoryPeakBytes': 4096, 'memoryLimitBytes': preparer.MYSQL_MEMORY,
            'swapLimitBytes': 0, 'events': {'oom_kill': 0}, 'state': {'Running': True, 'OOMKilled': False}}

    def test_same_process_and_capability_are_required_not_just_a_live_pid(self):
        with patch.object(preparer, 'proc_identity', return_value=dict(self.process)), \
             patch.object(preparer, 'group_members', return_value=[dict(self.process)]):
            self.assertTrue(self.watch.process_alive())
        with patch.object(preparer, 'proc_identity', return_value={**self.process, 'startTicks': 201}):
            with self.assertRaisesRegex(ValueError, 'reused'):
                self.watch.process_alive()
        with patch.object(preparer, 'proc_identity', return_value=dict(self.process)), \
             patch.object(preparer, 'group_members', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'ownership'):
                self.watch.process_alive()

    def test_zombie_is_not_a_running_watcher(self):
        with patch.object(preparer, 'proc_identity', return_value={**self.process, 'state': 'Z'}):
            self.assertFalse(self.watch.process_alive())

    def test_running_fresh_status_is_bound_to_exact_owner_and_runtime(self):
        self.status()
        with patch.object(self.watch, 'process_alive', return_value=True):
            self.assertEqual('RUNNING', self.watch.check()['status'])
        for key, change in (('ownerToken', '0' * 32), ('containerId', 'b' * 64), ('commit', 'b' * 40),
                            ('swapLimitBytes', 1), ('memoryLimitBytes', preparer.GIB)):
            with self.subTest(key=key):
                self.status(**{key: change})
                with self.assertRaises(ValueError):
                    self.watch.read_status()

    def test_locked_terminal_or_wrong_owner_status_cannot_admit_a_command(self):
        for damage in ('FAILED', 'STOPPED', 'owner'):
            self.status(damage if damage != 'owner' else 'RUNNING',
                        **({'ownerToken': '0' * 32} if damage == 'owner' else {}))
            with self.subTest(damage=damage), patch.object(self.watch, 'process_alive', return_value=True), \
                 patch.object(self.watch, 'read_status', wraps=self.watch.read_status) as reads:
                with self.assertRaises(ValueError): self.watch.check()
            self.assertEqual(1, reads.call_count)
            self.assertEqual('STATUS_IDENTITY' if damage == 'owner' else 'RUNNING', self.watch.check_failure['phase'])

    def test_publication_lock_wait_counts_toward_original_sample_age(self):
        import fcntl
        self.status(capturedMonotonic=98.5)
        clock = [100.0]; waited = []
        original = fcntl.flock
        def flock(descriptor, operation):
            if not waited:
                waited.append(True); raise BlockingIOError()
            return original(descriptor, operation)
        with patch.object(self.watch, 'process_alive', return_value=True), patch.object(fcntl, 'flock', side_effect=flock), \
             patch.object(preparer.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(preparer.time, 'sleep', side_effect=lambda _: clock.__setitem__(0, 100.6)):
            with self.assertRaisesRegex(ValueError, 'measurement is stale'): self.watch.check()
        self.assertEqual('FRESHNESS', self.watch.check_failure['phase'])
        self.assertEqual(2, len(self.watch.check_failure['samples']))
        for row in self.watch.check_failure['samples']: self.assertAlmostEqual(2.1, row['ageSeconds'])

    def test_status_lock_timeout_remains_a_diagnosed_failure_not_a_cached_sample(self):
        import fcntl
        self.status()
        with patch.object(self.watch, 'process_alive', return_value=True), \
             patch.object(fcntl, 'flock', side_effect=BlockingIOError), \
             patch.object(preparer.time, 'monotonic', side_effect=[10.0, 10.0, 11.0]), \
             patch.object(preparer.time, 'sleep'):
            with self.assertRaises(preparer.PrivateJsonError): self.watch.check()
        self.assertEqual('STATUS_IDENTITY', self.watch.check_failure['phase'])
        self.assertEqual([], self.watch.check_failure['samples'])
        self.assertEqual('PUBLICATION_LOCK_TIMEOUT', self.watch.check_failure['privateJsonFailure']['reason'])

    def test_status_metadata_failure_reaches_original_receipt_without_json_or_password(self):
        self.status(password='synthetic-private-password')
        self.watch.status_file.chmod(0o640)
        with patch.object(self.watch, 'process_alive', return_value=True):
            with self.assertRaises(preparer.PrivateJsonError) as failed: self.watch.check()
        observation = self.watch.check_failure['privateJsonFailure']
        self.assertEqual('STATUS_IDENTITY', self.watch.check_failure['phase'])
        self.assertEqual(['mode'], observation['fields'])
        self.assertEqual(0o640, observation['observations'][0]['mode'])
        self.assertEqual(self.watch.status_file.stat().st_ino, observation['observations'][0]['inode'])
        self.assertEqual(observation, preparer.failure_details(failed.exception)['privateJsonFailure'])
        spec = importlib.util.spec_from_file_location('private_json_failure_remote', MODULE.with_name('verify-remote.py'))
        remote = importlib.util.module_from_spec(spec); spec.loader.exec_module(remote)
        receipt = {'status': 'FAILED'}
        remote.record_verification_failure(receipt, failed.exception, MODULE.parents[2], self.watch)
        self.assertEqual(self.watch.check_failure, receipt['fixtureRuntime']['checkFailure'])
        raw = json.dumps(receipt)
        for private in ('synthetic-private-password', 'ownerToken', self.descriptor['ownerToken'], str(self.temp)):
            self.assertNotIn(private, raw)

    def test_stale_failed_stopped_and_dead_watch_cannot_admit_another_command(self):
        for status, alive, age in (('RUNNING', True, 3), ('FAILED', False, 0), ('STOPPED', False, 0), ('RUNNING', False, 0)):
            with self.subTest(status=status, alive=alive, age=age):
                self.status(status, capturedMonotonic=time.monotonic() - age)
                with patch.object(self.watch, 'process_alive', return_value=alive):
                    with self.assertRaises(ValueError):
                        self.watch.admit(0)

    def test_slow_identity_scan_uses_the_latest_status_instead_of_aging_a_held_snapshot(self):
        clock = [100.0]
        self.status(capturedMonotonic=100.0, probeCount=1)
        def alive():
            clock[0] = 103.0
            self.status(capturedMonotonic=103.0, probeCount=2)
            return True
        with patch.object(preparer.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(self.watch, 'process_alive', side_effect=alive), \
             patch.object(self.watch, 'read_status', wraps=self.watch.read_status) as read:
            self.assertEqual(2, self.watch.check()['probeCount'])
        self.assertEqual(1, read.call_count)
        self.assertIsNone(self.watch.check_failure)

    def test_stale_read_gets_only_one_immediate_latest_atomic_publication(self):
        self.status(capturedMonotonic=97.0, probeCount=1)
        original = self.watch.read_status
        def read():
            value = original()
            if value['probeCount'] == 1:
                self.status(capturedMonotonic=100.0, probeCount=2)
            return value
        with patch.object(preparer.time, 'monotonic', return_value=100.0), \
             patch.object(preparer.time, 'sleep') as sleep, \
             patch.object(self.watch, 'process_alive', return_value=True), \
             patch.object(self.watch, 'read_status', side_effect=read) as reads:
            self.assertEqual(2, self.watch.check()['probeCount'])
        self.assertEqual(2, reads.call_count); sleep.assert_not_called()
        self.assertIsNone(self.watch.check_failure)

    def test_truly_stale_watch_keeps_two_second_limit_and_both_failed_observations(self):
        self.status(capturedMonotonic=97.0, probeCount=17)
        with patch.object(preparer.time, 'monotonic', return_value=100.0), \
             patch.object(preparer.time, 'sleep') as sleep, \
             patch.object(self.watch, 'process_alive', return_value=True), \
             patch.object(self.watch, 'read_status', wraps=self.watch.read_status) as reads:
            with self.assertRaisesRegex(ValueError, 'measurement is stale'):
                self.watch.check()
        self.assertEqual(2, reads.call_count); sleep.assert_not_called()
        self.assertEqual({'freshnessLimitSeconds': 2, 'phase': 'FRESHNESS', 'samples': [
            {'probeCount': 17, 'capturedMonotonic': 97.0, 'observedMonotonic': 100.0, 'ageSeconds': 3.0}
        ] * 2}, self.watch.check_failure)
        self.status('STOPPED', capturedMonotonic=101.0, probeCount=18)
        self.assertEqual(17, self.watch.check_failure['samples'][-1]['probeCount'])

    def test_first_terminal_or_bad_owner_is_never_hidden_by_a_second_status(self):
        for damage in ('FAILED', 'STOPPED', 'owner'):
            with self.subTest(damage=damage):
                self.status(damage if damage != 'owner' else 'RUNNING', capturedMonotonic=97.0,
                            **({'ownerToken': '0' * 32} if damage == 'owner' else {}))
                with patch.object(self.watch, 'process_alive', return_value=True), \
                     patch.object(self.watch, 'read_status', wraps=self.watch.read_status) as reads:
                    with self.assertRaises(ValueError): self.watch.check()
                self.assertEqual(1, reads.call_count)
                self.assertEqual([], self.watch.check_failure['samples'])

    def test_latest_terminal_or_bad_owner_cannot_be_retried_until_healthy(self):
        for damage in ('FAILED', 'STOPPED', 'owner'):
            with self.subTest(damage=damage):
                self.status(capturedMonotonic=97.0, probeCount=1)
                original = self.watch.read_status
                def read():
                    value = original()
                    self.status(damage if damage != 'owner' else 'RUNNING', capturedMonotonic=100.0,
                                **({'ownerToken': '0' * 32} if damage == 'owner' else {}))
                    return value
                with patch.object(preparer.time, 'monotonic', return_value=100.0), \
                     patch.object(self.watch, 'process_alive', return_value=True), \
                     patch.object(self.watch, 'read_status', side_effect=read) as reads:
                    with self.assertRaises(ValueError): self.watch.check()
                self.assertEqual(2, reads.call_count)
                self.assertEqual(1, len(self.watch.check_failure['samples']))

    def test_invalid_or_future_capture_is_not_a_stale_retry_and_does_not_export_payload(self):
        for captured in ('MYSQL_PWD=synthetic-private', True, None, float('nan'), float('inf'), 101.0):
            with self.subTest(captured=repr(captured)):
                self.status(capturedMonotonic=captured)
                with patch.object(preparer.time, 'monotonic', return_value=100.0), \
                     patch.object(self.watch, 'process_alive', return_value=True), \
                     patch.object(self.watch, 'read_status', wraps=self.watch.read_status) as reads:
                    with self.assertRaisesRegex(ValueError, 'measurement is stale'): self.watch.check()
                self.assertEqual(1, reads.call_count)
                raw = json.dumps(self.watch.check_failure, allow_nan=False)
                self.assertNotIn('MYSQL_PWD', raw)

    def test_exact_freshness_boundary_is_accepted_but_a_new_stale_sample_is_not(self):
        self.status(capturedMonotonic=98.0)
        with patch.object(preparer.time, 'monotonic', return_value=100.0), \
             patch.object(self.watch, 'process_alive', return_value=True):
            self.assertEqual('RUNNING', self.watch.check()['status'])
        self.status(capturedMonotonic=96.0, probeCount=1)
        original = self.watch.read_status
        def read():
            value = original(); self.status(capturedMonotonic=97.0, probeCount=2); return value
        with patch.object(preparer.time, 'monotonic', return_value=100.0), \
             patch.object(self.watch, 'process_alive', return_value=True), \
             patch.object(self.watch, 'read_status', side_effect=read) as reads:
            with self.assertRaisesRegex(ValueError, 'measurement is stale'): self.watch.check()
        self.assertEqual(2, reads.call_count)
        self.assertEqual([4.0, 3.0], [row['ageSeconds'] for row in self.watch.check_failure['samples']])

    def test_watcher_descriptor_cannot_change_after_admission(self):
        self.status()
        preparer.write_json(self.file, {**self.descriptor, 'containerId': 'b' * 64}, replace=True)
        with self.assertRaisesRegex(ValueError, 'descriptor changed'):
            self.watch.read_status()

    def test_verify_admission_counts_fixture_remaining_tool_watch_and_host_reserve(self):
        status = self.status(lastProbe={'memoryCurrentBytes': preparer.GIB})
        meminfo = self.temp / 'meminfo'; meminfo.write_text('MemAvailable: 10000000 kB\n')
        original = preparer.Path
        with patch.object(self.watch, 'check', return_value=status), \
             patch.object(self.watch, 'mysql_memory', return_value={'component': 'mysql', 'containerId': 'a' * 64,
                 'cgroup': '/fixture/mysql', 'remainingMemoryBytes': 2 * preparer.GIB}), \
             patch.object(self.watch, 'watch_anonymous_memory', return_value=0), \
             patch.object(preparer, 'Path', side_effect=lambda value: meminfo if value == '/proc/meminfo' else original(value)):
            admitted = self.watch.admit(4 * preparer.GIB)
            self.assertEqual(7 * preparer.GIB + preparer.WATCH_MEMORY, admitted['requiredAvailableMemoryBytes'])
            self.assertEqual(preparer.GIB, admitted['hostMemoryReserveBytes'])
            meminfo.write_text('MemAvailable: 1048576 kB\n')
            with self.assertRaisesRegex(ValueError, 'cannot admit'):
                self.watch.admit(4 * preparer.GIB)
            self.assertEqual('REJECTED', self.watch.memory_admission['capacityVerdict'])
            self.assertEqual(6 * preparer.GIB + preparer.WATCH_MEMORY,
                             self.watch.memory_admission['memoryShortfallBytes'])

    def test_all_live_fixture_headroom_and_watch_credit_keep_the_full_limits(self):
        limits = {'mysql': 3 * preparer.GIB, 'qdrant': 512 * preparer.MIB,
                  'prometheus': 512 * preparer.MIB, 'redis': 128 * preparer.MIB}
        def measured(name, owned, limit):
            self.assertEqual(limits[name], limit)
            return {'component': name, 'containerId': name, 'cgroup': '/' + name,
                    'memoryLimitBytes': limit, 'anonymousMemoryBytes': 64 * preparer.MIB,
                    'remainingMemoryBytes': limit - 64 * preparer.MIB}
        meminfo = self.temp / 'meminfo'; meminfo.write_text('MemAvailable: 16777216 kB\n')
        original = preparer.Path
        with patch.object(self.watch, 'check'), patch.object(self.watch, 'container_memory', side_effect=measured), \
             patch.object(self.watch, 'mysql_memory', side_effect=lambda: measured('mysql', None, preparer.MYSQL_MEMORY)), \
             patch.object(self.watch, 'watch_anonymous_memory', return_value=32 * preparer.MIB), \
             patch.object(preparer, 'Path', side_effect=lambda value: meminfo if value == '/proc/meminfo' else original(value)):
            result = self.watch.admit(6 * preparer.GIB, fixture_owners={name: Mock() for name in limits if name != 'mysql'})
        expected = 7 * preparer.GIB + sum(limits.values()) + preparer.WATCH_MEMORY - 288 * preparer.MIB
        self.assertEqual(expected, result['requiredAvailableMemoryBytes'])
        self.assertEqual(6 * preparer.GIB, result['toolMemoryBoundBytes'])
        self.assertEqual(preparer.GIB, result['hostMemoryReserveBytes'])
        self.assertEqual('OWNED_ANONYMOUS_ONLY', result['creditPolicy'])
        self.assertEqual(4, len(result['fixtures']))

    def test_admission_uses_lower_before_after_available_and_keeps_exact_shortfall(self):
        meminfo = self.temp / 'meminfo'; meminfo.write_text('MemAvailable: 1048576 kB\n')
        original = preparer.Path
        def measured(*args):
            meminfo.write_text('MemAvailable: 16777216 kB\n')
            return {'containerId': 'mysql', 'cgroup': '/mysql', 'remainingMemoryBytes': 2 * preparer.GIB}
        with patch.object(self.watch, 'check'), patch.object(self.watch, 'mysql_memory', side_effect=measured), \
             patch.object(self.watch, 'watch_anonymous_memory', return_value=0), \
             patch.object(preparer, 'Path', side_effect=lambda value: meminfo if value == '/proc/meminfo' else original(value)):
            with self.assertRaisesRegex(ValueError, 'cannot admit'): self.watch.admit(6 * preparer.GIB)
        result = self.watch.memory_admission
        self.assertEqual(preparer.GIB, result['hostMemoryAvailableBytes'])
        self.assertEqual(8 * preparer.GIB + preparer.WATCH_MEMORY, result['memoryShortfallBytes'])
        self.assertEqual(16 * preparer.GIB, result['hostMemoryAvailableAfterBytes'])

    def test_unknown_or_duplicate_fixture_identity_cannot_inflate_admission_credit(self):
        with patch.object(self.watch, 'check'):
            with self.assertRaisesRegex(ValueError, 'registered owned fixtures'):
                self.watch.admit(0, fixture_owners={'production': Mock()})
        meminfo = self.temp / 'meminfo'; meminfo.write_text('MemAvailable: 16777216 kB\n')
        original = preparer.Path
        for same in ('containerId', 'cgroup'):
            def measured(name, *_):
                row = {'containerId': name, 'cgroup': '/' + name, 'remainingMemoryBytes': preparer.GIB}
                row[same] = 'same'; return row
            with self.subTest(same=same), patch.object(self.watch, 'check'), \
                 patch.object(self.watch, 'container_memory', side_effect=measured), \
                 patch.object(self.watch, 'mysql_memory', side_effect=lambda: measured('mysql')), \
                 patch.object(preparer, 'Path', side_effect=lambda value: meminfo if value == '/proc/meminfo' else original(value)):
                with self.assertRaisesRegex(ValueError, 'credited twice'):
                    self.watch.admit(0, fixture_owners={'redis': Mock()})

    def test_watcher_credit_uses_only_pinned_root_anonymous_rss(self):
        status = self.temp / 'proc-status'; status.write_text('VmRSS: 8192 kB\nRssAnon: 1024 kB\nRssFile: 7168 kB\n')
        original = preparer.Path
        with patch.object(preparer, 'Path', side_effect=lambda value: status if value == '/proc/6000/status' else original(value)), \
             patch.object(preparer, 'proc_identity', return_value=dict(self.process)):
            self.assertEqual(preparer.MIB, self.watch.watch_anonymous_memory())
            status.write_text('VmRSS: 8192 kB\n')
            with self.assertRaisesRegex(ValueError, 'anonymous RSS is unavailable'):
                self.watch.watch_anonymous_memory()

    def test_watcher_memory_process_replacement_is_not_credited(self):
        status = self.temp / 'proc-status'; status.write_text('RssAnon: 1024 kB\n')
        original = preparer.Path
        with patch.object(preparer, 'Path', side_effect=lambda value: status if value == '/proc/6000/status' else original(value)), \
             patch.object(preparer, 'proc_identity', side_effect=[dict(self.process), {**self.process, 'startTicks': 201}]):
            with self.assertRaisesRegex(ValueError, 'memory identity changed'):
                self.watch.watch_anonymous_memory()

    def test_dead_watcher_needs_terminal_original_before_exit_confirmation(self):
        self.status()
        with patch.object(self.watch, 'process_alive', return_value=False):
            with self.assertRaisesRegex(ValueError, 'without terminal'):
                self.watch.stop()
        self.status('FAILED', failure={'errorType': 'ValueError'})
        with patch.object(self.watch, 'process_alive', return_value=False):
            result = self.watch.stop()
        self.assertTrue(result['watchStopped'])
        self.assertTrue(json.loads(self.watch.status_file.read_text())['watchStopped'])
        self.assertNotIn('ownerToken', result)
        self.assertNotIn('groupToken', result)

    def test_oom_and_exit_state_fail_before_any_kernel_replacement(self):
        for state in ({'Running': False, 'Restarting': False, 'OOMKilled': True, 'ExitCode': 137, 'Pid': 0},
                      {'Running': True, 'Restarting': False, 'Paused': False, 'Dead': False, 'OOMKilled': False, 'Pid': 31416},
                      {'Running': True, 'Restarting': False, 'Paused': True, 'Dead': False, 'OOMKilled': False, 'Pid': 31415}):
            with self.subTest(state=state):
                self.preparation.inspect_owned.return_value = {'State': state}
                with patch.object(self.watch.probe, 'fixture_memory') as probe:
                    with self.assertRaisesRegex(ValueError, 'healthy running original'):
                        self.watch.sample()
                probe.assert_not_called()
                self.assertEqual(state['Pid'], self.watch.last_state['Pid'])

    def test_oom_without_kernel_kill_still_fails_the_owned_fixture(self):
        self.preparation.inspect_owned.return_value = {'State':
            {'Running': True, 'Restarting': False, 'Paused': False, 'Dead': False, 'OOMKilled': False, 'Pid': 31415}}
        self.watch.probe.fixture_observation = {**self.probe(), 'events': {'oom': 1, 'oom_kill': 0}}
        with patch.object(self.watch.probe, 'fixture_memory', return_value=(1024, 0)):
            with self.assertRaisesRegex(ValueError, 'memory boundary'):
                self.watch.sample()

    def test_rss_budget_includes_the_complete_watcher_and_metadata_client_tree(self):
        with patch.object(preparer, 'owned_tree_memory_snapshot', return_value={'rssBytes': preparer.WATCH_MEMORY}) as snapshot:
            self.watch.command_memory()
        snapshot.assert_called_once_with(os.getpid(), 200)
        self.assertEqual(preparer.WATCH_MEMORY, self.watch.peak_rss)
        with patch.object(preparer, 'owned_tree_memory_snapshot', return_value={'rssBytes': preparer.WATCH_MEMORY + 1}):
            with self.assertRaisesRegex(ValueError, 'RSS boundary'):
                self.watch.command_memory()

    def test_metadata_client_is_measured_during_wait_and_reaped_on_probe_failure(self):
        process = Mock(); process.returncode = 0; process.poll.return_value = 0
        calls = []
        def communicate(timeout):
            calls.append(timeout)
            if len(calls) == 1: raise subprocess.TimeoutExpired('metadata', timeout)
            return b'[]', b''
        process.communicate.side_effect = communicate
        memory = Mock()
        with patch.object(preparer.subprocess, 'Popen', return_value=process):
            self.assertEqual(b'[]', preparer.run(['docker', 'inspect', 'owned'], memory_probe=memory))
        self.assertEqual(3, memory.call_count)
        process.poll.return_value = None; process.communicate.side_effect = lambda **_: (b'', b'')
        with patch.object(preparer.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, 'RSS boundary'):
                preparer.run(['docker', 'inspect', 'owned'], memory_probe=Mock(side_effect=ValueError('RSS boundary')))
        process.kill.assert_called_once_with()

    def startup(self):
        preparation = preparer.Preparation.__new__(preparer.Preparation)
        preparation.work = self.temp; (self.temp / 'private').mkdir()
        preparation.args = SimpleNamespace(root=str(self.temp), tag=self.args.tag, commit=self.args.commit,
            source_sha256=self.args.source_sha256, instance_id='i-fixture', machine_id='a' * 32)
        preparation.identity = self.identity; preparation.journal = dict(self.journal)
        preparation.resources = SimpleNamespace(fixture_memory=Mock(return_value=(1024, 0)),
            _fixture_cgroup={'pid': 31415, 'startTicks': 100, 'relative': '/docker/fixture', 'directory': (1, 2)})
        preparation.save = Mock()
        self.file.unlink()
        return preparation

    def test_failed_spawn_proves_never_started_without_leaving_a_required_live_watch(self):
        preparation = self.startup()
        with patch.object(preparer.subprocess, 'Popen', side_effect=OSError('spawn refused')):
            with self.assertRaises(OSError): preparation.start_fixture_watch()
        self.assertNotIn('fixtureWatch', preparation.journal)
        proof = preparation.journal['fixtureWatchStartFailure']
        self.assertEqual('NOT_STARTED', proof['status'])
        self.assertTrue(proof['watchStopped'])
        self.assertFalse(proof['processCreated'])

    def test_failed_initial_descriptor_publish_is_also_proven_never_started(self):
        preparation = self.startup()
        original = preparer.write_json
        def publish(path, *args, **kwargs):
            if path == self.file: raise OSError('descriptor publication failed')
            return original(path, *args, **kwargs)
        with patch.object(preparer, 'write_json', side_effect=publish), patch.object(preparer.subprocess, 'Popen') as spawn:
            with self.assertRaises(OSError): preparation.start_fixture_watch()
        spawn.assert_not_called()
        self.assertNotIn('fixtureWatch', preparation.journal)
        self.assertEqual('NOT_STARTED', preparation.journal['fixtureWatchStartFailure']['status'])

    def test_failed_process_registration_cancels_and_reaps_that_exact_child_before_recording_stop(self):
        preparation = self.startup(); child = Mock(pid=6000, returncode=-15)
        with patch.object(preparer.subprocess, 'Popen', return_value=child), \
             patch.object(preparer, 'proc_identity', return_value=None), \
             patch.object(preparer, 'stop_owned_group') as stop:
            with self.assertRaisesRegex(ValueError, 'owned session'):
                preparation.start_fixture_watch()
        stop.assert_called_once()
        self.assertEqual(6000, stop.call_args.args[0])
        child.wait.assert_called_once_with(timeout=5)
        self.assertNotIn('fixtureWatch', preparation.journal)
        proof = preparation.journal['fixtureWatchStartFailure']
        self.assertEqual('STOPPED_BEFORE_READY', proof['status'])
        self.assertTrue(proof['watchStopped'] and proof['groupCancellationConfirmed'])

    def closed_admission_preparation(self):
        preparation = self.startup()
        group = self.install_kernel_probe()
        (group / 'memory.stat').write_text('anon 512\nfile 512\n')
        (self.temp / 'meminfo').write_text('MemAvailable: 16777216 kB\n')
        monitor = self.watch.probe
        monitor.preparation = preparation
        monitor.failed = threading.Event(); monitor.cleaning = False
        monitor.group_stream = io.StringIO(); monitor.group_stream.close()
        monitor.proxy = preparer.ControlledSubprocess(monitor)
        preparation.resources = monitor; preparation.docker = Path('/usr/bin/docker')
        return preparation, group

    def test_closed_command_owner_refuses_before_intent_or_process_creation(self):
        preparation, _ = self.closed_admission_preparation()
        with patch.object(preparer, 'write_json') as intent, patch.object(preparer.subprocess, 'Popen') as spawn:
            for cleaning in (False, True):
                preparation.resources.cleaning = cleaning
                with self.subTest(cleaning=cleaning), self.assertRaisesRegex(ValueError, 'Closed preparation command owner'):
                    preparation.resources.proxy.run(['docker', 'inspect', 'owned'], capture_output=True)
            intent.assert_not_called(); spawn.assert_not_called()

    def test_initial_watch_admission_uses_real_pinned_kernel_after_command_owner_closed(self):
        preparation, _ = self.closed_admission_preparation()
        self.file.unlink(); self.status()
        child = Mock(pid=6000, returncode=None)
        owner_tokens = iter(['e' * 32, 'f' * 32])
        token_hex = preparer.secrets.token_hex
        # Pin only ownership tokens; atomic JSON publication still needs its own random suffixes.
        with patch.object(preparer.secrets, 'token_hex', side_effect=lambda size:
                 next(owner_tokens) if size == 16 else token_hex(size)), \
             patch.object(preparer, 'proc_identity', side_effect=lambda pid:
                 dict(self.process) if pid == 6000 else {'pid': 31415, 'startTicks': 100}), \
             patch.object(preparer.FixtureWatch, 'process_alive', return_value=True), \
             patch.object(preparer.FixtureWatch, 'watch_anonymous_memory', return_value=0), \
             patch.object(preparer.subprocess, 'Popen', return_value=child) as spawn:
            preparation.start_fixture_watch()
        self.assertEqual(1, spawn.call_count)  # Only the new owned watcher, never a closed-owner Docker command.
        self.assertIn('watch', spawn.call_args.args[0])
        self.assertTrue(preparation.resources.group_stream.closed)
        self.assertNotIn('fixtureWatchStartFailure', preparation.journal)
        admission = preparation.journal['fixtureWatchAdmission']
        self.assertEqual('ADMITTED', admission['capacityVerdict'])
        self.assertEqual(0, admission['toolMemoryBoundBytes'])
        self.assertEqual(512, admission['fixtures'][0]['anonymousMemoryBytes'])
        self.assertEqual(31415, admission['fixtures'][0]['pid'])

    def test_remote_five_owner_admission_reuses_the_same_transferred_mysql_kernel(self):
        preparation, _ = self.closed_admission_preparation()
        watch = preparer.FixtureWatch(preparation); self.status()
        spec = importlib.util.spec_from_file_location('admission_remote', MODULE.with_name('verify-remote.py'))
        remote = importlib.util.module_from_spec(spec); spec.loader.exec_module(remote)
        spec = importlib.util.spec_from_file_location('admission_tool_runtime', MODULE.with_name('ecs-tool-runtime.py'))
        runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
        vector, metrics, redis = Mock(), Mock(), Mock()
        seen = []
        def ancillary(name, owned, limit):
            owned(); seen.append(name)
            return {'component': name, 'containerId': name, 'cgroup': '/' + name,
                    'remainingMemoryBytes': limit}
        with patch.object(watch, 'process_alive', return_value=True), \
             patch.object(watch, 'watch_anonymous_memory', return_value=0), \
             patch.object(watch, 'container_memory', side_effect=ancillary), \
             patch.object(preparer.subprocess, 'Popen') as spawn:
            result = remote.admit_fixture_memory(watch, runtime, {}, vector, metrics, redis)
        spawn.assert_not_called()
        self.assertEqual(['prometheus', 'qdrant', 'redis'], seen)
        vector.owned.assert_called_once_with(); redis.owned.assert_called_once_with()
        self.assertEqual(['prometheus'], [call.args[0] for call in metrics.owned.call_args_list])
        self.assertEqual('ADMITTED', result['capacityVerdict'])
        self.assertEqual(4, len(result['fixtures']))
        self.assertEqual(5888 * preparer.MIB, result['toolMemoryBoundBytes'])
        self.assertEqual(self.descriptor['containerId'], result['fixtures'][0]['containerId'])
        self.assertEqual(512, result['fixtures'][0]['anonymousMemoryBytes'])

    def test_transferred_mysql_admission_still_rejects_changed_kernel_or_oom(self):
        preparation, group = self.closed_admission_preparation()
        watch = preparer.FixtureWatch(preparation); self.status()
        damages = [('memory.max', 'max'), ('memory.swap.max', '1'),
                   ('memory.events', 'oom 1\noom_kill 0'), ('memory.stat', 'file 1024')]
        with patch.object(watch, 'process_alive', return_value=True), patch.object(preparer.subprocess, 'Popen') as spawn:
            for name, value in damages:
                file = group / name; original = file.read_bytes(); file.write_text(value + '\n')
                try:
                    with self.subTest(name=name), self.assertRaises(ValueError): watch.admit(0)
                finally:
                    file.write_bytes(original)
                self.assertIsNone(watch.memory_admission)
            with patch.object(preparer, 'proc_identity', return_value={'pid': 31415, 'startTicks': 101}):
                with self.assertRaisesRegex(ValueError, 'process identity changed'): watch.admit(0)
            spawn.assert_not_called()

    def run_context(self):
        self.stack.enter_context(patch.dict(preparer.os.environ,
            {preparer.OWNER_ENV: 'e' * 32, preparer.GROUP_ENV: 'f' * 32}))
        self.stack.enter_context(patch.object(preparer.os, 'getpid', return_value=6000))
        self.stack.enter_context(patch.object(self.watch, 'process_alive', return_value=True))
        self.stack.enter_context(patch('resource.setrlimit'))
        self.stack.enter_context(patch.object(preparer.time, 'sleep'))

    def test_normal_stop_samples_final_mysql_state_and_preserves_peak(self):
        self.run_context()
        preparer.write_json(self.watch.stop_file, {'ownerToken': 'e' * 32})
        with patch.object(self.watch, 'sample', return_value=self.probe()) as sample:
            self.assertEqual(0, self.watch.run())
        sample.assert_called_once_with()
        value = self.watch.read_status()
        self.assertEqual('STOPPED', value['status'])
        self.assertEqual(4096, value['kernelPeakMemoryBytes'])
        self.assertEqual(1024, value['sampledPeakMemoryBytes'])
        self.assertFalse(value['watchStopped'])  # Only the external observer can confirm process exit.
        self.assertEqual(preparer.CONTROLLER_AS, value['watchAddressSpaceLimitBytes'])
        self.assertEqual(preparer.WATCH_MEMORY, value['watchRssLimitBytes'])

    def test_failure_keeps_last_complete_probe_and_actual_failure_state(self):
        self.run_context()
        self.watch.last_state = {'Running': False, 'OOMKilled': True, 'ExitCode': 137, 'Pid': 0}
        with patch.object(self.watch, 'sample', side_effect=[self.probe(), ValueError('fixed failure')]):
            self.assertEqual(2, self.watch.run())
        value = self.watch.read_status()
        self.assertEqual('FAILED', value['status'])
        self.assertEqual(1024, value['lastProbe']['memoryCurrentBytes'])
        self.assertEqual(137, value['failureState']['ExitCode'])
        self.assertEqual(1, value['probeCount'])

    def install_kernel_probe(self):
        group = self.temp / 'cgroups/docker/fixture'; group.mkdir(parents=True)
        for name, body in {'memory.max': str(preparer.MYSQL_MEMORY), 'memory.swap.max': '0',
                           'memory.current': '1024', 'memory.events': 'oom 0\noom_kill 0'}.items():
            (group / name).write_text(body + '\n')
        proc_group = self.temp / 'proc-cgroup'; proc_group.write_text('0::/docker/fixture\n')
        meminfo = self.temp / 'meminfo'; meminfo.write_text('MemAvailable: 10000000 kB\n')
        cache = self.watch.probe._fixture_cgroup
        cache.update(path=group, directory=(group.stat().st_dev, group.stat().st_ino))
        self.descriptor['kernelIdentity']['directory'] = list(cache['directory'])
        self.watch.descriptor['kernelIdentity']['directory'] = list(cache['directory'])
        preparer.write_json(self.file, self.watch.descriptor, replace=self.file.exists())
        original_path = preparer.Path
        self.stack.enter_context(patch.object(preparer, 'Path', side_effect=lambda value:
            proc_group if str(value) == '/proc/31415/cgroup' else
            meminfo if str(value) == '/proc/meminfo' else
            self.temp / 'cgroups' if str(value) == '/sys/fs/cgroup' else original_path(value)))
        self.stack.enter_context(patch.object(preparer, 'proc_identity',
            return_value={'pid': 31415, 'startTicks': 100}))
        self.preparation.inspect_owned.return_value = {'State': {'Running': True, 'Restarting': False,
            'Paused': False, 'Dead': False, 'OOMKilled': False, 'Pid': 31415}}
        return group

    def test_real_first_limit_failure_is_published_without_incrementing_successful_probe(self):
        self.run_context(); group = self.install_kernel_probe()
        with patch.object(preparer.time, 'sleep', side_effect=lambda _: (group / 'memory.swap.max').write_text('max\n')):
            self.assertEqual(2, self.watch.run())
        value = self.watch.read_status()
        self.assertEqual('FAILED', value['status']); self.assertEqual(1, value['probeCount'])
        self.assertEqual('BEFORE_COUNTERS', value['kernelLimitFailure']['phase'])
        self.assertEqual('max', value['kernelLimitFailure']['controls']['memory.swap.max']['value'])
        self.assertEqual(0, value['lastProbe']['swapLimitBytes'])
        self.assertEqual(0, value['lastKernelObservation']['swapLimitBytes'])
        self.assertEqual('LAST_SUCCESSFUL_KERNEL_PROBE', value['lastKernelObservationRole'])
        self.assertTrue(value['failureState']['Running'])
        self.assertEqual(value['kernelLimitFailure'], self.watch.evidence()['kernelLimitFailure'])

    def test_real_second_limit_failure_is_published_without_replacing_last_complete_probe(self):
        self.run_context(); group = self.install_kernel_probe(); second = [False]
        original_open = os.open
        def drift(path, *args, **kwargs):
            if Path(path).name == 'memory.events' and second[0]:
                (group / 'memory.max').write_text('max\n')
            return original_open(path, *args, **kwargs)
        with patch.object(preparer.time, 'sleep', side_effect=lambda _: second.__setitem__(0, True)), \
             patch.object(preparer.os, 'open', side_effect=drift):
            self.assertEqual(2, self.watch.run())
        value = self.watch.read_status()
        self.assertEqual('FAILED', value['status']); self.assertEqual(1, value['probeCount'])
        self.assertEqual('AFTER_COUNTERS', value['kernelLimitFailure']['phase'])
        self.assertEqual('max', value['kernelLimitFailure']['controls']['memory.max']['value'])
        self.assertEqual(preparer.MYSQL_MEMORY, value['lastProbe']['memoryLimitBytes'])
        self.assertEqual(1024, value['lastKernelObservation']['memoryCurrentBytes'])


if __name__ == '__main__':
    unittest.main()
