"""HERO rescue for the submission video (data/demo/hero.jsonl): ONE case from zero to closed, with the loops closing.

  python tools/demo_hero.py --offline                    # embedded sample desk on :8097 (fake client, deterministic); PASS/FAIL per step
  python tools/demo_hero.py --offline --keep --port 8095 # same, then keep serving so you can open http://127.0.0.1:8095/v2
  python tools/demo_hero.py --live --url http://127.0.0.1:8080 --speed 4
                                                         # Orbit only: desk started against Nightshift; this tool never calls a model itself
  python tools/demo_hero.py --live --url ... --only 3 4  # run chosen steps (state of earlier steps is read from runtime/hero_state.json)
  python tools/demo_hero.py --live --url ... --gate-file runtime/hero_go
                                                         # before every step wait until that file exists (then it is deleted): lets the
                                                         # recorder start a scene, then `touch` the file to fire the next step

Story (demo video scenes 4-8): message -> real callback question -> [SIMULADO] reply with street -> automatic re-triage -> stretcher boat
-> land + water route -> landing with ambulance + shelter vacancy -> approve/dispatch -> [SIMULADO] GPS mover -> supervisor "sem sinal" alert
-> a fix closes it -> new nearby P1 (reroute proposal, human approves) -> crew report "Resgatamos 3" -> case closed.
Order note: the reroute (step 7) must come BEFORE the crew report (step 8) because a closed mission cannot be rerouted. Orbit may record
scene 8 right after step 7 and scene 7's "closed" shot after step 8, then cut them in the planned order.

Replay-time GPS: telemetry fixes carry REPLAY timestamps (2024-05-06T12:xx) so the supervisor, which ticks in replay time, sees them.
The fleet marker therefore reads "[SIMULADO] ... · replay" instead of seconds-old ages.
"""
import argparse
import copy
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_lib as lib  # noqa: E402
import demo_run  # noqa: E402

ROOT = lib.ROOT
HERO = Path(os.environ['HERO_FILE']) if os.environ.get('HERO_FILE') else ROOT/'data'/'demo'/'hero.jsonl'
STATE = ROOT/'runtime'/'hero_state.json'
HERO_EXPECT = {'route_land_leg', 'live_decision_in', 'reroute_snapshot', 'of', 'people_value', 'medical_flag', 'landmark_quote', 'street_contains', 'callback_question', 'street_after',
               'stretcher_unit', 'supervisor_loop', 'closed'}
lib.OPS = lib.OPS + ('callback_question', 'supervisor_tick', 'gps_replay', 'resource_register')
lib.EXPECT_KEYS = set(lib.EXPECT_KEYS) | HERO_EXPECT
lib.STEP_KEYS = set(lib.STEP_KEYS) | {'pause_s'}
lib.STATE = STATE


