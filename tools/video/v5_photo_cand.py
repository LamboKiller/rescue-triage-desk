"""v5: fetch thumbs of aerial Porto Alegre/Canoas candidates (landscape, free licence) + numbered contact sheets."""
import json, re, urllib.request, urllib.parse, time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'tools/video/assets/photos6/cand'; OUT.mkdir(parents=True, exist_ok=True)
pool = json.load(open(ROOT / 'out/video/v4/cand/pool.json', encoding='utf-8'))
UA = {'User-Agent': 'rtd-video/1 (hackathon)'}
sel = [v for v in pool if re.search(r'Sobrevoo', v['title']) and v['w'] > v['h'] * 1.3]
print(len(sel))
meta = []
for i, v in enumerate(sel):
    u = v['thumb'].replace('/420px-', '/1280px-')
    p = OUT / f'a{i:02}.jpg'
    if not p.exists():
        for k in range(4):
            try: p.write_bytes(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()); break
            except Exception as e: print('retry', e); time.sleep(8)
        time.sleep(.6)
    meta.append(dict(id=f'a{i:02}', **v))
json.dump(meta, open(OUT / 'meta.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
f = ImageFont.truetype('arial.ttf', 40)
for s in range(0, len(meta), 6):
    sh = Image.new('RGB', (2 * 960, 3 * 560), 'black'); d = ImageDraw.Draw(sh)
    for j, m in enumerate(meta[s:s+6]):
        try: im = Image.open(OUT / f"{m['id']}.jpg").convert('RGB')
        except Exception: continue
        im.thumbnail((950, 540)); x, y = (j % 2) * 960, (j // 2) * 560
        sh.paste(im, (x, y)); d.text((x + 10, y + 10), m['id'], fill='yellow', font=f)
    sh.save(OUT / f'sheet{s//6}.jpg', quality=85)
