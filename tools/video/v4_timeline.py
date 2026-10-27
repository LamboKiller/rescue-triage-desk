"""Build out/video/v4/timeline_v4.json (+ TIMELINE.md, .srt, sfx.json) from VIDEO_PLAN_v4, narration json and v4_edl.json.
Run with the hermes venv python (numpy not needed here)."""
import json, re, sys, math, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / 'out/video/v4'
RAW = ROOT / 'out/video/v4raw'
OLD = ROOT / 'out/video/raw'
NAR = V4 / 'narration'
FPS = 60
BEAT_P, BEAT_0 = 0.6207, 0.03   # music grid (measured on the bed)

SC = {  # scene: (start, end, vo offset)
 1: (0, 14, .5), 2: (14, 24, .4), 3: (24, 30, .3), 4: (30, 50, .5), 5: (50, 65, .4), 6: (65, 85, .4), 7: (85, 102, .4),
 8: (102, 110, .3), 9: (110, 126, .4), 10: (126, 138, .3), 11: (138, 150, .4), 12: (150, 168, .4), 13: (168, 180, .3)}
DUR = 180.0
SCRIPT = json.loads((V4 / 'script.json').read_text(encoding='utf-8'))['script']
CAPTION_WORDS = 7

def snap(t, lo=0):
    k = max(lo, round((t - BEAT_0) / BEAT_P)); return round(BEAT_0 + k * BEAT_P, 3)

# ---------------- narration words / captions ----------------
def words(sc):
    ev = json.loads((NAR / f'{sc:02}.json').read_text(encoding='utf-8'))
    toks = [w for w in SCRIPT[str(sc)].split() if re.search(r'\w', w)]
    out, i = [], 0
    for e in ev:
        n = len(e['text'].split()); txt = ' '.join(toks[i:i+n]); i += n
        out.append({'w': txt, 'a': SC[sc][0] + SC[sc][2] + e['start'], 'b': SC[sc][0] + SC[sc][2] + e['end']})
    return out

def chunk_caps(ws):
    sents, cur = [], []
    for w in ws:
        cur.append(w)
        if re.search(r'[.?!]”?$', w['w']): sents.append(cur); cur = []
    if cur: sents.append(cur)
    # merge too-short sentences into the next one when they fit
    m = []
    for s_ in sents:
        if m and len(m[-1]) < 3 and len(m[-1]) + len(s_) <= CAPTION_WORDS: m[-1] = m[-1] + s_
        else: m.append(s_)
    def split(c):
        n = len(c)
        if n <= CAPTION_WORDS: return [c]
        best, bs = None, -1e9
        for j in range(3, n - 2):
            d1 = c[j-1]['b'] - c[0]['a']; d2 = c[-1]['b'] - c[j]['a']
            sc_ = min(d1, d2) + (0.5 if re.search(r'[,;:—”]$', c[j-1]['w']) else 0) - 0.02 * abs(j - n / 2)
            if j <= CAPTION_WORDS and n - j <= 10 and sc_ > bs: best, bs = j, sc_
        if best is None: best = n // 2
        return split(c[:best]) + split(c[best:])
    merged = []
    for s_ in m: merged += split(s_)
    caps = []
    for i, c in enumerate(merged):
        a = c[0]['a'] - .22; b = c[-1]['b'] + .30
        nxt = merged[i+1][0]['a'] - .22 if i + 1 < len(merged) else 1e9
        b = min(b, nxt - .02)
        if b - a < .95: b = min(a + .95, nxt - .02)
        caps.append({'start': round(a, 3), 'end': round(b, 3), 'text': ' '.join(w['w'] for w in c)})
    return caps

# ---------------- items ----------------
items, sfx, flashes, kin, shots = [], [], [], [], []

def add_shot(a, b, sc, kind, what, vo='', text='', hold='', speed='1x', purpose=''):
    shots.append(dict(start=a, end=b, scene=sc, kind=kind, what=what, vo=vo, text=text, hold=hold, speed=speed, purpose=purpose))

