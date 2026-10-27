"""Build out/video/v5/timeline_v5.json (+ TIMELINE.md, .srt, sfx.json, voice.json) from VIDEO_PLAN_v5, narration json and v5_edl.json.
Run with the hermes venv python."""
import json, re, sys, shutil, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
V5 = ROOT / 'out/video/v5'
RAW = ROOT / 'out/video/v5raw'
NAR = V5 / 'narration'
FPS = 60
BEAT_P, BEAT_0 = 0.6207, 0.03
EDL = json.loads((ROOT / 'tools/video/v51_edl.json').read_text(encoding='utf-8'))
OUT = ROOT / 'out/video/v51'; OUT.mkdir(parents=True, exist_ok=True)
F = EDL['_facts']
SCRIPT = json.loads((V5 / 'script.json').read_text(encoding='utf-8'))['script']
CAPTION_WORDS = 7

def snap(t):
    k = round((t - BEAT_0) / BEAT_P); return round(BEAT_0 + k * BEAT_P, 3)

# scene: (start, end, vo offset)  -- starts snapped to the music grid
RAWSC = {1: (0, 11.6, .45), 2: (11.6, 21.4, .3), 3: (21.4, 27.6, .3), 4: (27.6, 37.4, .35), 5: (37.4, 52.6, .3), 6: (52.6, 69.6, .3),
         7: (69.6, 81.6, .3), 8: (81.6, 87.0, .25), 9: (87.0, 94.2, .25), 10: (94.2, 98.6, .2), 11: (98.6, 113.8, .3),
         12: (113.8, 124.8, .3), 13: (124.8, 131.0, .2), 14: (131.0, 142.8, .3), 15: (142.8, 152.0, .3), 16: (152.0, 166.4, .3)}
SC = {}
for k, (a, b, o) in RAWSC.items():
    SC[k] = [0.0 if k == 1 else snap(a), 0, o]
for k in SC: SC[k][1] = SC[k + 1][0] if k + 1 in SC else RAWSC[k][1]
DUR = SC[16][1]

def dur(key): return float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(NAR / f'{key}.wav')]))
VO = [(f'{sc:02}', SC[sc][0] + SC[sc][2]) for sc in SC]
VO.append(('17', SC[11][0] + SC[11][2] + dur('11') + EDL.get('_vo17_gap', 1.6)))
VOAT = dict(VO)

def words(key):
    ev = json.loads((NAR / f'{key}.json').read_text(encoding='utf-8'))
    raw = SCRIPT[str(int(key))].split(); toks = []
    for w in raw:
        if re.search(r'\w', w): toks.append(w)
        elif toks: toks[-1] += ' ' + w
    out, i = [], 0
    for e in ev:
        n = len(e['text'].split()); txt = ' '.join(toks[i:i + n]); i += n
        out.append({'w': txt, 'a': VOAT[key] + e['start'], 'b': VOAT[key] + e['end']})
    return out
def wt(key, word, nth=0):
    c = [w for w in words(key) if re.sub(r"[^\w'-]", '', w['w']).lower() == word.lower()]; return c[nth]['a']

BAD_END = {'a', 'an', 'the', 'of', 'to', 'in', 'on', 'and', 'with', 'every', 'dozens', 'running', 'one', 'that', 'can', 'her', 'their', 'by', 'for', 'is', 'no', 'at', 'from', 'then', 'when', 'next', 'we', 'they', 'so', 'built', 'make', 'people', 'water', 'flooded', 'real', 'live', 'whole', 'each', 'nothing', 'without', 'nvidia', 'defesa', 'el', 'ai', 'into', 'until', 'connect', 'ambulance'}
FORCE_BREAK = {'03': {'built', 'agents'}, '05': {'minute,', 'agents'}}
TEXT_FIX = {'a team of AI agents': 'a team of AI agents —', 'running on NVIDIA Nemotron reads her message,': 'running on NVIDIA Nemotron — reads her message,'}
def chunk_caps(ws, key=''):
    sents, cur = [], []
    for w in ws:
        cur.append(w)
        if re.search(r'[.?!:]”?$', w['w']): sents.append(cur); cur = []
    if cur: sents.append(cur)
    m = []
    for s_ in sents:
        if m and len(m[-1]) < 3 and len(m[-1]) + len(s_) <= CAPTION_WORDS: m[-1] = m[-1] + s_
        else: m.append(s_)
    def split(c):
        n = len(c); INF = 1e9; best = [INF] * (n + 1); prv = [0] * (n + 1); best[0] = 0
        for j in range(1, n + 1):
            for i in range(max(0, j - CAPTION_WORDS), j):
                L = j - i; endw = c[j - 1]['w']; last = re.sub(r"[^\w'-]", '', endw).lower()
                cost = .35 * (L - 5) ** 2 + (0 if j == n else (10 if last in BAD_END else 0) - (3 if re.search(r'[,;:—”]$', endw) else 0)) + (4 if L < 2 else 0)
                if j < n and endw.lower() in FORCE_BREAK.get(key, ()): cost -= 30
                if best[i] + cost < best[j]: best[j], prv[j] = best[i] + cost, i
        out, j = [], n
        while j > 0: out.append(c[prv[j]:j]); j = prv[j]
        return out[::-1]
    merged = []
    for s_ in m: merged += split(s_)
    caps = []
    for i, c in enumerate(merged):
        a = c[0]['a'] - .18; b = c[-1]['b'] + .30
        nxt = merged[i + 1][0]['a'] - .18 if i + 1 < len(merged) else 1e9
        b = min(b, nxt - .02)
        if b - a < .95: b = min(a + .95, nxt - .02)
        tx = ' '.join(w['w'] for w in c); tx = TEXT_FIX.get(tx, tx)
        caps.append({'start': round(a, 3), 'end': round(b, 3), 'text': tx})
    return caps

