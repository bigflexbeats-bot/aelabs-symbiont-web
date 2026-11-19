"""Regression checks for compact methane feed card in GIT WEB dashboard."""
import unittest
from pathlib import Path

HTML = (Path(__file__).parent / 'static' / 'index.html').read_text(encoding='utf-8')

class CompactMethaneCardTests(unittest.TestCase):
    def test_methane_art_uses_same_flow_paths_as_air(self):
        source_paths = (
            'M8 38C38 16 58 60 88 38S130 20 152 36',
            'M8 66C38 44 58 88 88 66S130 48 152 64',
            'M8 94C38 72 58 116 88 94S130 76 152 92',
        )
        for path in source_paths:
            self.assertEqual(HTML.count(path), 2, path)
        self.assertIn('id="methaneFeedFlow"', HTML)
        self.assertIn('stroke:#39c96d', HTML)
        self.assertIn("[data-art=ch4f] svg", HTML)

    def test_no_card_only_git_web_connection_caption(self):
        self.assertNotIn('ch4FlowStatus', HTML)
        self.assertNotIn('Нет связи с GIT WEB', HTML)
        self.assertIn("$('connection').textContent='Ошибка связи'", HTML)

    def test_live_web_feed_and_separate_offgas_unchanged(self):
        self.assertIn("CH4FLOW_KEYS=['ch4_flow_online_ae_l_min']", HTML)
        self.assertIn("fetch('/api/latest'", HTML)
        self.assertIn("offgas_ch4_online_ae_pct", HTML)
        self.assertIn('Подача CH₄', HTML)

    def test_compact_breakpoints_preserved(self):
        self.assertIn('AELABS WEB compact layout / methane feed', HTML)
        self.assertIn('.art{height:104px', HTML)
        self.assertIn('@media(max-width:760px)', HTML)
        self.assertIn('@media(max-width:420px)', HTML)

if __name__ == '__main__':
    unittest.main()