def text_item(**k):
    k.setdefault('type', 'text')
    if 'in_' in k: k['in'] = k.pop('in_')
    items.append(k)
    if k.get('cls') != 'src': kin.append({'start': k['start'], 'end': k['end'], 'text': re.sub('<[^>]+>', ' ', k.get('text') or k.get('html', ''))})
    return k

# ---- Scene 1: photo montage on beats + stats ----
PH = 'tools/video/assets/photos4/candidate_%d.jpg'
P5 = 'tools/video/assets/photos5g/c%03d.jpg'
PHOTOS = [  # (src, fx, fy, dx)  all reviewed: flood + rescue
 (P5 % 27, .5, .5, -.8), (P5 % 74, .5, .5, .8), (P5 % 9, .5, .5, -.8), (P5 % 15, .5, .5, .5), (P5 % 88, .5, .25, -.8),
 (P5 % 7, .5, .5, .8), (P5 % 22, .5, .5, -.8), (P5 % 62, .5, .5, .8), (P5 % 41, .5, .5, -.8)]
CUTBEATS = [3, 2, 2, 2, 2, 2, 2, 2, 3]
t = 0.0; k = 0
for i, (src, fx, fy, dx) in enumerate(PHOTOS):
    k2 = k + CUTBEATS[i]; a = 0.0 if i == 0 else round(BEAT_0 + k * BEAT_P, 3)
    b = DUR and (14.0 if i == len(PHOTOS) - 1 else round(BEAT_0 + k2 * BEAT_P, 3))
    items.append(dict(type='photo', start=a, end=b, src='/' + src, fx=fx, fy=fy, z=1, kb=dict(s0=1.0, s1=1.06, dx=dx, dy=0)))
    add_shot(a, b, 1, 'photo', f'Real flood photo {Path(src).stem} (graded, push-in)', purpose='stakes: real disaster imagery')
    if i: flashes.append({'at': a, 'a': .10})
    k = k2
STATS = [  # start, end, big, label, src
 (2.5, 5.45, '185', 'dead', 'Source: Defesa Civil RS · final bulletin'),
 (5.55, 8.45, '478 <span style="font-size:120px;color:#F5F7FA">of 497</span>', 'municipalities hit', 'Source: Defesa Civil RS · final bulletin'),
 (8.55, 11.25, '2.4 M', 'people affected', 'Source: Defesa Civil RS · 2,398,255 affected'),
 (11.35, 14.0, '5.35 m', 'Guaíba crest · 1941 record 4.76 m', 'Source: G1 / Serviço Geológico do Brasil'),
]
for a, b, big, lab, src in STATS:
    a = snap(a); b = b if b >= 14.0 else snap(b) - .06
    text_item(start=a, end=b, html=big, size=300, x=150, y=455, ax=0, ay=.5, anim='slam', z=20)
    text_item(start=a + .2, end=b, text=lab, size=66, x=156, y=640, ax=0, ay=.5, anim='rise', in_=.5, z=20, cls='')
    text_item(start=a + .35, end=b, text=src, size=24, x=156, y=716, ax=0, ay=.5, anim='fade', z=20, cls='src', color='#aab8c6')
    sfx.append({'t': a, 'k': 'boom'})
    add_shot(a, b, 1, 'text', f'Stat slam: {re.sub("<[^>]+>", "", big)} {lab}', text=f'{re.sub("<[^>]+>", "", big)} {lab}', hold=f'{b-a-.5:.1f}s', purpose='stakes (FACTS rows 1,4,5,10,11)')
text_item(start=0.3, end=14.0, text='Photos: Prefeitura de Pelotas / Michel Corvello, Gustavo Vara (public domain) — Wikimedia Commons', size=22, x=1864, y=44, ax=1, ay=.5, anim='fade', z=20, cls='src', color='#ffffff', out=.01)
kin.pop()

