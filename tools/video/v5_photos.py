"""v5 photos: fetch 2 aerial Commons originals (2560 px) + grade the vision-vetted set into assets/photos6g (same grade as v4_grade)."""
import time, urllib.request
import numpy as np
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
P5 = ROOT / 'tools/video/assets/photos5'; P6 = ROOT / 'tools/video/assets/photos6'; DST = ROOT / 'tools/video/assets/photos6g'; DST.mkdir(exist_ok=True)
UA = {'User-Agent': 'rtd-video/1 (hackathon; contact via github LamboKiller)'}
AER = {  # vision-vetted aerials (Commons, CC BY-SA 2.0, Ricardo Stuckert / PR)
 'a13': 'https://upload.wikimedia.org/wikipedia/commons/thumb/f/f1/05.05.2024_-_Sobrevoo_das_%C3%A1reas_afetadas_pelas_chuvas_na_Regi%C3%A3o_metropolitana_de_Porto_Alegre_%283%29.jpg/3840px-05.05.2024_-_Sobrevoo_das_%C3%A1reas_afetadas_pelas_chuvas_na_Regi%C3%A3o_metropolitana_de_Porto_Alegre_%283%29.jpg',
 'a08': 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4d/05.05.2024_-_Sobrevoo_das_%C3%A1reas_afetadas_pelas_chuvas_em_Canoas_-_53699607822.jpg/3840px-05.05.2024_-_Sobrevoo_das_%C3%A1reas_afetadas_pelas_chuvas_em_Canoas_-_53699607822.jpg',
}
for k, u in AER.items():
    p = P6 / f'{k}_2560.jpg'
    if p.exists() and p.stat().st_size > 300_000: continue
    for i in range(5):
        try: p.write_bytes(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90).read()); break
        except Exception as e: print('retry', k, e); time.sleep(6)
    print(k, p.stat().st_size if p.exists() else 'FAILED')

KEEP = [P5 / f'{c}.jpg' for c in ('c027', 'c009', 'c015', 'c039', 'c088', 'c035', 'c022', 'c074', 'c044')] + [P6 / 'a13_2560.jpg', P6 / 'a08_2560.jpg']
def grade(f, out):
    im0 = Image.open(f).convert('RGB'); w, h = im0.size
    im = np.asarray(im0.resize((2560, int(2560 * h / w)), Image.LANCZOS)).astype(np.float32) / 255
    y = im @ np.array([.2126, .7152, .0722], np.float32)
    lo, hi = np.percentile(y, [1, 99.5]); im = np.clip((im - lo) / (hi - lo), 0, 1)
    y = im @ np.array([.2126, .7152, .0722], np.float32); g = np.log(.40) / np.log(max(np.median(y), .05)); im = im ** g
    im = im * im * (3 - 2 * im) * .55 + im * .45
    y = (im @ np.array([.2126, .7152, .0722], np.float32))[..., None]
    im = y + (im - y) * .82
    t = np.clip((y - .5) * 2, -1, 1); im = im + np.array([-.020, .004, .028]) * (1 - np.clip(t, 0, 1)) + np.array([.030, .012, -.022]) * np.clip(t, 0, 1)
    im = np.clip(.035 + im * .93, 0, 1)
    Image.fromarray((im * 255 + .5).astype(np.uint8)).save(out, quality=93)
for f in KEEP:
    if not f.exists(): print('MISSING', f); continue
    out = DST / (f.stem.split('_')[0] + '.jpg')
    if not out.exists(): grade(f, out)
    print(out.name, Image.open(out).size)
