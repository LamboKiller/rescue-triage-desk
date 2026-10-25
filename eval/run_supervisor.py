"""Supervisor eval: 10 author-written scenarios over real street points (data/hazards/street_points.csv).
Offline uses a scripted agent (copies the top findings; no network). --live uses Nemotron via Nightshift.

Reports detector precision/recall, exact subject sets, uncited numbers in alerts, whether a bad agent
output is rejected, and act -> observe -> re-check loop correctness. Cases, times and resources are synthetic.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.agents.hazard_critic import numbers
from app.engines.world_model.registry import Registry
from app.feedback import FeedbackService
from app.supervisor.service import SupervisorService
from app.supervisor.detectors import Config
from tools.scratch import scratch

SET = Path(__file__).with_name('supervisor_set.jsonl')


def cid(key): return hashlib.sha256(('sup-'+key).encode()).hexdigest()[:24]


class ScriptedAgent:
    """Offline stand-in for Nemotron: valid JSON copying the top findings' own first sentence."""
    def __init__(self): self.calls = 0

    def call(self, role, system, payload, deadline):
        self.calls += 1
        found = json.loads(payload)['findings']
        alerts = [{'finding_id': f['id'], 'why_pt': re.split(r'(?<=[a-z\)])\.\s', f['text_pt'])[0].rstrip('.')+'.', 'action': f['allowed_actions'][0]} for f in found[:3]]
        return {'alerts': alerts}, {'role': role, 'status': 'ok', 'scripted': True}


class InventingAgent:
    """Adversarial: writes a number that is not in the finding. Must be rejected -> deterministic_only."""
    def call(self, role, system, payload, deadline):
        f = json.loads(payload)['findings'][0]
        return {'alerts': [{'finding_id': f['id'], 'why_pt': 'Há 37 pedidos críticos; agir agora.', 'action': f['allowed_actions'][0]}]}, {'role': role, 'status': 'ok'}


def seed(registry, spec, c):
    date = spec['date']
    at = lambda hhmm: f'{date}T{hhmm}:00-03:00'
    fields = {'people': {'value': c['people'], 'quote': 'sintético'}, 'street': {'value': c['street'], 'quote': c['street']},
              'municipality': {'value': c['municipality'], 'quote': c['municipality']}}
    case = {'message_id': 'sup-'+c['key'], 'text': 'Pedido de socorro sintético para o eval do supervisor.', 'synthetic': True,
            'received_at': at(c['received']), 'replay_time': at('23:59'), 'fields': fields,
            'position': {'lat': c['lat'], 'lon': c['lon'], 'position_kind': 'street_reference'},
            'result': {'decision': c.get('decision', 'SEND_CANDIDATE'), 'priority': 0, 'questions': []}, 'errors': [], 'fleet': []}
    if c.get('updated'): case['last_update_at'] = at(c['updated'])
    m = c.get('mission')
    if m:
        done = c['key'] in m['done']
        case.update(mission_id=m['id'], mission={'stops': [{'case_id': cid(k)} for k in m['stops']], 'units': []},
                    mission_stop_done=done, status='RESCUED' if done else 'ASSIGNED:'+m['id'],
                    last_update_at=at(m['feedback_at'] if done else c.get('updated', c['received'])))
        if done: case['feedback'] = [{'received_at': at(m['feedback_at']), 'text': 'retorno sintético', 'conflicts': []}]
    return registry.ingest(case)


def inventory(spec):
    return [{'id': u['id'], 'asset': u['asset'], 'capacity': u['capacity'], 'available': u['available'],
             'observed_date': u['observed_date'], 'synthetic': True} for u in spec['resources']]


def uncited(event):
    bad = 0
    facts = {f['id']: f for fd in event['findings'] for f in fd['facts']}
    for a in event['alerts']:
        allowed = {abs(x) for f in a['facts'] for x in numbers(f['text_pt'])} | {abs(x) for x in numbers(a['finding_id'])}
        bad += not {abs(x) for x in numbers(a['why_pt'])} <= allowed
    return bad


