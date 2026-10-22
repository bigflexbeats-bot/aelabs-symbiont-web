"""AELABS SYMBIONT WEB: read-only dashboard backed by GitHub JSON telemetry."""
import base64
import json
import os
import hmac
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote
from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.middleware.proxy_fix import ProxyFix
from history_csv import parse_github_log_csv

app = Flask(__name__, static_folder='static')
# Render terminates HTTPS at one trusted reverse proxy; this also allows per-client login throttling.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
# Keep the admin password and cookie-signing key in Render environment variables,
# never in this source file or client-side JavaScript.
ADMIN_PASSWORD = os.getenv('ANALYTICS_ADMIN_PASSWORD', '')
app.secret_key = os.getenv('FLASK_SECRET_KEY', '').strip() or None
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', 'true').strip().lower() not in {'0', 'false', 'no'},
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    SESSION_REFRESH_EACH_REQUEST=True,
)
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
SQLITE_PATH = os.path.abspath(os.getenv(
    'ANALYTICS_SQLITE_PATH',
    os.path.join(os.path.dirname(__file__), 'instance', 'aelabs_analytics.sqlite3'),
))
USE_POSTGRES = DATABASE_URL.startswith(('postgres://', 'postgresql://'))
try:
    ANALYTICS_TZ = ZoneInfo(os.getenv('ANALYTICS_TIMEZONE', 'Europe/Moscow'))
except Exception:
    ANALYTICS_TZ = ZoneInfo('UTC')
_analytics_schema_lock = threading.Lock()
_analytics_schema_ready = False
_login_attempts = {}
_login_attempts_lock = threading.Lock()


