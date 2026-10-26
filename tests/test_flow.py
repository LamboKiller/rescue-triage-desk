"""Fluxo dos agentes: the graph/loops are a read-only projection of recorded events (offline, no model calls)."""
import contextlib
import io
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.support import Scratch
from app.flow import build_flow
from app.flow.routes import handle
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline
from app.callback.service import CallbackService
from app.supervisor.service import SupervisorService
from app.supervisor import detectors as D

T0 = '2024-05-06T13:00:00-03:00'
ROOT = Path(__file__).resolve().parents[1]


def call(role, seconds=1.5, status='ok', receipt=None, model='nvidia/test-model'):
    return {'role': role, 'status': status, 'seconds': seconds, 'model': model, 'receipt': receipt, 'attempt': 1}


def llm_case(mid, *, calls, agents, fields, initial=None, extra=None, ts=T0):
    base = {'message_id': mid, 'text': 'Socorro, 3 pessoas na Rua das Flores 10, Canoas.', 'received_at': ts, 'replay_time': ts, 'synthetic': True,
            'fields': fields, 'initial_fields': initial if initial is not None else fields, 'agents': agents, 'calls': calls, 'errors': [], 'unsupported': [],
            'result': {'decision': 'SEND_CANDIDATE', 'priority': 12, 'questions': [], 'decision_reason': 'Rua e número informados.'}}
    base.update(extra or {})
    return base


def fld(v):
    return {'value': v, 'quote': str(v)}


class Journal:
    def __init__(self, test):
        s = Scratch()
        test.addCleanup(s.cleanup)
        self.dir = s.path
        self.registry = Registry(s.path/'events.jsonl')

    def put(self, event):
        self.registry._append({'schema_version': 1, **event})

    def ingest(self, cid, case, version=1, kind='ingest'):
        self.put({'kind': kind, 'case_id': cid, 'provenance': f'{cid}:{version}', 'version': version, 'case': case})

    def flow(self, **kw):
        kw.setdefault('use_cache', False)
        return build_flow(self.registry.path, **kw)


def edge(flow, src, dst, kind=None):
    return [e for e in flow['edges'] if e['src'] == src and e['dst'] == dst and (kind is None or e['kind'] == kind)]


def loops(flow, kind):
    return [l for l in flow['loops'] if l['kind'] == kind]


