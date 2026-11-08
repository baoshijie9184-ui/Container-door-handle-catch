"""Owned RSS snapshot traversal contracts; run through ECS CI only."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('owned_memory_preparer', Path(__file__).resolve().parents[1] / 'script/jenkins/prepare-compact-fixtures.py')
preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparer)


class OwnedMemoryTreeTests(unittest.TestCase):
    def measure(self, rows):
        paths = [SimpleNamespace(name=str(pid)) for pid in rows]
        with patch.object(preparer.Path, 'iterdir', return_value=iter(paths)), \
                patch.object(preparer, 'proc_identity', side_effect=lambda pid: rows[pid]):
            return preparer.owned_tree_memory(10)

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