items, sfx, flashes, kin, shots, dips = [], [], [], [], [], []
def add_shot(a, b, sc, kind, what, vo='', text='', speed='1x', purpose=''):
    shots.append(dict(start=a, end=b, scene=sc, kind=kind, what=what, vo=vo, text=text, speed=speed, purpose=purpose))
def text_item(**k):
    k.setdefault('type', 'text')
    if 'in_' in k: k['in'] = k.pop('in_')
    items.append(k)
    if k.get('cls') != 'src': kin.append({'start': k['start'], 'end': k['end'], 'text': re.sub('<[^>]+>', ' ', k.get('text') or k.get('html', ''))})
    return k
def gfx(name, a, b, p, z=3, sc=0, what='', vo='', text='', purpose=''):
    items.append(dict(type='gfx', name=name, start=round(a, 3), end=round(b, 3), z=z, p=p))
    if what: add_shot(a, b, sc, 'gfx', what, vo=vo, text=text, purpose=purpose)

# ---- 1: max 3 photos (vision-vetted: deep water + boats/rescue), weak-photo slots replaced by kinetic type on black ----
P = 'tools/video/assets/photos6g/%s.jpg'
s1a, s1b = SC[1][0], SC[1][1]
c1, c2, c3, c4 = snap(2.45), snap(4.9), snap(7.3), snap(9.5)
PHOTOS = [(0.0, c1, 'c009', .5, .45, -.6), (c1, c2, 'c088', .5, .5, .6), (c2, c3, 'c027', .5, .55, -.6)]
for a, b, k, fx, fy, dx in PHOTOS:
    items.append(dict(type='photo', start=a, end=b, src='/' + P % k, fx=fx, fy=fy, z=1, kb=dict(s0=1.02, s1=1.09, dx=dx, dy=0)))
    add_shot(a, b, 1, 'photo', f'Flood photo {k} (deep water + boats / people rescued)', purpose='stakes')
    if a: dips.append({'at': a, 'half': .05, 'a': .5})
items.append(dict(type='band', start=c1 - .2, end=c3, w=860, z=10))
text_item(start=0.25, end=c1 - .05, text='May 2024 · Rio Grande do Sul, Brazil', size=58, x=110, y=470, ax=0, ay=.5, anim='rise', z=20, cls='body')
for a, b, big, lab, src in ((c1, c2, '185', 'people dead', 'Source: Defesa Civil RS · final bulletin'), (c2, c3, '2.4 M', 'people affected', 'Source: Defesa Civil RS · 2,398,255 affected')):
    text_item(start=a, end=b - .04, html=big, size=250, x=110, y=430, ax=0, ay=.5, anim='slam', z=20)
    text_item(start=a + .15, end=b - .04, text=lab, size=60, x=116, y=600, ax=0, ay=.5, anim='rise', in_=.45, z=20)
    text_item(start=a + .3, end=b - .04, text=src, size=24, x=116, y=672, ax=0, ay=.5, anim='fade', z=20, cls='src', color='#c3d0dc')
    sfx.append({'t': a, 'k': 'boom'}); add_shot(a, b, 1, 'text', f'Stat on dark band: {big} {lab}', text=f'{big} {lab}', purpose='stakes')
gfx('stat', c3, c4, dict(big='478 <span style="font-size:110px;color:#9fb2c6">of 497</span>', label='municipalities hit', src='Source: Defesa Civil RS · final bulletin', dots=dict(total=497, lit=478)), sc=1,
    what='Kinetic stat on black: 478 of 497 municipalities (dot grid lights up)', text='478 of 497 municipalities hit', purpose='stakes')
