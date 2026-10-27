"""Writes tools/video/v5_edl.json (clips, framings in 2560x1440 source px, masks, overlay callouts, facts)."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
BG, PANEL = '#0d1518', '#151c22'

def card(kicker, title, lines=(), color='#3BA3FF', big=False):
    h = f'<div style="font:700 22px Inter;letter-spacing:.1em;color:{color};text-transform:uppercase">{kicker}</div>'
    if title: h += f'<div style="font:700 {46 if big else 38}px/1.12 InterD,Inter;color:#F5F7FA;margin-top:8px;white-space:normal">{title}</div>'
    for l in lines: h += f'<div style="font:500 28px/1.3 Inter;color:#b9c9d8;margin-top:10px;white-space:normal">{l}</div>'
    return h
def row(icon, text, color, sub=''):
    return f'<div style="display:flex;gap:16px;align-items:baseline;margin-top:12px"><b style="font:800 30px Inter;color:{color};width:30px">{icon}</b><div><div style="font:600 31px/1.2 Inter;color:#F5F7FA">{text}</div>' + (f'<div style="font:500 23px Inter;color:#8fa4b8">{sub}</div>' if sub else '') + '</div></div>'

H4m = [[150, 52, 2320, 60], [956, 552, 176, 52], [1222, 552, 130, 52], [10, 880, 420, 60]]
E = {
 '_photo_credit': 'Photos: Prefeitura de Pelotas / Michel Corvello, Gustavo Vara (public domain) · Wikimedia Commons',
 '_vo17_gap': 1.6,
 '_facts': {
   'hero_msg_pt': 'socorro!! estamos no segundo andar na rua voluntários da pátria 1067, porto alegre, eu, minha mãe acamada e meu filho de 8 anos, a água não para de subir',
   'hero_msg_en': 'help!! we are on the second floor at 1067 Voluntários da Pátria street, Porto Alegre — me, my bedridden mother and my 8-year-old son. The water won’t stop rising.'},
 '_live_scenes': [3, 5, 6, 7, 9, 10, 11],
 '_labels': {s: {'text': 'LIVE · Nemotron via Nightshift'} for s in ('5', '6', '7', '9', '10', '11')},
 '_masks': {
   'H7_dispatch_record': [[0, 1405, 2000, 35, '#10171c'], [2010, 232, 540, 46, PANEL]],
   'H6_fleet_route': [[2010, 205, 540, 52, PANEL]],
   'H9_reroute': [[2008, 226, 548, 66, PANEL]],
   'H10_closed': [[2010, 228, 540, 52, PANEL]],
   'S5_callback': [[2008, 228, 548, 40, PANEL]],
   'H8_boat_supervisor_SIM': [[1428, 4, 236, 32, '#161b1e']],
   'S9b_surge_agents': [[1428, 4, 236, 32, '#161b1e'], [370, 1160, 190, 34, '#10171c'], [780, 1164, 700, 26, '#10171c'], [1005, 1376, 175, 42, BG], [1190, 1376, 150, 42, BG]],
 },
 '3': [dict(clip='H6_fleet_route', a=0.3, b=2.6, fit=True, box=[0, 0, 2000, 1125])],
 '5': [
   dict(clip='H4_message_agents', a=30.1, b=45.1, speed=5.0, box=[16, 230, 1360, 420], masks=H4m),
   dict(clip='H4_message_agents', a=51.6, b=53.9, speed=1.0, box=[150, 200, 560, 260], shift=[260, 40], masks=H4m),
   dict(clip='H4_message_agents', a=62.5, b=64.8, speed=1.0, box=[2017, 600, 527, 160], smax=2.0),
   dict(clip='H4_message_agents', a=55.1, b=57.9, speed=1.0, box=[2125, 205, 420, 70], masks=H4m, rings=[dict(t=0.25, box=[2128, 220, 410, 40])]),
   dict(clip='H4_message_agents', a=63.4, b=67.3, fit=True, box=[0, 200, 420, 160], box2=[0, 200, 420, 130], move_at=.1, move_dur=4.5, shift=[-300, 0]),
 ],
 '6': [
   dict(clip='H6_fleet_route', a=2.4, b=9.9, fit=True, box=[2017, 344, 527, 265], box2=[2017, 520, 527, 100], move_at=2.6, move_dur=.6),
   dict(clip='H6_fleet_route', a=17.6, b=20.2, speed=1.0, box=[760, 560, 1000, 330]),
   dict(clip='H6_fleet_route', a=23.0, b=24.4, speed=1.0, box=[900, 450, 1000, 500]),
   dict(clip='H6_fleet_route', a=28.2, b=31.2, fit=True, box=[420, 99, 1580, 1207], box2=[600, 300, 1300, 731], move_at=.1, move_dur=7.5),
 ],
 '7': [
   dict(clip='H7_dispatch_record', a=2.2, b=8.4, speed=2.8, box=[2017, 470, 527, 360]),
   dict(clip='H7_dispatch_record', a=12.0, b=14.6, speed=1.0, box=[0, 210, 420, 190], shift=[-260, 0]),
   dict(clip='H7_dispatch_record', a=22.4, b=26.4, speed=1.0, box=[2017, 430, 527, 260], smax=2.0),
   dict(clip='H7_dispatch_record', a=26.4, b=28.6, fit=True, box=[2025, 515, 510, 60], smax=2.4),
 ],
 '8': [
   dict(clip='H8_boat_supervisor_SIM', a=3.0, b=7.0, speed=1.0, box=[1000, 30, 1560, 877]),
   dict(clip='H8_boat_supervisor_SIM', a=8.0, b=12.0, fit=True, box=[2088, 330, 460, 440]),
 ],
 '9': [
   dict(clip='H9_reroute', a=1.0, b=3.2, speed=1.0, box=[0, 230, 420, 280], shift=[-260, 0]),
   dict(clip='H9_reroute', a=4.0, b=6.6, speed=1.0, box=[2030, 880, 500, 140]),
   dict(clip='H9_reroute', a=9.5, b=12.5, fit=True, box=[2002, 55, 558, 240]),
 ],
 '10': [dict(clip='H10_closed', a=21.5, b=26.0, fit=True, box=[2002, 55, 558, 180])],
 '11': [
   dict(clip='S5_callback', a=1.0, b=2.7, fit=True, box=[2002, 55, 558, 120]),
   dict(clip='S5_callback', a=2.8, b=5.8, speed=1.0, box=[2017, 1020, 527, 150]),
   dict(clip='S5_callback', a=5.8, b=20.0, speed=7.5, box=[0, 200, 420, 300], shift=[-250, 0]),
   dict(clip='S5_callback', a=47.0, b=56.9, speed=4.0, box=[0, 200, 420, 300], shift=[-250, 0], nodip=True),
   dict(clip='S5_callback', a=56.9, b=59.9, speed=1.0, box=[2002, 55, 558, 340]),
   dict(clip='S5_callback', a=60.0, b=63.8, fit=True, box=[2017, 760, 527, 150]),
 ],
 '12': [
   dict(clip='S9b_surge_agents', a=2.9, b=9.6, fit=True, box=[0, 0, 2560, 1440], push=1.03),
   dict(clip='S9b_surge_agents', a=9.6, b=13.0, speed=1.0, box=[0, 0, 1300, 731], shift=[300, 0]),
   dict(clip='S9b_surge_agents', a=13.0, b=17.5, fit=True, box=[0, 1150, 2200, 290]),
 ],
 '13': [dict(clip='S10_map_3d_photos', a=1.6, b=11.6, fit=True, box=[420, 99, 2092, 1207], box2=[900, 420, 1300, 731], move_at=.2, move_dur=5.5)],
 '_callouts': {
  '5': [
   dict(at='05:Nemotron', end='05:reads+-0.05', items=[dict(x=60, y=150, w=620, html=card('LIVE · real request', 'NVIDIA Nemotron', ['running through Nightshift'], '#76b900'))]),
   dict(at='05:reads', end=5.25, items=[dict(x=60, y=150, w=700, html=card('Intake agent · live call', 'nemotron-3.5-super-vl-120b', ['answered in 5.3 s', 'receipt rcpt_req_7ngfp01b'], '#76b900'))], kin='Intake agent live call nemotron answered in 5.3 s receipt'),
   dict(at=5.35, end='05:finds+-0.1', items=[dict(x=60, y=120, w=760, html=card('Every fact, quoted from her words', '', [], '#FFB224') + row('“', '“minha mãe acamada”', '#FFB224', 'her mother · bedridden') + row('“', '“meu filho de 8 anos”', '#FFB224', 'her son · 8 years old') + row('“', '“a água não para de subir”', '#FFB224', 'the water is still rising'))]),
   dict(at='05:finds', end=10.4, items=[dict(x=60, y=150, w=760, html=card('Location agent → Zetaris', 'Street lookup: “rua voluntários da pátria”', ['2 matches → exact address · Porto Alegre'], '#4554e7'))], kin='Location agent Zetaris street lookup'),
   dict(at=10.5, items=[dict(x=1060, y=520, w=800, html=card('Checked by the other agents', 'P1 — top priority', ['3 people · bedridden → medical queue', 'address verified · a human approves next'], '#2BD47D', True))]),
  ],
  '6': [
   dict(at='06:checks', end='06:route+-0.1', items=[dict(x=60, y=130, w=760, html=card('Fleet agent · every boat on shift', '', ['20 units evaluated against this water'], '#3BA3FF')),
       dict(at='06:finds', x=60, y=330, w=760, css='border-color:#2BD47D', html=row('✓', 'Aluminium boat · 6 seats', '#2BD47D', 'reaches her through this water · 24 min')) ], kin='Fleet agent every boat on shift'),
   dict(at='06:real+-0.25', end="06:water's+-0.2", items=[dict(x=60, y=110, w=640, html=card('Land leg', 'Follows real streets', ['6.7 km by road to the water'], '#2BD47D'))]),
   dict(at="06:water's+-0.15", end='06:then+-0.2', items=[dict(x=60, y=110, w=640, html=card('Launch point', 'At the water’s edge', ['Rua João Moreira Maciel'], '#3BA3FF'))]),
   dict(at='06:then+-0.15', end='06:landing+-0.25', items=[dict(x=60, y=110, w=640, html=card('Water leg · estimated', 'Then 2.2 km by boat', ['straight-line estimate over the flooded blocks'], '#3BA3FF'))], kin='Water leg estimated'),
   dict(at='06:landing+-0.2', items=[dict(x=60, y=110, w=640, html=card('Landing plan', '', [], '#FF8A4D') + row('→', 'Landing · Rua João Moreira Maciel', '#FF8A4D')),
        dict(at='06:ambulance', x=60, y=290, w=640, html=row('✚', 'Ambulance request prepared', '#FF8A4D', 'for 3 people · a human sends it')),
        dict(at='06:shelter', x=60, y=440, w=640, html=row('⌂', 'Shelter · 30 free beds', '#2BD47D', 'Centro Histórico (demo shelter)'))]),
  ],
  '7': [
   dict(at='07:one', end='07:Every+-0.2', items=[dict(x=60, y=150, w=600, html=card('Dispatcher', 'One click: Dispatch', ['after 5 safety checks'], '#FFB224'))]),
   dict(at='07:Every+-0.15', end='07:Meterless+-0.2', items=[dict(x=900, y=170, w=640, html=card('Queue', 'Dispatched · on the way', ['10 seconds to undo'], '#2BD47D'))]),
   dict(at='07:Meterless+-0.15', end='07:nothing+-0.2', items=[dict(x=60, y=150, w=720, html=card('Meterless World Model', 'Every step written to the log', ['agent · model · receipt · what it proposed', 'append-only · can be replayed'], '#B084FF'))], kin='Meterless World Model every step written to the log can be replayed'),
   dict(at='07:nothing', items=[dict(x=60, y=200, w=760, html=card('Human-gated', 'Nothing moves without a human’s command', [], '#FFB224'))], kin='Nothing moves without a human command'),
  ],
  '8': [dict(at=0.5, items=[dict(x=60, y=150, w=720, html=card('Supervisor agent', 'Watches every boat', ['checks the desk every 30 min', 'GPS-signal alert for this boat · closed'], '#B084FF'))])],
  '9': [
   dict(at=0.3, end=2.4, items=[dict(x=900, y=200, w=760, html=card('New emergency nearby', 'Rua Beirute · 2 people', ['P1 — top priority · water rising'], '#ff6b5e'))]),
   dict(at=2.45, end='09:human+-0.2', items=[dict(x=60, y=150, w=720, html=card('Agents propose', 'Add the stop to the same boat', ['extra delay: +0.05 min'], '#3BA3FF'))]),
   dict(at='09:human+-0.15', items=[dict(x=60, y=150, w=640, html=card('A human approves', 'Mission change approved', [], '#2BD47D'))]),
  ],
  '10': [dict(at=0.4, items=[dict(x=60, y=170, w=700, html=card('Crew reports', '“resgatamos 3”', ['“we rescued 3” → case marked rescued'], '#2BD47D', True))])],
  '11': [
   dict(at=0.25, end=1.75, items=[dict(x=60, y=170, w=700, html=card('A vague message', '“…perto de um posto”', ['“…near a gas station” — no street, no number'], '#FFB224'))]),
   dict(at=1.8, end='11:checks+-0.2', items=[dict(x=60, y=130, w=820, css='border-radius:28px 28px 28px 8px;border-color:rgba(255,178,36,.6)', html=card('Callback agent · live question (sent by a person)', 'Você disse “perto de um posto”. Qual é a rua e o município?', ['You said “near a gas station”. What is the street and the city?'], '#FFB224'))]),
   dict(at='11:checks+-0.15', end='17:When+-0.15', items=[dict(x=60, y=130, w=820, css='border-radius:28px 28px 8px 28px;border-color:rgba(37,211,102,.6);background:linear-gradient(160deg,#173326,#0f231a)', html=card('Her reply', 'Rua Voluntários da Pátria, do lado de um posto de gasolina, prédio azul de 3 andares', ['Voluntários da Pátria street, next to a gas station, blue 3-storey building'], '#25D366'))]),
   dict(at='17:When', items=[dict(x=60, y=150, w=700, html=card('The whole team checks again', 'Facts don’t add up', ['street vs “quarto distrito” landmark', '→ Human review required'], '#ff6b5e', True))], kin='Facts don’t add up Human review required'),
  ],
  '12': [dict(at=0.6, items=[dict(x=1180, y=110, w=680, html='<div style="font:700 22px Inter;letter-spacing:.1em;color:#FFB224">SURGE · 60 REQUESTS AT ONCE</div><div style="font:800 96px/1 InterD,Inter;margin-top:10px"><span class="cnt">0</span><span style="font-size:44px;color:#9fb2c6"> accepted in 0.7 s</span></div><div style="font:600 30px Inter;color:#2BD47D;margin-top:12px">all 60 in the queue · none lost</div>' +
        ''.join(f'<div style="display:flex;align-items:center;gap:14px;margin-top:12px"><b style="font:800 24px Inter;width:46px;color:{c}">{p}</b><div style="flex:1;height:18px;background:rgba(255,255,255,.08);border-radius:9px"><div data-bar="{n/35*100:.1f}" style="height:100%;width:0;background:{c};border-radius:9px"></div></div><span style="font:700 26px Inter;width:46px;text-align:right">{n}</span></div>' for p, n, c in (('P1', 35, '#ff5a4d'), ('P2', 17, '#FFB224'), ('P3', 6, '#3BA3FF'), ('P4', 3, '#8fa4b8'))) +
        '<div style="font:500 22px Inter;color:#8fa4b8;margin-top:10px">P1 = top priority · open cases after the surge</div>', count=dict(**{'from': 0, 'to': 60, 'dur': 1.4, 'delay': .2}))], kin='60 accepted in 0.7 s all 60 in the queue none lost')],
 },
}
E['_labels'].update({'8': {'text': 'Simulated GPS · offline replay', 'dot': '#B084FF'}, '12': {'text': 'Offline replay · rules mode, no live model calls', 'dot': '#8fa4b8'}, '13': {'text': 'Offline replay', 'dot': '#8fa4b8'}})
(ROOT / 'tools/video/v5_edl.json').write_text(json.dumps(E, ensure_ascii=False, indent=1), encoding='utf-8')
print('edl ok')