# ---- Scene 2: mosaic ----
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
for i in range(28):
    kd, tg, pt, en = TPL[i % 6]; n = NB[(i * 3) % 8]
    if kd == 'call': pt = ['“tem um bebê aqui… a água não para”', '“meu pai não consegue andar, ajudem”', '“estamos no telhado, 6 pessoas”', '“a água entrou até o teto”', '“tem idosos aqui, sem remédio”', '“fala baixo, a bateria vai acabar”', '“ainda estamos esperando o barco”'][i % 7]; en = ['“there is a baby here… the water won’t stop”', '“my father can’t walk, please help”', '“we are on the roof, 6 people”', '“water has reached the ceiling”', '“elderly people here, no medicine”', '“speak softly, battery is dying”', '“still waiting for the boat”'][i % 7]
    m = dict(k=kd, tag=tg + (f' · {i % 5 + 1}:{(i * 7) % 60:02d}' if kd == 'call' else ''), pt=pt.format(n=n), en=en.format(n=n))
    msgs.append(m)
for pos in (9, 17):
    msgs[pos] = dict(k='wa', tag='Social post · repost', pt='alguém viu minha vó? Dona Maria, 78 anos', en='has anyone seen my grandmother? Maria, 78', dup='same family · ×3')
msgs[3]['dup'] = 'same family · ×3'
QUEUE = [dict(pri='P1', pt='socorro!! segundo andar, minha mãe acamada e meu filho de 8 anos', ch='WhatsApp'),
         dict(pri='P1', pt='SOCORRO telhado, 4 pessoas aqui', ch='WhatsApp'),
         dict(pri='P1', pt='preso no telhado. bateria 4%', ch='SMS'),
         dict(pri='P2', pt='alguém viu minha vó? Dona Maria, 78 anos', ch='Social ×3 → 1'),
         dict(pri='P2', pt='idosos sem remédio, térreo alagado', ch='Call'),
         dict(pri='P3', pt='precisamos de colchões no abrigo', ch='WhatsApp'),
         dict(pri='P3', pt='carro ilhado, ninguém ferido', ch='Call')]
items.append(dict(type='gfx', name='mosaic', start=14.0, end=24.0, z=3,
                  p=dict(msgs=msgs, queue=QUEUE, converge=6.7, title='One queue', sub='every channel · most urgent first')))
flashes.append({'at': 14.0, 'a': .30}); sfx.append({'t': 14.0, 'k': 'boom'})
for j in range(28): sfx.append({'t': round(14 + 3.55 + 2.9 * (1 - (1 - (j + 1) / 28) ** 2.2), 3), 'k': 'tick'})
sfx.append({'t': 14 + 6.7, 'k': 'riser_end'}); sfx.append({'t': 14.0 + 6.7 + .9, 'k': 'hit'})
kin.append({'start': 14 + 7.6, 'end': 24, 'text': 'One queue every channel most urgent first'})
add_shot(14, 24, 2, 'gfx', 'Mosaic of fictional PT messages (WhatsApp, call waveform, one-bar SMS, same family x3) accelerating into ONE queue',
         vo=SCRIPT['2'], text='One queue · every channel · most urgent first', hold='2.4s', speed='accelerating', purpose='problem: fragmented intake (FACTS row 17)')

# ---- Scene 3a: NOAA ----
items.append(dict(type='gfx', name='noaa', start=24.0, end=27.6, z=3,
                  p=dict(kicker='NOAA · CLIMATE PREDICTION CENTER · 8 OCT 2026', label='strong El Niño likely through early 2027',
                         src='Source: NOAA CPC ENSO Diagnostic Discussion, 8 Oct 2026 (strong-to-very-strong, >83%)')))
flashes.append({'at': 24.0, 'a': .12}); sfx.append({'t': 24.15, 'k': 'boom'})
kin.append({'start': 24.7, 'end': 27.6, 'text': 'strong El Niño likely through early 2027'})
add_shot(24, 27.6, 3, 'gfx', 'NOAA card: >83 % strong El Niño through early 2027', vo='A strong El Niño is coming again.', text='>83 % strong El Niño likely through early 2027', hold='2.2s', purpose='why now (FACTS row 23)')

