# Builds deck.html (source), deck.pptx (native, editable text) and speaker_notes.md from ONE element list per slide,
# so the HTML render (PNG/PDF) and the PPTX share every coordinate. Run with python3 (Pillow only for image sizes).
import html, json, zipfile, re
from pathlib import Path
from PIL import Image

D = Path(__file__).resolve().parents[1]
A = D / 'assets'
W, H = 1920, 1080
EMU = 6350  # 12192000 / 1920

INK = '#F5F7FA'; BG = '#0B0F14'; AMBER = '#FFB224'; BLUE = '#3BA3FF'; GREEN = '#2BD47D'; RED = '#FF4D4F'
MUTED = 0.72  # opacity for secondary text
M = 96  # outer margin

# ---------------------------------------------------------------- element helpers
def R(text, size, color=INK, weight=400, alpha=1.0, font='Inter', italic=False):
    return dict(text=text, size=size, color=color, weight=weight, alpha=alpha, font=font, italic=italic)

def P(*runs, align='l', lh=1.15, before=0):
    return dict(runs=list(runs), align=align, lh=lh, before=before)

def T(k, x, y, w, h, *paras, anchor='t'):
    return dict(type='text', k=k, x=x, y=y, w=w, h=h, paras=list(paras), anchor=anchor)

def HEAD(k, text, x=M, y=80, w=W - 2 * M, size=80, color=INK, h=None):
    lines = text.count('\n') + 1
    return T(k, x, y, w, h or round(size * 1.1 * lines + 10), P(R(text, size, color, 700, font='Inter Display'), lh=1.06))

def IMG(k, src, x, y, w, h, frame=False, radius=0):
    return dict(type='img', k=k, src=src, x=x, y=y, w=w, h=h, frame=frame, radius=radius)

def RECT(k, x, y, w, h, fill=None, alpha=1.0, grad=None, line=None, lalpha=1.0, lw=0, radius=0, dash=False):
    return dict(type='rect', k=k, x=x, y=y, w=w, h=h, fill=fill, alpha=alpha, grad=grad, line=line, lalpha=lalpha, lw=lw, radius=radius, dash=dash)

def LINE(k, pts, color=INK, alpha=1.0, w=3, arrow=False, dash=False):
    return dict(type='line', k=k, pts=pts, color=color, alpha=alpha, w=w, arrow=arrow, dash=dash)

def SRC(text):  # one source/credit line bottom-left, 20 px
    return T('source', M, 1022, 1640, 38, P(R(text, 26, INK, 500, 0.92)))

def size_of(rel):
    return Image.open(D / rel).size

def fit(rel, w=None, h=None):
    iw, ih = size_of(rel)
    if w and not h: return w, round(ih * w / iw)
    if h and not w: return round(iw * h / ih), h
    return w, h

PHOTO_BAND = [(0, '#05080C', 0.86), (0.36, '#05080C', 0.62), (0.62, '#05080C', 0.0)]

def photo(k, src):
    return [IMG(k, src, 0, 0, W, H), RECT(k + '_band', 0, 0, W, H, grad=dict(angle=90, stops=PHOTO_BAND))]

slides = []
def slide(title, els, notes, dark=True):
    slides.append(dict(title=title, els=els, notes=notes))

# ---------------------------------------------------------------- copy
HERO_PT = ('socorro!! estamos no segundo andar na rua voluntários da pátria 1067, porto alegre, '
           'eu, minha mãe acamada e meu filho de 8 anos, a água não para de subir')
HERO_PT_LINES = ('socorro!! estamos no segundo andar\nna rua voluntários da pátria 1067,\nporto alegre, eu, minha mãe acamada\n'
                 'e meu filho de 8 anos, a água não\npara de subir')
HERO_EN_LINES = ("help!! we're on the second floor at Voluntários da Pátria\nStreet 1067, Porto Alegre: me, my bedridden mother and\n"
                 "my 8-year-old son. The water won't stop rising.")
CB_PT = 'Você disse “perto de um posto”. Qual é a rua e o município?'
CB_EN = 'You said “near a gas station”. What is the street and the city?'

roster = json.loads((D.parent / 'deck2/agents_roster.json').read_text(encoding='utf8'))
assert len(roster) == 28 and sum(r['kind'] == 'model' for r in roster) == 19
N_MODEL = sum(r['kind'] == 'model' for r in roster); N_LOOP = len(roster) - N_MODEL

FOOT_BAND = [(0, '#05080C', 0.0), (1, '#05080C', 0.85)]
def foot_band(k='foot_band', y=900):
    return RECT(k, 0, y, W, H - y, grad=dict(angle=180, stops=FOOT_BAND))