gfx('stat', c4, s1b, dict(big='5.35 m', label='Guaíba river crest', src='Source: Serviço Geológico do Brasil · 1941 record 4.76 m',
    level=dict(val=5.35, max=6.2, rec=4.76, recLabel='1941 record 4.76 m', nowLabel='2024 · 5.35 m')), sc=1,
    what='Kinetic stat on black: Guaíba 5.35 m vs 1941 record (rising water bar)', text='5.35 m Guaíba river crest', purpose='stakes')
for t_ in (c3, c4): sfx.append({'t': t_, 'k': 'boom'}); dips.append({'at': t_, 'half': .05, 'a': .6})
kin += [{'start': c3, 'end': c4, 'text': '478 of 497 municipalities hit'}, {'start': c4, 'end': s1b, 'text': '5.35 m Guaíba river crest'}]
text_item(start=0.3, end=c3, text=EDL['_photo_credit'], size=21, x=1880, y=40, ax=1, ay=.5, anim='fade', z=20, cls='src', color='#ffffff', out=.01)

# ---- 2: mosaic -> one queue ----
NB = ['Sarandi', 'Navegantes', 'Humaitá', 'Cidade Baixa', 'Menino Deus', 'Ilhas', 'Mathias Velho', 'São João']
TPL = [('wa', 'WhatsApp · group', '{n}: família no telhado, mandem barco', '{n}: family on the roof, send a boat'),
       ('sms', 'SMS · one bar', 'sem luz, água subindo, {n}', 'no power, water rising, {n}'),
       ('post', 'Social post', 'repassem!! idosos sem remédio em {n}', 'share!! elderly without medicine in {n}'),
       ('call', 'Phone call · 02:14', '“tem um bebê aqui… a água não para”', '“there is a baby here… the water won’t stop”'),
       ('wa', 'WhatsApp · group', 'alguém tem barco em {n}?', 'does anyone have a boat in {n}?'),
       ('wa', 'WhatsApp · group', 'criança com febre, 2º andar, {n}', 'child with fever, 2nd floor, {n}')]
msgs = [dict(k='wa', tag='WhatsApp · Resgate Zona Norte', pt='SOCORRO telhado, 4 pessoas aqui', en='ROOFTOP help, 4 people here'),
        dict(k='call', tag='Phone call · 02:14', pt='“a água já está na escada…”', en='“the water is already on the stairs…”'),
        dict(k='sms', tag='SMS · one bar of signal', pt='preso no telhado. bateria 4%', en='stuck on the roof. battery 4%'),
        dict(k='wa', tag='WhatsApp · Humaitá unido', pt='alguém viu minha vó? Dona Maria, 78 anos', en='has anyone seen my grandmother? Maria, 78')]
CALLS = [('“meu pai não consegue andar, ajudem”', '“my father can’t walk, please help”'), ('“estamos no telhado, 6 pessoas”', '“we are on the roof, 6 people”'),
         ('“a água entrou até o teto”', '“water has reached the ceiling”'), ('“ainda estamos esperando o barco”', '“still waiting for the boat”')]
for i in range(28):
    kd, tg, pt, en = TPL[i % 6]; n = NB[(i * 3) % 8]
    if kd == 'call': pt, en = CALLS[i % 4]
    msgs.append(dict(k=kd, tag=tg, pt=pt.format(n=n), en=en.format(n=n)))
msgs[3]['dup'] = 'same family · ×3'
QUEUE = [dict(pri='P1', pt='socorro!! segundo andar, minha mãe acamada e meu filho de 8 anos', ch='WhatsApp'),
         dict(pri='P1', pt='SOCORRO telhado, 4 pessoas aqui', ch='WhatsApp'), dict(pri='P1', pt='preso no telhado. bateria 4%', ch='SMS'),
         dict(pri='P2', pt='alguém viu minha vó? Dona Maria, 78 anos', ch='Social ×3 → 1'), dict(pri='P2', pt='idosos sem remédio, térreo alagado', ch='Call'),
         dict(pri='P3', pt='precisamos de colchões no abrigo', ch='WhatsApp'), dict(pri='P3', pt='carro ilhado, ninguém ferido', ch='Call')]
a2, b2 = SC[2][0], SC[2][1]
conv = round(wt('02', 'Every') - a2 - .1, 2)
gfx('mosaic', a2, b2, dict(msgs=msgs, queue=QUEUE, converge=conv, title='One queue', sub='every channel · most urgent first', slow=[.05, .4, .8, 1.15], s0=1.35, sd=conv - 1.6),
    sc=2, what='Mosaic of PT messages (WhatsApp, calls, one-bar SMS, duplicates) filling the frame from 0 s, converging into ONE queue', vo=SCRIPT['2'], purpose='problem')
