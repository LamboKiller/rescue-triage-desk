"""Shared engine for the scripted 8-message demo (tools/demo_run.py, tools/demo_check.py, tests/test_demo.py).

The scenario file (data/demo/scenario.jsonl) holds INPUTS (citizen messages, timed operator/crew actions, scripted
[SIMULADO] replies) plus the EXPECTED outcome of every step. Nothing the desk decides is written into the inputs: the
runner posts them to a running desk over HTTP and the checker compares what the desk did with `expect`.
No model is called from here: --offline runs against the sample server (deterministic fake pipeline); --live talks to
a desk that Orbit started against Nightshift.
"""
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT/'data'/'demo'/'scenario.jsonl'
STATE = ROOT/'runtime'/'demo_state.json'
ACTOR = 'operador (demo)'
CREW = 'equipe (demo)'
OPS = ('confirm_location', 'request_callback', 'citizen_reply', 'approve_mission', 'gps_sim', 'shelter_register', 'shelter_report',
       'landing_choose', 'landing_report', 'crew_report', 'volunteer_verify')
EXPECT_KEYS = {'decision_in', 'priority_min', 'position_kind', 'duplicate_of_step', 'decision_after_in', 'status_in', 'mission',
               'route_water_leg', 'landing', 'shelter_vacancy', 'volunteer', 'fleet_has_volunteer', 'reroute', 'medical',
               'no_new_mission', 'gps', 'not_dispatchable', 'callback_open'}
MESSAGE_KEYS = {'id', 'text', 'channel'}
STEP_KEYS = {'type', 'step', 'title', 't', 'message', 'actions', 'expect', 'say', 'screen'}
HEAD_KEYS = {'type', 'name', 'replay_day', 'start', 'synthetic', 'version', 'note'}
DECISIONS = ('SEND_CANDIDATE', 'CALLBACK', 'REVIEW_REQUIRED', 'NO_ACTION', 'DUPLICATE')
PHONE = re.compile(r'\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b')


class ScenarioError(ValueError):
    pass


# ---- scenario -------------------------------------------------------------------------------------------------
def load(path=None):
    rows = []
    for number, line in enumerate(Path(path or SCENARIO).read_text(encoding='utf-8-sig').splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise ScenarioError(f'linha {number}: JSON inválido ({exc})')
    return validate(rows)


def validate(rows):
    if not rows or rows[0].get('type') != 'scenario':
        raise ScenarioError('primeira linha deve ser o cabeçalho (type=scenario)')
    head = rows[0]
    if set(head)-HEAD_KEYS:
        raise ScenarioError('chaves no cabeçalho: '+', '.join(sorted(set(head)-HEAD_KEYS)))
    if head.get('synthetic') is not True or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(head.get('replay_day'))):
        raise ScenarioError('cabeçalho exige synthetic=true e replay_day AAAA-MM-DD')
    steps = [r for r in rows[1:]]
    if [s.get('step') for s in steps] != list(range(1, len(steps)+1)):
        raise ScenarioError('passos devem ser 1..N em ordem')
    ids, last = set(), '00:00'
    for s in steps:
        if s.get('type') != 'step' or set(s)-STEP_KEYS:
            raise ScenarioError(f"passo {s.get('step')}: tipo/chaves inválidos {sorted(set(s)-STEP_KEYS)}")
        if not re.fullmatch(r'\d{2}:\d{2}', str(s.get('t'))) or s['t'] < last:
            raise ScenarioError(f"passo {s['step']}: horário t ausente ou fora de ordem")
        last = s['t']
        if not isinstance(s.get('expect'), dict) or not s['expect'] or set(s['expect'])-EXPECT_KEYS:
            raise ScenarioError(f"passo {s['step']}: expect ausente ou com chaves desconhecidas {sorted(set(s.get('expect') or {})-EXPECT_KEYS)}")
        msg = s.get('message')
        if msg is not None:
            if set(msg) - MESSAGE_KEYS or not str(msg.get('text', '')).strip() or msg.get('id') in ids:
                raise ScenarioError(f"passo {s['step']}: mensagem inválida ou id repetido")
            ids.add(msg['id'])
            if PHONE.search(msg['text']) and not re.search(r'\b51 9\d{4}-0000\b', msg['text']):
                raise ScenarioError(f"passo {s['step']}: telefone fora do padrão 51 9XXXX-0000")
        elif s['step'] == 1:
            raise ScenarioError('passo 1 precisa de mensagem')
        last_at = s['t']
        for action in s.get('actions', []):
            if action.get('op') not in OPS:
                raise ScenarioError(f"passo {s['step']}: operação desconhecida {action.get('op')!r}")
            if action.get('at') is not None:
                if not re.fullmatch(r'\d{2}:\d{2}', str(action['at'])) or action['at'] < last_at:
                    raise ScenarioError(f"passo {s['step']}: horário da ação fora de ordem")
                last_at = action['at']
            if action.get('ref') is not None and not (type(action['ref']) is int and 1 <= action['ref'] <= s['step']):
                raise ScenarioError(f"passo {s['step']}: ref deve ser um passo anterior")
            if 'decision' in action:
                raise ScenarioError(f"passo {s['step']}: ação não pode trazer decisão")
        for d in s['expect'].get('decision_in', []):
            if d not in DECISIONS:
                raise ScenarioError(f"passo {s['step']}: decisão esperada desconhecida {d!r}")
    return {'meta': head, 'steps': steps}