def chip(k, x, y, w, h, text, size=28, color=INK, fill='#0B0F14', alpha=0.92, line=None, weight=600, tcolor=None):
    return [RECT(k, x, y, w, h, fill=fill, alpha=alpha, line=line, lalpha=0.9 if line else 1.0, lw=2 if line else 0, radius=h // 2 if h < 70 else 14),
            T(k + '_t', x, y + (h - round(size * 1.25)) // 2, w, round(size * 1.3), P(R(text, size, tcolor or color, weight), align='c'))]

def box(k, x, y, w, h, title, sub, color=INK, tsize=44, ssize=28, line=None, fill='#FFFFFF', falpha=0.06, lw=2):
    lines = sub.count('\n') + 1 if sub else 0
    th = round(tsize * 1.2) + (14 + round(ssize * 1.25 * lines) if sub else 0)
    ty = y + (h - th) // 2
    els = [RECT(k, x, y, w, h, fill=fill, alpha=falpha, line=line or INK, lalpha=0.9 if line else 0.35, lw=lw, radius=16),
           T(k + '_t', x, ty, w, round(tsize * 1.25), P(R(title, tsize, color, 700, font='Inter Display'), align='c'))]
    if sub:
        els.append(T(k + '_s', x, ty + round(tsize * 1.2) + 14, w, round(ssize * 1.25 * lines) + 6, P(R(sub, ssize, INK, 500, 0.95), align='c', lh=1.22)))
    return els

# ================================================================= S1 title (photo)
slide('Arca: AI agents for flood rescue', [
    *photo('photo_s1', 'assets/photos/s01_c009.jpg'), foot_band(y=640),
    T('name', M - 14, 330, 1300, 340, P(R('Arca', 300, INK, 700, font='Inter Display'), lh=1.0)),
    T('tagline', M, 680, 1400, 84, P(R('AI agents for flood rescue', 68, AMBER, 700, font='Inter Display'))),
    T('sub', M, 800, 1400, 60, P(R('No call for help should go unheard.', 44, INK, 500, 0.95))),
    T('event', M, 888, 1200, 46, P(R('Team Orbital · Open Agent Hackathon 2026', 34, INK, 500, 0.92))),
    SRC('Photo: rescuers in Laranjal, Pelotas, 10 May 2024 · Michel Corvello / Prefeitura de Pelotas · public domain'),
], """In May 2024 the worst floods in the history of Rio Grande do Sul, in southern Brazil, put whole cities under water. People asked for help any way they could, and many requests were hard to read, hard to locate, or simply lost in the noise. We built Arca, Portuguese for ark: a team of AI agents that reads every request, finds the place, plans the rescue and hands it to a human dispatcher, who approves every boat that leaves. This is a replay of 6 May 2024.""")

# ================================================================= S2 the scale (dark, gauge)
gx, gy, gh, gw = 1120, 230, 660, 200   # Guaíba gauge: 0..6 m mapped to gh px
lvl = lambda m: gy + gh - gh * m / 6.0
slide('185 lives lost', [
    RECT('bg', 0, 0, W, H, fill=BG),
    T('headline', M, 76, 1728, 70, P(R('May 2024: the worst flood in Rio Grande do Sul’s history.', 52, INK, 700, font='Inter Display'))),
    T('hero', M - 12, 140, 1050, 420, P(R('185', 380, AMBER, 700, font='Inter Display'), lh=1.0)),
    T('hero_label', M, 506, 1050, 110, P(R('lives lost', 88, INK, 700, font='Inter Display'))),
    T('stat1', M, 740, 520, 150, P(R('2.4 million', 64, INK, 700, font='Inter Display')), P(R('people affected', 34, INK, 400, 0.9))),
    T('stat2', 620, 740, 520, 150, P(R('478 of 497', 64, INK, 700, font='Inter Display')), P(R('municipalities hit', 34, INK, 400, 0.9))),
    # gauge
    RECT('gauge_base', gx - 20, gy + gh, gw + 40, 4, fill=INK, alpha=0.6),
    RECT('gauge_water', gx, lvl(5.35), gw, gy + gh - lvl(5.35), fill=BLUE, alpha=0.88, radius=10),
    LINE('gauge_2024', [(gx, lvl(5.35)), (gx + gw + 30, lvl(5.35))], BLUE, 1, 5),
    LINE('gauge_1941', [(gx, lvl(4.76)), (gx + gw + 30, lvl(4.76))], INK, 0.95, 5, dash=True),
    T('gauge_2024_l', gx + gw + 40, lvl(5.35) - 104, 360, 130, P(R('May 2024', 32, INK, 400, 0.85)), P(R('5.35 m', 72, BLUE, 700, font='Inter Display'))),
    T('gauge_1941_l', gx + gw + 40, lvl(4.76) + 18, 360, 120, P(R('1941 record', 32, INK, 400, 0.85)), P(R('4.76 m', 56, INK, 700, font='Inter Display'))),
    T('gauge_cap', gx, gy + gh + 22, 640, 100, P(R('Guaíba river, Porto Alegre', 32, INK, 700)), P(R('59 cm above the 1941 record', 32, BLUE, 600), before=4)),
    SRC('Defesa Civil RS (final bulletin, 19 Aug 2025); G1 / Serviço Geológico do Brasil'),
], """The scale first. One hundred and eighty-five people died. Two point four million were affected, in 478 of the state's 497 municipalities. On the right is the Guaíba river at Porto Alegre: it peaked at 5.35 metres, above the 1941 record of 4.76. Whole neighbourhoods stayed under water for weeks, and rescue was done street by street, by boat. Every number on this slide comes from Defesa Civil's final bulletin and the Brazilian Geological Service; sources are in the appendix.""")

# ================================================================= S3 every channel (photo)
slide('Calls came from everywhere', [
    RECT('bg3', 0, 0, W, H, fill='#05080C'), IMG('photo_s3', 'assets/photos/s03_c015.jpg', 760, 0, W - 760, H),
    RECT('scrim', 760, 0, 600, H, grad=dict(angle=90, stops=[(0, '#05080C', 1.0), (0.45, '#05080C', 0.7), (1, '#05080C', 0.0)])),
    foot_band(y=860),
    HEAD('headline', 'Calls came\nfrom everywhere.', y=90, w=1000, size=88),
    T('hero', M - 6, 370, 1000, 205, P(R('77,000+', 164, AMBER, 700, font='Inter Display'), lh=1.0)),
    T('hero_label', M, 572, 900, 70, P(R('people rescued', 60, INK, 700, font='Inter Display'))),
    T('body', M, 700, 1000, 130, P(R('Dozens of WhatsApp groups.\nNo shared picture.', 48, INK, 600), lh=1.2)),
    T('users', M, 850, 1100, 120, P(R('For civil-defence dispatch rooms and', 40, INK, 700)), P(R('volunteer rescue coordinators.', 40, INK, 700))),
    SRC('Defesa Civil RS (30 May 2024); Exame; Agência Lupa · Photo: Laranjal, Pelotas, 10 May 2024 · M. Corvello / Pref. de Pelotas · public domain'),
], """More than 77,000 people were rescued, many by volunteers in their own boats. The requests arrived through dozens of WhatsApp groups, phone calls, social media posts and single texts sent with the last bar of signal. The volunteers were brave and fast; what they lacked was one shared picture of who needed help, where, and how urgently. Arca is built for the municipal Defesa Civil dispatch rooms and the volunteer rescue coordinators who face that flood of requests.""")

# ================================================================= S4 next one (dark)
slide('A strong El Niño is coming again', [
    RECT('bg', 0, 0, W, H, fill=BG),
    HEAD('headline', 'A strong El Niño is coming again.', y=80, size=80),
    T('hero', M - 10, 230, 1100, 380, P(R('83%', 330, AMBER, 700, font='Inter Display'), lh=1.0)),
    T('hero_label', M, 620, 1500, 140, P(R('chance of a strong-to-very-strong El Niño\nthrough early 2027', 56, INK, 600), lh=1.15)),
    RECT('bar_bg', M, 830, 1728, 22, fill='#FFFFFF', alpha=0.10, radius=11),
    RECT('bar', M, 830, round(1728 * 0.83), 22, fill=AMBER, radius=11),
    T('why', M, 890, 1728, 60, P(R('The next flood season will need every call answered, fast.', 40, INK, 500, 0.92))),
    SRC('NOAA Climate Prediction Center, ENSO discussion, 8 Oct 2026'),
], """Why now. NOAA's Climate Prediction Center, in its 8 October 2026 discussion, gives a better-than-83 percent chance of a strong to very strong El Niño through early 2027. El Niño years bring heavy rain to southern Brazil. We cannot say when the next flood comes, but the planning window is short, and the next time requests flood in, the people answering them should not be reading messages one by one with no shared picture.""")

# ================================================================= S5 one call for help
HERO_EN5 = ("“Help!! We’re on the second floor\nat Voluntários da Pátria 1067,\nPorto Alegre: me, my bedridden\nmother and my 8-year-old son.\nThe water won’t stop rising.”")
HERO_PT5 = ('“socorro!! estamos no segundo andar na rua voluntários\nda pátria 1067, porto alegre, eu, minha mãe acamada\ne meu filho de 8 anos, a água não para de subir”')
bx5, by5, bw5, bh5 = M, 230, 900, 720
cx5, cw5 = 1100, 724
slide('One call for help', [
    RECT('bg', 0, 0, W, H, fill=BG),
    HEAD('headline', 'One call for help. The agents read it.', y=80, size=76),
    RECT('bubble', bx5, by5, bw5, bh5, fill='#1F2C34', radius=28),
    T('wa', bx5 + 48, by5 + 40, bw5 - 96, 40, P(R('WhatsApp · 6 May 2024, 12:00 · replay', 28, GREEN, 600))),
    T('msg_en', bx5 + 48, by5 + 104, bw5 - 96, 340, P(R(HERO_EN5, 48, INK, 600), lh=1.25)),
    RECT('rule', bx5 + 48, by5 + 486, bw5 - 96, 2, fill=INK, alpha=0.2),
    T('pt_label', bx5 + 48, by5 + 512, bw5 - 96, 36, P(R('Original, as written:', 28, INK, 600, 0.75))),
    T('msg_pt', bx5 + 48, by5 + 556, bw5 - 96, 130, P(R(HERO_PT5, 29, INK, 400, 0.95), lh=1.32)),
    LINE('arrow', [(bx5 + bw5 + 28, by5 + bh5 // 2), (cx5 - 36, by5 + bh5 // 2)], AMBER, 1, 10, arrow=True),
    # the case card (values from the live capture, redrawn large)
    RECT('card', cx5, by5, cw5, bh5, fill='#FFFFFF', alpha=0.06, line=INK, lalpha=0.25, lw=2, radius=24),
    RECT('card_edge', cx5 + 24, by5 + 40, 8, bh5 - 80, fill=AMBER, radius=4),
    T('card_k', cx5 + 56, by5 + 40, cw5 - 90, 40, P(R('Case card · produced live by the agents', 28, INK, 600, 0.75))),
    T('card_p1', cx5 + 56, by5 + 92, cw5 - 90, 124, P(R('P1', 96, AMBER, 700, font='Inter Display'), R('   medical · top priority', 36, INK, 600))),
    T('card_addr', cx5 + 56, by5 + 230, cw5 - 90, 110, P(R('Voluntários da Pátria 1067', 40, INK, 700)), P(R('✓ address verified in Zetaris', 32, GREEN, 600), before=8)),
    T('card_people', cx5 + 56, by5 + 380, cw5 - 90, 110, P(R('3 people', 40, INK, 700)), P(R('me · bedridden mother · son, 8', 32, INK, 400, 0.95), before=8)),
    T('card_water', cx5 + 56, by5 + 530, cw5 - 90, 110, P(R('Water ≥ 1.2 m', 40, INK, 700)), P(R('→ ready to dispatch, pending a human', 32, AMBER, 600), before=8)),
    SRC('Live capture, English UI (values redrawn for legibility) · the message is a synthetic replay case written for the demo'),
], """Here is one call for help, followed end to end. A woman writes on WhatsApp: socorro, we are on the second floor at Voluntários da Pátria 1067, Porto Alegre, me, my bedridden mother and my 8-year-old son, the water won't stop rising. Our agents read it in Portuguese, as written. They count three people, see that the mother is bedridden, so this is medical and P1, top priority, and they verify the street address in Zetaris. On the right is the case card Arca produced, live.""")

# ================================================================= S6 agents check each other (clean diagram)
ny6, nh6, gap6 = 236, 250, 64
n6 = [('msg', 'Message', 'WhatsApp,\ncall, post', 240), ('intake', 'Intake', 'reads people,\nneeds, risk', 240),
      ('loc', 'Location', 'finds the street\nvia Zetaris', 260)]
els6 = [RECT('bg', 0, 0, W, H, fill=BG), HEAD('headline', 'Agents check each other’s work, live.', y=80, size=76)]
x = M; xc6 = {}
for k, t, s_, w in n6:
    els6 += box('n_' + k, x, ny6, w, nh6, t, s_, tsize=44, ssize=32)
    els6.append(LINE('a_' + k, [(x + w + 6, ny6 + nh6 // 2), (x + w + gap6 - 8, ny6 + nh6 // 2)], INK, 0.9, 6, arrow=True))
    xc6[k] = x + w // 2; x += w + gap6
cw6 = 472
els6.append(RECT('n_check', x, ny6, cw6, nh6, fill=GREEN, alpha=0.08, line=GREEN, lalpha=0.85, lw=3, radius=16))
els6.append(T('n_check_t', x, ny6 + 26, cw6, 50, P(R('Checker agents', 38, GREEN, 700, font='Inter Display'), align='c')))
for i, nm in enumerate(['Critic', 'Credibility', 'Hazard', 'Duplicates']):
    cxx = x + 26 + (i % 2) * 218; cyy = ny6 + 98 + (i // 2) * 72
    els6 += chip('chk_' + nm, cxx, cyy, 202, 58, nm, 30, fill='#FFFFFF', alpha=0.16, line=GREEN)
xck = x + cw6 // 2
els6.append(LINE('a_check', [(x + cw6 + 6, ny6 + nh6 // 2), (x + cw6 + gap6 - 8, ny6 + nh6 // 2)], INK, 0.9, 6, arrow=True))
x += cw6 + gap6
els6 += box('n_human', x, ny6, 1824 - x, nh6, 'Human', 'dispatcher\napproves', color=AMBER, tsize=44, ssize=30, line=AMBER, fill=AMBER, falpha=0.10, lw=3)
# feedback loop: a checker objection sends the message back to Intake
fy6 = ny6 + nh6 + 62
els6 += [LINE('loop6', [(xck, ny6 + nh6 + 2), (xck, fy6), (xc6['intake'], fy6), (xc6['intake'], ny6 + nh6 + 8)], BLUE, 1, 8, arrow=True),
         T('loop6_t', xc6['intake'], fy6 + 26, xck - xc6['intake'], 40, P(R('An objection sends it back: Intake re-reads', 32, BLUE, 700), align='c'))]
ry, rh = 660, 300
els6 += [RECT('rc', M, ry, 1000, rh, fill='#FFFFFF', alpha=0.05, line=INK, lalpha=0.2, lw=1, radius=20),
         T('rc_t', M + 48, ry + 34, 920, 56, P(R('Every model call carries a Nemotron receipt.', 38, INK, 700, font='Inter Display'))),
         RECT('rc_chip', M + 48, ry + 120, 904, 140, fill=GREEN, alpha=0.10, line=GREEN, lalpha=0.8, lw=2, radius=14),
         T('rc_k', M + 84, ry + 142, 200, 110, P(R('MODEL', 28, GREEN, 700)), P(R('RECEIPT', 28, GREEN, 700), before=20)),
         T('rc_v', M + 260, ry + 140, 680, 110, P(R('nvidia/nemotron-3.5-super-vl-120b-a12b', 32, INK, 400, font='mono')), P(R('rcpt_req_7ngfp01b · Intake · 5.3 s', 32, INK, 400, font='mono'), before=14))]
ex6 = M + 1000 + 48; ew6 = 1824 - ex6
els6 += [RECT('ev', ex6, ry, ew6, rh, fill='#FFFFFF', alpha=0.05, line=INK, lalpha=0.2, lw=1, radius=20),
         T('ev_t', ex6 + 44, ry + 34, ew6 - 80, 56, P(R('Each agent quotes its evidence.', 38, INK, 700, font='Inter Display'))),
         T('ev_q', ex6 + 44, ry + 124, ew6 - 80, 70, P(R('“minha mãe acamada”', 52, INK, 700))),
         T('ev_a', ex6 + 44, ry + 212, ew6 - 80, 56, P(R('✓ my mother is bedridden → medical', 36, GREEN, 600)))]
els6.append(SRC('Live run (Oct 2026) on the 6 May 2024 replay · values from the Intake agent’s record · checkers run when a case needs them'))
slide("Agents check each other's work, live", els6,
"""This is how the agents handle that message. Intake reads it, the Location agent finds the street through Zetaris, and checker agents challenge the reading: a critic, a credibility reviewer, a hazard checker and a duplicate reviewer. An objection sends it back and Intake re-reads the message. Only then does a proposal reach a human dispatcher. Every model call carries a Nemotron receipt with model, receipt id and time, and every fact quotes the exact words it came from: minha mãe acamada, my mother is bedridden.""")

# ================================================================= S7 plan + approve (one hero visual)
mw7, mh7 = 1150, 862   # route map crop (H6 live clip, t=12.5 s)
mx7, my7 = M, 200
sc7 = mw7 / 1148
els7 = [RECT('bg', 0, 0, W, H, fill=BG),
        HEAD('headline', 'The agents plan the rescue. A person approves it.', y=80, size=68),
        IMG('route_hero', 'assets/shots/route_hero.png', mx7, my7, mw7, mh7 - 86, frame=True)]
# map callouts (cover the PT launch label with an English chip)
els7 += chip('c_launch', mx7 + 470, my7 + 395, 220, 48, 'Launch point', 28, fill='#0B0F14', alpha=0.95, line=AMBER)
els7 += chip('c_home', mx7 + 220, my7 + 8, 200, 48, 'Her house', 28, fill='#0B0F14', alpha=0.95, line=RED)
els7 += chip('c_boat', mx7 + 300, my7 + 206, 285, 48, 'By boat · estimated', 28, fill='#0B0F14', alpha=0.95, line=BLUE)
els7 += chip('c_road', mx7 + 610, my7 + 642, 170, 48, 'By road', 28, fill='#0B0F14', alpha=0.95, line=GREEN)
els7 += chip('c_dist', mx7 + 24, my7 + mh7 - 86 - 72, 300, 52, '8.9 km · 24 min', 30, fill='#0B0F14', alpha=0.95)
rx7 = mx7 + mw7 + 48; rw7 = 1824 - rx7
els7 += [T('r1', rx7, my7, rw7, 40, P(R('1  The fleet agent picks the boat', 34, INK, 700))),
         RECT('boat', rx7, my7 + 52, rw7, 150, fill='#FFFFFF', alpha=0.06, line=INK, lalpha=0.3, lw=2, radius=18),
         T('boat_t', rx7 + 32, my7 + 72, rw7 - 64, 50, P(R('Aluminium boat', 40, INK, 700, font='Inter Display'))),
         T('boat_s', rx7 + 32, my7 + 132, rw7 - 64, 50, P(R('24 min · 6 seats · 1 trip', 32, INK, 500, 0.9)))]
yb = my7 + 52 + 150 + 40
els7 += [T('r2', rx7, yb, rw7, 40, P(R('2  A person ticks the checks', 34, INK, 700))),
         RECT('chk', rx7, yb + 52, rw7, 130, fill=GREEN, alpha=0.12, line=GREEN, lalpha=0.9, lw=3, radius=18),
         T('chk_t', rx7, yb + 52 + 30, rw7, 70, P(R('✓  5 safety checks', 52, GREEN, 700, font='Inter Display'), align='c'))]
yd = yb + 52 + 130 + 40
els7 += [T('r3', rx7, yd, rw7, 40, P(R('3  Only then: dispatch', 34, INK, 700))),
         RECT('disp', rx7, yd + 52, rw7, 130, fill=AMBER, radius=18),
         T('disp_t', rx7, yd + 52 + 18, rw7, 60, P(R('Dispatch', 52, BG, 700, font='Inter Display'), align='c')),
         T('disp_s', rx7, yd + 52 + 80, rw7, 40, P(R('10 s to undo', 30, BG, 600, 0.85), align='c'))]
els7.append(T('sim', rx7, yd + 52 + 130 + 30, rw7, 80, P(R('Simulated fleet & GPS.\nWater leg is an estimate.', 28, INK, 400, 0.85), lh=1.25)))
els7.append(SRC('Live capture, English UI, 6 May 2024 replay · map labels are local names · © OpenStreetMap contributors · Protomaps · MapLibre'))
slide('The agents plan the rescue. A person approves it.', els7,
"""Then the planning agents take over. The fleet agent checks every boat on shift and finds the one that can reach her: here, a simulated aluminium boat for six, 24 minutes away. Routing plans the road to the water's edge, then the water leg by boat, which is an estimate: 8.9 kilometres in total. Nothing moves until a human dispatcher ticks five safety checks and presses Dispatch, and even then there are ten seconds to undo. When the crew reports resgatamos 3, we rescued 3, the case closes.""")

# ================================================================= S8 team: Read -> Plan -> Watch -> Human + World Model
bw8, gap8, by8, bh8 = 384, 64, 372, 270
blocks8 = [('Read', 'Intake · Location\nCritic · Hazard', INK),
           ('Plan', 'Fleet · Routing\nLanding · Shelter', INK),
           ('Watch', 'Supervisor\nField feedback', INK),
           ('Human', 'approves\nevery boat', AMBER)]
els8 = [RECT('bg', 0, 0, W, H, fill=BG),
        HEAD('headline', 'How the agents work together.', y=72, size=76),
        T('numberline', M, 182, 1728, 50, P(R(f'{len(roster)} agents and loops', 36, AMBER, 700), R(f' · {N_MODEL} model agents + {N_LOOP} operational loops', 36, INK, 400, 0.9)))]
bx8 = lambda i: M + i * (bw8 + gap8)
for i, (t, s, c) in enumerate(blocks8):
    hum = t == 'Human'
    els8 += box('b_' + t, bx8(i), by8, bw8, bh8, t, s, color=c, tsize=60, ssize=34,
                line=AMBER if hum else None, fill=AMBER if hum else '#FFFFFF', falpha=0.10 if hum else 0.06, lw=3 if hum else 2)
    if i < 3:
        els8.append(LINE(f'a{i}', [(bx8(i) + bw8 + 14, by8 + bh8 // 2), (bx8(i + 1) - 16, by8 + bh8 // 2)], INK, 0.9, 6, arrow=True))
# three loops (blue)
lt = by8 - 56
I8 = 96
loops8 = [('l_cb', [(bx8(0) + bw8 - I8, by8 - 4), (bx8(0) + bw8 - I8, lt), (bx8(0) + I8, lt), (bx8(0) + I8, by8 - 9)], 'Callback: ask back, same channel', 0, 0),
          ('l_rr', [(bx8(2) + I8, by8 - 4), (bx8(2) + I8, lt), (bx8(1) + bw8 - I8, lt), (bx8(1) + bw8 - I8, by8 - 9)], 'Reroute on a new P1', 0, 0),
          ('l_sv', [(bx8(2) + bw8 - I8, by8 - 4), (bx8(2) + bw8 - I8, lt), (bx8(3) + I8, lt), (bx8(3) + I8, by8 - 9)], 'Supervisor alerts', 0, 0)]
for k, pts, lab, lx, lw_ in loops8:
    cx8 = (min(p[0] for p in pts) + max(p[0] for p in pts)) // 2
    els8.append(LINE(k, pts, BLUE, 1, 5, arrow=True))
    els8.append(T(k + '_t', (bx8(0) + I8 - 8) if k == 'l_cb' else cx8 - 270, lt - 54, 540, 44, P(R(lab, 32, BLUE, 700), align='l' if k == 'l_cb' else 'c')))
# World Model event log: prominent band, every block writes to it
wy8, wh8 = 730, 220
for i in range(4):
    els8.append(LINE(f'w{i}', [(bx8(i) + bw8 // 2, by8 + bh8 + 14), (bx8(i) + bw8 // 2, wy8 - 20)], '#B48CFF', 1, 5, arrow=True, dash=True))
els8 += [RECT('wm', M, wy8, 1728, wh8, fill='#B48CFF', alpha=0.10, line='#B48CFF', lalpha=0.9, lw=3, radius=20),
         T('wm_k', M + 48, wy8 + 34, 900, 40, P(R('METERLESS WORLD MODEL', 28, '#B48CFF', 700))),
         T('wm_t', M + 48, wy8 + 80, 1100, 70, P(R('One shared event log', 56, INK, 700, font='Inter Display'))),
         T('wm_s', M + 48, wy8 + 152, 1100, 50, P(R('Every agent action recorded and replayable.', 36, INK, 500, 0.95)))]
for i, ev in enumerate(['Intake → Location', 'Location → street lookup', 'Decision → human approval']):
    els8.append(RECT(f'ev{i}', 1150, wy8 + 30 + i * 56, 626, 48, fill='#B48CFF', alpha=0.16, radius=10))
    els8.append(T(f'ev{i}_t', 1176, wy8 + 35 + i * 56, 600, 40, P(R(ev, 32, INK, 500, 0.95))))
els8.append(SRC(f'Counted from the code’s agent roster: {N_MODEL} model agents + {N_LOOP} operational loops · event log entries from the live run'))
slide('How the agents work together', els8,
"""Here is the whole team on one page. 28 agents and loops, 19 of them model agents and 9 operational loops, work in four stages: read, plan, watch, and a human who approves. Three loops keep the picture current: the callback agent asks the citizen one question on the same channel the request came from and re-reads the reply, a new P1 can reroute a boat, and the supervisor keeps alerting until a problem is closed. Underneath, the Meterless World Model keeps one shared event log: every agent action recorded and replayable.""")

# ================================================================= S9 results (owner framing: safety-first, 100 % true)
stats9 = [('29/30', 'live requests\ntriaged correctly', '11 s average', INK),
          ('42/42', 'red-team attacks\nstopped', 'offline attack set', INK),
          ('94/100', 'safe recommendations on\nnever-seen blind requests', 'run once, live', AMBER)]
els9 = [RECT('bg', 0, 0, W, H, fill=BG), HEAD('headline', 'Built safety-first. Tested hard.', y=80, size=80)]
for i, (num, lab, sub, c) in enumerate(stats9):
    x = M + i * (544 + 48)
    els9 += [RECT(f'st{i}', x, 236, 544, 440, fill='#FFFFFF', alpha=0.06, line=c if c == AMBER else INK, lalpha=0.85 if c == AMBER else 0.2, lw=3 if c == AMBER else 2, radius=22),
             T(f'num{i}', x, 272, 544, 170, P(R(num, 140, c, 700, font='Inter Display'), align='c', lh=1.0)),
             T(f'lab{i}', x, 452, 544, 110, P(R(lab, 40, INK, 600), align='c', lh=1.2)),
             T(f'sub{i}', x, 588, 544, 46, P(R(sub, 34, INK, 400, 0.85), align='c'))]
els9 += [RECT('take_bg', M, 720, 1728, 150, fill=AMBER, alpha=0.10, line=AMBER, lalpha=0.8, lw=2, radius=18),
         T('take', M + 48, 748, 1640, 110, P(R('When unsure, the agents ask again instead of guessing —', 40, INK, 700)),
           P(R('and no boat moves without a human.', 40, AMBER, 700), before=6)),
         T('foot9', M, 900, 1728, 100, P(R('Blind sets (never seen, run once live, commit 6ba4233): set A 34/50 correct, set B 29/50 correct, 3 unsafe sends each = 94 of 100 safe.', 24, INK, 400, 0.9)),
           P(R('Dev set is ours: 29/30 live, was 19/30; mean 11.3 s, was 46.7 s. Red team 42/42 offline. The blind gap is our next work.', 24, INK, 400, 0.9), before=6)),
         SRC('Live and offline runs, 27 Oct 2026 · details in the README evaluation table')]
slide('Built safety-first. Tested hard.', els9,
"""We built this safety-first and tested it hard. On live requests the agents triage 29 of 30 correctly, in 11 seconds on average. They stopped all 42 red-team attacks. On 100 never-seen blind requests, run once live, 94 recommendations were safe. To be exact: 34 of 50 and 29 of 50 correct, with 3 unsafe sends in each set, so the blind gap is our next work. When unsure, the agents ask again instead of guessing, and no boat moves without a human.""")

# ================================================================= S10 built on (equal tiles + pipeline strip)
tw10, th10, ty10, gap10 = 544, 440, 300, 48
tiles10 = [('nvidia', 'NVIDIA Nemotron', 'The model behind every\nagent decision'),
           ('meterless', 'Meterless Nightshift\n+ World Model', 'One gateway for every call;\none shared event log'),
           ('zetaris', 'Zetaris', 'Streets, landmarks and\nflood data in one query')]
els10 = [RECT('bg', 0, 0, W, H, fill=BG), HEAD('headline', 'Built on three sponsor technologies.', y=72, size=72),
         T('hook', M, 172, 1728, 110, P(R('Zetaris knows the ground · Nemotron reads and reasons · Nightshift makes every call accountable ·', 34, AMBER, 700)),
           P(R('the World Model makes “no boat without a human” a rule', 34, AMBER, 700), before=6))]
for i, (key, name, line) in enumerate(tiles10):
    x = M + i * (tw10 + gap10)
    els10.append(RECT('tile_' + key, x, ty10, tw10, th10, fill='#FFFFFF', alpha=0.06, line=INK, lalpha=0.22, lw=2, radius=22))
    lb_y, lb_h = ty10 + 32, 150   # equal logo box per tile
    if key == 'nvidia':
        w, h = fit('assets/logos/nvidia_white.png', h=lb_h); els10.append(IMG('logo_nvidia', 'assets/logos/nvidia_white.png', x + (tw10 - w) // 2, lb_y, w, h))
    elif key == 'zetaris':
        w, h = fit('assets/logos/zetaris_white.png', w=380); els10.append(IMG('logo_zetaris', 'assets/logos/zetaris_white.png', x + (tw10 - w) // 2, lb_y + (lb_h - h) // 2, w, h))
    else:
        els10.append(T('logo_meterless', x, lb_y + 50, tw10, 80, P(R('METERLESS', 62, INK, 700, font='Inter Display'), align='c')))
    els10.append(RECT('rule_' + key, x + 48, ty10 + 206, tw10 - 96, 2, fill=INK, alpha=0.18))
    nl = name.count('\n') + 1
    els10.append(T('name_' + key, x, ty10 + 228, tw10, 40 * nl + 10, P(R(name, 34, INK, 700), align='c', lh=1.15)))
    els10.append(T('line_' + key, x, ty10 + 228 + 40 * nl + 22, tw10, 90, P(R(line, 32, INK, 400, 0.9), align='c', lh=1.25)))
# pipeline strip: where each one sits
sy10, sh10 = 846, 120
steps10 = [('Message', None), ('Zetaris\nfinds the place', 'zetaris'), ('Nemotron agents\nvia Nightshift', 'nvidia'), ('World Model\nlogs every step', 'meterless'), ('Human\napproves', 'human')]
sw10 = (1728 - 4 * 52) // 5
for i, (t, key) in enumerate(steps10):
    x = M + i * (sw10 + 52)
    colr = AMBER if key == 'human' else INK
    els10.append(RECT('st_' + str(i), x, sy10, sw10, sh10, fill=colr, alpha=0.12, line=colr, lalpha=0.85, lw=2, radius=14))
    lines = t.count('\n') + 1
    els10.append(T('st_t' + str(i), x, sy10 + (sh10 - round(30 * 1.2 * lines)) // 2, sw10, round(30 * 1.25 * lines), P(R(t, 30, INK, 600), align='c', lh=1.2)))
    if i < 4:
        els10.append(LINE('sa' + str(i), [(x + sw10 + 8, sy10 + sh10 // 2), (x + sw10 + 44, sy10 + sh10 // 2)], INK, 0.95, 6, arrow=True))
els10.append(T('strip_k', M, sy10 - 52, 1728, 44, P(R('Where each one sits in the live pipeline', 32, INK, 700))))
els10.append(SRC('Logos: official brand assets (NVIDIA, Zetaris), shown monochrome · Meterless shown as a wordmark'))
slide('Built on', els10,
"""Three sponsor technologies carry the system. NVIDIA Nemotron is the model behind every agent decision, and every call leaves a receipt we can audit. Meterless Nightshift is the single gateway every agent call goes through, and our event log follows the Meterless World Model: one shared, replayable record of every agent action. Zetaris holds the city: streets, landmarks and flood data, queried in one place, which is how the agents verified Voluntários da Pátria 1067 in the demo.""")

# ================================================================= S11 technical stack
stack = [('Agents', 'nvidia', 'Nemotron via Meterless Nightshift'),
         ('Memory', 'meterless', 'World Model engine · one event log'),
         ('Place & flood', 'zetaris', 'REST · S3 · USL views + OpenStreetMap roads'),
         ('App', None, 'Python standard library · HTTP /run API'),
         ('Ship', None, 'Docker · SAMPLE_MODE: offline, no keys')]
els11 = [RECT('bg', 0, 0, W, H, fill=BG), HEAD('headline', 'A small stack. Every decision replayable.', y=80, size=76)]
for i, (lab, logo, txt) in enumerate(stack):
    lw11 = 1300 + i * 107; lx = (W - lw11) // 2; y = 212 + i * 152
    top = i < 3
    els11 += [RECT(f'sb{i}', lx, y, lw11, 136, fill=AMBER if top else '#FFFFFF', alpha=0.10 + 0.03 * i if top else 0.07,
                   line=AMBER if top else INK, lalpha=0.7 if top else 0.3, lw=2, radius=18),
              T(f'sl{i}', lx + 290, y + 18, 900, 40, P(R(lab.upper(), 28, AMBER, 700))),
              T(f'st{i}', lx + 290, y + 62, lw11 - 330, 56, P(R(txt, 40, INK, 600)))]
    if logo == 'nvidia':
        w_, h_ = fit('assets/logos/nvidia_white.png', h=96); els11.append(IMG('mk_nv', 'assets/logos/nvidia_white.png', lx + 40 + (210 - w_) // 2, y + 20, w_, h_))
    elif logo == 'zetaris':
        w_, h_ = fit('assets/logos/zetaris_white.png', w=200); els11.append(IMG('mk_zt', 'assets/logos/zetaris_white.png', lx + 56, y + (136 - h_) // 2, w_, h_))
    elif logo == 'meterless':
        els11.append(T('mk_ml', lx + 30, y + 46, 240, 44, P(R('METERLESS', 36, INK, 700, font='Inter Display'), align='c')))
    else:
        els11.append(T(f'mk{i}', lx + 30, y + 44, 240, 50, P(R('Python' if lab == 'App' else 'Docker', 38, INK, 700, font='Inter Display'), align='c')))
els11.append(SRC('Architecture and setup: repository README · no keys or tokens are shown or needed for SAMPLE_MODE'))
slide('The technical stack', els11,
"""Under the hood the stack is small on purpose. The agents run on NVIDIA Nemotron, reached through Meterless Nightshift. The Meterless World Model engine keeps one event log of every action. Zetaris serves place and flood data through REST, S3 and USL views, next to an OpenStreetMap road graph. The app itself is a Python standard-library server with an HTTP run API, shipped in Docker, and SAMPLE_MODE runs the whole desk offline with no keys. What is unique: agents cite their receipts, and every decision can be replayed.""")

# ================================================================= S12 what's next
nexts = [('1', 'WhatsApp Business\n+ the 193 line', 'requests flow into the\nsame queue'),
         ('2', 'Live river gauges', 'Guaíba, Jacuí, Taquari\nlevels via Zetaris'),
         ('3', 'Defesa Civil pilot', 'before the next\nEl Niño season')]
els12 = [RECT('bg', 0, 0, W, H, fill=BG), HEAD('headline', 'What comes next.', y=80, size=76)]
for i, (n, t, sub) in enumerate(nexts):
    x = M + i * (544 + 48)
    els12 += [RECT(f'nx{i}', x, 210, 544, 540, fill='#FFFFFF', alpha=0.06, line=INK, lalpha=0.22, lw=2, radius=22),
              T(f'nn{i}', x + 48, 230, 300, 210, P(R(n, 190, AMBER, 700, font='Inter Display'), lh=1.0)),
              T(f'nt{i}', x + 40, 446, 490, 140, P(R(t, 50, INK, 700, font='Inter Display'), lh=1.1)),
              T(f'ns{i}', x + 48, 610, 470, 110, P(R(sub, 38, INK, 400, 0.92), lh=1.22))]
els12 += [RECT('first_bg', M, 790, 1728, 140, fill=AMBER, alpha=0.10, line=AMBER, lalpha=0.8, lw=2, radius=18),
          T('first', M + 48, 828, 1640, 66, P(R('Before any real use: close the gap on never-seen tests.', 48, INK, 700))),
          SRC('Roadmap: repository README · call transcripts are text input today; no speech recognition is built')]
slide('What comes next', els12,
"""What comes next. First, intake where people already ask for help: the WhatsApp Business API and the 193 fire-brigade line, feeding the same queue. Second, live river gauges for the Guaíba, Jacuí and Taquari through Zetaris, replacing retrospective flood layers with observed levels. Third, a Defesa Civil pilot before the next El Niño season: a tabletop exercise on replayed messages, then a supervised pilot. And before any real use, we close the gap on the blind tests.""")

# ================================================================= S11 close (photo)
slide('Every request heard', [
    *photo('photo_s11', 'assets/photos/s11_c027.jpg'),
    RECT('scrim_top', 0, 0, W, 600, grad=dict(angle=180, stops=[(0, '#05080C', 0.95), (0.6, '#05080C', 0.82), (1, '#05080C', 0.0)])),
    HEAD('headline', 'Every request heard.\nEvery agent working together.', y=70, w=1300, size=76),
    T('close2', M, 262, 1300, 140, P(R('When the next flood comes,\nno call for help gets lost.', 52, INK, 600), lh=1.18)),
    RECT('band_fade', 0, 620, W, 160, grad=dict(angle=180, stops=[(0, '#0B0F14', 0.0), (1, '#0B0F14', 0.96)])),
    RECT('band', 0, 780, W, H - 780, fill='#0B0F14', alpha=0.96),
    T('arca', M - 6, 790, 560, 190, P(R('Arca', 170, INK, 700, font='Inter Display'), lh=1.0)),
    RECT('qr_bg', 600, 806, 176, 176, fill='#FFFFFF', radius=10),
    IMG('qr', 'assets/qr_repo.png', 610, 816, 156, 156),
    T('ask', 816, 812, 1008, 50, P(R('Help us pilot it with Defesa Civil before the next El Niño.', 34, AMBER, 700))),
    T('repo', 816, 874, 1008, 46, P(R('github.com/LamboKiller/rescue-triage-desk', 34, INK, 700))),
    T('team', 816, 930, 1008, 40, P(R('Team Orbital · code, evaluations and this deck, open source', 28, INK, 500, 0.9))),
    T('source', 816, 1022, 940, 36, P(R('Photo: Colônia Z-3, Pelotas, 31 May 2024 · G. Vara / Pref. de Pelotas · public domain', 24, INK, 500, 0.85))),
], """Every request heard. Every agent working together. When the next flood comes, no call for help should get lost. Today this is a replay of 6 May 2024 with a simulated fleet and GPS; we do not claim lives saved, only the potential. Our ask is concrete: help us pilot it with Defesa Civil before the next El Niño, with real dispatchers, real channels and real boats, measured honestly. The code, the evaluations and this deck are open at github.com/LamboKiller/rescue-triage-desk.""")

# ================================================================= A1 sources & credits
src_left = ('Numbers\n'
            '185 deaths · 478 of 497 municipalities · 2,398,255 affected\n'
            '   Defesa Civil RS final bulletin, 19 Aug 2025 (sosenchentes.rs.gov.br); IPEA\n'
            'Over 77,000 rescued (77,729 on 30 May 2024)\n'
            '   Defesa Civil RS bulletin, 30 May 2024\n'
            'Guaíba 5.35 m (5 May 2024); 1941 record 4.76 m\n'
            '   G1; Serviço Geológico do Brasil\n'
            'Channels: Exame; Agência Lupa\n'
            '>83 % strong-to-very-strong El Niño, Jan–Mar 2027\n'
            '   NOAA CPC ENSO discussion, 8 Oct 2026\n'
            'Dev 29/30 (was 19/30), 11.3 s (was 46.7 s): live, 27 Oct 2026\n'
            'Red team 42/42: offline attack set\n'
            'Blind A 34/50, 3 unsafe · Blind B 29/50, 3 unsafe (94/100 safe)\n'
            '   live, run once, commit 6ba4233\n'
            '28 agents and loops = 19 model agents + 9 operational loops\n'
            '   agents_roster.json')
src_right = ('Photographs (Wikimedia Commons)\n'
             'S1: Resgates, bairro Laranjal (53712679145)\n'
             '   Michel Corvello / Prefeitura de Pelotas · public domain\n'
             'S3: Resgates, bairro Laranjal (53712420573)\n'
             '   Michel Corvello / Prefeitura de Pelotas · public domain\n'
             'S11: Missão humanitária, Colônia Z-3 (53761203109)\n'
             '   Gustavo Vara / Prefeitura de Pelotas · public domain\n'
             'Full URLs: CREDITS.md\n'
             'Product frames: live captures, English UI\n'
             'Map: © OpenStreetMap contributors · Protomaps · MapLibre\n'
             'Logos: NVIDIA, Zetaris official assets\n'
             'Typeface: Inter (OFL)\n'
             'Team Orbital · all work built during the build window')
def block(k, x, text, w):
    lines = text.split('\n'); paras = [P(R(lines[0], 30, AMBER, 700))]
    for ln in lines[1:]:
        paras.append(P(R(ln.strip(), 24, INK, 400, 0.72 if ln.startswith('   ') else 0.95), lh=1.3, before=0 if ln.startswith('   ') else 14))
    return T(k, x, 230, w, 720, *paras)
slide('Appendix · Sources & credits', [
    RECT('bg', 0, 0, W, H, fill=BG),
    HEAD('headline', 'Appendix · Sources & credits', y=80, size=64),
    block('src_left', src_left, 900) if False else block('src_left', M, src_left, 900),
    block('src_right', 1080, src_right, 744),
    T('honest', M, 1018, 1728, 40, P(R('Replay of 6 May 2024. Fleet and GPS simulated. Lives saved shown only as potential.', 30, AMBER, 700))),
], """Every number in the deck, with its source and date, and every photograph with author and licence; full URLs are in CREDITS.md. The hero message is a synthetic case written for the replay; the product frames are live captures of Arca on 27 October 2026 with real Nemotron calls through Nightshift. The fleet, GPS, shelter and ambulance data are simulated. Development tooling not shown on the slides, such as our red-team generator, is described in the repository.""")

# ================================================================= renderers
def rgba(hexc, a):
    h = hexc.lstrip('#'); return f'rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})'

def html_el(e):
    k = e['k']
    if e['type'] == 'img':
        st = f"left:{e['x']}px;top:{e['y']}px;width:{e['w']}px;height:{e['h']}px"
        cls = 'img frame' if e['frame'] else 'img'
        return f'<img class="{cls}" data-k="{k}" src="{e["src"]}" style="{st}" alt="">'
    if e['type'] == 'rect':
        st = f"left:{e['x']}px;top:{e['y']}px;width:{e['w']}px;height:{e['h']}px;border-radius:{e['radius']}px;"
        if e['grad']:
            g = e['grad']; st += f"background:linear-gradient({g['angle']}deg," + ','.join(f"{rgba(c,a)} {p*100:.0f}%" for p, c, a in g['stops']) + ');'
        elif e['fill']:
            st += f"background:{rgba(e['fill'], e['alpha'])};"
        if e['line']:
            st += f"border:{e['lw']}px {'dashed' if e['dash'] else 'solid'} {rgba(e['line'], e['lalpha'])};box-sizing:border-box;"
        return f'<div class="shape" data-k="{k}" style="{st}"></div>'
    if e['type'] == 'line':
        pts = ' '.join(f'{x},{y}' for x, y in e['pts'])
        mk = f' marker-end="url(#ah_{k})"' if e['arrow'] else ''
        dash = ' stroke-dasharray="14 10"' if e['dash'] else ''
        defs = (f'<defs><marker id="ah_{k}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
                f'<path d="M0,0 L10,5 L0,10 z" fill="{rgba(e["color"], e["alpha"])}"/></marker></defs>') if e['arrow'] else ''
        return (f'<svg class="shape" data-k="{k}" style="left:0;top:0;width:{W}px;height:{H}px;overflow:visible" viewBox="0 0 {W} {H}">{defs}'
                f'<polyline points="{pts}" fill="none" stroke="{rgba(e["color"], e["alpha"])}" stroke-width="{e["w"]}"{dash}{mk} stroke-linejoin="round"/></svg>')
    if e['type'] == 'text':
        st = f"left:{e['x']}px;top:{e['y']}px;width:{e['w']}px;height:{e['h']}px"
        out = []
        for p in e['paras']:
            ps = f"text-align:{dict(l='left', c='center', r='right')[p['align']]};margin-top:{p['before']}px"
            rs = ''
            for r in p['runs']:
                fam = "'Inter Display','Inter',sans-serif" if r['font'] == 'Inter Display' else ("Consolas,'Cascadia Mono','Courier New',monospace" if r['font'] == 'mono' else "'Inter',sans-serif")
                ls = '-0.012em' if r['size'] >= 48 else ('-0.01em' if r['size'] >= 34 else '0')
                rs += (f'<span style="font-family:{fam};font-size:{r["size"]}px;font-weight:{r["weight"]};color:{rgba(r["color"], r["alpha"])};'
                       f'letter-spacing:{ls};line-height:{p["lh"]}">{html.escape(r["text"])}</span>')
            out.append(f'<div class="p" style="{ps};line-height:{p["lh"]}">{rs}</div>')
        return f'<div class="t" data-k="{k}" style="{st}">{"".join(out)}</div>'
    raise ValueError(e)

CSS = """@font-face{font-family:'Inter';src:url(assets/fonts/InterVariable.woff2) format('woff2');font-weight:100 900}
@font-face{font-family:'Inter Display';src:url(assets/fonts/InterDisplay-Bold.ttf) format('truetype');font-weight:700}
*{box-sizing:border-box;margin:0;padding:0}body{background:#000;overflow:hidden;font-family:Inter,sans-serif;-webkit-font-smoothing:antialiased}
#stage{position:absolute;left:50%;top:50%;width:1920px;height:1080px;transform-origin:center}
.slide{display:none;position:absolute;inset:0;width:1920px;height:1080px;overflow:hidden;background:#0B0F14}.slide.active{display:block}
.img,.shape,.t{position:absolute}.img{object-fit:cover;object-position:top}.frame{border:1px solid rgba(255,255,255,.15);border-radius:12px;box-shadow:0 18px 50px rgba(0,0,0,.55)}
.t{white-space:pre;overflow:hidden}.t .p{white-space:pre}.note{display:none}
.pg{position:absolute;right:96px;top:1022px;font-size:26px;line-height:1.15;font-weight:500;color:rgba(245,247,250,.92)}
#notes{display:none;position:fixed;left:0;right:0;bottom:0;max-height:30vh;overflow:auto;background:#000d;color:#fff;padding:18px;font:18px/1.4 Inter}
.shownotes #notes{display:block}
@page{size:1920px 1080px;margin:0}
@media print{body{overflow:visible;background:none}#stage{position:static;transform:none!important}.slide{display:block!important;position:relative;break-after:page;print-color-adjust:exact;-webkit-print-color-adjust:exact}.slide:last-child{break-after:auto}#notes{display:none!important}}"""
JS = """const S=[...document.querySelectorAll('.slide')];let cur=0;
function fitStage(){const s=Math.min(innerWidth/1920,innerHeight/1080);document.getElementById('stage').style.transform=`translate(-50%,-50%) scale(${s})`}
window.goSlide=n=>{cur=Math.max(0,Math.min(S.length-1,n));S.forEach((s,i)=>s.classList.toggle('active',i===cur));document.getElementById('notes').textContent=S[cur].querySelector('.note').textContent;try{localStorage.setItem('rtd_deck_final',cur)}catch(e){};history.replaceState(null,'','#'+(cur+1))};
addEventListener('keydown',e=>{if(['ArrowRight','PageDown',' '].includes(e.key))goSlide(cur+1);else if(['ArrowLeft','PageUp'].includes(e.key))goSlide(cur-1);else if(e.key==='n')document.body.classList.toggle('shownotes');else if(e.key==='f')document.documentElement.requestFullscreen?.()});
addEventListener('resize',fitStage);fitStage();goSlide(location.hash?parseInt(location.hash.slice(1))-1:0);"""

def build_html():
    secs = []
    for i, s in enumerate(slides, 1):
        body = ''.join(html_el(e) for e in s['els'])
        secs.append(f'<section class="slide" id="s{i:02d}" data-title="{html.escape(s["title"])}">{body}'
                    f'<div class="pg">{i:02d}</div><aside class="note">{html.escape(s["notes"])}</aside></section>')
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Arca · pitch deck</title>'
           f'<style>{CSS}</style></head><body><div id="stage">{"".join(secs)}</div><div id="notes"></div><script>{JS}</script></body></html>')
    (D / 'deck.html').write_text(doc, encoding='utf8')

# ---------------------------------------------------------------- PPTX (pure OOXML)
NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
XH = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
RELNS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
def E(v): return str(round(v * EMU))
def xe(s): return html.escape(s, quote=True)
def col(hexc, a=1.0):
    alpha = '' if a >= 0.999 else f'<a:alpha val="{round(a*100000)}"/>'
    return f'<a:srgbClr val="{hexc.lstrip("#").upper()}">{alpha}</a:srgbClr>'
def xfrm(e): return f'<a:xfrm><a:off x="{E(e["x"])}" y="{E(e["y"])}"/><a:ext cx="{E(e["w"])}" cy="{E(e["h"])}"/></a:xfrm>'
def geom(radius, w, h):
    if radius:
        adj = round(radius / min(w, h) * 100000)
        return f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val {adj}"/></a:avLst></a:prstGeom>'
    return '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'

def pptx_slide(s, si, media):
    sid = [2]; rels = [('rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml')]
    def nid(): sid[0] += 1; return sid[0]
    parts = []
    for e in s['els']:
        if e['type'] == 'img':
            src = e['src']
            if src not in media: media[src] = f'image{len(media)+1}{Path(src).suffix.lower()}'
            rid = f'rId{len(rels)+1}'; rels.append((rid, 'image', '../media/' + media[src]))
            # object-fit: cover, top aligned -> srcRect crop
            iw, ih = size_of(src); sc = max(e['w'] / iw, e['h'] / ih)
            cw, chh = e['w'] / sc, e['h'] / sc
            l = (iw - cw) / 2 / iw; r_ = l; t = 0; b = (ih - chh) / ih
            crop = f'<a:srcRect l="{round(l*100000)}" t="{round(t*100000)}" r="{round(r_*100000)}" b="{round(b*100000)}"/>' if (l > 1e-4 or b > 1e-4) else ''
            ln = '<a:ln w="12700"><a:solidFill>' + col('#FFFFFF', 0.15) + '</a:solidFill></a:ln>' if e['frame'] else ''
            eff = ('<a:effectLst><a:outerShdw blurRad="571500" dist="228600" dir="5400000" algn="t" rotWithShape="0">'
                   + col('#000000', 0.55) + '</a:outerShdw></a:effectLst>') if e['frame'] else ''
            g = geom(12 if e['frame'] else e['radius'], e['w'], e['h'])
            parts.append(f'<p:pic><p:nvPicPr><p:cNvPr id="{nid()}" name="{xe(e["k"])}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
                         f'<p:blipFill><a:blip r:embed="{rid}"/>{crop}<a:stretch><a:fillRect/></a:stretch></p:blipFill>'
                         f'<p:spPr>{xfrm(e)}{g}{ln}{eff}</p:spPr></p:pic>')
        elif e['type'] == 'rect':
            if e['grad']:
                g = e['grad']; ang = round(((g['angle'] - 90) % 360) * 60000)
                fill = '<a:gradFill rotWithShape="1"><a:gsLst>' + ''.join(f'<a:gs pos="{round(p*100000)}">{col(c, a)}</a:gs>' for p, c, a in g['stops']) + f'</a:gsLst><a:lin ang="{ang}" scaled="0"/></a:gradFill>'
            elif e['fill']:
                fill = f'<a:solidFill>{col(e["fill"], e["alpha"])}</a:solidFill>'
            else:
                fill = '<a:noFill/>'
            ln = (f'<a:ln w="{round(e["lw"]*EMU)}"><a:solidFill>{col(e["line"], e["lalpha"])}</a:solidFill>' + ('<a:prstDash val="dash"/>' if e['dash'] else '') + '</a:ln>') if e['line'] else '<a:ln><a:noFill/></a:ln>'
            parts.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{nid()}" name="{xe(e["k"])}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>{xfrm(e)}{geom(e["radius"], e["w"], e["h"])}{fill}{ln}</p:spPr></p:sp>')
        elif e['type'] == 'line':
            xs = [p[0] for p in e['pts']]; ys = [p[1] for p in e['pts']]
            x0, y0 = min(xs), min(ys); w = max(max(xs) - x0, 1); h = max(max(ys) - y0, 1)
            path = ''.join((f'<a:moveTo><a:pt x="{E(px_-x0)}" y="{E(py_-y0)}"/></a:moveTo>' if i == 0 else f'<a:lnTo><a:pt x="{E(px_-x0)}" y="{E(py_-y0)}"/></a:lnTo>') for i, (px_, py_) in enumerate(e['pts']))
            tail = '<a:tailEnd type="triangle" w="med" len="med"/>' if e['arrow'] else ''
            dash = '<a:prstDash val="dash"/>' if e['dash'] else ''
            parts.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{nid()}" name="{xe(e["k"])}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>'
                         f'<a:xfrm><a:off x="{E(x0)}" y="{E(y0)}"/><a:ext cx="{E(w)}" cy="{E(h)}"/></a:xfrm>'
                         f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/><a:pathLst><a:path w="{E(w)}" h="{E(h)}" fill="none">{path}</a:path></a:pathLst></a:custGeom>'
                         f'<a:noFill/><a:ln w="{round(e["w"]*EMU)}" cap="rnd"><a:solidFill>{col(e["color"], e["alpha"])}</a:solidFill>{dash}<a:round/>{tail}</a:ln></p:spPr></p:sp>')
        elif e['type'] == 'text':
            ps = ''
            for p in e['paras']:
                algn = dict(l='l', c='ctr', r='r')[p['align']]
                ppr = f'<a:pPr algn="{algn}"><a:lnSpc><a:spcPct val="{round(p["lh"]/1.21*100000)}"/></a:lnSpc><a:spcBef><a:spcPts val="{round(p["before"]*0.75*100)}"/></a:spcBef></a:pPr>'
                runs = ''
                for r in p['runs']:
                    pt = r['size'] * 0.5  # 1920 px slide = 13.333 in -> 1 px = 0.5 pt
                    spc = round(-0.012 * pt * 100) if r['size'] >= 48 else (round(-0.01 * pt * 100) if r['size'] >= 34 else 0)
                    face = 'Inter Display' if r['font'] == 'Inter Display' else 'Consolas' if r['font'] == 'mono' else ('Inter SemiBold' if r['weight'] == 600 else ('Inter Medium' if r['weight'] == 500 else 'Inter'))
                    b = ' b="1"' if r['weight'] >= 700 else ''
                    rpr = f'<a:rPr lang="en-US" sz="{round(pt*100)}"{b} spc="{spc}" dirty="0"><a:solidFill>{col(r["color"], r["alpha"])}</a:solidFill><a:latin typeface="{face}"/><a:cs typeface="{face}"/></a:rPr>'
                    segs = r['text'].split('\n')
                    for j, sgm in enumerate(segs):
                        if j: runs += f'<a:br>{rpr}</a:br>'
                        if sgm: runs += f'<a:r>{rpr}<a:t>{xe(sgm)}</a:t></a:r>'
                ps += f'<a:p>{ppr}{runs}</a:p>'
            anchor = dict(t='t', b='b', c='ctr')[e['anchor']]
            parts.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{nid()}" name="{xe(e["k"])}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>{xfrm(e)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
                         f'<p:txBody><a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}"><a:noAutofit/></a:bodyPr><a:lstStyle/>{ps}</p:txBody></p:sp>')
    # slide number
    parts.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{nid()}" name="slide number"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{E(1744)}" y="{E(1022)}"/><a:ext cx="{E(80)}" cy="{E(38)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
                 f'<p:txBody><a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0"/><a:lstStyle/><a:p><a:pPr algn="r"/><a:r><a:rPr lang="en-US" sz="1300"><a:solidFill>{col(INK, 0.92)}</a:solidFill><a:latin typeface="Inter"/></a:rPr><a:t>{si:02d}</a:t></a:r></a:p></p:txBody></p:sp>')
    grp = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
           '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')
    xml = (XH + f'<p:sld {NS}><p:cSld><p:bg><p:bgPr><a:solidFill>{col(BG)}</a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>{grp}{"".join(parts)}</p:spTree></p:cSld>'
           '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
    return xml, rels

def relsxml(items):
    return XH + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(
        f'<Relationship Id="{i}" Type="{RELNS}/{t}" Target="{g}"/>' for i, t, g in items) + '</Relationships>'

def build_pptx():
    grp = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
           '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')
    clrmap = ('<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" '
              'accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>')
    theme = (XH + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="RTD"><a:themeElements><a:clrScheme name="RTD">'
             '<a:dk1><a:srgbClr val="0B0F14"/></a:dk1><a:lt1><a:srgbClr val="F5F7FA"/></a:lt1><a:dk2><a:srgbClr val="0B0F14"/></a:dk2><a:lt2><a:srgbClr val="F5F7FA"/></a:lt2>'
             '<a:accent1><a:srgbClr val="FFB224"/></a:accent1><a:accent2><a:srgbClr val="3BA3FF"/></a:accent2><a:accent3><a:srgbClr val="2BD47D"/></a:accent3>'
             '<a:accent4><a:srgbClr val="FF4D4F"/></a:accent4><a:accent5><a:srgbClr val="8A96A3"/></a:accent5><a:accent6><a:srgbClr val="C9D3DE"/></a:accent6>'
             '<a:hlink><a:srgbClr val="FFB224"/></a:hlink><a:folHlink><a:srgbClr val="C9D3DE"/></a:folHlink></a:clrScheme>'
             '<a:fontScheme name="Inter"><a:majorFont><a:latin typeface="Inter Display"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
             '<a:minorFont><a:latin typeface="Inter"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
             '<a:fmtScheme name="m"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
             '<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
             '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
             '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
    master = (XH + f'<p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="0B0F14"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>{grp}</p:spTree></p:cSld>{clrmap}'
              '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>')
    layout = XH + f'<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{grp}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    nmaster = (XH + f'<p:notesMaster {NS}><p:cSld><p:spTree>{grp}<p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
               '<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="4400550"/><a:ext cx="5486400" cy="3600450"/></a:xfrm>'
               f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp></p:spTree></p:cSld>{clrmap}</p:notesMaster>')
    def nslide(text):
        return (XH + f'<p:notes {NS}><p:cSld><p:spTree>{grp}<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
                '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp><p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
                f'<p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/><a:t>{xe(text)}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>'
                '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')
    N = len(slides); media = {}; built = []
    for i, s in enumerate(slides, 1):
        built.append(pptx_slide(s, i, media))
    ct = (XH + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Default Extension="jpg" ContentType="image/jpeg"/>'
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
          '<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"/>'
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          '<Override PartName="/ppt/theme/theme2.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
          '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>')
    for i in range(1, N + 1):
        ct += (f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
               f'<Override PartName="/ppt/notesSlides/notesSlide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>')
    ct += '</Types>'
    pres = (XH + f'<p:presentation {NS} saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            '<p:notesMasterIdLst><p:notesMasterId r:id="rId2"/></p:notesMasterIdLst><p:sldIdLst>'
            + ''.join(f'<p:sldId id="{255+i}" r:id="rId{3+i}"/>' for i in range(1, N + 1)) +
            '</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    prels = [('rId1', 'slideMaster', 'slideMasters/slideMaster1.xml'), ('rId2', 'notesMaster', 'notesMasters/notesMaster1.xml'),
             ('rId3', 'theme', 'theme/theme1.xml')] + [(f'rId{3+i}', 'slide', f'slides/slide{i}.xml') for i in range(1, N + 1)]
    core = (XH + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>Arca</dc:title><dc:creator>Arca team</dc:creator></cp:coreProperties>')
    app = (XH + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Arca deck builder</Application>'
           f'<Slides>{N}</Slides><Notes>{N}</Notes></Properties>')
    out = D / 'deck.pptx'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', relsxml([('rId1', 'officeDocument', 'ppt/presentation.xml')]).replace(
            '</Relationships>', '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>'))
        z.writestr('docProps/core.xml', core); z.writestr('docProps/app.xml', app)
        z.writestr('ppt/presentation.xml', pres)
        z.writestr('ppt/_rels/presentation.xml.rels', relsxml(prels))
        z.writestr('ppt/slideMasters/slideMaster1.xml', master)
        z.writestr('ppt/slideMasters/_rels/slideMaster1.xml.rels', relsxml([('rId1', 'slideLayout', '../slideLayouts/slideLayout1.xml'), ('rId2', 'theme', '../theme/theme1.xml')]))
        z.writestr('ppt/slideLayouts/slideLayout1.xml', layout)
        z.writestr('ppt/slideLayouts/_rels/slideLayout1.xml.rels', relsxml([('rId1', 'slideMaster', '../slideMasters/slideMaster1.xml')]))
        z.writestr('ppt/notesMasters/notesMaster1.xml', nmaster)
        z.writestr('ppt/notesMasters/_rels/notesMaster1.xml.rels', relsxml([('rId1', 'theme', '../theme/theme2.xml')]))
        z.writestr('ppt/theme/theme1.xml', theme); z.writestr('ppt/theme/theme2.xml', theme)
        for i, (xml, rels) in enumerate(built, 1):
            rels = rels + [(f'rId{len(rels)+1}', 'notesSlide', f'../notesSlides/notesSlide{i}.xml')]
            z.writestr(f'ppt/slides/slide{i}.xml', xml)
            z.writestr(f'ppt/slides/_rels/slide{i}.xml.rels', relsxml(rels))
            z.writestr(f'ppt/notesSlides/notesSlide{i}.xml', nslide(slides[i-1]['notes']))
            z.writestr(f'ppt/notesSlides/_rels/notesSlide{i}.xml.rels', relsxml([('rId1', 'notesMaster', '../notesMasters/notesMaster1.xml'), ('rId2', 'slide', f'../slides/slide{i}.xml')]))
        for src, name in media.items():
            z.write(D / src, 'ppt/media/' + name)
    return out

def build_notes():
    md = '# Arca — speaker notes\n\n'
    for i, s in enumerate(slides, 1):
        md += f'## Slide {i:02d} — {s["title"]}\n\n{s["notes"]}\n\n'
        if s['title'] == 'How the agents work together':
            md += 'Full roster (counted from agents_roster.json; 19 model agents + 9 operational loops):\n\n'
            for r in roster:
                kind = 'model agent' if r['kind'] == 'model' else 'operational loop'
                extra = ' (development tooling; not on the slides)' if r['name'] in ('Red team', 'Red-team judge') else ''
                md += f'- **{r["name"]}** ({kind}): {r["job"]}{extra}\n'
            md += '\n'
    (D / 'speaker_notes.md').write_text(md, encoding='utf8')

if __name__ == '__main__':
    assert len(slides) == 14, len(slides)
    for s in slides:
        n = len(s['notes'].split()); assert 55 <= n <= 95, (s['title'], n)
    build_html(); out = build_pptx(); build_notes()
    print('slides', len(slides), 'pptx', out.stat().st_size)