# ---- UI shots from the EDL ----
EDL = json.loads((ROOT / 'tools/video/v4_edl.json').read_text(encoding='utf-8'))
def probe(path):
    import subprocess
    o = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height,r_frame_rate', '-of', 'json', str(path)])
    s = json.loads(o)['streams'][0]; return s['width'], s['height']

SRC = V4 / 'src'; SRC.mkdir(parents=True, exist_ok=True)
import shutil, time, subprocess
def snapshot_all():
    """Copy finished CAPTURE clips (mp4 + marks, mp4 untouched >20 s, ffprobe ok) into out/video/v4/src so retakes never break a render."""
    for m in RAW.glob('*.mp4'):
        mk = RAW / (m.stem + '.marks.json')
        if m.name.startswith('_') or not mk.exists() or time.time() - m.stat().st_mtime < 20: continue
        dst = SRC / m.name
        if dst.exists() and dst.stat().st_mtime >= m.stat().st_mtime: continue
        if subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(m)], capture_output=True).returncode: continue
        shutil.copy2(m, dst); shutil.copy2(mk, SRC / mk.name)
snapshot_all()

def load_marks(clip):
    p = (SRC if (SRC / f'{clip}.mp4').exists() else OLD) / f'{clip}.marks.json'
    if not p.exists(): return []
    d = json.loads(p.read_text(encoding='utf-8'))
    out = []
    for m in d.get('marks', []):
        ev = m.get('event') or m.get('name')
        out.append(dict(t=m['t'], event=ev, box=m.get('box'), m=m))
    return out

def clip_path(clip):
    if (SRC / f'{clip}.mp4').exists(): return SRC / f'{clip}.mp4', False
    return OLD / f'{clip}.mp4', True

def ev_t(marks, ref, after=0):
    if isinstance(ref, (int, float)): return float(ref)
    ref, _, off = ref.partition('+'); off = float(off or 0)
    name, _, idx = ref.partition('#'); idx = int(idx or 0)
    c = [m['t'] for m in marks if m['event'] == name and m['t'] >= after]
    if not c: raise KeyError(f'event {ref} not found')
    return c[idx] + off

CAMEV = re.compile(r'question|reply|answer|card|node_|route|alert|landing|ambulance|shelter|boat|closed|reroute|summary|retriag|dispatch|badge|new_p1|supervisor|callback|assets|ver_rota|sorted|fill|closed|after_gps|map|photo|popup|surge|counter|undo|signal|gps', re.I)
NOZOOM = {'queue_empty', 'expand_agents', 'sse_attached', 'end', 'go', 'click', 'eval', 'wait', 'run', 'run_end', 'hero_start_step1', 'hero_end_step1', 'agents_hold', 'agents_full'}
uiid = 0
ui_report = []
def build_ui(sc, seg, a, b):
    """seg: EDL entry; a,b: global start/end. returns item."""
    global uiid
    clip = seg['clip']; path, placeholder = clip_path(clip)
    W, H = probe(path); marks = load_marks(clip)
    sa = ev_t(marks, seg['a']); sb = ev_t(marks, seg['b'], after=sa)
    speed = (sb - sa) / (b - a)
    sFull = 1920 / W; sMax = 1.0 if W > 1920 else 1.33
    cam = []; rings = []; last_start = -9; cur = dict(cx=W/2, cy=H/2, s=sFull)
    if not seg.get('nocam') and not placeholder or seg.get('cam'):
        pts = [m for m in marks if sa <= m['t'] < sb and m['box'] and m['event'] not in NOZOOM and CAMEV.search(m['event'] or '') and m['box']['w'] * m['box']['h'] < .5 * W * H]
        for m in pts:
            tl = (m['t'] - sa) / speed
            bx = m['box']; vis_w = max(bx['w'] * 2.4, 960 * (W / 1920)); s_t = min(sMax, max(sFull, 1920 / vis_w))
            rings.append(dict(at=round(max(0, tl - .05), 3), dur=1.7, box=bx))
            if s_t < sFull * 1.12: continue
            t0 = tl - .15
            if t0 < 0.1 or t0 - last_start < 2.0 or t0 + .6 > (b - a) - .2: continue
            tgt = dict(cx=bx['x'] + bx['w'] / 2, cy=bx['y'] + bx['h'] / 2, s=s_t)
            cam.append(dict(t0=round(t0, 3), dur=.6, **{'from': dict(cur), 'to': tgt})); cur = tgt; last_start = t0
            # ease back
            tb = t0 + .6 + 1.5
            nxt = [x for x in pts if (x['t'] - sa) / speed - .15 > tb - 0.3 and (x['t'] - sa) / speed - .15 < tb + 1.0]
            if tb + .7 < (b - a) - .1 and not nxt:
                back = dict(cx=W/2, cy=H/2, s=sFull)
                cam.append(dict(t0=round(tb, 3), dur=.7, **{'from': dict(cur), 'to': back})); cur = back; last_start = tb
    it = dict(type='ui', id=f'u{uiid:02}', start=a, end=b, z=2, W=W, H=H, sFull=sFull, cam0=dict(cx=W/2, cy=H/2, s=sFull), cam=cam, rings=rings,
              dir=f'/out/video/v4/frames/u{uiid:02}', n=round((b - a) * FPS),
              extract=dict(src=str(path.relative_to(ROOT)).replace('\\', '/'), a=sa, b=sb, speed=speed), placeholder=placeholder, clip=clip, scene=sc)
    if seg.get('badge'):
        it['badge'] = dict(text=f"{speed:.0f}× · real time {sb - sa:.0f} s", at=.25, dur=(b - a) - .5)
    uiid += 1
    return it

