"""Live fixture cgroup identity contracts; execute only on the admitted ECS."""
from contextlib import ExitStack
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


MODULE = Path(__file__).resolve().parents[1] / 'script/jenkins/prepare-compact-fixtures.py'
SPEC = importlib.util.spec_from_file_location('fixture_cgroup_preparer', MODULE)
preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparer)


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


if __name__ == '__main__':
    unittest.main()
