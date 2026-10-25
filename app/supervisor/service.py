"""Supervisor ticks and the act -> observe -> re-check loop. State lives in the World Model journal as
kind='supervisor' events (append-only); nothing here can approve a dispatch or mission."""
import copy
import hashlib
import json
import threading
from datetime import timedelta
from app.decide import timestamp
from app.engines.world_model.registry import Conflict
from app.redact import redact
from app.supervisor import detectors as D
from app.supervisor.agent import Supervisor

MAX_SERIES = 24
ADDRESSED = ('human_approved', 'dispatched', 'callback_requested')


def _iso(dt):
    return dt.isoformat()


class SupervisorService:
    def __init__(self, registry, inventory_fn=None, proposals_fn=None, client=None, cfg=None):
        self.registry = registry
        self.inventory_fn = inventory_fn or (lambda: [])
        self.proposals_fn = proposals_fn
        self.agent = Supervisor(client)
        self.cfg = cfg or D.Config.from_env()
        self.lock = threading.RLock()

    # ---- journal ---------------------------------------------------------------------------
    def events(self):
        with self.registry.locked():
            if not self.registry.path.exists():
                return []
            out = []
            for line in self.registry.path.read_text(encoding='utf-8').splitlines():
                if '"kind":"supervisor"' in line:
                    e = json.loads(line)
                    if e.get('kind') == 'supervisor':
                        out.append(e)
            return out

    def state(self):
        ticks, alerts, first_seen, callbacks = [], {}, {}, {}
        for e in self.events():
            if e['type'] == 'tick':
                ticks.append(e)
                for mid, when in e.get('missions_seen', {}).items():
                    first_seen.setdefault(mid, when)
                for a in e['alerts']:
                    alerts[a['alert_id']] = {**copy.deepcopy(a), 'status': 'open', 'outcome': None, 'rechecks': [], 'decision': None}
                for r in e['rechecks']:
                    a = alerts.get(r['alert_id'])
                    if a:
                        a['outcome'] = r['outcome']
                        a['rechecks'].append({**r, 'tick_id': e['tick_id'], 'replay_time': e['replay_time']})
            else:
                a = alerts.get(e['alert_id'])
                if a:
                    a['status'] = 'accepted' if e['decision'] == 'accept' else 'dismissed'
                    a['decision'] = {k: e.get(k) for k in ('decision', 'actor', 'replay_time', 'execution')}
                    for r in (e.get('execution') or {}).get('results', []):
                        if r.get('ok') and r.get('case_id') and (e['execution'] or {}).get('action') == 'trigger_callback':
                            callbacks[r['case_id']] = e['replay_time']
        return {'ticks': ticks, 'alerts': alerts, 'first_seen': first_seen, 'callback_times': callbacks}

    # ---- re-check --------------------------------------------------------------------------
    @staticmethod
    def recheck(alert, by_id, current):
        orig = set(alert['case_ids'])
        if alert['kind'] == 'cluster_growth':
            left = sorted(c for c in orig if c in by_id and D.is_open(by_id[c]) and not by_id[c].get('status', '').startswith('ASSIGNED:')
                          and by_id[c].get('status') not in ADDRESSED)
            subject = 'pedidos sem atendimento'
        else:
            cur = current.get(alert['finding_id'])
            left = sorted(orig & set(cur['case_ids'])) if cur else []
            subject = 'pedidos ainda no achado'
            if alert['kind'] == 'idle_resources' and cur and not set(alert['resource_ids']) & set(cur['resource_ids']):
                left = []
        removed = sorted(orig - set(left))
        outcome = 'still_open' if left else 'resolved'
        return {'alert_id': alert['alert_id'], 'outcome': outcome, 'remaining_case_ids': left,
                'delta': {'before': len(orig), 'after': len(left), 'removed_case_ids': removed},
                'delta_pt': f"{subject}: {len(orig)} -> {len(left)}"}

    # ---- tick ------------------------------------------------------------------------------
    def tick(self, now):
        timestamp(now)
        with self.lock:
            st = self.state()
            cases = self.registry.read()
            findings, seen = D.detect(cases, now, self.inventory_fn(), self.cfg, st['first_seen'], st['callback_times'])
            by_id = {c['case_id']: c for c in seen}
            current = {f['id']: f for f in findings}
            rechecks = [self.recheck(a, by_id, current) for a in st['alerts'].values()
                        if a['status'] == 'accepted' and a['outcome'] != 'resolved' and a['decision']
                        and timestamp(now) >= timestamp(a['decision']['replay_time'])]
            blocked = set()
            for a in st['alerts'].values():
                if a['status'] == 'open' or (a['status'] == 'accepted' and a['outcome'] != 'resolved'):
                    blocked.add(a['finding_id'])
            fresh = []
            for f in findings:
                if f['id'] in blocked:
                    continue
                dismissed = [set(a['case_ids']) for a in st['alerts'].values() if a['finding_id'] == f['id'] and a['status'] == 'dismissed']
                if dismissed and any(set(f['case_ids']) <= d for d in dismissed):
                    continue
                fresh.append(f)
            n = sum(1 for t in st['ticks'] if t['replay_time'] == now)+1
            tick_id = 't-'+hashlib.sha1(f'{now}#{n}'.encode()).hexdigest()[:10]
            ranked = self.agent.rank(fresh, tick_id)
            alerts = []
            for r in ranked['alerts']:
                f = current[r['finding_id']]
                alerts.append({'alert_id': 'al-'+hashlib.sha1((tick_id+f['id']).encode()).hexdigest()[:10], 'tick_id': tick_id,
                               'created_at': now, 'finding_id': f['id'], 'kind': f['kind'], 'why_pt': r['why_pt'],
                               'action': r['action'], 'action_label_pt': D.ACTION_LABEL_PT[r['action']],
                               'case_ids': f['case_ids'], 'resource_ids': f['resource_ids'], 'mission_ids': f['mission_ids'],
                               'facts': f['facts'], 'numbers': f['numbers'], 'evidence': f['evidence'], 'severity': f['severity']})
            alerted = {a['finding_id'] for a in alerts}
            event = {'schema_version': 1, 'kind': 'supervisor', 'type': 'tick', 'tick_id': tick_id, 'replay_time': now,
                     'interval_min': self.cfg.interval_min, 'cases_seen': len(seen),
                     'findings': [{k: f[k] for k in ('id', 'kind', 'case_ids', 'resource_ids', 'numbers', 'severity', 'facts')} for f in findings],
                     'alerts': alerts, 'rechecks': rechecks, 'unalerted_finding_ids': [f['id'] for f in fresh if f['id'] not in alerted],
                     'supervisor_check': ranked['supervisor_check'], 'rejected_alerts': ranked['rejected'],
                     'fallback_reason': ranked.get('fallback_reason'), 'calls': ranked['calls'],
                     'missions_seen': {mid: now for mid, ms in D.missions_state(seen).items()
                                       if any(c.get('status') == 'ASSIGNED:'+mid for c in ms)}}
            with self.registry.locked():
                self.registry._append(json.loads(redact(json.dumps(event, ensure_ascii=False))))
            return event

    def run(self, start, until=None):
        timestamp(start)
        out, t = [], timestamp(start)
        end = timestamp(until) if until else t
        step = timedelta(minutes=self.cfg.interval_min)
        while t <= end and len(out) < MAX_SERIES:
            out.append(self.tick(_iso(t)))
            t += step
        return out

    def ticks(self, day):
        st = self.state()
        ticks = [t for t in st['ticks'] if t['replay_time'][:10] == day]
        alerts = [a for a in st['alerts'].values() if a['created_at'][:10] == day]
        return {'date': day, 'interval_min': self.cfg.interval_min, 'config': self.cfg.__dict__, 'ticks': ticks,
                'alerts': sorted(alerts, key=lambda a: (a['created_at'], -a['severity'])),
                'counts': {'open': sum(a['status'] == 'open' for a in alerts), 'accepted': sum(a['status'] == 'accepted' for a in alerts),
                           'dismissed': sum(a['status'] == 'dismissed' for a in alerts),
                           'resolved': sum(a['outcome'] == 'resolved' for a in alerts),
                           'still_open': sum(a['outcome'] == 'still_open' for a in alerts)}}

    # ---- human decision -> existing API -----------------------------------------------------
    def decide(self, alert_id, decision, actor, replay_time=None):
        if decision not in ('accept', 'dismiss'):
            raise ValueError('Decisão deve ser accept ou dismiss.')
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError('Identifique o operador.')
        with self.lock:
            alert = self.state()['alerts'].get(alert_id)
            if alert is None:
                raise KeyError(alert_id)
            if alert['status'] != 'open':
                raise Conflict('Alerta já decidido.')
            when = replay_time or alert['created_at']
            timestamp(when)
            actor = redact(actor.strip())
            execution = self.execute(alert, actor, when) if decision == 'accept' else None
            event = {'schema_version': 1, 'kind': 'supervisor', 'type': 'decision', 'alert_id': alert_id,
                     'decision': decision, 'actor': actor, 'replay_time': when, 'execution': execution}
            with self.registry.locked():
                self.registry._append(event)
            return self.state()['alerts'][alert_id]

    def execute(self, alert, actor, when):
        """Calls the existing human-facing API for the action; the supervisor never approves anything."""
        action, results = alert['action'], []
        if action == 'trigger_callback':
            for cid in alert['case_ids'][:5]:
                case = self.registry.read(cid)
                if not case or case.get('status') in ('callback_requested',) or case.get('status', '').startswith('ASSIGNED:') or not D.is_open(case):
                    results.append({'case_id': cid, 'ok': False, 'skipped': True,
                                    'error': 'caso em missão, encerrado ou retorno já solicitado'})
                    continue
                try:
                    c = self.registry.action(cid, 'request_callback', case['version'], actor, human=True)
                    results.append({'case_id': cid, 'ok': True, 'status': c['status'], 'version': c['version']})
                except (Conflict, ValueError, KeyError) as exc:
                    results.append({'case_id': cid, 'ok': False, 'error': str(exc)[:200]})
            if not any(r['ok'] for r in results):
                raise Conflict('Nenhum retorno pôde ser solicitado: '+'; '.join(r['error'] for r in results))
            summary = f"{sum(r['ok'] for r in results)} retornos solicitados"
        elif action == 'create_mission_proposal':
            if self.proposals_fn is None:
                raise Conflict('Planejador de missões indisponível.')
            plans = self.proposals_fn(when[:10])['proposals']
            ids = set(alert['case_ids'])
            for p in plans:
                if ids & {s['case_id'] for s in p['stops']}:
                    results.append({'ok': True, 'proposal_id': p['proposal_id'], 'case_ids': [s['case_id'] for s in p['stops']],
                                    'asset': p.get('asset'), 'blocking_reasons': p.get('blocking_reasons', [])})
            summary = (f"{len(results)} propostas geradas para revisão humana em Missões; nada foi aprovado" if results else
                       'Nenhuma proposta elegível (recursos, localização ou profundidade); ver Missões')
        elif action == 'reprioritise':
            from app.priority import queue
            top = queue(self.registry.read(), when)[:5]
            results = [{'ok': True, 'case_id': c['case_id'], 'priority': c['live_priority']['score'], 'place': D.place(c)} for c in top]
            summary = 'Fila recalculada com prioridade ao vivo; ordem no topo registrada'
        elif action == 'request_resources':
            results = [{'ok': True, 'case_ids': alert['case_ids'][:10], 'note': 'Pedido registrado no World Model; nenhum sistema externo acionado.'}]
            summary = 'Pedido de reforço registrado para o coordenador'
        else:
            raise ValueError('Ação desconhecida.')
        return {'action': action, 'ok': True, 'summary_pt': summary, 'results': results}