def place_edl(sc):
    a0, b0, _ = SC[sc]
    a0 = EDL.get('_start', {}).get(str(sc), a0)
    segs = EDL[str(sc)]
    start = a0 + (segs[0].get('lead', 0) if False else 0)
    # durations: fixed natural (speed given) or fit (wait)
    nat = []
    D = (EDL.get('_end', {}).get(str(sc)) or b0) - a0
    for sg in segs:
        path, ph = clip_path(sg['clip']); marks = load_marks(sg['clip'])
        sa = ev_t(marks, sg['a']); sb = ev_t(marks, sg['b'], after=sa)
        sg['_sa'], sg['_sb'] = sa, sb
        nat.append(None if sg.get('fit') else (sb - sa) / sg.get('speed', 1))
    fixed = sum(n for n in nat if n is not None); nfit = sum(1 for n in nat if n is None)
    fit_total = D - fixed
    out = []; t = a0
    for sg, n in zip(segs, nat):
        d = n if n is not None else fit_total / nfit
        if d <= 0.3: raise ValueError(f'scene {sc}: segment too short ({d:.2f}s)')
        it = build_ui(sc, sg, round(t, 4), round(t + d, 4)); out.append(it); t += d
    out[-1]['end'] = a0 + D
    out[-1]['n'] = round((out[-1]['end'] - out[-1]['start']) * FPS)
    return out

UI_SCENES = {}
for sc in sorted(int(k) for k in EDL if k.isdigit()):
    try:
        ui_items = place_edl(sc)
    except Exception as ex:
        if str(sc) not in EDL.get('_fb', {}): raise
        print(f'scene {sc}: CAPTURE clip not usable yet ({ex!r}) -> fallback placeholder')
        EDL[str(sc)] = EDL['_fb'][str(sc)]; ui_items = place_edl(sc)
    UI_SCENES[sc] = ui_items
    for it in ui_items:
        items.append(it)
        sp = it['extract']['speed']
        add_shot(it['start'], it['end'], sc, 'ui', f"{'PLACEHOLDER (PT UI, old capture) ' if it['placeholder'] else ''}UI clip {it['clip']} {it['extract']['a']:.1f}-{it['extract']['b']:.1f}s, camera moves: {len(it['cam'])}, rings: {len(it['rings'])}",
                 speed=f'{sp:.1f}x', purpose=f"scene {sc} live system")
    sp_vo = SC[sc]