def epoch(day, hhmm, seconds=0):
    return datetime.fromisoformat(f'{day}T{hhmm}:{seconds % 60:02d}-03:00').timestamp()+(seconds//60)*60


class HeroRunner(lib.Runner):
    def __init__(self, desk, scenario, *, speed=1.0, gate_file=None, **kw):
        super().__init__(desk, scenario, **kw)
        self.speed = speed or 0
        self.gate_file = Path(gate_file) if gate_file else None
        self.state['mode'] = desk.health().get('mode')

    def scaled(self, seconds):
        return seconds/self.speed if self.speed else 0

    def run_step(self, step):
        if self.gate_file:
            self.say(f"   (aguardando {self.gate_file} para o passo {step['step']})")
            while not self.gate_file.exists():
                time.sleep(0.25)
            self.gate_file.unlink()
        n = step['step']
        rec = self.state['steps'].setdefault(str(n), {'title': step['title'], 'log': []})
        if step.get('message') or not step.get('actions'):
            return super().run_step(step)
        for action in step.get('actions', []):
            if action.get('delay_s'):
                self.sleep(self.scaled(action['delay_s']))
            try:
                getattr(self, 'op_'+action['op'])(n, step, action)
            except Exception as exc:
                self.log(n, action['op'], 0, {'error': f'{type(exc).__name__}: {exc}'}, ok=False)
        lib.save_state(self.state, STATE)
        return rec

    def run(self, only=None, speed=None):
        for step in self.scenario['steps']:
            if only and step['step'] not in only:
                continue
            self.say(f"[{step['step']}/{len(self.scenario['steps'])}] {step['t']}  {step['title']}")
            started = time.monotonic()
            rec = self.run_step_message_scaled(step)
            for entry in rec['log']:
                self.say(('   ok   ' if entry['ok'] else '   FALHA ')+entry['what']+('' if entry['ok'] else ' -> '+entry.get('error', '')))
            self.sleep(self.scaled(float(step.get('pause_s', 1.0))))
            rec['wall_seconds'] = round(time.monotonic()-started, 3)
            self.say(f"   TEMPO passo {step['step']}: {rec['wall_seconds']:.3f} s (inclui pausas)")
        return self.state

    def snapshot_reroute(self, step):
        rec = self.state['steps'][str(step['step'])]
        status, rr = self.desk.get('/api/reroutes?date='+self.day)
        alerts = [a for a in rr.get('alerts', []) if a.get('case_id') == rec.get('case_id')]
        rec['reroute_snapshot'] = {'found': bool(alerts), 'auto_applied': rr.get('auto_applied'), 'human_approval_required': rr.get('human_approval_required'),
                                   'delay_min': alerts[0].get('mission_delay_minutes') if alerts else None, 'text_pt': alerts[0].get('text_pt') if alerts else None}

    def run_step_message_scaled(self, step):
        # steps carrying a message use the base implementation (which sleeps raw delay_s); scale its delays
        if step.get('message') and any(a.get('delay_s') for a in step.get('actions', [])):
            step = copy.deepcopy(step)
            for a in step['actions']:
                if a.get('delay_s'):
                    a['delay_s'] = self.scaled(a['delay_s'])
        rec = self.run_step(step)
        if 'reroute' in step['expect']:
            self.snapshot_reroute(step)
        return rec

    # ---- hero-specific operations --------------------------------------------------------------------------
    def op_resource_register(self, n, step, action):
        """Document a synthetic shift unit through the same operator API as the desk."""
        unit = json.loads((ROOT/'data/demo/hero_boat.json').read_text(encoding='utf-8'))
        if not unit.get('synthetic') or '[SIMULADO]' not in unit.get('source', ''):
            raise ValueError('hero fleet must be explicitly simulated')
        status, listing = self.desk.get('/api/resources')
        if not self.log(n, 'inventário do turno', status, listing):
            return
        old = next((u for u in listing.get('resources', []) if u['id'] == unit['id']), {})
        status, body = self.desk.post('/api/resources', {
            'actor': lib.ACTOR, 'expected_version': old.get('version', 0), 'unit': unit})
        self.log(n, f"[SIMULADO] recurso cadastrado: {unit['id']}", status, body)

    def op_callback_question(self, n, step, action):
        ref = self.target(n, action)
        c = self.case(ref)
        status, view = self.desk.get(f"/api/cases/{c['case_id']}/callback")
        if self.log(n, f'pergunta de retorno (passo {ref})', status, view):
            plan = view.get('plan') or {}
            questions = plan.get('questions') or []
            self.state['steps'][str(ref)]['callback'] = {
                'decision_before': view.get('decision'), 'items': [i['id'] for i in view.get('items', [])],
                'questions': [q.get('text_pt') or q.get('text') or q if isinstance(q, dict) else q for q in questions][:3]}
            self.say('   RETORNO REAL: '+str(self.state['steps'][str(ref)]['callback']['questions']))

    def op_shelter_register(self, n, step, action):
        """Idempotent: a desk that already knows the demo shelter (second take) reuses it instead of failing."""
        body = {'kind': 'register', 'name': action['name'], 'lat': action['lat'], 'lon': action['lon'], 'municipality': action.get('municipality', ''),
                'actor': lib.ACTOR, 'source': 'operator', 'at': self.stamp(step, action), 'quote': '[SIMULADO] abrigo cadastrado para a demonstração'}
        status, out = self.desk.post('/api/shelters/reports', body)
        if status != 200 and 'cadastrado' in str(out.get('error', '')):
            s2, listing = self.desk.get(f'/api/shelters?date={self.day}T23:59:00-03:00')
            row = next((x for x in listing.get('shelters', []) if x.get('name') == action['name']), None)
            if row:
                self.state['shelter_id'] = row['shelter_id']
                return self.log(n, f"abrigo já cadastrado (reuso): {action['name']}", 200, {})
        if self.log(n, f"abrigo cadastrado: {action['name']}", status, out):
            self.state['shelter_id'] = out['recorded'][0]['shelter_id']

    def op_gps_replay(self, n, step, action):
        """[SIMULADO] fixes stamped with REPLAY time so that supervisor ticks (also replay time) see them."""
        ref = self.target(n, action)
        rec = self.state['steps'][str(ref)]
        unit = rec.get('unit_id')
        if not unit:
            return self.log(n, 'GPS simulado', 409, {'error': 'sem missão aprovada para mover'})
        device = 'sim:'+unit
        if not rec.get('gps_bound'):
            status, body = self.desk.post('/api/telemetry/bindings', {'device': device, 'unit_id': unit, 'actor': lib.ACTOR})
            self.log(n, f'vínculo {device} (operador)', status, body)
            rec['gps_bound'] = status == 200
        if rec.get('gps_points') is None:
            status, missions = self.desk.get('/api/telemetry/missions')
            mission = next((m for m in missions.get('missions', []) if m['unit_id'] == unit and (m.get('segments') or m.get('proven_prefix_segments'))), None) if status == 200 else None
            if mission is None:
                return self.log(n, 'rota para o GPS simulado', 404, {'error': 'missão sem segmentos de rota'})
            points = []
            for seg in (mission.get('segments') or mission.get('proven_prefix_segments') or []):
                points += seg['polyline']
            rec['gps_points'] = points
        points = rec['gps_points']
        count, step_s, offset = int(action.get('fixes', 6)), int(action.get('step_s', 30)), int(action.get('offset_s', 0))
        done = rec.setdefault('gps', {'sent': 0, 'accepted': 0, 'last_ts': None})
        t0 = epoch(self.day, action['at'])+offset
        for i in range(count):
            idx = len(points)-1 if count == 1 else round(i*(len(points)-1)/(count-1))
            lon, lat = points[idx]
            ts = t0+i*step_s
            q = f'id={device}&lat={lat:.6f}&lon={lon:.6f}&timestamp={ts:.0f}&speed=4&bearing=0&accuracy=10&source=simulated'
            s2, r = self.desk.call('GET', '/api/telemetry/osmand?'+q)
            done['sent'] += 1
            done['accepted'] += s2 == 200 and r.get('status') in ('accepted', 'ok', 'trusted')
            done['last_ts'] = ts
            self.sleep(self.scaled(float(action.get('pause_s', 1.0))))
        self.log(n, f"[SIMULADO] GPS: {count} posições (tempo de replay {action['at']})", 200, {},
                 ok=done['accepted'] == done['sent'])

    def op_supervisor_tick(self, n, step, action):
        stamp = lib.iso(self.day, action['at'], int(action.get('seconds', 0)))
        status, body = self.desk.post('/api/supervisor/tick', {'replay_time': stamp})
        if not self.log(n, f"tick do supervisor {action['at']}", status, body):
            return
        status, view = self.desk.get(f'/api/supervisor/ticks?date={self.day}')
        gps = [a for a in view.get('alerts', []) if a['kind'] in ('gps_no_signal', 'unit_silent')]
        sup = self.state.setdefault('supervisor', {})
        sup[action.get('label', action['at'])] = {
            'at': stamp, 'alerts': [{'id': a['alert_id'], 'kind': a['kind'], 'status': a['status'], 'outcome': a.get('outcome')} for a in gps]}


class HeroCheck(lib.Check):
    def step(self, step):
        n, e = step['step'], dict(step['expect'])
        of = e.pop('of', None)
        extra = {k: e.pop(k) for k in list(e) if k in HERO_EXPECT}
        reroute = e.pop('reroute', None)
        steps = self.state['steps']
        rec_n = steps.get(str(n), {})
        src = steps.get(str(of or n), {})
        shadow = None
        if of and not step.get('message'):
            shadow = steps.get(str(n))
            steps[str(n)] = {**src, 'log': rec_n.get('log', [])}
        try:
            ok, fails, notes = super().step({**step, 'expect': e})
        finally:
            if shadow is not None:
                steps[str(n)] = shadow
        case = None
        cid = src.get('case_id')
        if cid and extra:
            status, case = self.desk.get('/api/cases/'+cid)
            case = case if status == 200 else None
        if 'live_decision_in' in extra and self.state.get('mode') == 'live':
            got = (src.get('intake') or {}).get('decision')
            (notes if got in extra['live_decision_in'] else fails).append(f"AO VIVO: decisão inicial {got} (esperado {extra['live_decision_in']})")
        if reroute:
            snap = rec_n.get('reroute_snapshot') or {}
            if not snap.get('found'):
                fails.append('sem proposta de desvio para o novo P1 (no momento do passo)')
            elif (snap.get('delay_min') or 0) <= 0 or snap.get('auto_applied') is not False or snap.get('human_approval_required') is not True:
                fails.append(f'desvio inválido: {snap}')
            else:
                notes.append(f"desvio +{snap['delay_min']} min aguardando aprovação humana")
        fields = (case or {}).get('fields') or {}
        if 'people_value' in extra:
            got = (fields.get('people') or {}).get('value')
            (notes if got == extra['people_value'] else fails).append(f"pessoas derivadas = {got} (esperado {extra['people_value']}; idade 8 não conta)")
        if extra.get('medical_flag') and not ((case or {}).get('medical') or 'acamad' in str(case).lower()):
            fails.append('acamada não entrou na fila médica')
        elif extra.get('medical_flag'):
            notes.append('fila médica: acamada')
        if 'landmark_quote' in extra and extra['landmark_quote'] not in str((fields.get('landmark') or {}).get('quote', '')).lower():
            fails.append('referência da rodoviária ausente no campo landmark')
        if 'street_contains' in extra and extra['street_contains'] not in str((fields.get('street') or {}).get('value', '')):
            fails.append(f"rua não resolvida ({(fields.get('street') or {}).get('value')})")
        if extra.get('callback_question') and not (src.get('callback') or {}).get('questions'):
            fails.append('nenhuma pergunta de retorno gerada')
        elif extra.get('callback_question'):
            notes.append('pergunta: '+str(src['callback']['questions'][0])[:90])
        if 'street_after' in extra:
            got = str((fields.get('street') or {}).get('value', ''))
            pk = str((case or {}).get('position', {}).get('position_kind', ''))
            (notes if extra['street_after'] in got and pk.startswith('street') else fails).append(f"rua após a resposta = {got!r} (esperado conter {extra['street_after']!r}); posição: {str((case or {}).get('position', {}).get('position_kind', ''))[:60]}")
        if extra.get('route_land_leg') and not (src.get('route') or {}).get('land'):
            fails.append('rota sem trecho terrestre alcançável')
        if extra.get('stretcher_unit'):
            status, listing = self.desk.get('/api/resources')
            assets = {a['id']: a for a in listing.get('typed_resources', [])} if status == 200 else {}
            if not assets.get(src.get('unit_id'), {}).get('stretcher'):
                fails.append('unidade escolhida não tem maca')
            else:
                notes.append(f"{src.get('unit_id')} com maca")
        if extra.get('supervisor_loop'):
            sup = self.state.get('supervisor', {})
            opened = sup.get('no_signal', {}).get('alerts', [])
            closed = {a['id']: a for a in sup.get('closes', {}).get('alerts', [])}
            opened = [a for a in opened if a['kind'] == 'gps_no_signal' and a['status'] == 'open']
            if not opened:
                fails.append('alerta de sem sinal não abriu')
            else:
                after = closed.get(opened[0]['id'])
                if not after or after['status'] != 'closed':
                    fails.append(f"alerta não fechou com o fix ({after})")
                else:
                    notes.append(f"alerta {opened[0]['kind']} aberto → fechado pelo fix")
        if extra.get('closed'):
            status_now = (case or {}).get('status', '')
            if 'RESCUED' not in status_now.upper() and 'RESGAT' not in status_now.upper() and 'CLOSED' not in status_now.upper():
                fails.append(f'caso não encerrado (status {status_now})')
            else:
                notes.append(f'caso encerrado ({status_now})')
        return not fails, fails, notes


def main():
    global STATE
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true')
    mode.add_argument('--live', action='store_true')
    p.add_argument('--url')
    p.add_argument('--port', type=int, default=8097)
    p.add_argument('--speed', type=float, default=0, help='0 = no pauses (default); 1 = real pacing; 4 = four times faster')
    p.add_argument('--only', type=int, nargs='*')
    p.add_argument('--keep', action='store_true')
    p.add_argument('--upto', type=int, help='stop after this step number (debug / partial takes)')
    p.add_argument('--gate-file')
    p.add_argument('--workdir', help='embedded desk data dir (default runtime/demo_hero)')
    args = p.parse_args()
    if args.workdir:
        STATE = Path(args.workdir).resolve()/'runtime/hero_state.json'
        lib.STATE = STATE
    if args.live and not args.url:
        p.error('--live needs --url of the desk you started')
    scenario = lib.load(HERO)
    print(f"Herói: {scenario['meta']['name']} · {len(scenario['steps'])} passos")
    sleep = time.sleep if args.speed or args.gate_file else (lambda s: None)

    def go(desk, server=None):
        runner = HeroRunner(desk, scenario, speed=args.speed, gate_file=args.gate_file, sleep=sleep)
        if args.only and STATE.is_file():
            runner.state = lib.load_state(STATE)
        only = set(args.only) if args.only else ({x['step'] for x in scenario['steps'] if x['step'] <= args.upto} if args.upto else None)
        state = runner.run(only=only)
        lib.save_state(state, STATE)
        rows = [r for r in HeroCheck(desk, scenario, state).all() if not only or r[0] in only]
        ok = demo_run.report(rows)
        for n, title, good, fails, notes in rows:
            for x in notes:
                print(f'        · passo {n}: {x}')
        return ok

    if args.url:
        desk = lib.Desk(args.url)
        want = 'live' if args.live else 'sample_offline'
        have = desk.health().get('mode')
        if have != want:
            p.error(f'o desk em {args.url} está em modo {have!r}; esperado {want!r}')
        sys.exit(0 if go(desk) else 1)
    import app.web.server as web
    workdir = Path(args.workdir) if args.workdir else ROOT/'runtime'/'demo_hero'
    if workdir.exists() and any(workdir.iterdir()):
        p.error('workdir precisa estar vazio; use um diretório novo para cada tomada')
    import socket
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', args.port)) == 0:
            p.error(f'porta {args.port} já em uso (outro desk?); escolha --port livre')
    original = web.ROOT
    server = demo_run.serve_embedded(workdir, args.port)
    try:
        ok = go(lib.Desk(f'http://127.0.0.1:{server.server_port}'))
        if args.keep:
            print(f'Desk offline em http://127.0.0.1:{server.server_port}/v2 — Ctrl+C para encerrar')
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        sys.exit(0 if ok else 1)
    finally:
        server.shutdown()
        server.server_close()
        web.ROOT = original


if __name__ == '__main__':
    main()