@contextmanager
def analytics_connection():
    # Use PostgreSQL when DATABASE_URL exists; SQLite is a convenient fallback.
    if USE_POSTGRES:
        import psycopg
        url = DATABASE_URL
        if url.startswith('postgres://'):
            url = 'postgresql://' + url[len('postgres://'):]
        conn = psycopg.connect(url, connect_timeout=8)
    else:
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, timeout=10)
        conn.execute('PRAGMA busy_timeout = 10000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def analytics_execute(conn, sql, params=()):
    if USE_POSTGRES:
        sql = sql.replace('?', '%s')
    return conn.execute(sql, params)


def ensure_analytics_schema():
    global _analytics_schema_ready
    if _analytics_schema_ready:
        return
    with _analytics_schema_lock:
        if _analytics_schema_ready:
            return
        with analytics_connection() as conn:
            analytics_execute(conn, '''CREATE TABLE IF NOT EXISTS analytics_visitors (
                visitor_id TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )''')
            analytics_execute(conn, '''CREATE TABLE IF NOT EXISTS analytics_visits (
                session_id TEXT PRIMARY KEY,
                visitor_id TEXT NOT NULL,
                visit_date TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                last_path TEXT NOT NULL,
                ping_count INTEGER NOT NULL DEFAULT 1
            )''')
            analytics_execute(conn, 'CREATE INDEX IF NOT EXISTS idx_analytics_visits_date ON analytics_visits (visit_date)')
            analytics_execute(conn, 'CREATE INDEX IF NOT EXISTS idx_analytics_visits_last_seen ON analytics_visits (last_seen)')
        _analytics_schema_ready = True


def valid_analytics_uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def analytics_time_pair():
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    return now_utc, now_utc.astimezone(ANALYTICS_TZ)


def admin_not_ready_response():
    if not ADMIN_PASSWORD:
        return jsonify({'error': 'Панель не настроена: добавьте ANALYTICS_ADMIN_PASSWORD в переменные окружения сервера.'}), 503
    if not app.secret_key:
        return jsonify({'error': 'Панель не настроена: добавьте FLASK_SECRET_KEY в переменные окружения сервера.'}), 503
    return None


def login_retry_seconds(client_key):
    now = time.time()
    with _login_attempts_lock:
        for key in list(_login_attempts):
            recent = [stamp for stamp in _login_attempts[key] if now - stamp < 900]
            if recent:
                _login_attempts[key] = recent
            else:
                _login_attempts.pop(key, None)
        recent = _login_attempts.get(client_key, [])
        if len(recent) >= 5:
            return max(1, int(900 - (now - recent[0])))
    return 0


def record_failed_login(client_key):
    with _login_attempts_lock:
        _login_attempts.setdefault(client_key, []).append(time.time())

OWNER = os.getenv('GITHUB_OWNER', 'bigflexbeats-bot').strip()
REPO = os.getenv('GITHUB_REPO', 'aelabs-symbiont-data').strip()
BRANCH = os.getenv('GITHUB_BRANCH', 'main').strip() or 'main'
TOKEN = os.getenv('GITHUB_TOKEN', '').strip()
API = f'https://api.github.com/repos/{OWNER}/{REPO}'
# Optional independent CSV history source (AELABS Desktop GIT LOG channel).
_log_repo_setting = os.getenv('GITHUB_LOG_REPO', '').strip()
_log_owner_setting = os.getenv('GITHUB_LOG_OWNER', '').strip()
if '/' in _log_repo_setting:
    _repo_owner, _repo_name = _log_repo_setting.split('/', 1)
    LOG_OWNER = _log_owner_setting or _repo_owner
    LOG_REPO = _repo_name.strip()
else:
    LOG_OWNER = _log_owner_setting or OWNER
    LOG_REPO = _log_repo_setting
LOG_BRANCH = os.getenv('GITHUB_LOG_BRANCH', 'main').strip() or 'main'
LOG_PATH = os.getenv('GITHUB_LOG_PATH', 'data/log/aelabs_log.csv').strip().strip('/')
LOG_TOKEN = os.getenv('GITHUB_LOG_TOKEN', '').strip() or TOKEN
LOG_API = f'https://api.github.com/repos/{LOG_OWNER}/{LOG_REPO}' if LOG_REPO else ''
LOG_CACHE_TTL = max(10, int(os.getenv('GITHUB_LOG_CACHE_TTL', '15')))

# GitHub API is rate-limited. Keep a short cache so live values and trend
# history refresh quickly while avoiding duplicate requests within one interval.
_cache = {}
_cache_lock = threading.Lock()

def gh(path):
    if not TOKEN:
        raise RuntimeError('На сервере не задан GITHUB_TOKEN')
    req = urllib.request.Request(f'{API}/{path}', headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {TOKEN}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'AELABS-SYMBIONT-Web-Monitor',
    })
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))

def cached(key, ttl, loader):
    now = time.monotonic()
    with _cache_lock:
        item = _cache.get(key)
        if item and now - item['time'] < ttl:
            return item['value']
    value = loader()
    with _cache_lock:
        _cache[key] = {'time': time.monotonic(), 'value': value}
    return value

def file_json(path):
    item = gh('contents/' + path + '?ref=' + BRANCH)
    if item.get('type') != 'file' or 'content' not in item:
        raise ValueError(f'GitHub не вернул содержимое файла: {path}')
    return json.loads(base64.b64decode(item['content']).decode('utf-8'))