# scene 5 callback question (exact LIVE text, EN gloss)
text_item(start=50.3, end=56.3, text='Você disse “perto de um posto”. Qual é a rua, o ponto de referência exato e o município?', size=36, x=96, y=872, ax=0, ay=.5, anim='rise', z=25, cls='body', weight=600)
text_item(start=50.5, end=56.3, text="EN: You said 'near a gas station'. What is the street, the exact landmark and the city?", size=26, x=96, y=922, ax=0, ay=.5, anim='fade', z=25, cls='src', color='#b9c7d6')
# scene 3b overlay chip + desk hit
if 3 in UI_SCENES:
    text_item(start=27.75, end=30.0, html='<span class="chipdot"></span>LIVE · Nemotron via Nightshift', size=40, x=960, y=120, ax=.5, ay=.5, anim='slam', z=25, cls='body')
    flashes.append({'at': 27.6, 'a': .35}); sfx.append({'t': 27.6, 'k': 'hit'})

# ---- Scene 11: agent-team build ----
AG = [('Shift handover', 'Hands open cases to the next crew', '#3BA3FF'), ('Family reunification', 'Matches “have you seen…?” posts to rescues', '#B084FF'),
      ('Shelters & vacancies', 'Tracks every shelter’s free beds', '#2BD47D'), ('Coverage gaps', 'Finds neighbourhoods nobody reached', '#FFB224'),
      ('Volunteer boats', 'Adds private boats to the fleet', '#3BA3FF'), ('Conflicting reports', 'Flags contradictions before dispatch', '#FF8A4D'),
      ('Red team', 'Attacks our own system to harden it', '#FF4D4D')]
agents = []
for i, (n, s, c) in enumerate(AG):
    at = snap(138 + .45 + i * 1.3) - 138; agents.append(dict(name=n, sub=s, c=c, at=at)); sfx.append({'t': 138 + at, 'k': 'boom' if i in (0, 6) else 'hit'})
items.append(dict(type='gfx', name='build', start=138.0, end=150.0, z=3, p=dict(title='The rest of the team', agents=agents)))
flashes.append({'at': 138.0, 'a': .2})
add_shot(138, 150, 11, 'gfx', 'Agent-team build: 7 agent cards snap in on the beat (shift handover, family reunification, shelters & vacancies, coverage gaps, volunteer boats, conflicting reports, red team)',
         vo=SCRIPT['11'], text='7 agent cards', hold='>=3.9s each', purpose='breadth of the agent team (rubric: agents)')

# ---- Scene 12: results ----
items.append(dict(type='gfx', name='results', start=150.0, end=168.0, z=3, p=dict(
    tAB=6.2, tBC=11.8,
    a=dict(kicker='DEVELOPMENT SET · LIVE NEMOTRON', src='30 messages · live run 27 Oct 2026 · before: 19/30 correct, 46.7 s'),
    b=dict(kicker='NEVER-SEEN SETS · BLIND, RUN ONCE', l='34/50', r='29/50', note='When they miss, they ask again.', src='Two 50-message sets the agents had never seen'),
    c=dict(big='0', text='unsafe dispatches on dev &amp; red-team sets', human='A human approves every dispatch', src='Scope: development and red-team sets only'))))
flashes += [{'at': 150.0, 'a': .2}, {'at': 156.2, 'a': .15}, {'at': 161.8, 'a': .25}]
sfx += [{'t': 150.2, 'k': 'boom'}, {'t': 152.3, 'k': 'hit'}, {'t': 156.3, 'k': 'boom'}, {'t': 161.9, 'k': 'boom'}]
for t_, w in ((150, 'DEV 19/30->29/30 · 46.7s->11.3s'), (156.2, 'NEVER-SEEN 34/50 · 29/50'), (161.8, '0 unsafe on dev & red-team sets + human approves')):
    pass