# ---- HTTP -----------------------------------------------------------------------------------------------------
class Desk:
    def __init__(self, base):
        self.base = base.rstrip('/')

    def call(self, method, path, body=None, timeout=300):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base+path, data=data, method=method, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b'{}')
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read() or b'{}')
            except ValueError:
                payload = {}
            return exc.code, payload

    def get(self, path):
        return self.call('GET', path)

    def post(self, path, body):
        return self.call('POST', path, body)

    def health(self):
        return self.get('/api/health')[1]


def iso(day, hhmm, seconds=0):
    return f'{day}T{hhmm}:{seconds:02d}-03:00'


# ---- state ----------------------------------------------------------------------------------------------------
def save_state(state, path=None):
    path = Path(path or STATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')


def load_state(path=None):
    path = Path(path or STATE)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'steps': {}}


# ---- runner ---------------------------------------------------------------------------------------------------
class Runner:
    """Posts one scenario step at a time. Every call result is kept in `log` so failures are visible, never swallowed."""
    def __init__(self, desk, scenario, *, sleep=time.sleep, say=print):
        self.desk, self.scenario, self.sleep, self.say = desk, scenario, sleep, say
        self.day = scenario['meta']['replay_day']
        self.state = {'day': self.day, 'steps': {}, 'base': desk.base}

    def case(self, step):
        cid = self.state['steps'][str(step)].get('case_id')
        status, body = self.desk.get('/api/cases/'+cid)
        if status != 200:
            raise RuntimeError(f'passo {step}: caso {cid} indisponível ({status})')
        return body

    def log(self, step, what, status, body=None, ok=None):
        entry = {'what': what, 'http': status, 'ok': (200 <= status < 300) if ok is None else ok}
        if not entry['ok']:
            entry['error'] = str((body or {}).get('error', ''))[:240]
        self.state['steps'][str(step)].setdefault('log', []).append(entry)
        return entry['ok']

    def run_step(self, step):
        n = step['step']
        rec = self.state['steps'].setdefault(str(n), {'title': step['title'], 'log': []})
        message = step.get('message')
        if message:
            stamp = iso(self.day, step['t'])
            status, body = self.desk.post('/run', {'replay_time': stamp, 'messages': [{'message_id': 'demo-'+message['id'], 'text': message['text'],
                                                                                         'received_at': stamp, 'synthetic': True}]})
            ok = self.log(n, 'mensagem enviada ao pipeline', status, body)
            if ok and body.get('cases'):
                case = body['cases'][0]
                r = case.get('result', {})
                rec.update(case_id=case['case_id'], message_id='demo-'+message['id'],
                           intake={'decision': r.get('decision'), 'priority': r.get('priority'), 'route': (case.get('route') or {}).get('id'),
                                   'position_kind': (case.get('position') or {}).get('position_kind'), 'duplicates': len(case.get('duplicates') or [])})
        for action in step.get('actions', []):
            if action.get('delay_s'):
                self.sleep(action['delay_s'])
            try:
                getattr(self, 'op_'+action['op'])(n, step, action)
            except Exception as exc:  # visible in the log and in demo_check; the run continues with the next action
                self.log(n, action['op'], 0, {'error': f'{type(exc).__name__}: {exc}'}, ok=False)
        save_state(self.state)
        return rec

    def target(self, n, action):
        return action.get('ref') or n

    def stamp(self, step, action):
        return iso(self.day, action.get('at') or step['t'], 30 if not action.get('at') else 0)

    # -- operator / crew operations (the same HTTP routes the screens use) -------------------------------------
    def simple_action(self, n, step, action, name):
        ref = self.target(n, action)
        c = self.case(ref)
        status, body = self.desk.post(f"/api/cases/{c['case_id']}/actions", {'action': name, 'expected_version': c['version'], 'actor': ACTOR})
        self.log(n, f'{name} (passo {ref})', status, body)

    def op_confirm_location(self, n, step, action):
        self.simple_action(n, step, action, 'confirm_location')

    def op_request_callback(self, n, step, action):
        self.simple_action(n, step, action, 'request_callback')

    def op_citizen_reply(self, n, step, action):
        ref = self.target(n, action)
        c = self.case(ref)
        text = '[SIMULADO] '+action['text']
        status, body = self.desk.post(f"/api/cases/{c['case_id']}/callback/reply",
                                      {'text': text, 'received_at': self.stamp(step, action), 'expected_version': c['version']})
        if self.log(n, f'resposta [SIMULADO] do cidadão (passo {ref})', status, body):
            if 'diff' not in body:  # accept-and-queue: the re-triage runs in the background; wait for the new version
                deadline = time.monotonic()+60
                while time.monotonic() < deadline:
                    now = self.case(ref)
                    if now['version'] > c['version']:
                        break
                    time.sleep(0.2)
                body = {'diff': {'decision': {'after': now['result']['decision']}}}
            self.state['steps'][str(ref)]['decision_after_reply'] = body['diff']['decision']['after']

    def op_approve_mission(self, n, step, action):
        ref = self.target(n, action)
        c = self.case(ref)
        day, rec = self.day, self.state['steps'][str(ref)]
        status, body = self.desk.get(f"/api/cases/{c['case_id']}/assets?date={day}")
        if not self.log(n, 'meios disponíveis (Qual meio enviar)', status, body):
            return
        row = next((r for r in body['top3'] if r['id'] == action['unit']), None)
        if row is None:
            return self.log(n, f"unidade {action['unit']} não está no top-3", 409, {'error': 'unidade fora do top-3'})
        rec['asset_options'] = [r['id'] for r in body['top3']]
        if row['approval_blockers']:
            return self.log(n, 'aprovação bloqueada', 409, {'error': '; '.join(row['approval_blockers'])[:200]})
        status, mission = self.desk.post('/api/missions', {
            'proposal_id': row['proposal_id'], 'expected_versions': row['expected_versions'], 'actor': ACTOR, 'caution_acknowledged': True,
            'override_reason': 'Meio com a capacidade e o equipamento exigidos pelo caso (demo).' if row['rank'] > 1 else '',
            'received_at': self.stamp(step, action),
            'checklist_confirmations': {x['code']: True for x in row['confirmation_checklist']}})
        if self.log(n, f"missão aprovada com {action['unit']} (humano)", status, mission):
            rec.update(mission_id=mission.get('mission_id'), unit_id=action['unit'], mission_people=mission.get('people'), mission_status=mission.get('status'))
            if action.get('route', True):
                s2, route = self.desk.get(f"/api/cases/{c['case_id']}/route?unit={action['unit']}&date={day}")
                rec['route'] = {'http': s2, 'land': bool((route.get('land') or {}).get('reachable')) if isinstance(route, dict) else False,
                                'water_leg': bool(route.get('water')) if isinstance(route, dict) else False,
                                'keys': sorted(route)[:12] if isinstance(route, dict) else []}

    def op_gps_sim(self, n, step, action):
        """[SIMULADO] GPS: binds sim:<unit> (explicit operator action) and posts accelerated fixes along the planned route."""
        ref = self.target(n, action)
        rec = self.state['steps'][str(ref)]
        unit = rec.get('unit_id')
        if not unit:
            return self.log(n, 'GPS simulado', 409, {'error': 'sem missão aprovada para mover'})
        device = 'sim:'+unit
        status, body = self.desk.post('/api/telemetry/bindings', {'device': device, 'unit_id': unit, 'actor': ACTOR})
        self.log(n, f'vínculo {device} (operador)', status, body)
        status, missions = self.desk.get('/api/telemetry/missions')
        if status != 200:
            return self.log(n, 'rota para o GPS simulado', status, missions)
        mission = next((m for m in missions['missions'] if m['unit_id'] == unit and (m.get('segments') or m.get('proven_prefix_segments'))), None)
        if mission is None:
            return self.log(n, 'rota para o GPS simulado', 404, {'error': 'missão sem segmentos de rota'})
        points = []
        # Full tracked route if proven; else only the proven prefix (land) — the sim stops where proven geometry ends.
        for seg in (mission.get('segments') or mission.get('proven_prefix_segments') or []):
            points += seg['polyline']
        count = int(action.get('fixes', 6))
        sent = accepted = 0
        now = time.time()
        for i in range(count):
            idx = min(len(points)-1, round(i*(len(points)-1)/max(1, count-1)))
            lon, lat = points[idx]
            q = f'id={device}&lat={lat:.6f}&lon={lon:.6f}&timestamp={now-(count-i)*3:.0f}&speed=4&bearing=0&accuracy=10&source=simulated'
            s2, r = self.desk.call('GET', '/api/telemetry/osmand?'+q)
            sent += 1
            accepted += s2 == 200 and r.get('status') in ('accepted', 'ok', 'trusted')
            self.sleep(float(action.get('pause_s', 0.2)))
        rec['gps'] = {'sent': sent, 'accepted': accepted}
        self.log(n, f'[SIMULADO] GPS: {sent} posições enviadas', 200, {})

    def op_shelter_register(self, n, step, action):
        status, body = self.desk.post('/api/shelters/reports', {'kind': 'register', 'name': action['name'], 'lat': action['lat'], 'lon': action['lon'],
                                                               'municipality': action.get('municipality', ''), 'actor': ACTOR, 'source': 'operator',
                                                               'at': self.stamp(step, action), 'quote': '[SIMULADO] abrigo cadastrado para a demonstração'})
        if self.log(n, f"abrigo cadastrado: {action['name']}", status, body):
            self.state['shelter_id'] = body['recorded'][0]['shelter_id']

    def op_shelter_report(self, n, step, action):
        status, body = self.desk.post('/api/shelters/reports', {'text': action['text'], 'shelter_id': self.state.get('shelter_id'), 'actor': ACTOR,
                                                               'source': 'operator', 'at': self.stamp(step, action)})
        self.log(n, 'relato de vagas', status, body, ok=status == 200 and bool(body.get('recorded')))

    def op_landing_choose(self, n, step, action):
        ref = self.target(n, action)
        c = self.case(ref)
        at = self.stamp(step, action)
        status, plan = self.desk.get(f"/api/cases/{c['case_id']}/landing?date={at}")
        if not self.log(n, 'plano de desembarque', status, plan):
            return
        options = plan.get('options') or []
        rec = self.state['steps'][str(ref)]
        rec['landing'] = {'options': len(options), 'with_shelter': sum(1 for o in options if o.get('shelters')),
                          'top_shelter_remaining': next(((o['shelters'][0] or {}).get('remaining') for o in options if o.get('shelters')), None)}
        if not options:
            return self.log(n, 'desembarque', 409, {'error': 'nenhuma opção de desembarque'})
        top = next((o for o in options if o.get('shelters')), options[0])
        body = {'landing_id': top['landing_id'], 'shelter_id': top['shelters'][0]['shelter_id'] if top.get('shelters') else None,
                'actor': ACTOR, 'at': at}
        if top['rank'] != 1:
            body['override_reason'] = 'Ponto com abrigo com vagas relatadas (demo).'
        status, chosen = self.desk.post(f"/api/cases/{c['case_id']}/landing/choice", body)
        if self.log(n, f"desembarque escolhido pelo operador: {top['label'][:60]}", status, chosen):
            rec['landing'].update(landing_id=top['landing_id'], shelter_id=body['shelter_id'])
            handoff = plan.get('handoff') or {}
            rec['landing']['ambulance_note'] = bool(re.search(r'ambul', json.dumps(plan, ensure_ascii=False), re.I))

    def op_landing_report(self, n, step, action):
        ref = self.target(n, action)
        landing_id = self.state['steps'][str(ref)].get('landing', {}).get('landing_id')
        if not landing_id:
            return self.log(n, 'relato no ponto', 409, {'error': 'sem ponto escolhido'})
        body = {'actor': CREW, 'source': 'crew', 'at': self.stamp(step, action)}
        if action.get('people'):
            body['people'] = action['people']
        status, out = self.desk.post(f"/api/landing/{landing_id}/{action['kind']}", body)
        self.log(n, f"ponto de desembarque: {action['kind']}", status, out)

    def op_crew_report(self, n, step, action):
        ref = self.target(n, action)
        c = self.case(ref)
        mission_id = self.state['steps'][str(ref)].get('mission_id')
        request = {'text': action['text'], 'actor': CREW, 'source': 'crew', 'received_at': self.stamp(step, action), 'expected_version': c['version'],
                   'case_id': c['case_id']}
        status, out = self.desk.post(f'/api/missions/{mission_id}/feedback' if mission_id else f"/api/cases/{c['case_id']}/feedback", request)
        self.log(n, f'relato da equipe (passo {ref})', status, out)

    def op_volunteer_verify(self, n, step, action):
        ref = self.target(n, action)
        cid = self.state['steps'][str(ref)].get('case_id')
        status, listing = self.desk.get('/api/volunteers')
        offer = next((v for v in listing.get('volunteers', []) if v.get('source_ref') == 'case:'+str(cid)), None)
        self.state['steps'][str(ref)]['volunteer_id'] = offer['id'] if offer else None
        self.state['steps'][str(ref)]['volunteer_status_before'] = offer['status'] if offer else None
        if offer is None:
            return self.log(n, 'oferta de voluntário', 404, {'error': 'oferta não apareceu na lista de voluntários'})
        status, out = self.desk.post(f"/api/volunteers/{offer['id']}/verify", {'actor': ACTOR, 'method': action.get('method', 'ligacao'),
                                                                               'note': 'Verificado por telefone (demo [SIMULADO]).'})
        self.log(n, 'oferta verificada pelo operador', status, out)

    def run(self, only=None, speed=1.0):
        for step in self.scenario['steps']:
            if only and step['step'] not in only:
                continue
            self.say(f"[{step['step']}/{len(self.scenario['steps'])}] {step['t']}  {step['title']}")
            rec = self.run_step(step)
            for entry in rec['log']:
                self.say(('   ok   ' if entry['ok'] else '   FALHA ')+entry['what']+('' if entry['ok'] else ' -> '+entry.get('error', '')))
            if speed and speed > 0:
                self.sleep(float(step.get('pause_s', 1.0))/speed)
        return self.state


