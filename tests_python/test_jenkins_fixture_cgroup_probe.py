"""Live fixture cgroup identity contracts; execute only on the admitted ECS."""
from contextlib import ExitStack
import importlib.util
import os
import json
import subprocess
from pathlib import Path
import tempfile
import time
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
        preparer.write_json(self.watch.status_file, value, replace=self.watch.status_file.exists())
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

    def test_stale_failed_stopped_and_dead_watch_cannot_admit_another_command(self):
        for status, alive, age in (('RUNNING', True, 3), ('FAILED', False, 0), ('STOPPED', False, 0), ('RUNNING', False, 0)):
            with self.subTest(status=status, alive=alive, age=age):
                self.status(status, capturedMonotonic=time.monotonic() - age)
                with patch.object(self.watch, 'process_alive', return_value=alive):
                    with self.assertRaises(ValueError):
                        self.watch.check()

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
             patch.object(preparer, 'Path', side_effect=lambda value: meminfo if value == '/proc/meminfo' else original(value)):
            admitted = self.watch.admit(4 * preparer.GIB)
            self.assertEqual(7 * preparer.GIB + preparer.WATCH_MEMORY, admitted['requiredAvailableMemoryBytes'])
            self.assertEqual(preparer.GIB, admitted['hostMemoryReserveBytes'])
            meminfo.write_text('MemAvailable: 1048576 kB\n')
            with self.assertRaisesRegex(ValueError, 'cannot admit'):
                self.watch.admit(4 * preparer.GIB)

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


if __name__ == '__main__':
    unittest.main()
