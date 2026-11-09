"""Verify snapshot query sessions on ECS; no local database or local test run."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import stat
import unittest
from unittest.mock import patch
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('snapshot_session_contract', ROOT / 'script/schema/compact_migration_runtime.py')
# The runtime imports its sibling schema helpers.
import sys
sys.path.insert(0, str(ROOT / 'script/schema'))
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class SnapshotSessionTests(unittest.TestCase):
    def invoke(self, response, *, status=0, limit=None):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'private').mkdir(mode=0o700)
            mysql = runtime.Mysql.__new__(runtime.Mysql)
            mysql.sequence = 0
            mysql.output = output
            mysql.command = lambda database: (['owned-mysql-client'], b'')
            calls = []

            def run(command, *, stdin, stdout, stderr, env, timeout):
                calls.append(stdin.read())
                stdout.write(response)
                return SimpleNamespace(returncode=status)

            with patch.object(runtime.subprocess, 'run', side_effect=run), \
                    patch.object(runtime.Mysql, 'environment', return_value={}), \
                    patch.object(runtime, 'MAX_QUERY_BYTES', limit if limit is not None else 1024):
                result = mysql.script('SELECT 0;', label='catalog')
            self.assertEqual(1, len(calls))
            self.assertIn(b'SET SESSION information_schema_stats_expiry=0;', calls[0])
            self.assertIn(b'@@SESSION.information_schema_stats_expiry', calls[0])
            self.assertLess(calls[0].index(b'@@SESSION.information_schema_stats_expiry'), calls[0].index(b'SELECT 0;'))
            self.assertNotIn(b'ANALYZE', calls[0])
            self.assertNotIn(b'SET GLOBAL', calls[0])
            for path in (output / 'private').iterdir():
                self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            return result

    def test_marker_is_removed_without_changing_json_result(self):
        self.assertEqual(b'{"n":1}\n', self.invoke(runtime.STATS_EXPIRY_MARKER + b'{"n":1}\n'))

    def test_no_result_statement_preserves_empty_response(self):
        self.assertEqual(b'', self.invoke(runtime.STATS_EXPIRY_MARKER))

    def test_zero_query_response_is_not_mistaken_for_the_protocol(self):
        self.assertEqual(b'0\n', self.invoke(runtime.STATS_EXPIRY_MARKER + b'0\n'))

    def test_missing_marker_is_rejected(self):
        with self.assertRaises(ValueError):
            self.invoke(b'{"n":1}\n')

    def test_cached_default_value_is_rejected(self):
        with self.assertRaises(ValueError):
            self.invoke(b'doorhandle-stats-expiry-v1:86400\n{}\n')

    def test_any_nonzero_expiry_is_rejected(self):
        with self.assertRaises(ValueError):
            self.invoke(b'doorhandle-stats-expiry-v1:1\n{}\n')

    def test_failed_mysql_command_cannot_be_accepted_by_a_marker(self):
        with self.assertRaises(ValueError):
            self.invoke(runtime.STATS_EXPIRY_MARKER, status=2)

    def test_later_business_text_cannot_substitute_for_the_session_marker(self):
        with self.assertRaises(ValueError):
            self.invoke(b'{}\n' + runtime.STATS_EXPIRY_MARKER)

    def test_query_budget_applies_to_the_response_after_the_fixed_marker(self):
        with self.assertRaises(ValueError):
            self.invoke(runtime.STATS_EXPIRY_MARKER + b'x' * 9, limit=8)

    def test_exact_query_budget_is_preserved(self):
        self.assertEqual(b'x' * 8, self.invoke(runtime.STATS_EXPIRY_MARKER + b'x' * 8, limit=8))

    def test_empty_client_response_does_not_claim_freshness(self):
        with self.assertRaises(ValueError):
            self.invoke(b'')

    def test_result_rows_are_preserved_byte_for_byte(self):
        body = b'{"table":"a"}\n{"table":"b"}\n'
        self.assertEqual(body, self.invoke(runtime.STATS_EXPIRY_MARKER + body))


if __name__ == '__main__':
    unittest.main()
