from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest

HTML = Path(__file__).parent / 'static' / 'index.html'

class ThemeMarkupParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.theme_choices = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'button' and 'data-theme-choice' in attrs:
            self.theme_choices.append(attrs['data-theme-choice'])

class ThemePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HTML.read_text(encoding='utf-8')
        cls.parser = ThemeMarkupParser()
        cls.parser.feed(cls.source)

    def test_three_theme_choices_are_present(self):
        self.assertEqual(set(self.parser.theme_choices), {'russian', 'classic', 'aero'})

    def test_theme_is_persisted_and_restored(self):
        self.assertIn("localStorage.setItem('aelabs-web-theme', theme)", self.source)
        self.assertIn("localStorage.getItem('aelabs-web-theme')", self.source)

    def test_no_duplicate_dom_ids(self):
        duplicates = [key for key, count in Counter(self.parser.ids).items() if count > 1]
        self.assertEqual(duplicates, [])

    def test_monitoring_elements_remain_present(self):
        for required in ('id="trendPlot"', 'id="historyRows"', 'id="refresh"', 'id="repoStatus"', 'function drawTrend'):
            self.assertIn(required, self.source)

if __name__ == '__main__':
    unittest.main()