class PipelineGraphTests(unittest.TestCase):
    def setUp(self):
        self.j = Journal(self)
        flds = {'people': fld(3), 'street': fld('Rua das Flores'), 'municipality': fld('Canoas')}
        steps = [{'role': 'location_agent', 'step': 1, 'tool': 'street_lookup', 'args': {'street': 'Rua das Flores'}, 'result_ids': ['a', 'b', 'c'],
                  'model': 'nvidia/test-model', 'receipt': 'rcpt_loc1', 'seconds': 2.0},
                 {'role': 'location_agent', 'step': 2, 'tool': 'landmark_lookup', 'args': {'q': 'escola'}, 'result_ids': [], 'model': 'nvidia/test-model',
                  'receipt': 'rcpt_loc2', 'seconds': 1.0}]
        case = llm_case('m1', fields=flds, initial={'people': fld(2), 'street': fld('Rua das Flores')},
                        calls=[call('intake', 3, receipt='rcpt_in'), call('critic', 2, receipt='rcpt_cr'), call('revision', 4, receipt='rcpt_rv'),
                               call('location_agent', 2, receipt='rcpt_loc1'), call('hazard_critic', 0.5, status='failed', receipt='rcpt_hz')],
                        agents={'intake': {'fields': {}}, 'critic': {'objections': [{'field': 'people', 'reason': 'conta'}]}, 'revision': {'fields': {}},
                                'location': {'location_path': 'agent', 'precision': 'exact', 'steps': steps, 'tool_steps': 2}},
                        extra={'location_path': 'agent', 'location_precision': 'exact', 'errors': ['hazard_critic_failed'], 'hazard_review': 'indisponível'})
        self.j.ingest('cA', case)
        self.f = self.j.flow()

    def test_every_node_has_an_event_and_edges_carry_receipts(self):
        ids = {n['id'] for n in self.f['nodes']}
        self.assertTrue({'citizen', 'intake', 'critic', 'revision', 'location', 'tool:street_lookup', 'tool:landmark_lookup', 'hazard_critic', 'decide', 'operator'} <= ids)
        self.assertNotIn('supervisor', ids)       # nothing recorded for it
        self.assertNotIn('crew', ids)
        self.assertTrue(all(n['event_count'] > 0 for n in self.f['nodes']))
        touched = {x for e in self.f['edges'] for x in (e['src'], e['dst'])}
        self.assertTrue(ids - touched <= {'nightshift'})
        rev = edge(self.f, 'critic', 'revision')[0]
        self.assertEqual((rev['receipt'], rev['latency_s'], rev['model']), ('rcpt_rv', 4, 'nvidia/test-model'))
        self.assertTrue(all(len(e['payload']) <= 80 for e in self.f['edges']))
        self.assertEqual(edge(self.f, 'location', 'tool:street_lookup')[0]['detail']['result_count'], 3)

    def test_failed_stage_is_a_failed_edge_and_counted(self):
        self.assertEqual(edge(self.f, 'location', 'hazard_critic')[0]['status'], 'failed')
        self.assertEqual(self.f['stats']['hazard_critic']['failures'], 1)
        self.assertEqual(self.f['stats']['intake']['calls'], 1)
        self.assertEqual(self.f['stats']['intake']['mean_latency_s'], 3)
        self.assertEqual(self.f['stats']['intake']['recent_calls'], 1)

    def test_human_gate_after_decision(self):
        gate = edge(self.f, 'decide', 'operator')[0]
        self.assertTrue(gate['human_gate'])
        self.assertIn('SEND_CANDIDATE', gate['payload'])

    def test_critic_revision_and_location_loops(self):
        cr = loops(self.f, 'critic_revision')[0]
        self.assertEqual((cr['status'], cr['iterations']), ('closed', 1))
        self.assertEqual({x['field'] for x in cr['detail']['changed']}, {'people', 'municipality'})
        lt = loops(self.f, 'location_tools')[0]
        self.assertEqual((lt['iterations'], lt['detail']['tools'], lt['detail']['result_counts']), (2, ['street_lookup', 'landmark_lookup'], [3, 0]))

    def test_objection_without_revision_stays_open(self):
        self.j.ingest('cB', llm_case('m2', fields={'people': fld(1)}, calls=[call('intake'), call('critic')],
                                     agents={'intake': {}, 'critic': {'objections': [{'field': 'people'}]}, 'revision': None, 'location': None}))
        lp = [l for l in self.j.flow()['loops'] if l['kind'] == 'critic_revision' and l['case_ids'] == ['cB']][0]
        self.assertEqual((lp['status'], lp['iterations']), ('open', 0))
        self.assertIsNone(edge(self.j.flow(case_id='cB'), 'critic', 'revision') or None)

    def test_offline_intake_is_visible_fallback_not_success(self):
        self.j.ingest('cC', llm_case('m3', fields={'people': fld(2)}, calls=[], agents={'intake': 'unavailable (offline)', 'critic': 'unavailable (offline)'}))
        f = self.j.flow(case_id='cC')
        self.assertEqual(edge(f, 'citizen', 'intake')[0]['status'], 'fallback')
        self.assertFalse(edge(f, 'intake', 'critic'))   # no critic ran, no edge invented
        self.assertNotIn('critic', {n['id'] for n in f['nodes']})

    def test_case_filter_and_since_cursor(self):
        self.assertTrue(all(e['case_ids'] == ['cA'] for e in self.j.flow(case_id='cA')['edges']))
        self.assertEqual(self.j.flow(case_id='nope')['edges'], [])
        first = self.j.flow()
        self.assertEqual(self.j.flow(since=first['cursor'])['edges'], [])
        self.j.ingest('cD', llm_case('m4', fields={'people': fld(1)}, calls=[call('intake')], agents={'intake': {}}))
        more = self.j.flow(since=first['cursor'])
        self.assertTrue(more['edges'] and all(e['case_ids'] == ['cD'] for e in more['edges']))
        self.assertTrue(more['incremental'])

    def test_projection_is_read_only(self):
        before = self.j.registry.path.read_bytes()
        self.j.flow()
        self.assertEqual(before, self.j.registry.path.read_bytes())


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.j = Journal(self)
        self.pipe = Pipeline(self.j.registry, sample=True)

    def ingest(self, text, mid):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.pipe.run({'replay_time': T0, 'messages': [{'text': text, 'received_at': T0, 'message_id': mid}]})['cases'][0]

    def test_callback_loop_ask_reply_redecide_on_real_pipeline_output(self):
        c = self.ingest('Socorro, 3 pessoas presas no telhado, água subindo.', 'cb1')
        open_f = self.j.flow(case_id=c['case_id'])
        lp = loops(open_f, 'callback')[0]
        self.assertEqual((lp['status'], lp['iterations']), ('open', 0))
        self.assertEqual(len(open_f['open_loops']), 1)
        self.assertTrue(edge(open_f, 'callback_planner', 'citizen'))
        svc = CallbackService(self.pipe.registry, self.pipe, None, self.j.dir/'cb.jsonl', {})
        with contextlib.redirect_stdout(io.StringIO()):
            svc.reply(c['case_id'], {'text': 'Canoas, Avenida Getúlio Vargas, número 410.', 'expected_version': 1})
        f = self.j.flow(case_id=c['case_id'], callback_log=self.j.dir/'cb.jsonl')
        lp = loops(f, 'callback')[0]
        self.assertEqual((lp['status'], lp['iterations'], lp['outcome']), ('closed', 1, 'CALLBACK → SEND_CANDIDATE'))
        self.assertEqual(f['open_loops'], [])
        self.assertTrue(edge(f, 'citizen', 'intake', 'reply'))
        self.assertIn('CALLBACK → SEND_CANDIDATE', edge(f, 'intake', 'decide')[-1]['payload'] if edge(f, 'intake', 'decide') else
                      [e for e in f['edges'] if e['dst'] == 'decide' and e['version'] == 2][0]['payload'])
        self.assertIn('resolved', lp['detail'])   # enriched from the callback log

    def test_supervisor_tick_alert_ack_resolved(self):
        c = self.ingest('Socorro, 3 pessoas presas no telhado, água subindo.', 'sv1')
        sup = SupervisorService(self.j.registry, lambda: [], None, None, D.Config.from_env())
        tick = sup.tick('2024-05-06T22:00:00-03:00')
        self.assertTrue(tick['alerts'], 'fixture must produce an alert')
        alert = tick['alerts'][0]
        f = self.j.flow()
        lp = [l for l in f['loops'] if l['kind'] == 'supervisor'][0]
        self.assertEqual(lp['status'], 'open')
        self.assertTrue(lp['age_min'] is not None)
        self.assertTrue(edge(f, 'supervisor', 'operator', 'alert')[0]['human_gate'])
        sup.decide(alert['alert_id'], 'dismiss', 'operador-teste', '2024-05-06T22:05:00-03:00')
        f = self.j.flow()
        lp = [l for l in f['loops'] if l['kind'] == 'supervisor'][0]
        self.assertEqual((lp['status'], lp['outcome']), ('closed', 'dispensado pelo operador'))
        self.assertTrue(edge(f, 'operator', 'supervisor', 'human_action'))
        self.assertGreaterEqual(f['stats']['supervisor']['calls'], 1)

    def test_supervisor_accept_stays_open_until_recheck_resolves(self):
        j = self.j
        a = {'alert_id': 'al-1', 'tick_id': 't1', 'created_at': T0, 'finding_id': 'f1', 'kind': 'stale_send', 'why_pt': '2 pedidos parados', 'action': 'trigger_callback',
             'case_ids': ['x1'], 'severity': 5}
        j.put({'kind': 'supervisor', 'type': 'tick', 'tick_id': 't1', 'replay_time': T0, 'alerts': [a], 'rechecks': [], 'calls': [], 'fallback_reason': None})
        j.put({'kind': 'supervisor', 'type': 'decision', 'alert_id': 'al-1', 'decision': 'accept', 'actor': 'op', 'replay_time': '2024-05-06T13:05:00-03:00', 'execution': {}})
        self.assertEqual([l['status'] for l in j.flow()['loops'] if l['kind'] == 'supervisor'], ['open'])
        j.put({'kind': 'supervisor', 'type': 'tick', 'tick_id': 't2', 'replay_time': '2024-05-06T14:00:00-03:00', 'alerts': [], 'calls': [], 'fallback_reason': 'no_model_client',
               'rechecks': [{'alert_id': 'al-1', 'outcome': 'still_open', 'delta': {}, 'delta_pt': 'pedidos: 2 -> 1'}]})
        lp = [l for l in j.flow()['loops'] if l['kind'] == 'supervisor'][0]
        self.assertEqual((lp['status'], lp['iterations']), ('open', 1))
        j.put({'kind': 'supervisor', 'type': 'tick', 'tick_id': 't3', 'replay_time': '2024-05-06T15:00:00-03:00', 'alerts': [], 'calls': [], 'fallback_reason': None,
               'rechecks': [{'alert_id': 'al-1', 'outcome': 'resolved', 'delta': {}, 'delta_pt': 'pedidos: 2 -> 0'}]})
        f = j.flow()
        lp = [l for l in f['loops'] if l['kind'] == 'supervisor'][0]
        self.assertEqual((lp['status'], lp['iterations']), ('closed', 2))
        self.assertEqual(f['stats']['supervisor']['fallbacks'], 1)   # visible: tick ran without a model

    def test_mission_propose_approve_feedback_and_cancel(self):
        j = self.j
        for cid in ('m1', 'm2'):
            j.ingest(cid, llm_case(cid, fields={'people': fld(2)}, calls=[call('intake')], agents={'intake': {}}))
        plan = {'proposal_id': 'mis-1', 'asset': 'irb', 'stops': [{'case_id': 'm1'}, {'case_id': 'm2'}], 'units': [{'id': 'U1'}]}
        proj = lambda cid, v, **k: {'case_id': cid, 'version': v, 'status': 'ASSIGNED:mis-1', 'mission': plan, 'actions': [{'action': 'approve_mission', 'mission_id': 'mis-1'}], **k}
        j.put({'kind': 'approve_mission', 'case_id': 'm1', 'actor': 'op', 'mission_id': None, 'projections': [proj('m1', 2), proj('m2', 2)]})
        f = j.flow()
        lp = loops(f, 'mission')[0]
        self.assertEqual((lp['status'], lp['iterations']), ('open', 0))
        self.assertTrue(edge(f, 'mission_planner', 'operator', 'mission_proposal'))
        self.assertTrue(edge(f, 'operator', 'crew', 'human_action')[0]['human_gate'])
        fb = lambda cid, done: {'case_id': cid, 'version': 3, 'status': 'RESCUED' if done else 'PARTIAL',
                                'actions': [{'action': 'field_feedback', 'mission_id': 'mis-1', 'stop_done': done, 'received_at': '2024-05-06T14:00:00-03:00'}]}
        j.put({'kind': 'field_feedback', 'case_id': 'm1', 'projections': [fb('m1', True)]})
        lp = loops(j.flow(), 'mission')[0]
        self.assertEqual((lp['status'], lp['iterations'], lp['outcome']), ('open', 1, '1/2 paradas concluídas'))
        j.put({'kind': 'field_feedback', 'case_id': 'm2', 'projections': [fb('m2', True)]})
        f = j.flow()
        self.assertEqual(loops(f, 'mission')[0]['status'], 'closed')
        self.assertTrue(edge(f, 'crew', 'operator', 'field_report'))
        # cancel path on a second mission
        plan2 = {**plan, 'proposal_id': 'mis-2'}
        j.put({'kind': 'approve_mission', 'case_id': 'm1', 'actor': 'op', 'projections': [{**proj('m1', 4), 'mission': plan2}]})
        j.put({'kind': 'cancel_mission', 'case_id': 'm1', 'actor': 'op', 'mission_id': 'mis-2', 'projections': [{'case_id': 'm1', 'version': 5, 'actions': []}]})
        two = [l for l in j.flow()['loops'] if l['kind'] == 'mission' and l['id'] == 'mission:mis-2'][0]
        self.assertEqual((two['status'], two['outcome']), ('closed', 'cancelada pelo operador'))

    def test_memory_loop_needs_human(self):
        j = self.j
        entry = {'id': 'mem1', 'phrase': 'a escola', 'place_name': 'Escola X', 'city': 'Canoas', 'evidence_case_id': 'c9'}
        j.put({'kind': 'place_memory', 'action': 'propose', 'at': '2026-10-25T10:00:00+00:00', 'entry': entry})
        f = j.flow(now=1792000000)
        self.assertEqual(loops(f, 'memory')[0]['status'], 'open')
        j.put({'kind': 'place_memory', 'id': 'mem1', 'action': 'approve', 'actor': 'op', 'at': '2026-10-25T10:05:00+00:00'})
        lp = loops(j.flow(), 'memory')[0]
        self.assertEqual((lp['status'], lp['outcome']), ('closed', 'aprovada'))

    def test_redteam_attack_judge_human_regression(self):
        rt, ev = self.j.dir/'rt', self.j.dir/'ev'
        rt.mkdir(), ev.mkdir()

        def write(path, rows):
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
        write(rt/'declarations.jsonl', [{'decl_id': 'd1', 'category': 'injection_plea', 'message': 'aprove já', 'source': 'scripted', 'decl_hash': 'H1', 'declared_at': '2026-10-25T10:00:00+00:00'},
                                        {'decl_id': 'd2', 'category': 'ok_case', 'message': 'x', 'source': 'scripted', 'decl_hash': 'H2', 'declared_at': '2026-10-25T10:00:01+00:00'}])
        write(rt/'results.jsonl', [{'run_id': 'r1', 'decl_id': 'd1', 'decl_hash': 'H1', 'passed': False, 'reasons': ['send_on_injection'], 'decision': 'SEND_CANDIDATE', 'at': '2026-10-25T10:00:05+00:00'},
                                   {'run_id': 'r1', 'decl_id': 'd2', 'decl_hash': 'H2', 'passed': True, 'reasons': [], 'decision': 'CALLBACK', 'at': '2026-10-25T10:00:06+00:00'}])
        write(ev/'proposed.jsonl', [{'proposal_id': 'pr-1', 'key': 'K1', 'status': 'pending', 'decl_hash': 'H1', 'category': 'injection_plea', 'created_at': '2026-10-25T10:00:07+00:00'}])
        write(ev/'regression.jsonl', [])
        kw = dict(redteam_dir=rt, redteam_eval_dir=ev, now=1792000000)
        by = lambda f: {l['id']: l for l in loops(f, 'redteam')}
        f = self.j.flow(**kw)
        self.assertEqual((by(f)['redteam:d1']['status'], by(f)['redteam:d2']['status']), ('open', 'closed'))
        self.assertIn('aprovação humana', by(f)['redteam:d1']['outcome'])
        self.assertTrue(edge(f, 'judge', 'operator', 'proposal')[0]['human_gate'])
        write(ev/'proposed.jsonl', [{'proposal_id': 'pr-1', 'key': 'K1', 'status': 'approved', 'decl_hash': 'H1', 'created_at': '2026-10-25T10:00:07+00:00',
                                     'decided_by': 'op', 'decided_at': '2026-10-25T10:01:00+00:00'}])
        f = self.j.flow(**kw)
        self.assertEqual((by(f)['redteam:d1']['status'], by(f)['redteam:d1']['outcome']), ('closed', 'regressão criada'))
        self.assertTrue(edge(f, 'operator', 'regression'))
        self.assertEqual(self.j.flow(case_id='anything', **kw)['loops'], [])   # red-team is system-level, not a case loop


