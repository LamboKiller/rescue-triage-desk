"""Replay runner: advances a replay clock over a scenario and feeds each input through the REAL desk code.

Messages go through Pipeline.run; supervisor ticks through SupervisorService.tick; operator/crew/citizen inputs through
the same registry actions, MissionService, FeedbackService and CallbackService the HTTP desk uses. The runner never
decides: it only schedules inputs and records what the desk did (events), each with its replay time.
"""
import copy
import threading
import time
from datetime import datetime, timedelta
from app.callback.service import CallbackService
from app.engines.world_model.registry import Conflict

OPERATOR = 'operador (cenário)'
CREW = 'equipe (cenário)'
LANES = ('message', 'agent', 'decision', 'supervisor', 'mission', 'feedback')
SPEEDS = (1, 10, 60)
SLICE_S = 0.2          # real seconds per clock step
LOCK_WAIT_S = 600


class Desk:
    """The services a replay drives. Built from a mission-enabled server or assembled by tests."""
    def __init__(self, registry, pipeline, supervisor, missions, feedback, callback_client=None):
        self.registry, self.pipeline, self.supervisor = registry, pipeline, supervisor
        self.missions, self.feedback, self.callback_client = missions, feedback, callback_client

    @classmethod
    def from_server(cls, server):
        return cls(server.pipeline.registry, server.pipeline, server.supervisor, server.missions, server.feedback,
                   getattr(server.callback, 'client', None))


