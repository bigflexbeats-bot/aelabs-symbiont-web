import ast
import unittest
from pathlib import Path

# Load only the pure normalization function so these tests can run even when
# Flask/Gunicorn dependencies are not installed in the local test environment.
_source = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
_tree = ast.parse(_source)
_func = next(node for node in _tree.body if isinstance(node, ast.FunctionDef) and node.name == 'normalize_observation')
_module = ast.Module(body=[_func], type_ignores=[])
_namespace = {}
exec(compile(_module, 'app.py:normalize_observation', 'exec'), _namespace)
normalize_observation = _namespace['normalize_observation']

class NormalizeObservationTests(unittest.TestCase):
    def test_wrapper_keeps_source_time_and_does_not_fill_from_outer_payload(self):
        observation = {'source_time_raw': '20.10.2026 14:05:10', 'event_time_utc': '2026-10-20T09:05:10Z', 'measurements': {'ph': 7.0}}
        got = normalize_observation({'timestamp': '2099-01-01T00:00:00Z', 'observation': observation})
        self.assertEqual(got, observation)

    def test_legacy_timestamp_is_source_time_not_received_time(self):
        got = normalize_observation({'timestamp': '2026-10-20T09:05:10Z', 'measurements': {'ph': 7.0}})
        self.assertEqual(got['source_time_raw'], '2026-10-20T09:05:10Z')
        self.assertNotIn('received_at_utc', got)

    def test_values_payload_keeps_only_explicit_receipt_field(self):
        got = normalize_observation({'timestamp': '2026-10-20T09:05:10Z', 'received_at_utc': '2026-10-20T09:05:14Z', 'values': {'ph': 7.0}})
        self.assertEqual(got['source_time_raw'], '2026-10-20T09:05:10Z')
        self.assertEqual(got['received_at_utc'], '2026-10-20T09:05:14Z')

    def test_values_payload_without_timestamp_does_not_invent_one(self):
        got = normalize_observation({'values': {'ph': 7.0}})
        self.assertIsNone(got['source_time_raw'])
        self.assertIsNone(got['received_at_utc'])

if __name__ == '__main__':
    unittest.main()
