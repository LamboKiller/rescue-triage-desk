"""Collect free-licensed flood photos from Wikimedia Commons (candidate pool + contact sheets)."""
import json, urllib.request, urllib.parse, re, time, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; OUT = ROOT / 'out/video/v4/cand'; OUT.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'rtd-video/1 (hackathon; contact via repo)'}
def api(**p):
    p['format'] = 'json'; u = 'https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(p)
    time.sleep(1.2)
    for k in range(5):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
        except Exception as e: err = e; time.sleep(40 if '429' in str(e) else 5)
    raise RuntimeError(f'api {err} {p}')
def members(cat, typ):
    out, cont = [], {}
    while True:
        r = api(action='query', list='categorymembers', cmtitle=cat, cmtype=typ, cmlimit=500, **cont)
        out += [x['title'] for x in r['query']['categorymembers']]
        if 'continue' not in r: return out
        cont = r['continue']
roots = ['Category:2024 Rio Grande do Sul floods in Porto Alegre', 'Category:2024 Rio Grande do Sul floods in Canoas', 'Category:2024 Rio Grande do Sul floods in Eldorado do Sul', 'Category:Aerial photographs of the 2024 Rio Grande do Sul floods', 'Category:2024 Rio Grande do Sul floods by city', 'Category:2024 Rio Grande do Sul floods']
seen, files = set(), []
def walk(c, d):
    if c in seen or d > 1: return
    seen.add(c); files.extend(members(c, 'file'))
    for s in members(c, 'subcat'):
        if re.search(r'by photographer|art|Politic|Document|Fundrais|Reconstruction|Video|Animals|Humanitarian|Maps|Events', s): continue
        walk(s, d + 1)
for r_ in roots: walk(r_, 0)
files = [f for f in dict.fromkeys(files) if re.search(r'\.jpe?g$', f, re.I)]
print('files', len(files), 'cats', len(seen), flush=True)
info = {}
for i in range(0, len(files), 40):
    r = api(action='query', prop='imageinfo', iiprop='extmetadata|size|url', iiurlwidth=420, titles='|'.join(files[i:i+40]))
    for p in r['query']['pages'].values():
        if 'imageinfo' not in p: continue
        ii = p['imageinfo'][0]; m = ii['extmetadata']
        info[p['title']] = dict(title=p['title'], w=ii['width'], h=ii['height'], lic=m.get('LicenseShortName', {}).get('value', ''), art=re.sub('<[^>]+>', '', m.get('Artist', {}).get('value', '')).strip()[:80],
                                page=ii['descriptionurl'], thumb=ii['thumburl'], cats=m.get('Categories', {}).get('value', '')[:200])
keep = [v for v in info.values() if v['w'] >= 1920 and re.search(r'CC BY|CC0|Public domain|PD', v['lic'], re.I) and not re.search(r'NC|ND', v['lic'])]
print('kept', len(keep), flush=True)
json.dump(keep, open(OUT / 'pool.json', 'w'), indent=1, ensure_ascii=False)
