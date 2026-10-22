import json
import os
import re
import tempfile
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

BASE = Path(__file__).parent
HTML = BASE / 'static' / 'index.html'
APP_SOURCE = (BASE / 'app.py').read_text(encoding='utf-8')
CLIENT_SOURCE = (BASE / 'static' / 'index.html').read_text(encoding='utf-8')


class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
    def handle_starttag(self, tag, attrs):
        value = dict(attrs).get('id')
        if value:
            self.ids.append(value)


class VisitorAnalyticsMarkupTests(unittest.TestCase):
    def test_panel_button_and_dialog_exist(self):
        for expected in ('id="analyticsOpen"', 'id="analyticsModal"', 'id="analyticsLoginForm"', 'id="analyticsDashboard"'):
            self.assertIn(expected, CLIENT_SOURCE)

    def test_no_duplicate_ids_after_adding_panel(self):
        parser = IdParser()
        parser.feed(CLIENT_SOURCE)
        duplicates = [name for name, count in Counter(parser.ids).items() if count > 1]
        self.assertEqual(duplicates, [])

    def test_client_uses_random_ids_and_does_not_send_query_string(self):
        self.assertIn("storedId('localStorage', 'aelabs_analytics_visitor_id')", CLIENT_SOURCE)
        self.assertIn("storedId('sessionStorage', 'aelabs_analytics_session_id')", CLIENT_SOURCE)
        self.assertIn("path: window.location.pathname", CLIENT_SOURCE)
        self.assertIn('window.setInterval(ping, 25000)', CLIENT_SOURCE)

    def test_admin_password_is_not_hardcoded_or_sent_to_client(self):
        self.assertIn("os.getenv('ANALYTICS_ADMIN_PASSWORD', '')", APP_SOURCE)
        self.assertNotIn("ANALYTICS_ADMIN_PASSWORD = '15426'", APP_SOURCE)
        self.assertNotIn('password: "15426"', CLIENT_SOURCE)
        self.assertIn('hmac.compare_digest', APP_SOURCE)
        self.assertIn('900', APP_SOURCE)  # failed login attempts expire after 15 minutes

    def test_admin_stats_route_requires_server_session(self):
        self.assertIn("@app.get('/api/analytics/stats')", APP_SOURCE)
        self.assertIn("if not session.get('analytics_admin')", APP_SOURCE)
        self.assertIn("@app.post('/api/analytics/login')", APP_SOURCE)
        self.assertIn("@app.post('/api/analytics/logout')", APP_SOURCE)

    def test_render_declares_secret_and_password_env_vars(self):
        render = (BASE / 'render.yaml').read_text(encoding='utf-8')
        self.assertIn('key: FLASK_SECRET_KEY\n        generateValue: true', render)
        self.assertIn('key: ANALYTICS_ADMIN_PASSWORD\n        sync: false', render)
        self.assertIn('psycopg[binary]', (BASE / 'requirements.txt').read_text(encoding='utf-8'))


try:
    import flask  # noqa: F401
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


@unittest.skipUnless(HAS_FLASK, 'Flask is not installed in this test environment; endpoint tests run in the deployment environment.')
class VisitorAnalyticsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix='aelabs-analytics-tests-')
        os.environ['DATABASE_URL'] = ''
        os.environ['ANALYTICS_SQLITE_PATH'] = str(Path(cls.tempdir.name) / 'analytics.sqlite3')
        os.environ['ANALYTICS_ADMIN_PASSWORD'] = 'test-panel-password'
        os.environ['FLASK_SECRET_KEY'] = 'test-cookie-signing-key-that-is-not-used-in-production'
        os.environ['SESSION_COOKIE_SECURE'] = 'false'
        # The app module may have already been imported by another test runner.
        import importlib
        import app as app_module
        cls.app_module = importlib.reload(app_module)
        cls.app = cls.app_module.app
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def setUp(self):
        self.client = self.app.test_client()
        with self.app_module._login_attempts_lock:
            self.app_module._login_attempts.clear()

    def login(self):
        return self.client.post('/api/analytics/login', json={'password': 'test-panel-password'})

    def ping(self, visitor, session, path='/'):
        return self.client.post('/api/analytics/ping', json={'visitor_id': visitor, 'session_id': session, 'path': path})

    def test_stats_rejects_unauthenticated_client(self):
        self.assertEqual(self.client.get('/api/analytics/stats').status_code, 401)

    def test_login_and_aggregate_visit(self):
        visitor = 'd17e7fd8-b3ca-4c4b-9775-4832bda088ef'
        session = 'd17e7fd8-b3ca-4c4b-9775-4832bda088ee'
        self.assertEqual(self.ping(visitor, session, '/metrics?token=do-not-store').status_code, 200)
        self.assertEqual(self.ping(visitor, session, '/trend').status_code, 200)
        self.assertEqual(self.login().status_code, 200)
        response = self.client.get('/api/analytics/stats')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['active_visitors'], 1)
        self.assertEqual(data['active_sessions'], 1)
        self.assertEqual(data['total_visits'], 1)
        self.assertEqual(data['total_visitors'], 1)
        self.assertEqual(data['active_pages'][0]['path'], '/trend')
        self.assertFalse(data['persistent_storage'])

    def test_bad_ids_are_rejected(self):
        self.assertEqual(self.client.post('/api/analytics/ping', json={'visitor_id': 'not-an-id', 'session_id': 'x'}).status_code, 400)

    def test_bad_password_is_rejected(self):
        self.assertEqual(self.client.post('/api/analytics/login', json={'password': 'wrong'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