flashes.append({'at': a2, 'a': .25}); sfx.append({'t': a2, 'k': 'boom'})
for j in range(24): sfx.append({'t': round(a2 + 1.35 + (conv - 1.6) * (1 - (1 - (j + 1) / 24) ** 1.6), 3), 'k': 'tick'})
sfx.append({'t': a2 + conv, 'k': 'riser_end'}); sfx.append({'t': a2 + conv + .9, 'k': 'hit'})
kin.append({'start': a2 + conv + .9, 'end': b2, 'text': 'One queue every channel most urgent first'})

# ---- 3: El Niño card -> desk opens LIVE ----
a3, b3 = SC[3][0], SC[3][1]
tdesk = round(wt('03', 'So') - .25, 3)
gfx('noaa', a3, tdesk, dict(kicker='NOAA · CLIMATE PREDICTION CENTER · 8 OCT 2026', label='strong El Niño likely through early 2027',
                             src='Source: NOAA CPC ENSO Diagnostic Discussion, 8 Oct 2026 (strong-to-very-strong, >83%)'), sc=3,
    what='NOAA card: >83 % strong El Niño', text='strong El Niño likely through early 2027', purpose='why now')
flashes.append({'at': a3, 'a': .12}); sfx.append({'t': a3 + .1, 'k': 'boom'})
kin.append({'start': a3 + .6, 'end': tdesk, 'text': 'strong El Niño likely through early 2027'})

# ---- UI from EDL ----
def probe(path):
    o = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'json', str(path)])
    s = json.loads(o)['streams'][0]; return s['width'], s['height']
SRC = V5 / 'src'; SRC.mkdir(parents=True, exist_ok=True)
def snapshot(clip):
    m = RAW / f'{clip}.mp4'; mk = RAW / f'{clip}.marks.json'
    if m.exists() and mk.exists():
        dst = SRC / m.name
        if not dst.exists() or dst.stat().st_mtime < m.stat().st_mtime: shutil.copy2(m, dst); shutil.copy2(mk, SRC / mk.name)
    return (SRC / f'{clip}.mp4').exists()
def load_marks(clip):
    d = json.loads((SRC / f'{clip}.marks.json').read_text(encoding='utf-8'))
    return [dict(t=float(m['t']), event=m.get('event') or m.get('name'), box=m.get('box')) for m in d.get('marks', []) if isinstance(m.get('t'), (int, float))]
def ev_t(marks, ref, after=0):
    if isinstance(ref, (int, float)): return float(ref)
    ref, _, off = ref.partition('+'); off = float(off or 0)
    name, _, idx = ref.partition('#'); idx = int(idx or 0)
    c = [m['t'] for m in marks if m['event'] == name and m['t'] >= after - 1e-6]
    if not c: raise KeyError(f'event {ref} not found')
    return c[idx] + off if idx >= 0 else c[idx] + off

SMAX = 1.6
def framing(box, W, H, smax=None):
    sFull = 1920 / W
    if not box: return dict(cx=W / 2, cy=H / 2, s=sFull)
    x, y, w, h = box; s = min(smax or SMAX, max(sFull, min(1920 / w, 1080 / h)))
    return dict(cx=x + w / 2, cy=y + h / 2, s=round(s, 4))