class ReplayRunner:
    def __init__(self, desk, scenario, *, speed=10, sleep=time.sleep, tick_every=None):
        self.desk, self.scenario = desk, scenario
        meta = scenario['meta']
        self.day, self.start = meta['replay_day'], meta['start']
        self.end_min, self.tick_every = meta['end_min'], tick_every or meta.get('tick_every_min', 30)
        self.base = datetime.fromisoformat(f'{self.day}T{self.start}:00-03:00')
        self.speed, self.sleep = speed, sleep
        self.lock = threading.RLock()
        self.resume = threading.Event()
        self.resume.set()
        self.stop_flag = False
        self.events, self.status, self.clock = [], 'idle', 0.0
        self.msg_case = {}        # scenario message id -> case id
        self.thread = None
        self.error = None
        self.foreign_cases = 0

    # ---- clock -----------------------------------------------------------------------------
    def iso(self, minute=None):
        return (self.base+timedelta(minutes=self.clock if minute is None else minute)).isoformat()

    def agenda(self):
        """Inputs first, then the supervisor tick at the same minute (the tick sees what just arrived)."""
        rows = [(float(r['t']), 0, n, r) for n, r in enumerate(self.scenario['items'])]
        minute = 0
        while minute <= self.end_min:
            rows.append((float(minute), 1, -1, {'type': 'tick'}))
            minute += self.tick_every
        if minute-self.tick_every != self.end_min:
            rows.append((float(self.end_min), 1, -1, {'type': 'tick'}))
        return sorted(rows, key=lambda x: x[:3])

    def advance(self, target):
        while self.clock < target and not self.stop_flag:
            self.resume.wait()
            step = min(target-self.clock, SLICE_S*self.speed/60)
            self.sleep(min(SLICE_S, step*60/self.speed))
            with self.lock:
                self.clock = min(target, self.clock+step)

    # ---- control ---------------------------------------------------------------------------
    def start_thread(self):
        with self.lock:
            if self.status in ('running', 'paused'):
                raise Conflict('O replay já está em andamento.')
            self.status = 'running'
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def pause(self, paused=True):
        with self.lock:
            if self.status not in ('running', 'paused'):
                raise Conflict('Nenhum replay em andamento.')
            self.status = 'paused' if paused else 'running'
            (self.resume.clear if paused else self.resume.set)()

    def set_speed(self, speed):
        if speed not in SPEEDS:
            raise ValueError('Velocidade deve ser 1, 10 ou 60.')
        self.speed = speed

    def stop(self):
        self.stop_flag = True
        self.resume.set()

    # ---- events ----------------------------------------------------------------------------
    def emit(self, kind, lane, **fields):
        with self.lock:
            event = {'seq': len(self.events)+1, 'kind': kind, 'lane': lane, 'replay_time': self.iso(), 't_min': round(self.clock, 2),
                     'case_id': None, 'scenario_input': False, **fields}
            self.events.append(event)
            return event

    def state(self, since=0):
        with self.lock:
            return {'status': self.status, 'speed': self.speed, 'error': self.error,
                    'clock': {'replay_time': self.iso(), 't_min': round(self.clock, 2), 'day': self.day, 'start': self.start, 'end_min': self.end_min},
                    'scenario': {'name': self.scenario['meta'].get('name'), 'synthetic': True, 'items': len(self.scenario['items']),
                                 'tick_every_min': self.tick_every, 'note': self.scenario['meta'].get('note')},
                    'lanes': list(LANES), 'events': copy.deepcopy([e for e in self.events if e['seq'] > since]),
                    'event_count': len(self.events)}

    # ---- execution -------------------------------------------------------------------------
    def run(self):
        try:
            with self.lock:
                self.status = 'running'
            for minute, _, _, row in self.agenda():
                if self.stop_flag:
                    break
                self.advance(minute)
                try:
                    getattr(self, 'do_'+row['type'])(row)
                except Exception as exc:  # visible, never silent; the replay continues
                    self.emit('error', 'decision', type=row.get('type'), op=row.get('op'), ref=row.get('ref'),
                              case_id=self.msg_case.get(row.get('ref')), message=str(exc)[:300], error_class=type(exc).__name__,
                              scenario_input=bool(row.get('scenario_input')))
            with self.lock:
                self.status = 'stopped' if self.stop_flag else 'finished'
            self.emit('finished', 'decision', cases=len(self.desk.registry.read()))
        except Exception as exc:
            with self.lock:
                self.status, self.error = 'error', type(exc).__name__+': '+str(exc)[:200]

    def case(self, ref):
        cid = self.msg_case.get(ref)
        case = self.desk.registry.read(cid) if cid else None
        if case is None:
            raise Conflict(f'Mensagem {ref} ainda não virou caso.')
        return case

    @staticmethod
    def brief(case):
        r = case.get('result', {})
        pos = case.get('position') or {}
        return {'decision': r.get('decision'), 'decision_reason': r.get('decision_reason'), 'priority': r.get('priority'),
                'location_confidence': r.get('location_confidence'), 'position_kind': pos.get('position_kind'),
                'people': (case.get('fields', {}).get('people') or {}).get('value'), 'status': case.get('status'),
                'version': case.get('version'), 'route': (case.get('route') or {}).get('id'),
                'duplicates': len(case.get('duplicates') or [])}

    def do_resource(self, row):
        from app.resources import register
        unit = register(self.desk.registry, {'actor': OPERATOR, 'expected_version': 0, 'unit': row['unit']})
        self.emit('resource_registered', 'mission', scenario_input=True, unit_id=unit['id'], asset=unit['asset'],
                  capacity=unit['capacity'], synthetic=unit.get('synthetic'))

    def do_message(self, row):
        mid, now = row['id'], self.iso()
        self.emit('message_arrived', 'message', message_id=mid, text=row['text'], channel=row.get('channel'), synthetic=True)

        def sink(stage, **data):
            self.emit('agent_stage', 'agent', message_id=mid, stage=stage, role=data.get('role'), seconds=data.get('seconds'),
                      case_id=data.get('case_id'))
        request = {'replay_time': now, 'messages': [{'message_id': mid, 'text': row['text'], 'received_at': now}]}
        deadline = time.monotonic()+LOCK_WAIT_S
        while True:
            try:
                out = self.desk.pipeline.run(request, event_sink=sink)
                break
            except ValueError as exc:
                if 'execução ativa' not in str(exc) or time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        case = out['cases'][0]
        self.msg_case[mid] = case['case_id']
        self.emit('decision', 'decision', case_id=case['case_id'], message_id=mid, **self.brief(case))

    def do_citizen_reply(self, row):
        case = self.case(row['ref'])
        records = {case['message_id']: {'message_id': case['message_id'], 'citizen_replies': row['citizen_replies'],
                                        'unknown_reply': row.get('unknown_reply')}}
        service = CallbackService(self.desk.registry, self.desk.pipeline, self.desk.callback_client, None, records)
        out = service.reply(case['case_id'], {'simulated': True, 'received_at': self.iso(), 'expected_version': case['version']})
        d = out['diff']
        self.emit('citizen_reply', 'message', scenario_input=True, simulated=True, case_id=case['case_id'], message_id=row['ref'],
                  text=out['reply_text'], resolved=d['items']['resolved'], remaining=d['items']['remaining'])
        self.emit('decision_changed', 'decision', case_id=case['case_id'], message_id=row['ref'], before=d['decision']['before'],
                  after=d['decision']['after'], reason=d['decision']['reason_after'], version=out['case']['version'])

    def do_operator(self, row):
        op = row['op']
        if op == 'decide_alert':
            return self.decide_alert(row)
        case = self.case(row['ref'])
        cid = case['case_id']
        if op in ('confirm_location', 'request_callback'):
            updated = self.desk.registry.action(cid, op, case['version'], OPERATOR, human=True)
            return self.emit('operator_'+op, 'decision', scenario_input=True, case_id=cid, message_id=row['ref'], note=row.get('note'),
                             status=updated['status'], version=updated['version'])
        return self.approve_mission(row, case)

    def approve_mission(self, row, case):
        cid = case['case_id']
        plans = self.desk.missions.proposals(self.day)['proposals']
        plan = next((p for p in plans if cid in {s['case_id'] for s in p['stops']}), None)
        if plan is None:
            return self.emit('mission_proposal_missing', 'mission', scenario_input=True, case_id=cid, message_id=row['ref'],
                             reason='Nenhuma proposta cobre este caso (recursos, localização ou profundidade).')
        info = {'proposal_id': plan['proposal_id'], 'asset': plan.get('asset'), 'stops': [s['case_id'] for s in plan['stops']],
                'blocking_reasons': plan.get('blocking_reasons', [])}
        self.emit('mission_proposed', 'mission', case_id=cid, message_id=row['ref'], **info)
        if plan.get('blocking_reasons'):
            return self.emit('mission_blocked', 'mission', case_id=cid, message_id=row['ref'], reason='; '.join(plan['blocking_reasons'])[:400])
        request = {'proposal_id': plan['proposal_id'], 'actor': OPERATOR, 'caution_acknowledged': bool(row.get('acknowledge_caution')),
                   'expected_versions': {s['case_id']: s['expected_version'] for s in plan['stops']}}
        detail = self.desk.missions.approve(request)
        return self.emit('mission_approved', 'mission', scenario_input=True, case_id=cid, message_id=row['ref'], mission_id=detail['mission_id'],
                         status=detail['status'], asset=detail.get('asset'), stops=len(detail['stops']), note=row.get('note'))

    def decide_alert(self, row):
        alert = next((a for a in self.desk.supervisor.state()['alerts'].values()
                      if a['status'] == 'open' and a['kind'] == row['alert_kind']), None)
        if alert is None:
            return self.emit('alert_not_found', 'supervisor', scenario_input=True, alert_kind=row['alert_kind'],
                             note='Nenhum alerta aberto deste tipo neste momento.')
        out = self.desk.supervisor.decide(alert['alert_id'], row['choice'], OPERATOR, self.iso())
        ex = (out.get('decision') or {}).get('execution') or {}
        return self.emit('alert_decided', 'supervisor', scenario_input=True, alert_id=alert['alert_id'], alert_kind=alert['kind'],
                         case_ids=alert['case_ids'], case_id=(alert['case_ids'] or [None])[0], decision=row['choice'],
                         summary=ex.get('summary_pt'), action=alert['action'])

    def do_crew_report(self, row):
        case = self.case(row['ref'])
        cid = case['case_id']
        request = {'actor': CREW, 'expected_version': case['version'], 'text': row['text'], 'received_at': self.iso(), 'source': 'crew'}
        mission_id = case['status'].split(':', 1)[1] if str(case.get('status')).startswith('ASSIGNED:') else None
        updated = (self.desk.missions.feedback(mission_id, {**request, 'case_id': cid}, self.desk.feedback) if mission_id
                   else self.desk.feedback.submit(cid, request))
        last = (updated.get('feedback') or [{}])[-1]
        self.emit('crew_report', 'feedback', scenario_input=True, case_id=cid, message_id=row['ref'], mission_id=mission_id, text=row['text'],
                  outcomes=[{k: o.get(k) for k in ('kind', 'quote', 'value')} for o in last.get('outcomes', [])],
                  conflicts=last.get('conflicts', []), feedback_check=last.get('feedback_check'), status=updated.get('status'),
                  remaining_n=updated.get('remaining_n'))
        if updated.get('status') == 'PARTIAL':
            self.emit('requeue', 'feedback', case_id=cid, message_id=row['ref'], remaining_n=updated.get('remaining_n'),
                      decision=updated['result'].get('decision'), reason=updated['result'].get('decision_reason'))

    def do_tick(self, row):
        tick = self.desk.supervisor.tick(self.iso())
        self.emit('supervisor_tick', 'supervisor', tick_id=tick['tick_id'], cases_seen=tick['cases_seen'], findings=len(tick['findings']),
                  alerts=len(tick['alerts']), rechecks=len(tick['rechecks']), supervisor_check=tick['supervisor_check'],
                  fallback_reason=tick.get('fallback_reason'))
        for a in tick['alerts']:
            self.emit('supervisor_alert', 'supervisor', alert_id=a['alert_id'], alert_kind=a['kind'], case_ids=a['case_ids'],
                      case_id=a['case_ids'][0] if a['case_ids'] else None, why=a['why_pt'], action=a['action'], severity=a['severity'])
        for r in tick['rechecks']:
            self.emit('supervisor_recheck', 'supervisor', alert_id=r['alert_id'], outcome=r['outcome'], delta=r['delta_pt'],
                      case_id=(r['remaining_case_ids'] or [None])[0])
