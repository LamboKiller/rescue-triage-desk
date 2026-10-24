"""Diagnose why intake calls fail live while the smoke call works. Read-only: 4-5 Nightshift calls, no data writes.

Run (PowerShell, repo folder):  python tools/diagnose_intake.py
Uses NIGHTSHIFT_* from .env / environment. Never prints the key.
"""
import json, os, sys, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import load_env, setting  # noqa: E402
from app.agents.intake import SYSTEM  # noqa: E402

load_env()  # read .env (the app's own scripts do this too)

BASE = setting('NIGHTSHIFT_BASE_URL', 'http://127.0.0.1:8088/v1').rstrip('/')
KEY = setting('NIGHTSHIFT_API_KEY')
LIGHT = 'nvidia/nemotron-3.5-lightning-30b-a3b'
TEXT = 'oi gnt, somos 6 pesssoas na Rua Capistrano de Abreu, número 956, Canoas. 1 crianças. 1 idosos. água subindo!'
PAYLOAD = json.dumps({'message_data': '<message_data>' + TEXT + '</message_data>', 'critic_objections': []}, ensure_ascii=False)

VARIANTS = [
    ('A as the app sends it (system+user, 2000 tok)', LIGHT, 2000, True),
    ('B same, max_tokens 6000', LIGHT, 6000, True),
    ('C no system role (instructions in user msg), 2000', LIGHT, 2000, False),
    ('D super 120B, as app', 'nvidia/nemotron-3-super-120b-a12b', 2000, True),
    ('E 3.5 super VL 120B, as app', 'nvidia/nemotron-3.5-super-vl-120b-a12b', 2000, True),
]

if not KEY:
    sys.exit('NIGHTSHIFT_API_KEY missing (.env)')
for name, model, mt, use_system in VARIANTS:
    msgs = ([{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': PAYLOAD}] if use_system
            else [{'role': 'user', 'content': SYSTEM + '\n\n' + PAYLOAD}])
    body = {'model': model, 'max_tokens': mt, 'messages': msgs}
    req = urllib.request.Request(BASE + '/chat/completions', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY,
                                          'meterless-app': 'rescue-triage-desk', 'meterless-scope': 'user'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        c = d['choices'][0]
        m = d.get('meterless', {})
        print(f'[{name}] OK {time.time()-t0:.1f}s model={m.get("routed_model")} finish={c.get("finish_reason")} '
              f'usage={d.get("usage")}\n   answer: {(c["message"].get("content") or "(EMPTY)")[:300]!r}')
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode('utf-8', 'replace')).get('error', {})
        except Exception:
            err = {}
        print(f'[{name}] HTTP {e.code} after {time.time()-t0:.1f}s: {err.get("meterless_detail") or err.get("message")}')
    except Exception as e:
        print(f'[{name}] FAIL after {time.time()-t0:.1f}s: {type(e).__name__}: {e}')