uiid = 0
def build_ui(sc, seg, a, b):
    global uiid
    clip = seg['clip']; path = SRC / f'{clip}.mp4'
    W, H = probe(path); marks = load_marks(clip)
    sa = seg['_sa']; sb = seg['_sb']; speed = (sb - sa) / (b - a)
    c0 = framing(seg.get('box'), W, H, seg.get('smax')); cam = []
    if seg.get('box2'):
        c1 = framing(seg['box2'], W, H, seg.get('smax')); t0 = seg.get('move_at', 0.15); cam.append(dict(t0=t0, dur=seg.get('move_dur', .7), **{'from': c0, 'to': c1}))
    else:  # slow push keeps every framing alive
        c1 = dict(c0); c1['s'] = round(c0['s'] * seg.get('push', 1.035), 4); cam.append(dict(t0=0, dur=round(b - a, 3), **{'from': c0, 'to': c1}))
    rings = []
    for r in seg.get('rings', []):
        tr = (ev_t(marks, r['t']) - sa) / speed if not isinstance(r['t'], (int, float)) else r['t']
        rings.append(dict(at=round(max(0, tr), 3), dur=r.get('dur', 1.8), box=dict(zip('xywh', r['box']))))
    it = dict(type='ui', id=f'u{uiid:02}', start=round(a, 4), end=round(b, 4), z=2, W=W, H=H, sFull=1920 / W, cam0=c0, cam=cam, rings=rings,
              dir=f'/out/video/v51/frames/u{uiid:02}', n=round((b - a) * FPS),
              extract=dict(src=str(path.relative_to(ROOT)).replace('\\', '/'), a=sa, b=sb, speed=speed), clip=clip, scene=sc)
    it['masks'] = [dict(m) if isinstance(m, dict) else dict(x=m[0], y=m[1], w=m[2], h=m[3], c=(m[4] if len(m) > 4 else '#0d1518')) for m in ([] if seg.get('nomask') else EDL.get('_masks', {}).get(clip, [])) + seg.get('masks', [])]
    if seg.get('shift'):
        for c in {id(c): c for c in [c0] + [x['to'] for x in cam] + [x['from'] for x in cam]}.values(): c['cx'] -= seg['shift'][0] / c['s']; c['cy'] -= seg['shift'][1] / c['s']
    if speed > 2.5: it['badge'] = dict(text=f"{speed:.0f}× · real time {sb - sa:.0f} s", at=.15, dur=(b - a) - .3)
    uiid += 1
    return it

def place(sc, a0=None, b0=None):
    a0 = SC[sc][0] if a0 is None else a0; b0 = SC[sc][1] if b0 is None else b0
    segs = EDL[str(sc)]; D = b0 - a0; nat = []
    for sg in segs:
        if not snapshot(sg['clip']): raise FileNotFoundError(sg['clip'])
        marks = load_marks(sg['clip']); sg['_sa'] = ev_t(marks, sg['a']); sg['_sb'] = ev_t(marks, sg['b'], after=sg['_sa'])
        nat.append(None if sg.get('fit') else (sg['_sb'] - sg['_sa']) / sg.get('speed', 1))
    fixed = sum(n for n in nat if n is not None); nfit = sum(1 for n in nat if n is None)
    if nfit == 0:  # scale everything to fit the slot
        k = fixed / D; nat = [n / k for n in nat]; fixed = D
    out = []; t = a0
    for sg, n in zip(segs, nat):
        d = n if n is not None else (D - fixed) / nfit
        if d <= .4: raise ValueError(f'scene {sc}: segment too short ({d:.2f}s) {sg}')
        it = build_ui(sc, sg, t, t + d); out.append(it); t += d
        if len(out) > 1 and not sg.get('nodip'): dips.append({'at': round(it['start'], 3), 'half': .05, 'a': .55})
    out[-1]['end'] = round(b0, 4); out[-1]['n'] = round((out[-1]['end'] - out[-1]['start']) * FPS)
    for it in out:
        items.append(it)
        add_shot(it['start'], it['end'], sc, 'ui', f"{it['clip']} {it['extract']['a']:.1f}-{it['extract']['b']:.1f}s framing s={it['cam0']['s']:.2f} rings {len(it['rings'])}",
                 speed=f"{it['extract']['speed']:.1f}x", purpose=f'scene {sc}')
    return out

missing = []
def try_place(sc, a0=None, b0=None):
    try: return place(sc, a0, b0)
    except FileNotFoundError as e:
        missing.append((sc, str(e)))
        gfx('callouts', SC[sc][0] if a0 is None else a0, SC[sc][1] if b0 is None else b0, dict(items=[dict(at=0, end=99, x=460, y=380, w=1000, html=f'<div style="font:700 44px Inter">PENDING CLIP {e}</div>')]), sc=sc, what=f'PENDING {e}')
        return []

LIVE = 'LIVE · Nemotron via Nightshift'
def chip(a, b, text=LIVE, dot='#ff4d4d'): items.append(dict(type='chip', start=round(a, 3), end=round(b, 3), text=text, dot=dot, z=31))

try_place(3, tdesk, b3)
text_item(start=tdesk + .1, end=b3, html='<span style="display:inline-block;padding:18px 34px;border-radius:999px;background:rgba(5,9,15,.9);border:1px solid rgba(255,255,255,.2)"><span class="chipdot"></span>' + LIVE + '</span>', size=46, x=960, y=500, ax=.5, ay=.5, anim='slam', z=25, cls='body')
flashes.append({'at': tdesk, 'a': .3}); sfx.append({'t': tdesk, 'k': 'hit'})

