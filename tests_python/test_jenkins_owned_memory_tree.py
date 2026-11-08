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


if __name__ == '__main__':
    unittest.main()
