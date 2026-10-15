"""AELABS SYMBIONT WEB: read-only dashboard backed by GitHub JSON telemetry."""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder='static')
OWNER = os.getenv('GITHUB_OWNER', 'chernushkindm-lab').strip()
REPO = os.getenv('GITHUB_REPO', 'symbiont_lab').strip()
BRANCH = os.getenv('GITHUB_BRANCH', 'main').strip() or 'main'
TOKEN = os.getenv('GITHUB_TOKEN', '').strip()
API = f'https://api.github.com/repos/{OWNER}/{REPO}'

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

def normalize_observation(payload):
    """Accept both current publisher wrapper and legacy direct observations."""
    if not isinstance(payload, dict):
        raise ValueError('Формат latest.json должен быть JSON-объектом')
    observation = payload.get('observation')
    if isinstance(observation, dict):
        return observation
    # Legacy payload used by the first web test.
    if isinstance(payload.get('measurements'), dict):
        return payload
    # A values-only payload is deliberately not presented as a complete
    # observation because it has no traceable timestamp/quality metadata.
    if isinstance(payload.get('values'), dict):
        return {
            'schema': payload.get('schema'),
            'observation_no': None,
            'source_id': payload.get('source', 'AELABS MONITORING'),
            'source_time_raw': None,
            'source_timezone': None,
            'event_time_utc': None,
            'received_at_utc': payload.get('timestamp'),
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
        latest = cached('latest', 1, lambda: file_json('data/live/latest.json'))
        normalize_observation(latest)
        return jsonify({'ok': True, 'repo': f'{OWNER}/{REPO}', 'branch': BRANCH, 'latest_available': True})
    except urllib.error.HTTPError as exc:
        return jsonify({'ok': False, 'error': f'GitHub HTTP {exc.code}', 'repo': f'{OWNER}/{REPO}'}), 502
    except Exception as exc:
        app.logger.warning('Health check failed: %s', exc)
        return jsonify({'ok': False, 'error': str(exc), 'repo': f'{OWNER}/{REPO}'}), 502

@app.get('/api/latest')
def latest():
    try:
        payload = cached('latest', 1, lambda: file_json('data/live/latest.json'))
        return jsonify(normalize_observation(payload))
    except urllib.error.HTTPError as exc:
        app.logger.warning('GitHub latest request failed: HTTP %s', exc.code)
        return jsonify({'error': f'GitHub HTTP {exc.code}; проверьте путь data/live/latest.json, ветку и права токена'}), 502
    except Exception as exc:
        app.logger.warning('Latest request failed: %s', exc)
        return jsonify({'error': str(exc)}), 502

@app.get('/api/history')
def history():
    def load_history():
        tree = gh('git/trees/' + BRANCH + '?recursive=1')
        paths = [item['path'] for item in tree.get('tree', [])
                 if item.get('type') == 'blob'
                 and item.get('path', '').startswith('data/history/')
                 and item.get('path', '').endswith('.json')]
        paths = sorted(paths, reverse=True)[:50]
        rows = []
        for path in paths:
            try:
                obj = file_json(path)
                obj = normalize_observation(obj) if obj.get('schema') == 'symbiont-live-monitor/v1' else obj
                measurements = obj.get('measurements', {})
                rows.append({
                    'path': path,
                    'observation_no': obj.get('observation_no'),
                    'source_time_raw': obj.get('source_time_raw'),
                    'event_time_utc': obj.get('event_time_utc'),
                    'measurements': measurements if isinstance(measurements, dict) else {},
                    'source_id': obj.get('source_id'),
                })
            except Exception as exc:
                app.logger.warning('Skipping invalid history file %s: %s', path, exc)
        return {'items': rows, 'count': len(rows)}
    try:
        return jsonify(cached('history', 2, load_history))
    except Exception as exc:
        app.logger.warning('History request failed: %s', exc)
        return jsonify({'error': str(exc), 'items': []}), 502

@app.get('/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8080')))
