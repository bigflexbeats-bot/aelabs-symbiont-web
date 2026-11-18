"""Regression for the methane-feed GIT WEB observation contract; Flask not required."""
import ast
import unittest
from pathlib import Path

WEB = Path(__file__).parent
source = (WEB / 'app.py').read_text(encoding='utf-8')
func = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'normalize_observation')
ns = {}
exec(compile(ast.Module(body=[func], type_ignores=[]), 'normalize_observation', 'exec'), ns)
normalize_observation = ns['normalize_observation']

class GitWebMethaneFlowTests(unittest.TestCase):
    def test_wrapped_git_web_observation_preserves_independent_channels(self):
        sample = {
            'source_time_raw': '18.11.2026 11:00:00',
            'event_time_utc': '2026-11-18T06:00:00Z',
            'measurements': {
                'ph': 7.1,
                'offgas_ch4_online_ae_pct': 27.2,
                'ch4_flow_online_ae_l_min': 1.235,
            },
        }
        got = normalize_observation({'observation': sample, 'values': {'ch4_flow_online_ae_l_min': 99}})
        self.assertEqual(got['measurements']['ch4_flow_online_ae_l_min'], 1.235)
        self.assertEqual(got['measurements']['offgas_ch4_online_ae_pct'], 27.2)

    def test_zero_flow_and_null_are_transmitted_without_conversion(self):
        for value in (0, None):
            with self.subTest(value=value):
                sample = {'source_time_raw': '18.11.2026 11:00:00', 'measurements': {'ch4_flow_online_ae_l_min': value}}
                got = normalize_observation({'observation': sample})
                self.assertIs(got['measurements']['ch4_flow_online_ae_l_min'], value)

    def test_web_view_only_uses_feed_field_for_feed_card_and_history(self):
        src = (WEB / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("CH4FLOW_KEYS=['ch4_flow_online_ae_l_min']", src)
        self.assertIn("numericValue(m,CH4FLOW_KEYS)", src)
        self.assertIn("const ch4Feed=numericValue(m,CH4FLOW_KEYS)", src)
        self.assertIn("const CH4_WEB_HISTORY_KEY='aelabs_git_web_ch4_flow_v1'", src)
        self.assertIn('Подача CH₄', src)
        self.assertIn('CH₄ в абгазе', src)
        self.assertIn("fetch('/api/latest'", src)

if __name__ == '__main__':
    unittest.main()