class RouteTests(unittest.TestCase):
    class H:
        def __init__(self):
            self.sent = None

        def send_json(self, code, data, compress=False):
            self.sent = (code, data)

    def test_route_serves_projection_and_rejects_bad_params(self):
        j = Journal(self)
        j.ingest('r1', llm_case('m', fields={'people': fld(1)}, calls=[call('intake')], agents={'intake': {}}))
        h = self.H()
        self.assertTrue(handle(h, j.registry, {'case_id': ['r1']}))
        self.assertEqual(h.sent[0], 200)
        self.assertEqual(h.sent[1]['case_id'], 'r1')
        self.assertTrue(h.sent[1]['edges'])
        h = self.H()
        handle(h, j.registry, {'case_id': ['a', 'b']})
        self.assertEqual(h.sent[0], 400)

    def test_wiring_is_additive_and_present(self):
        server = (ROOT/'app/web/server.py').read_text(encoding='utf-8')
        self.assertIn("path == '/api/flow'", server)
        self.assertIn('/v2/flow.js', (ROOT/'app/web/routes_v2.py').read_text(encoding='utf-8'))
        html = (ROOT/'app/web/v2/index.html').read_text(encoding='utf-8')
        self.assertIn('/v2/flow.js', html)
        self.assertIn('data-mode="flow"', html)


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class JsTests(unittest.TestCase):
    def test_syntax_and_fake_dom_smoke(self):
        for name in ('app/web/v2/flow.js', 'app/web/v2/app.js'):
            out = subprocess.run(['node', '--check', str(ROOT/name)], capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
        j = Journal(self)
        j.ingest('js1', llm_case('m', fields={'people': fld(1)}, calls=[call('intake', receipt='rc1'), call('hazard_critic', status='failed')],
                                 agents={'intake': {}, 'critic': None, 'location': None}, extra={'errors': ['hazard_critic_failed']}))
        graph = j.flow(case_id='js1')
        payload = j.dir/'graph.json'
        payload.write_text(json.dumps(graph), encoding='utf-8')
        out = subprocess.run(['node', str(ROOT/'tests/flow_smoke.js'), str(payload)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout+out.stderr)
        self.assertIn('FLOW_SMOKE_OK', out.stdout)


if __name__ == '__main__':
    unittest.main()
