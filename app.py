import os, json, urllib.request, urllib.error
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder='static')
OWNER = os.getenv('GITHUB_OWNER', 'bigflexbeats-bot')
REPO = os.getenv('GITHUB_REPO', 'aelabs-symbiont-data')
BRANCH = os.getenv('GITHUB_BRANCH', 'main')
TOKEN = os.getenv('GITHUB_TOKEN', '').strip()
API = f'https://api.github.com/repos/{OWNER}/{REPO}'

def gh(path):
    if not TOKEN:
        raise RuntimeError('На сервере не задан GITHUB_TOKEN')
    req = urllib.request.Request(f'{API}/{path}', headers={
        'Accept':'application/vnd.github+json', 'Authorization':f'Bearer {TOKEN}',
        'X-GitHub-Api-Version':'2022-11-28', 'User-Agent':'AELABS-Web-Monitor'
    })
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode('utf-8'))

def file_json(path):
    import base64
    item = gh('contents/' + path + '?ref=' + BRANCH)
    return json.loads(base64.b64decode(item['content']).decode('utf-8'))

@app.get('/')
def home():
    return send_from_directory('static', 'index.html')

@app.get('/api/health')
def health():
    try:
        info = gh('contents/data/live/latest.json?ref=' + BRANCH)
        return jsonify({'ok': True, 'repo': f'{OWNER}/{REPO}', 'latest_available': True})
    except urllib.error.HTTPError as e:
        return jsonify({'ok':False, 'error':f'GitHub HTTP {e.code}', 'repo':f'{OWNER}/{REPO}'}), 502
    except Exception as e:
        return jsonify({'ok':False, 'error':str(e), 'repo':f'{OWNER}/{REPO}'}), 502

@app.get('/api/latest')
def latest():
    try:
        return jsonify(file_json('data/live/latest.json'))
    except urllib.error.HTTPError as e:
        return jsonify({'error':f'GitHub HTTP {e.code}; проверьте путь data/live/latest.json и права токена'}), 502
    except Exception as e:
        return jsonify({'error':str(e)}), 502

@app.get('/api/history')
def history():
    try:
        tree = gh('git/trees/' + BRANCH + '?recursive=1')
        paths = [x['path'] for x in tree.get('tree', []) if x.get('type') == 'blob' and x.get('path','').startswith('data/history/') and x.get('path','').endswith('.json')]
        paths = sorted(paths, reverse=True)[:50]
        rows=[]
        for p in paths:
            try:
                o=file_json(p)
                rows.append({'path':p,'observation_no':o.get('observation_no'),'source_time_raw':o.get('source_time_raw'),'event_time_utc':o.get('event_time_utc'),'measurements':o.get('measurements',{}),'source_id':o.get('source_id')})
            except Exception:
                continue
        return jsonify({'items':rows,'count':len(rows)})
    except Exception as e:
        return jsonify({'error':str(e),'items':[]}), 502

@app.get('/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','8080')))