kin += [{'start': 150, 'end': 156, 'text': 'development set live nemotron 29/30 11.3 s'}, {'start': 156.2, 'end': 161.8, 'text': 'never-seen sets 34/50 29/50 when they miss they ask again'}, {'start': 161.8, 'end': 168, 'text': '0 unsafe dev red-team human approves every dispatch'}]
add_shot(150, 156.2, 12, 'gfx', 'Results A: 19/30->29/30 and 46.7 s->11.3 s counters', vo='On our test sets, twenty-nine of thirty right in eleven seconds.', text='19/30 -> 29/30 · 46.7 s -> 11.3 s', hold='4.5s', purpose='proof')
add_shot(156.2, 161.8, 12, 'gfx', 'Results B: never-seen blind sets 34/50 and 29/50', vo="On messages they'd never seen, they still miss more — and when they miss, they ask again.", text='34/50 · 29/50 · When they miss, they ask again.', hold='4.0s', purpose='honesty')
add_shot(161.8, 168, 12, 'gfx', "Results C: '0 unsafe' scoped to dev & red-team sets; a human approves every dispatch", vo='A human approves every dispatch.', text='0 unsafe on dev & red-team sets · A human approves every dispatch', hold='5.0s', purpose='safety')

# ---- Scene 13: close (times from VO words) ----
w13 = words(13)
def wt(ws, word, nth=0):
    c = [w for w in ws if re.sub(r'\W', '', w['w']).lower() == word.lower()]; return c[nth]['a']
t1, t2, t3 = wt(w13, 'Every', 0) - .05, wt(w13, 'Every', 1) - .05, wt(w13, 'When') - .05
tS = round(max(t3 + 3.4, 7.3), 2) if False else None
vo13_end = w13[-1]['b']
tS = vo13_end + .35
items.append(dict(type='gfx', name='close', start=168.0, end=180.0, z=3, p=dict(
    sponsors=['NVIDIA Nemotron', 'Nightshift / Meterless', 'Zetaris'], sponsorLine='BUILT WITH', repo='github.com/LamboKiller/rescue-triage-desk',
    l1='Every request heard.', l2='Every agent working together.', l3='When the next flood comes, no call for help gets lost.',
    t1=round(t1 - 168, 2), t2=round(t2 - 168, 2), t3=round(t3 - 168, 2), tS=round(tS - 168, 2))))
flashes.append({'at': 168.0, 'a': .15}); sfx += [{'t': t1, 'k': 'hit'}, {'t': t2, 'k': 'hit'}, {'t': t3, 'k': 'boom'}, {'t': tS, 'k': 'hit'}]
kin += [{'start': t1, 'end': t3, 'text': 'Every request heard.'}, {'start': t2, 'end': t3, 'text': 'Every agent working together.'}, {'start': t3, 'end': tS, 'text': 'When the next flood comes, no call for help gets lost.'},
        {'start': tS, 'end': 180, 'text': 'BUILT WITH NVIDIA Nemotron Nightshift / Meterless Zetaris github.com/LamboKiller/rescue-triage-desk'}]
add_shot(168, 180, 13, 'gfx', 'Closing: three kinetic lines on VO words, then sponsors (NVIDIA Nemotron · Nightshift/Meterless · Zetaris) + repo', vo=SCRIPT['13'],
         text='closing line; sponsors; github.com/LamboKiller/rescue-triage-desk', hold=f'{180-tS:.1f}s (sponsors)', purpose='close + sponsors')

# ---------------- captions (dedupe vs kinetic) ----------------
caps = []
for sc in SC: caps += chunk_caps(words(sc))
def toks(s): return set(re.sub(r'[^\w ]', '', s.lower()).split())
dropped = []
final = []
for c in caps:
    ct = toks(c['text']); drop = False
    for k in kin:
        if k['start'] < c['end'] and k['end'] > c['start']:
            kt = toks(k['text'])
            if ct and len(ct & kt) / len(ct) >= .6 and len(kt) >= 2: drop = True; break
    (dropped if drop else final).append(c)
caps = final
for i in range(1, len(caps)):
    if caps[i]['start'] < caps[i-1]['end']: caps[i-1]['end'] = caps[i]['start'] - .02