# ---- 4: the message (who is there) ----
a4, b4 = SC[4][0], SC[4][1]
gfx('message', a4, b4, dict(tag='WHATSAPP · 6 MAY 2024 · 12:00', time='12:00', pt=F['hero_msg_pt'], en=F['hero_msg_en'], wordDt=.07, enAt=2.6,
    who=[dict(name='She writes', sub='2nd floor · Voluntários da Pátria', c='#3BA3FF', at=round(wt('04', 'woman') - a4, 2)),
         dict(name='Her mother', sub='bedridden · cannot walk', c='#FF8A4D', at=round(wt('04', 'bedridden') - a4, 2)),
         dict(name='Her son', sub='8 years old', c='#2BD47D', at=round(wt('04', 'eight-year-old') - a4, 2))],
    alert='WATER STILL RISING', alertAt=round(wt('04', 'water') - a4, 2)), sc=4,
    what='Hero message as a WhatsApp bubble (PT word-by-word + EN gloss); the three people appear on the VO words', vo=SCRIPT['4'], text='She writes · Her mother (bedridden) · Her son (8)', purpose='human stakes')
kin.append({'start': a4, 'end': b4, 'text': 'She writes 2nd floor Her mother bedridden Her son 8 years old water still rising'})
sfx += [{'t': a4, 'k': 'boom'}, {'t': a4 + wt('04', 'bedridden') - a4, 'k': 'hit'}, {'t': wt('04', 'eight-year-old'), 'k': 'hit'}]

# ---- 5..13: UI beats ----
for sc in (5, 6, 7, 8, 9, 10, 11, 12, 13):
    out = try_place(sc)
LIVE_SC = EDL['_live_scenes']
for sc in (5, 6, 7, 8, 9, 10, 11, 12, 13):
    lab = EDL['_labels'].get(str(sc))
    if lab: chip(SC[sc][0] + .05, SC[sc][1] - .02, lab['text'], lab.get('dot', '#ff4d4d'))
# overlay callouts (times relative to the scene start or to VO words)
def tref(sc, r):
    if isinstance(r, (int, float)): return SC[sc][0] + r
    k, _, w = r.partition(':'); w, _, off = w.partition('+'); n = 0
    if '#' in w: w, n = w.split('#'); n = int(n)
    return wt(k, w, n) + float(off or 0)
for sc, lst in EDL.get('_callouts', {}).items():
    sc = int(sc)
    for grp in lst:
        a = tref(sc, grp['at']); b = tref(sc, grp['end']) if 'end' in grp else SC[sc][1]
        dy = max(0, 200 - min(c['y'] for c in grp['items']))
        its = []
        for c in grp['items']:
            c = dict(c); c['y'] += dy; c['at'] = round(tref(sc, c['at']) - a, 3) if 'at' in c else 0; c['end'] = round((tref(sc, c['end']) if 'end' in c else b) - a, 3)
            if 'swapAt' in c: c['swapAt'] = round(tref(sc, c['swapAt']) - a, 3)
            its.append(c)
        gfx('callouts', a, b, dict(items=its), z=6, sc=sc, what='Callout: ' + re.sub('<[^>]+>', ' ', its[0]['html'])[:90], text=grp.get('kin', ''))
        if grp.get('kin'): kin.append({'start': a, 'end': b, 'text': grp['kin']})
        sfx.append({'t': a, 'k': 'hit'})

# ---- 14: autonomy / team (no red team) ----
a14, b14 = SC[14][0], SC[14][1]
AG = [('Intake', 'Reads every message, quotes each fact', '#3BA3FF'), ('Location', 'Finds the address in Zetaris', '#2BD47D'), ('Verifier', 'Checks the other agents’ work', '#B084FF'),
      ('Callback', 'Asks one precise question', '#FFB224'), ('Fleet', 'Picks the right boat', '#3BA3FF'), ('Routing', 'Streets to the water, then by boat', '#2BD47D'),
      ('Landing', 'Ambulance at the landing', '#FF8A4D'), ('Shelter', 'Finds free beds', '#2BD47D'), ('Supervisor', 'Watches every boat', '#B084FF'),
      ('Handover', 'Briefs the next shift', '#3BA3FF'), ('Reunification', 'Reunites families', '#FF8A4D')]
t_read = wt('14', 'read') - a14; t_own = wt('14', 'own') + .2 - a14
agents = [dict(name=n, sub=s, c=c, at=round(t_read + i * (t_own - t_read) / len(AG), 2)) for i, (n, s, c) in enumerate(AG)]
gfx('build', a14, b14, dict(title='The agents work on their own · around the clock', agents=agents, human='People make one decision: send the boat', humanAt=round(wt('14', 'People') - a14, 2)), sc=14,
    what='Team build: 11 agent cards (no red team) + human decision bar', vo=SCRIPT['14'], text='11 agents · People make one decision: send the boat', purpose='autonomy')