def git_log_csv_text():
    """Read the canonical GIT LOG CSV verbatim; do not use commit/receipt time."""
    if not LOG_REPO:
        raise RuntimeError('GIT LOG CSV не настроен: задайте GITHUB_LOG_REPO в переменных окружения веб-сервера')
    if not LOG_TOKEN:
        raise RuntimeError('Для GIT LOG CSV не задан GITHUB_LOG_TOKEN с правом Contents: Read-only')
    if not LOG_PATH.lower().endswith('.csv'):
        raise RuntimeError('GITHUB_LOG_PATH должен указывать на CSV-файл')
    path = quote(LOG_PATH, safe='/')
    branch = quote(LOG_BRANCH, safe='')
    url = f'{LOG_API}/contents/{path}?ref={branch}'
    req = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github.raw+json',
        'Authorization': f'Bearer {LOG_TOKEN}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'AELABS-SYMBIONT-Web-Log-Reader',
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read()
            content_type = response.headers.get('Content-Type', '').lower()
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8', errors='replace')
            parsed = json.loads(detail)
            detail = str(parsed.get('message', detail))
        except Exception:
            detail = detail[:300]
        raise RuntimeError(f'GIT LOG GitHub HTTP {exc.code}: {detail or exc.reason}') from exc
    except Exception as exc:
        raise RuntimeError(f'Не удалось прочитать CSV из GIT LOG: {exc}') from exc

    # GitHub normally returns raw CSV for this media type. Accommodate JSON
    # responses too, in case an intermediary/older API response wraps content.
    if 'json' in content_type or raw.lstrip().startswith(b'{'):
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            payload = None
        if isinstance(payload, dict) and payload.get('type') == 'file':
            if payload.get('encoding') == 'base64' and payload.get('content'):
                raw = base64.b64decode(payload['content'])
            else:
                raise RuntimeError('GitHub не вернул CSV-файл в поддерживаемом формате')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise RuntimeError('CSV GIT LOG должен быть в кодировке UTF-8') from exc


def load_git_log_history():
    content = git_log_csv_text()
    return parse_github_log_csv(content)

def normalize_observation(payload):
    """Accept current observations and legacy snapshots without inventing receipt timestamps."""
    if not isinstance(payload, dict):
        raise ValueError('Формат latest.json должен быть JSON-объектом')
    observation = payload.get('observation')
    if isinstance(observation, dict):
        # The wrapped observation is authoritative. Do not substitute the outer
        # Git/API receipt time for a missing measurement time.
        return observation

    # Legacy snapshots: the timestamp field is stored in the Git file itself,
    # so treat it as source time, not as the time the web server downloaded it.
    if isinstance(payload.get('measurements'), dict):
        normalized = dict(payload)
        if not normalized.get('source_time_raw'):
            source_time = normalized.get('timestamp_local') or normalized.get('timestamp')
            if isinstance(source_time, (str, int, float)) and str(source_time).strip():
                normalized['source_time_raw'] = str(source_time).strip()
        if not normalized.get('event_time_utc') and normalized.get('timestamp_utc'):
            normalized['event_time_utc'] = normalized['timestamp_utc']
        return normalized

    if isinstance(payload.get('values'), dict):
        source_time = payload.get('source_time_raw') or payload.get('timestamp_local') or payload.get('timestamp')
        event_time = payload.get('event_time_utc') or payload.get('timestamp_utc')
        return {
            'schema': payload.get('schema'),
            'observation_no': payload.get('observation_no'),
            'source_id': payload.get('source', 'AELABS MONITORING'),
            'source_time_raw': str(source_time).strip() if isinstance(source_time, (str, int, float)) and str(source_time).strip() else None,
            'source_timezone': payload.get('source_timezone'),
            'event_time_utc': event_time,
            # Only an explicit receipt field belongs here. `timestamp` above is source time.
            'received_at_utc': payload.get('received_at_utc'),
            'measurements': payload['values'],
            'quality': {'status': 'raw_received', 'flags': []},
        }
    raise ValueError('Неизвестный формат data/live/latest.json')

@app.get('/')
def home():
    return send_from_directory('static', 'index.html')

@app.get('/api/health')
def health():
    try:
        latest = cached('latest', 4, lambda: file_json('data/live/latest.json'))
        normalize_observation(latest)
        return jsonify({'ok': True, 'repo': f'{OWNER}/{REPO}', 'branch': BRANCH, 'latest_available': True, 'git_log_csv_configured': bool(LOG_REPO)})
    except urllib.error.HTTPError as exc:
        return jsonify({'ok': False, 'error': f'GitHub HTTP {exc.code}', 'repo': f'{OWNER}/{REPO}'}), 502
    except Exception as exc:
        app.logger.warning('Health check failed: %s', exc)
        return jsonify({'ok': False, 'error': str(exc), 'repo': f'{OWNER}/{REPO}'}), 502