# ---- checker --------------------------------------------------------------------------------------------------
class Check:
    def __init__(self, desk, scenario, state):
        self.desk, self.scenario, self.state = desk, scenario, state
        self.day = scenario['meta']['replay_day']

    def case_of(self, n):
        rec = self.state.get('steps', {}).get(str(n), {})
        if not rec.get('case_id'):
            return None
        status, body = self.desk.get('/api/cases/'+rec['case_id'])
        return body if status == 200 else None

    def step(self, step):
        n, e, fails, notes = step['step'], step['expect'], [], []
        rec = self.state.get('steps', {}).get(str(n), {})
        if not rec:
            return False, ['passo não executado (rode tools/demo_run.py)'], []
        bad = [x for x in rec.get('log', []) if not x['ok']]
        for x in bad:
            fails.append(f"ação falhou: {x['what']} ({x.get('error', 'http '+str(x['http']))})")
        case = self.case_of(n)
        if step.get('message') and case is None:
            return False, fails+['caso não encontrado no desk'], notes
        result = rec.get('intake') or {}  # what the desk decided when the message arrived (later steps legitimately change the case)
        if 'decision_in' in e and result.get('decision') not in e['decision_in']:
            fails.append(f"decisão {result.get('decision')} fora de {e['decision_in']}")
        elif 'decision_in' in e:
            notes.append(f"decisão {result.get('decision')}")
        if 'decision_after_in' in e and rec.get('decision_after_reply') not in e['decision_after_in']:
            fails.append(f"decisão após resposta {rec.get('decision_after_reply')} fora de {e['decision_after_in']}")
        if 'priority_min' in e and (result.get('priority') or 0) < e['priority_min']:
            fails.append(f"prioridade {result.get('priority')} < {e['priority_min']}")
        if 'position_kind' in e and not str(result.get('position_kind') or '').startswith(e['position_kind']):
            fails.append(f"posição {result.get('position_kind')} não começa com {e['position_kind']}")
        if 'status_in' in e and (case or {}).get('status') not in e['status_in']:
            fails.append(f"status {(case or {}).get('status')} fora de {e['status_in']}")
        if 'duplicate_of_step' in e:
            other = self.state['steps'].get(str(e['duplicate_of_step']), {}).get('case_id')
            linked = {d.get('case_id') or d.get('other_case_id') or d.get('id') for d in (case or {}).get('duplicates') or []}
            if not other or other not in linked:
                fails.append(f"duplicado não vinculado ao passo {e['duplicate_of_step']}")
            else:
                notes.append(f"duplicado vinculado ao passo {e['duplicate_of_step']}")
        if e.get('no_new_mission') and (rec.get('mission_id') or str((case or {}).get('status', '')).startswith('ASSIGNED')):
            fails.append('duplicado gerou nova missão')
        if 'mission' in e:
            m = e['mission']
            if not rec.get('mission_id'):
                fails.append('sem missão aprovada')
            else:
                status, mission = self.desk.get('/api/missions/'+rec['mission_id'])
                if status != 200:
                    fails.append('missão não encontrada')
                else:
                    if 'asset_in' in m and rec.get('unit_id') not in m['asset_in']:
                        fails.append(f"unidade {rec.get('unit_id')} fora de {m['asset_in']}")
                    if 'status_in' in m and mission.get('status') not in m['status_in']:
                        fails.append(f"missão {mission.get('status')} fora de {m['status_in']}")
                    if m.get('human_approved') and not any(a.get('action') == 'approve_mission' and a.get('actor') for cc in [case] for a in (cc or {}).get('actions', [])):
                        fails.append('sem aprovação humana registrada')
                    notes.append(f"missão {rec['mission_id'][:8]} {mission.get('status')} com {rec.get('unit_id')}")
        if e.get('route_water_leg') and not (rec.get('route') or {}).get('water_leg'):
            fails.append('rota sem trecho aquático')
        if 'landing' in e:
            ld = rec.get('landing') or {}
            if ld.get('options', 0) < e['landing'].get('options_min', 1):
                fails.append(f"opções de desembarque {ld.get('options')}")
            if e['landing'].get('chosen') and not ld.get('landing_id'):
                fails.append('desembarque não escolhido')
            if e['landing'].get('ambulance') and not ld.get('ambulance_note'):
                fails.append('sem indicação de ambulância no desembarque')
        if 'shelter_vacancy' in e:
            status, sh = self.desk.get(f"/api/shelters?date={self.day}T23:59:00-03:00")
            row = next((s for s in sh.get('shelters', []) if s['shelter_id'] == self.state.get('shelter_id')), None)
            if not row or (row.get('remaining') or 0) < e['shelter_vacancy'].get('min', 1):
                fails.append(f"abrigo sem vagas relatadas ({(row or {}).get('remaining')})")
            else:
                notes.append(f"abrigo com {row['remaining']} vagas")
        if 'volunteer' in e:
            status, vl = self.desk.get('/api/volunteers')
            v = next((x for x in vl.get('volunteers', []) if x['id'] == rec.get('volunteer_id')), None)
            if v is None:
                fails.append('oferta de voluntário ausente')
            else:
                if rec.get('volunteer_status_before') != e['volunteer'].get('before', 'pending_verification'):
                    fails.append(f"antes da verificação estava {rec.get('volunteer_status_before')}")
                if v['status'] != e['volunteer'].get('after', 'available'):
                    fails.append(f"oferta {v['status']}")
        if e.get('fleet_has_volunteer'):
            status, res = self.desk.get('/api/resources')
            if not any(str(u.get('id', '')).startswith('vol-') for u in res.get('typed_resources', []) + res.get('resources', [])):
                fails.append('voluntário verificado não aparece na frota')
        if 'reroute' in e:
            status, rr = self.desk.get('/api/reroutes?date='+self.day)
            alerts = [a for a in rr.get('alerts', []) if a.get('case_id') == rec.get('case_id')]
            if not alerts:
                fails.append('sem proposta de desvio para este caso')
            else:
                a = alerts[0]
                if (a.get('mission_delay_minutes') or 0) <= 0:
                    fails.append('desvio sem +min')
                if rr.get('auto_applied') is not False or rr.get('human_approval_required') is not True:
                    fails.append('desvio sem aprovação humana')
                notes.append(f"desvio +{a.get('mission_delay_minutes')} min aguardando aprovação")
        if 'medical' in e:
            fl = ' '.join(str(x) for x in (case or {}).get('flags', []) or [])
            if not (case or {}).get('medical_queue') and not re.search(r'medic|oxig', json.dumps(case or {}, ensure_ascii=False), re.I):
                fails.append('caso não entrou na fila médica')
        if 'gps' in e and (rec.get('gps') or {}).get('accepted', 0) < e['gps'].get('min_accepted', 1):
            fails.append(f"GPS simulado aceito: {(rec.get('gps') or {}).get('accepted')}")
        return not fails, fails, notes

    def all(self):
        return [(s['step'], s['title'])+self.step(s) for s in self.scenario['steps']]