for g in agents: sfx.append({'t': a14 + g['at'], 'k': 'tick'})
sfx.append({'t': wt('14', 'People'), 'k': 'boom'}); flashes.append({'at': a14, 'a': .15})
kin.append({'start': wt('14', 'People'), 'end': b14, 'text': 'People make one decision: send the boat'})

# ---- 15: future ----
a15, b15 = SC[15][0], SC[15][1]
gfx('future', a15, b15, dict(kicker='NEXT', rows=[dict(t='WhatsApp Business + 193 intake', s='the real channels people already use', c='#25D366', at=round(wt('15', 'connect') - a15, 2)),
    dict(t='Live river gauges', s='Guaíba and tributaries, straight into triage', c='#3BA3FF', at=round(wt('15', 'live') - a15, 2)),
    dict(t='A pilot with Defesa Civil', s='before the next El Niño', c='#FFB224', at=round(wt('15', 'pilot') - a15, 2))]), sc=15,
    what='Future card: WhatsApp Business + 193 · live river gauges · pilot with Defesa Civil', vo=SCRIPT['15'], text='Next: 3 rows', purpose='future')
for w in ('connect', 'live', 'pilot'): sfx.append({'t': wt('15', w), 'k': 'hit'})
kin.append({'start': a15, 'end': b15, 'text': 'Next WhatsApp Business + 193 intake real channels Live river gauges A pilot with Defesa Civil before the next El Niño'})

# ---- 16: close ----
a16, b16 = SC[16][0], SC[16][1]
t1, t2, t3 = wt('16', 'Every') - .05, wt('16', 'Every', 1) - .05, wt('16', 'When') - .05
tS = words('16')[-1]['b'] + .45
gfx('close', a16, b16, dict(sponsorLine='BUILT WITH', repo='github.com/LamboKiller/rescue-triage-desk',
    logos=[dict(src='/tools/video/assets/logos/nvidia.svg', css='height:150px;margin:-18px 0 -24px', cap='Nemotron'), dict(word='Meterless', cap='Nightshift · World Model'),
           dict(src='/tools/video/assets/logos/zetaris.svg', css='width:330px', cap='Zetaris')],
    l1='Every request heard.', l2='Every agent working together.', l3='When the next flood comes, no call for help gets lost.',
    t1=round(t1 - a16, 2), t2=round(t2 - a16, 2), t3=round(t3 - a16, 2), tS=round(tS - a16, 2)), sc=16,
    what='Close: three lines on VO words, then NVIDIA / Meterless / Zetaris logos in one row + repo URL 56 px', vo=SCRIPT['16'], purpose='close + sponsors')
flashes.append({'at': a16, 'a': .12}); sfx += [{'t': t1, 'k': 'hit'}, {'t': t2, 'k': 'hit'}, {'t': t3, 'k': 'boom'}, {'t': tS, 'k': 'hit'}]
kin += [{'start': t1, 'end': t3, 'text': 'Every request heard.'}, {'start': t2, 'end': t3, 'text': 'Every agent working together.'}, {'start': t3, 'end': tS, 'text': 'When the next flood comes, no call for help gets lost.'}]

# ---- chapter titles (one per chapter, top-left) ----
CHAP = [(1, 1, 'The disaster'), (3, 2, 'One call for help'), (5, 3, 'The agents read it'), (6, 4, 'Choosing the boat'), (7, 5, 'Dispatch'),
        (8, 6, 'Watching until rescued'), (11, 7, 'When a message is vague'), (12, 8, 'A surge of calls'), (14, 9, 'Working around the clock'), (15, 10, "What's next")]
for i, (sc, num, title) in enumerate(CHAP):
    a = SC[sc][0] + (0.0 if sc != 1 else 0.0); b = SC[CHAP[i + 1][0]][0] if i + 1 < len(CHAP) else SC[16][0]
    items.append(dict(type='chapter', start=round(a, 3), end=round(b, 3), num=str(num), text=title, z=32))
    add_shot(a, a + 2.6, sc, 'chapter', f'Chapter title "{num} · {title}"', text=f'{num} · {title}', purpose='structure')
    kin.append({'start': a, 'end': a + 2.6, 'text': title})

# ---------------- captions ----------------
caps = []
for k, _ in VO: caps += chunk_caps(words(k), k)
caps.sort(key=lambda c: c['start'])
def toks(s): return set(re.sub(r"[^\w ]", '', s.lower()).split())
dropped, final = [], []
for c in caps:
    ct = toks(c['text']); drop = False
    for k in kin:
        if k['start'] < c['end'] and k['end'] > c['start']:
            kt = toks(k['text'])
            if ct and len(ct & kt) / len(ct) >= .6 and len(kt) >= 2: drop = True; break
    (dropped if drop else final).append(c)
