"""Owned RSS snapshot traversal contracts; run through ECS CI only."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import json
import subprocess

SPEC = importlib.util.spec_from_file_location('owned_memory_preparer', Path(__file__).resolve().parents[1] / 'script/jenkins/prepare-compact-fixtures.py')
preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparer)


class OwnedMemoryTreeTests(unittest.TestCase):
    def measure(self, rows):
        for pid, row in rows.items():
            row.setdefault('startTicks', pid * 100)
        paths = [SimpleNamespace(name=str(pid)) for pid in rows]
        with patch.object(preparer.Path, 'iterdir', return_value=iter(paths)), \
                patch.object(preparer, 'proc_identity', side_effect=lambda pid: rows[pid]):
            return preparer.owned_tree_memory_snapshot(10, 1000)['rssBytes']

    def test_only_root_and_all_descendants_are_summed(self):
        rows = {pid: {'pid': pid, 'parent': parent, 'rssBytes': rss}
                for pid, parent, rss in [(10, 1, 100), (11, 10, 20), (12, 11, 30), (99, 1, 999)]}
        self.assertEqual(150, self.measure(rows))

    def test_cycle_does_not_double_count(self):
        rows = {10: {'pid': 10, 'parent': 11, 'rssBytes': 100},
                11: {'pid': 11, 'parent': 10, 'rssBytes': 20}}
        self.assertEqual(120, self.measure(rows))

    def test_original_process_bound_is_enforced(self):
        rows = {pid: {'pid': pid, 'parent': pid - 1, 'rssBytes': 1} for pid in range(10, 267)}
        with self.assertRaises(ValueError):
            self.measure(rows)

    def sample(self, response=None, **process_fields):
        response = response or {'rootPid': 10, 'rootStartTicks': 1000, 'rssBytes': 150, 'processCount': 3}
        process = SimpleNamespace(returncode=0, stderr=b'', stdout=json.dumps(response).encode())
        process.__dict__.update(process_fields)
        with patch.object(preparer, 'proc_identity', return_value={'startTicks': 1000}), \
                patch.object(preparer.subprocess, 'run', return_value=process) as launch:
            result = preparer.owned_tree_memory(10)
        command = launch.call_args.args[0]
        self.assertEqual(['--sample-owned-memory', '10', '1000'], command[-3:])
        self.assertEqual(1, launch.call_args.kwargs['timeout'])
        return result

    def test_independent_sampler_preserves_complete_rss_and_bounded_execution(self):
        self.assertEqual(150, self.sample())

    def test_independent_sampler_rejects_reused_root_pid(self):
        with self.assertRaises(ValueError):
            self.sample({'rootPid': 10, 'rootStartTicks': 1001, 'rssBytes': 150, 'processCount': 3})

    def test_independent_sampler_rejects_foreign_root(self):
        with self.assertRaises(ValueError):
            self.sample({'rootPid': 11, 'rootStartTicks': 1000, 'rssBytes': 150, 'processCount': 3})

    def test_independent_sampler_rejects_boolean_counter(self):
        with self.assertRaises(ValueError):
            self.sample({'rootPid': 10, 'rootStartTicks': 1000, 'rssBytes': True, 'processCount': 3})

    def test_independent_sampler_rejects_excess_processes(self):
        with self.assertRaises(ValueError):
            self.sample({'rootPid': 10, 'rootStartTicks': 1000, 'rssBytes': 150, 'processCount': 257})

    def test_independent_sampler_rejects_empty_tree(self):
        with self.assertRaises(ValueError):
            self.sample({'rootPid': 10, 'rootStartTicks': 1000, 'rssBytes': 0, 'processCount': 0})

    def test_independent_sampler_rejects_stderr_and_unsuccessful_exit(self):
        for fields in ({'stderr': b'error'}, {'returncode': 2}, {'stdout': b'x' * 1025}):
            with self.subTest(fields=tuple(fields)), self.assertRaises(ValueError):
                self.sample(**fields)

    def test_independent_sampler_timeout_is_not_replaced_by_a_stale_value(self):
        with patch.object(preparer, 'proc_identity', return_value={'startTicks': 1000}), \
                patch.object(preparer.subprocess, 'run', side_effect=subprocess.TimeoutExpired('sampler', 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                preparer.owned_tree_memory(10)

    def test_snapshot_rejects_a_root_reused_during_the_scan(self):
        rows = [{'pid': 10, 'parent': 1, 'rssBytes': 100, 'startTicks': value} for value in (1000, 1001, 1001)]
        with patch.object(preparer.Path, 'iterdir', return_value=iter([SimpleNamespace(name='10')])), \
                patch.object(preparer, 'proc_identity', side_effect=rows):
            with self.assertRaises(ValueError):
                preparer.owned_tree_memory_snapshot(10, 1000)

    def test_host_scan_limit_rejects_instead_of_truncating_coverage(self):
        paths = (SimpleNamespace(name=str(pid)) for pid in range(20, 16405))
        with patch.object(preparer.Path, 'iterdir', return_value=paths), \
                patch.object(preparer, 'proc_identity', side_effect=lambda pid: {'startTicks': 1000} if pid == 10 else None):
            with self.assertRaisesRegex(ValueError, 'Complete host process snapshot'):
                preparer.owned_tree_memory_snapshot(10, 1000)

    def test_protocol_rejects_duplicate_fields_even_when_last_value_matches(self):
        with self.assertRaises(ValueError):
            self.sample(stdout=b'{"rootPid":11,"rootPid":10,"rootStartTicks":1000,"rssBytes":150,"processCount":3}')

    def test_snapshot_rejects_missing_root_before_scan(self):
        with patch.object(preparer, 'proc_identity', return_value=None):
            with self.assertRaises(ValueError):
                preparer.owned_tree_memory_snapshot(10, 1000)

    def test_snapshot_rejects_root_missing_from_snapshot(self):
        root = {'pid': 10, 'parent': 1, 'rssBytes': 100, 'startTicks': 1000}
        with patch.object(preparer.Path, 'iterdir', return_value=iter([SimpleNamespace(name='10')])), \
                patch.object(preparer, 'proc_identity', side_effect=[root, None, root]):
            with self.assertRaises(ValueError):
                preparer.owned_tree_memory_snapshot(10, 1000)

    def test_snapshot_rejects_root_disappearing_after_snapshot(self):
        root = {'pid': 10, 'parent': 1, 'rssBytes': 100, 'startTicks': 1000}
        with patch.object(preparer.Path, 'iterdir', return_value=iter([SimpleNamespace(name='10')])), \
                patch.object(preparer, 'proc_identity', side_effect=[root, root, None]):
            with self.assertRaises(ValueError):
                preparer.owned_tree_memory_snapshot(10, 1000)

    def test_helper_rejects_unadmitted_uid(self):
        with patch.object(preparer.sys, 'platform', 'linux'), patch.object(preparer.os, 'getuid', return_value=0):
            with self.assertRaises(ValueError):
                preparer.sample_owned_memory_entry(['10', '1000'])

    def test_helper_rejects_target_owned_by_another_user(self):
        with patch.object(preparer.sys, 'platform', 'linux'), patch.object(preparer.os, 'getuid', return_value=1000), \
                patch.object(preparer.os, 'geteuid', return_value=1000), \
                patch.object(preparer.Path, 'stat', return_value=SimpleNamespace(st_uid=1001)):
            with self.assertRaises(ValueError):
                preparer.sample_owned_memory_entry(['10', '1000'])

    def test_worker_locations_exclude_locals_and_foreign_frames(self):
        monitor = preparer.PreparationMonitor.__new__(preparer.PreparationMonitor)
        monitor.collector = SimpleNamespace(ident=22)
        own = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(SPEC.origin), co_name='proc_identity'),
                              f_lineno=70, f_back=None, f_locals={'password': 'opaque-secret'})
        foreign = SimpleNamespace(f_code=SimpleNamespace(co_filename='/private/opaque-secret.py', co_name='secret'),
                                  f_lineno=1, f_back=own)
        frames = {11: foreign, 22: own}
        with patch.object(preparer.sys, '_current_frames', return_value=frames), \
                patch.object(preparer.threading, 'main_thread', return_value=SimpleNamespace(ident=11)):
            result = monitor.worker_locations()
        self.assertEqual({}, frames)
        self.assertEqual([{'file': 'prepare-compact-fixtures.py', 'function': 'proc_identity', 'line': 70}], result['main'])
        self.assertNotIn('opaque-secret', repr(result))

    def test_worker_locations_are_bounded_and_missing_thread_is_safe(self):
        monitor = preparer.PreparationMonitor.__new__(preparer.PreparationMonitor)
        frame = None
        for _ in range(20):
            frame = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(SPEC.origin), co_name='bounded'),
                                    f_lineno=1, f_back=frame)
        with patch.object(preparer.sys, '_current_frames', return_value={11: frame}), \
                patch.object(preparer.threading, 'main_thread', return_value=SimpleNamespace(ident=11)):
            result = monitor.worker_locations()
        self.assertEqual(8, len(result['main']))
        self.assertEqual([], result['collector'])


if __name__ == '__main__':
    unittest.main()
