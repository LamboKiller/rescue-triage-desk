"""Extract exact 60 fps JPEG sequences for every UI item in timeline_v5.json (speed ramps baked in).
usage: python v4_frames.py [--force] [--only u03]"""
import json, subprocess, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT = Path(__file__).resolve().parents[2]
V5 = ROOT / 'out/video/v5'
T = json.loads((V5 / 'timeline_v5.json').read_text(encoding='utf-8'))
force = '--force' in sys.argv
only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None

def job(it):
    d = V5 / 'frames' / it['id']; d.mkdir(parents=True, exist_ok=True)
    have = len(list(d.glob('*.jpg')))
    sig = d / 'sig.json'; ex = it['extract']; want = json.dumps([ex, it['n']])
    if not force and have == it['n'] and sig.exists() and sig.read_text() == want:
        return it['id'], 'cached'
    for f in d.glob('*.jpg'): f.unlink()
    a, b, sp = ex['a'], ex['b'], ex['speed']
    vf = f"setpts=PTS/{sp:.9f},fps=60,scale=in_range=tv:out_range=full:flags=bicubic,format=yuvj420p"
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-ss', f'{a:.4f}', '-t', f'{(b - a) + 0.5:.4f}', '-i', str(ROOT / ex['src']),
           '-vf', vf, '-frames:v', str(it['n']), '-q:v', '3', '-start_number', '1', str(d / '%05d.jpg')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    got = len(list(d.glob('*.jpg')))
    if got < it['n']:  # pad by repeating last frame (clip ended slightly early)
        last = d / f'{got:05d}.jpg'
        for i in range(got + 1, it['n'] + 1): (d / f'{i:05d}.jpg').write_bytes(last.read_bytes())
    sig.write_text(want)
    return it['id'], f'{got}/{it["n"]} {r.stderr[-200:]}'

ui = [it for it in T['items'] if it['type'] == 'ui' and (not only or it['id'] == only)]
with ThreadPoolExecutor(6) as ex:
    for r in ex.map(job, ui): print(*r, flush=True)