# ---------------- validation (reading time etc.) ----------------
errs = []
for it in items:
    if it['type'] != 'text' or it.get('cls') == 'src': continue
    txt = re.sub('<[^>]+>', ' ', it.get('text') or it.get('html', '')); nw = len([w for w in txt.split() if re.search(r'\w', w)])
    hold = it['end'] - it['start'] - .25 - .25
    need = max(1.2, .28 * nw + .4)
    if hold + 1e-6 < need: errs.append(f"text '{txt[:40]}' hold {hold:.2f} < {need:.2f}")
    if re.search(r'0 unsafe', txt, re.I) and not re.search(r'dev', txt, re.I): errs.append('unsafe scope')
for c in caps:
    if c['end'] - c['start'] < .65: errs.append(f"caption short: {c}")
    if len(c['text'].split()) > 8: errs.append(f"caption long: {c}")
for it in items:
    if it['type'] == 'ui':
        d = it['end'] - it['start']
        if it['extract']['speed'] > 8.01: errs.append(f"{it['id']} speed {it['extract']['speed']:.1f}x > 8")
        if it['extract']['speed'] < .95 and it['extract']['speed'] > 0: pass
        mv = sorted(c['t0'] for c in it['cam'])
        for a_, b_ in zip(mv, mv[1:]):
            if b_ - a_ < 1.99: errs.append(f"{it['id']} camera moves {b_-a_:.2f}s apart")

tl = dict(fps=FPS, width=1920, height=1080, duration=DUR, items=items, captions=caps, flashes=flashes,
          fades=[dict(at=0, dur=.35, to=0), dict(at=179.15, dur=.85, to=1)], beat=dict(p=BEAT_P, ph=BEAT_0))
(V4 / 'timeline_v4.json').write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding='utf-8')
(V4 / 'sfx.json').write_text(json.dumps(sorted(sfx, key=lambda x: x['t']), indent=1), encoding='utf-8')
voice = [dict(scene=sc, start=SC[sc][0] + SC[sc][2], wav=f'out/video/v4/narration/{sc:02}.wav') for sc in SC]
(V4 / 'voice.json').write_text(json.dumps(voice, indent=1), encoding='utf-8')

def srt_t(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f'{h:02}:{m:02}:{int(s):02},{int(round((s - int(s)) * 1000)):03}'
(V4 / 'rtd_demo_v4.srt').write_text('\n'.join(f"{i+1}\n{srt_t(c['start'])} --> {srt_t(c['end'])}\n{c['text']}\n" for i, c in enumerate(caps)), encoding='utf-8')

def mmss(t): return f'{int(t//60)}:{t%60:04.1f}'
rows = ['# TIMELINE v4 (auto-generated by tools/video/v4_timeline.py)', '', '| start-end | sc | kind | on screen | VO | text (hold) | speed | purpose |', '|---|---|---|---|---|---|---|---|']
for s in sorted(shots, key=lambda x: (x['start'], x['kind'])):
    rows.append(f"| {mmss(s['start'])}-{mmss(s['end'])} | {s['scene']} | {s['kind']} | {s['what']} | {s['vo']} | {s['text']} {('('+s['hold']+')') if s['hold'] else ''} | {s['speed']} | {s['purpose']} |")
rows += ['', f'Captions: {len(caps)} (one line, bottom safe area); {len(dropped)} caption chunks suppressed because identical kinetic type is on screen:']
rows += [f"- {mmss(c['start'])} \"{c['text']}\"" for c in dropped]
(V4 / 'TIMELINE.md').write_text('\n'.join(rows), encoding='utf-8')
print('items', len(items), 'captions', len(caps), 'dropped', len(dropped), 'ui', uiid)
print('PLACEHOLDER ui items:', [(i['id'], i['clip'], i['scene']) for i in items if i['type'] == 'ui' and i['placeholder']])
if errs: print('VALIDATION ERRORS:\n' + '\n'.join(errs)); sys.exit(2)
print('validation ok')