caps = final
for i in range(1, len(caps)):
    if caps[i]['start'] < caps[i - 1]['end']: caps[i - 1]['end'] = round(caps[i]['start'] - .02, 3)

# ---------------- validation ----------------
errs = []
for c in caps:
    if c['end'] - c['start'] < .6: errs.append(f'caption short: {c}')
    if len(c['text'].split()) > CAPTION_WORDS: errs.append(f'caption long: {c}')
    last = re.sub(r"[^\w'-]", '', c['text'].split()[-1]).lower()
    if last in BAD_END and not re.search(r'[.?!:]”?$', c['text']): errs.append(f'caption ends on "{last}": {c["text"]}')
for it in items:
    if it['type'] == 'ui' and it['extract']['speed'] > 8.01: errs.append(f"{it['id']} speed {it['extract']['speed']:.1f}x > 8")
    if it['type'] == 'ui' and it['end'] - it['start'] > 4.6 and not (len(it['cam']) and it['cam'][0]['t0'] > 0): errs.append(f"{it['id']} {it['clip']} holds one framing {it['end'] - it['start']:.1f}s > 4.5")
txt_all = json.dumps(items, ensure_ascii=False).lower()
for bad in ('red team', 'red-team', 'unsafe', '29/30', '34/50'):
    if bad in txt_all: errs.append(f'forbidden text: {bad}')
for k, a in VO:
    if a + dur(k) > DUR - .5: errs.append(f'VO {k} runs past the end')

tl = dict(fps=FPS, width=1920, height=1080, duration=DUR, items=items, captions=caps, flashes=flashes, dips=dips,
          fades=[dict(at=0, dur=.35, to=0), dict(at=DUR - .85, dur=.85, to=1)], beat=dict(p=BEAT_P, ph=BEAT_0))
(OUT / 'timeline_v5_1.json').write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding='utf-8')
(OUT / 'sfx.json').write_text(json.dumps(sorted(sfx, key=lambda x: x['t']), indent=1), encoding='utf-8')
(OUT / 'voice.json').write_text(json.dumps([dict(key=k, start=round(a, 3), wav=f'out/video/v5/narration/{k}.wav') for k, a in VO], indent=1), encoding='utf-8')
def srt_t(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60; ms = int(round((s - int(s)) * 1000))
    if ms == 1000: ms = 999
    return f'{h:02}:{m:02}:{int(s):02},{ms:03}'
# srt carries every VO line (kinetic-type duplicates included) so the file is a full transcript
allcaps = []
for k, _ in VO: allcaps += chunk_caps(words(k), k)
allcaps.sort(key=lambda c: c['start'])
for i in range(1, len(allcaps)):
    if allcaps[i]['start'] < allcaps[i - 1]['end']: allcaps[i - 1]['end'] = round(allcaps[i]['start'] - .02, 3)
(OUT / 'rtd_demo_v5_1.srt').write_text('\n'.join(f"{i + 1}\n{srt_t(c['start'])} --> {srt_t(c['end'])}\n{c['text']}\n" for i, c in enumerate(allcaps)), encoding='utf-8')
def mmss(t): return f'{int(t // 60)}:{t % 60:04.1f}'
rows = ['# TIMELINE v5.1 (auto-generated by tools/video/v51_timeline.py)', '', f'Duration {mmss(DUR)} · 1920x1080 · 60 fps CFR', '',
        '| start-end | sc | kind | on screen | VO | text | speed | purpose |', '|---|---|---|---|---|---|---|---|']
for s in sorted(shots, key=lambda x: (x['start'], x['kind'])):
    rows.append(f"| {mmss(s['start'])}-{mmss(s['end'])} | {s['scene']} | {s['kind']} | {s['what']} | {s['vo']} | {s['text']} | {s['speed']} | {s['purpose']} |")
rows += ['', f'Burned-in captions: {len(caps)} (one line, bottom); {len(dropped)} chunks suppressed where the same words are on screen as type:']
rows += [f"- {mmss(c['start'])} \"{c['text']}\"" for c in dropped]
(OUT / 'TIMELINE.md').write_text('\n'.join(rows), encoding='utf-8')
print('DUR', DUR, 'items', len(items), 'captions', len(caps), 'dropped', len(dropped), 'ui', uiid)
print('scenes', {k: (v[0], v[1]) for k, v in SC.items()})
if missing: print('MISSING CLIPS:', missing)
if errs: print('VALIDATION ERRORS:\n' + '\n'.join(errs)); sys.exit(2)
print('validation ok')
