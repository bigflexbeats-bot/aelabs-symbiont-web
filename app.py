"""AELABS SYMBIONT WEB: read-only dashboard backed by GitHub JSON telemetry."""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from flask import Flask, jsonify, send_from_directory
from history_csv import parse_github_log_csv

app = Flask(__name__, static_folder='static')
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
    return parse_github_log_csv(content, limit=500)

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
    response = send_from_directory('static', 'index.html', max_age=0)
    response.headers['Cache-Control'] = 'no-cache'
    return response

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
    # Logo, icons and scripts are static: browsers may cache them for a day.
    return send_from_directory('static', path, max_age=86400)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8080')))