@app.get('/api/latest')
def latest():
    try:
        payload = cached('latest', 4, lambda: file_json('data/live/latest.json'))
        return jsonify(normalize_observation(payload))
    except urllib.error.HTTPError as exc:
        app.logger.warning('GitHub latest request failed: HTTP %s', exc.code)
        return jsonify({'error': f'GitHub HTTP {exc.code}; проверьте путь data/live/latest.json, ветку и права токена'}), 502
    except Exception as exc:
        app.logger.warning('Latest request failed: %s', exc)
        return jsonify({'error': str(exc)}), 502

@app.get('/api/history')
def history():
    # The trend/table use the independent GIT LOG CSV when configured. The file
    # is cached to avoid consuming GitHub API quota on every browser poll.
    if not LOG_REPO:
        return jsonify({'items': [], 'count': 0, 'storage': 'browser-local', 'configured': False})
    try:
        payload = cached('git_log_csv', LOG_CACHE_TTL, load_git_log_history)
        payload['configured'] = True
        payload['repo'] = f'{LOG_OWNER}/{LOG_REPO}'
        payload['branch'] = LOG_BRANCH
        payload['path'] = LOG_PATH
        return jsonify(payload)
    except Exception as exc:
        app.logger.warning('GIT LOG CSV read failed: %s', exc)
        return jsonify({'error': str(exc), 'items': [], 'count': 0, 'storage': 'github-csv', 'configured': True}), 502

@app.get('/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

@app.after_request
def analytics_no_cache(response):
    if request.path.startswith('/api/analytics/'):
        response.headers['Cache-Control'] = 'no-store, private, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/api/analytics/session')
def analytics_session_status():
    return jsonify({
        'configured': bool(ADMIN_PASSWORD and app.secret_key),
        'authenticated': bool(session.get('analytics_admin')),
    })


@app.post('/api/analytics/login')
def analytics_login():
    not_ready = admin_not_ready_response()
    if not_ready:
        return not_ready
    client_key = request.remote_addr or 'unknown'
    retry = login_retry_seconds(client_key)
    if retry:
        response = jsonify({'error': 'Слишком много попыток входа. Попробуйте позже.'})
        response.status_code = 429
        response.headers['Retry-After'] = str(retry)
        return response
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    supplied = body.get('password', '')
    if not isinstance(supplied, str) or len(supplied) > 256 or not hmac.compare_digest(supplied.encode('utf-8'), ADMIN_PASSWORD.encode('utf-8')):
        record_failed_login(client_key)
        return jsonify({'error': 'Неверный пароль.'}), 401
    with _login_attempts_lock:
        _login_attempts.pop(client_key, None)
    session.clear()
    session['analytics_admin'] = True
    session.permanent = True
    return jsonify({'ok': True})


@app.post('/api/analytics/logout')
def analytics_logout():
    if app.secret_key:
        session.clear()
    return jsonify({'ok': True})