def run_scenario(spec, client, cfg):
    with scratch() as folder:
        registry = Registry(Path(folder)/'events.jsonl')
        for c in spec['cases']: seed(registry, spec, c)
        proposals = lambda day: {'proposals': [{'proposal_id': 'synthetic-proposal', 'stops': [{'case_id': cid(c['key'])} for c in spec['cases']], 'asset': None, 'blocking_reasons': ['eval stub']}]}
        service = SupervisorService(registry, lambda: inventory(spec), proposals, client, cfg)
        now = f"{spec['date']}T{spec['now']}:00-03:00"
        tick = service.tick(now)
        inv = {cid(c['key']): c['key'] for c in spec['cases']}
        found = {f['kind']: f for f in tick['findings']}
        exp = spec['expect']
        got_cases = {k: sorted(inv[i] for i in f['case_ids']) for k, f in found.items()}
        exact = all(got_cases.get(k) == sorted(v) for k, v in exp.get('cases', {}).items())
        res_ok = all(sorted(found.get('idle_resources', {}).get('resource_ids', [])) == sorted(exp['resources']) for _ in [0] if 'resources' in exp)
        out = {'id': spec['id'], 'expected_kinds': sorted(exp['kinds']), 'got_kinds': sorted(found), 'subjects_exact': exact and res_ok,
               'alerts': len(tick['alerts']), 'uncited_numbers': uncited(tick), 'supervisor_check': tick['supervisor_check']}
        loop = spec.get('loop')
        if loop:
            alert = next((a for a in tick['alerts'] if a['kind'] == loop['accept']), None)
            if alert is None:
                out['loop'] = {'correct': False, 'reason': 'no alert for finding'}
            else:
                alert = service.decide(alert['alert_id'], 'accept', 'eval-operator', now)
                fb = FeedbackService(registry)
                for op in loop['after']:
                    c = next(x for x in spec['cases'] if x['key'] == op['case'])
                    case = registry.read(cid(c['key']))
                    fb.submit(case['case_id'], {'actor': 'eval-operator', 'text': f"resgatamos {c['people']}", 'source': 'crew',
                                                'received_at': f"{spec['date']}T12:10:00-03:00",
                                                'expected_version': case['version']})
                second = service.tick(f"{spec['date']}T12:30:00-03:00")
                final = service.state()['alerts'][alert['alert_id']]
                out['loop'] = {'accepted_action': alert['action'], 'executed': alert['decision']['execution']['summary_pt'],
                               'outcome': final['outcome'], 'expected': loop['outcome'], 'delta_pt': (final['rechecks'] or [{}])[-1].get('delta_pt'),
                               'correct': final['outcome'] == loop['outcome'] and alert['action'] == loop['action'],
                               'second_tick_uncited': uncited(second)}
        return out


def evaluate(live=False):
    specs = [json.loads(l) for l in SET.read_text(encoding='utf-8').splitlines() if l.strip()]
    cfg = Config()
    agent = None
    if live:
        from app.missions.client import MissionClient
        agent = MissionClient(ROOT/'runtime/supervisor_eval_trace.jsonl')
    results = [run_scenario(s, agent if live else ScriptedAgent(), cfg) for s in specs]
    tp = sum(len(set(r['expected_kinds']) & set(r['got_kinds'])) for r in results)
    fp = sum(len(set(r['got_kinds']) - set(r['expected_kinds'])) for r in results)
    fn = sum(len(set(r['expected_kinds']) - set(r['got_kinds'])) for r in results)
    loops = [r['loop'] for r in results if 'loop' in r]
    bad = run_scenario(specs[0], InventingAgent(), cfg)
    return {'mode': 'live' if live else 'offline', 'synthetic': True, 'scenarios': len(results), 'tp': tp, 'fp': fp, 'fn': fn,
            'precision': tp/(tp+fp) if tp+fp else 1.0, 'recall': tp/(tp+fn) if tp+fn else 1.0,
            'subjects_exact': sum(r['subjects_exact'] for r in results), 'uncited_numbers': sum(r['uncited_numbers'] for r in results)+sum(l.get('second_tick_uncited', 0) for l in loops),
            'loops': len(loops), 'loops_correct': sum(l['correct'] for l in loops),
            'inventing_agent': {'supervisor_check': bad['supervisor_check'], 'uncited_numbers': bad['uncited_numbers']},
            'results': results,
            'limits': 'Author-written synthetic scenarios over real street coordinates; world changes in loops are simulated through the real feedback service. Offline uses a scripted agent, so it verifies detectors, validator and loop code, not model quality.'}


if __name__ == '__main__':
    load_env(); p = argparse.ArgumentParser(description=__doc__); m = p.add_mutually_exclusive_group()
    m.add_argument('--offline', action='store_true'); m.add_argument('--live', action='store_true'); p.add_argument('--output', type=Path)
    a = p.parse_args(); r = evaluate(a.live); text = json.dumps(r, ensure_ascii=False, indent=2)
    if a.output: a.output.write_text(text+'\n', encoding='utf-8')
    print(text)
    raise SystemExit(not (r['fp'] == 0 and r['fn'] == 0 and r['uncited_numbers'] == 0 and r['loops_correct'] == r['loops']
                          and r['subjects_exact'] == r['scenarios'] and r['inventing_agent']['supervisor_check'] == 'deterministic_only'))