@app.post('/api/analytics/ping')
def analytics_ping():
    # Anonymous random browser/session IDs only; IP addresses and query strings are not stored.
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    visitor_id = valid_analytics_uuid(body.get('visitor_id'))
    session_id = valid_analytics_uuid(body.get('session_id'))
    if not visitor_id or not session_id:
        return jsonify({'error': 'Invalid analytics IDs'}), 400
    raw_path = body.get('path', '/')
    if not isinstance(raw_path, str):
        raw_path = '/'
    path = raw_path.split('?', 1)[0].split('#', 1)[0][:120]
    if not path.startswith('/'):
        path = '/'
    now_utc, now_local = analytics_time_pair()
    timestamp = now_utc.isoformat()
    visit_date = now_local.date().isoformat()
    try:
        ensure_analytics_schema()
        with analytics_connection() as conn:
            analytics_execute(conn, '''INSERT INTO analytics_visitors (visitor_id, first_seen, last_seen)
                VALUES (?, ?, ?)
                ON CONFLICT(visitor_id) DO UPDATE SET last_seen = excluded.last_seen''',
                (visitor_id, timestamp, timestamp))
            analytics_execute(conn, '''INSERT INTO analytics_visits
                (session_id, visitor_id, visit_date, first_seen, last_seen, last_path, ping_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    last_path = excluded.last_path,
                    ping_count = analytics_visits.ping_count + 1''',
                (session_id, visitor_id, visit_date, timestamp, timestamp, path))
        return jsonify({'ok': True})
    except Exception as exc:
        app.logger.warning('Analytics ping could not be stored: %s', exc)
        return jsonify({'error': 'Статистика временно недоступна.'}), 503


@app.get('/api/analytics/stats')
def analytics_stats():
    if not session.get('analytics_admin'):
        return jsonify({'error': 'Требуется вход.'}), 401
    now_utc, now_local = analytics_time_pair()
    timestamp = now_utc.isoformat()
    cutoff = (now_utc - timedelta(seconds=90)).isoformat()
    today = now_local.date()
    first_day = today - timedelta(days=6)
    try:
        ensure_analytics_schema()
        with analytics_connection() as conn:
            active_visitors = analytics_execute(conn,
                'SELECT COUNT(DISTINCT visitor_id) FROM analytics_visits WHERE last_seen >= ?', (cutoff,)).fetchone()[0]
            active_sessions = analytics_execute(conn,
                'SELECT COUNT(*) FROM analytics_visits WHERE last_seen >= ?', (cutoff,)).fetchone()[0]
            today_visits = analytics_execute(conn,
                'SELECT COUNT(*) FROM analytics_visits WHERE visit_date = ?', (today.isoformat(),)).fetchone()[0]
            total_visits = analytics_execute(conn, 'SELECT COUNT(*) FROM analytics_visits').fetchone()[0]
            total_visitors = analytics_execute(conn, 'SELECT COUNT(*) FROM analytics_visitors').fetchone()[0]
            daily_rows = analytics_execute(conn,
                'SELECT visit_date, COUNT(*) FROM analytics_visits WHERE visit_date >= ? GROUP BY visit_date ORDER BY visit_date',
                (first_day.isoformat(),)).fetchall()
            pages = analytics_execute(conn,
                'SELECT last_path, COUNT(*) FROM analytics_visits WHERE last_seen >= ? GROUP BY last_path ORDER BY COUNT(*) DESC LIMIT 5',
                (cutoff,)).fetchall()
        daily_map = {str(day): int(count) for day, count in daily_rows}
        daily = []
        for offset in range(7):
            day = first_day + timedelta(days=offset)
            daily.append({'date': day.isoformat(), 'label': day.strftime('%d.%m'), 'visits': daily_map.get(day.isoformat(), 0)})
        return jsonify({
            'active_visitors': int(active_visitors),
            'active_sessions': int(active_sessions),
            'today_visits': int(today_visits),
            'total_visits': int(total_visits),
            'total_visitors': int(total_visitors),
            'daily': daily,
            'active_pages': [{'path': str(path), 'sessions': int(count)} for path, count in pages],
            'storage': 'postgresql' if USE_POSTGRES else 'sqlite',
            'persistent_storage': bool(USE_POSTGRES),
            'timezone': str(ANALYTICS_TZ),
            'updated_at': timestamp,
        })
    except Exception as exc:
        app.logger.warning('Analytics stats could not be read: %s', exc)
        return jsonify({'error': 'Не удалось прочитать статистику. Проверьте настройки базы данных.'}), 503

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8080')))
