"""Supervisor: detectors, cited-number validator, fallback visibility, loop closure, HTTP, journal safety."""
import contextlib
import copy
import http.client
import importlib.util
import json
import threading
import unittest
from pathlib import Path
from app.config import ROOT
from app.engines.world_model.registry import Registry
from app.supervisor import detectors as D
from app.supervisor.agent import Supervisor, validate, template
from app.supervisor.service import SupervisorService
from tests.support import Scratch

spec = importlib.util.spec_from_file_location('run_supervisor', ROOT/'eval/run_supervisor.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

DAY = '2024-05-08'
NOW = DAY+'T12:00:00-03:00'
CFG = D.Config()


def case(cid, lat=-29.898964, lon=-51.135298, received='11:30', people=2, **kw):
    c = {'case_id': cid, 'version': 1, 'status': 'proposed', 'received_at': f'{DAY}T{received}:00-03:00',
         'position': {'lat': lat, 'lon': lon}, 'fields': {'people': {'value': people}, 'street': {'value': 'Rua Teste'}},
         'result': {'decision': 'SEND_CANDIDATE', 'priority': 0}}
    c.update(kw)
    return c


class Scripted:
    def __init__(self, output): self.output = output; self.calls = 0

    def call(self, role, system, payload, deadline):
        self.calls += 1
        if isinstance(self.output, Exception): raise self.output
        out = self.output(json.loads(payload)) if callable(self.output) else self.output
        return out, {'role': role, 'status': 'ok'}


class DetectorTests(unittest.TestCase):
    def test_cluster_needs_k_cases_inside_radius_and_window(self):
        near = [case('a'), case('b', lon=-51.1350), case('c', lat=-29.8995)]
        found = D.cluster_growth(near, NOW, CFG)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['numbers']['novos_pedidos'], 3)
        self.assertEqual(found[0]['numbers']['pessoas'], 6)
        self.assertEqual(D.cluster_growth(near[:2], NOW, CFG), [])
        far = [case('a'), case('b', lat=-29.80), case('c', lat=-29.70)]
        self.assertEqual(D.cluster_growth(far, NOW, CFG), [])
        old = [case(x, received='08:00') for x in 'abc']
        self.assertEqual(D.cluster_growth(old, NOW, CFG), [])

    def test_no_hindsight_cases_after_tick_are_invisible(self):
        late = [case('a', received='12:30'), case('b', received='12:31'), case('c', received='12:32')]
        found, seen = D.detect(late, NOW, [], CFG)
        self.assertEqual((found, seen), ([], []))

    def test_closed_cases_do_not_count(self):
        group = [case('a'), case('b'), case('c', status='RESCUED')]
        self.assertEqual(D.cluster_growth(group, NOW, CFG), [])

    def test_stale_reuses_priority_logic_and_skips_requested_callbacks(self):
        old = case('a', received='04:00')
        fresh = case('b', received='11:50')
        asked = case('c', received='03:00', status='callback_requested')
        found = D.stale_send([old, fresh, asked], NOW, CFG)
        self.assertEqual(found[0]['case_ids'], ['a'])
        self.assertEqual(found[0]['numbers']['maior_espera_h'], 8.0)

    def test_idle_requires_documented_availability_and_replay_date(self):
        waiting = [case('a', received='10:00')]
        unit = lambda i, **kw: {'id': i, 'asset': 'irb', 'capacity': None, 'available': True, 'observed_date': DAY, **kw}
        inventory = [unit('ok'), unit('unknown', available=None), unit('busy', available=False), unit('future', observed_date='2024-05-09')]
        found = D.idle_resources(waiting, NOW, inventory, CFG)
        self.assertEqual(found[0]['resource_ids'], ['ok'])
        self.assertIn('a confirmar', found[0]['facts'][0]['text_pt'])
        self.assertEqual(D.idle_resources([case('a', received='11:45')], NOW, inventory, CFG), [])
        self.assertEqual(D.idle_resources(waiting, NOW, [], CFG), [])

    def test_rising_depth_is_dated_retrospective_and_absent_before_second_date(self):
        spot = dict(lat=-29.768962, lon=-51.156295)
        self.assertEqual(len(D.rising_depth([case('a', **spot)], NOW, CFG)), 1)
        found = D.rising_depth([case('a', **spot)], NOW, CFG)[0]
        self.assertTrue(found['evidence'][0]['retrospective'])
        self.assertIn('retrospectivo', found['facts'][0]['text_pt'])
        self.assertEqual(D.rising_depth([case('a', **spot)], '2024-05-07T12:00:00-03:00', CFG), [])

    def test_callback_aging_uses_supervisor_request_time(self):
        c = case('a', received='06:00', status='callback_requested', last_update_at=f'{DAY}T07:00:00-03:00')
        self.assertEqual(len(D.callback_aging([c], NOW, CFG)), 1)
        self.assertEqual(D.callback_aging([c], NOW, CFG, {'a': f'{DAY}T11:30:00-03:00'}), [])

    def test_mission_feedback_needs_reference_time(self):
        plan = {'stops': [{'case_id': 'a'}, {'case_id': 'b'}]}
        a = case('a', mission_id='m', mission=plan, mission_stop_done=True, status='RESCUED',
                 feedback=[{'received_at': f'{DAY}T08:00:00-03:00'}])
        b = case('b', mission_id='m', mission=plan, status='ASSIGNED:m', last_update_at=f'{DAY}T08:00:00-03:00')
        found = D.mission_feedback([a, b], NOW, CFG)
        self.assertEqual((found[0]['case_ids'], found[0]['numbers']['paradas_com_retorno']), (['b'], 1))
        a2 = copy.deepcopy(a); a2['feedback'][0]['received_at'] = f'{DAY}T11:30:00-03:00'
        self.assertEqual(D.mission_feedback([a2, b], NOW, CFG), [])
        both_pending = [dict(a, mission_stop_done=False, status='ASSIGNED:m', feedback=[]), b]
        self.assertEqual(D.mission_feedback(both_pending, NOW, CFG), [])
        self.assertEqual(len(D.mission_feedback(both_pending, NOW, CFG, {'m': f'{DAY}T06:00:00-03:00'})), 1)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.findings = D.cluster_growth([case('a'), case('b'), case('c')], NOW, CFG) + D.stale_send([case('s', received='03:00')], NOW, CFG)

    def alert(self, why, i=0, action=None):
        f = self.findings[i]
        return {'finding_id': f['id'], 'why_pt': why, 'action': action or f['allowed_actions'][0]}

    def test_validator_accepts_only_cited_numbers(self):
        ok, rejected = validate({'alerts': [self.alert('Há 3 novos pedidos em 500 m; agir agora.')]}, self.findings)
        self.assertEqual((len(ok), rejected), (1, 0))
        with self.assertRaises(ValueError):
            validate({'alerts': [self.alert('Há 9 novos pedidos.')]}, self.findings)

    def test_validator_rejects_unknown_ids_actions_and_duplicates(self):
        good = self.alert('Aglomeração de 3 pedidos.')
        bad_id = {**good, 'finding_id': 'cluster:zzzz'}
        bad_action = {**good, 'action': 'approve_dispatch'}
        wrong_kind = self.alert('x', 1, 'create_mission_proposal')
        ok, rejected = validate({'alerts': [bad_id, bad_action, wrong_kind, good, good]}, self.findings)
        self.assertEqual(len(ok), 1)
        self.assertEqual(rejected, 4)
        for broken in (None, {}, {'alerts': 'x'}, {'alerts': [good]*0}):
            with self.assertRaises(ValueError): validate(broken, self.findings)

    def test_at_most_three_alerts(self):
        many = [dict(self.findings[0], id=f'cluster:{i:08x}') for i in range(5)]
        ok, rejected = validate({'alerts': [{'finding_id': f['id'], 'why_pt': 'Há 3 pedidos.', 'action': 'reprioritise'} for f in many]}, many)
        self.assertEqual((len(ok), rejected), (3, 2))

    def test_model_reviewed_vs_visible_fallback(self):
        good = Supervisor(Scripted(lambda p: {'alerts': [{'finding_id': p['findings'][0]['id'], 'why_pt': 'Há 3 pedidos novos.', 'action': 'reprioritise'}]}))
        out = good.rank(self.findings, 't1')
        self.assertEqual((out['supervisor_check'], len(out['alerts'])), ('model_reviewed', 1))
        liar = Supervisor(Scripted({'alerts': [self.alert('Há 41 pedidos.')]}))
        out = liar.rank(self.findings, 't2')
        self.assertEqual(out['supervisor_check'], 'deterministic_only')
        self.assertEqual(out['alerts'], template(self.findings))
        self.assertEqual(liar.client.calls, 2)  # one short retry, then fallback
        down = Supervisor(Scripted(TimeoutError())).rank(self.findings, 't3')
        self.assertEqual((down['supervisor_check'], down['fallback_reason']), ('deterministic_only', 'TimeoutError'))
        none = Supervisor(None).rank(self.findings, 't4')
        self.assertEqual(none['fallback_reason'], 'no_model_client')
        self.assertEqual(Supervisor(Scripted({})).rank([], 't5')['supervisor_check'], 'no_findings')

    def test_template_alert_text_has_only_cited_numbers(self):
        for a in template(self.findings):
            ok, _ = validate({'alerts': [a]}, self.findings)
            self.assertEqual(len(ok), 1)


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Registry(self.tmp.path/'events.jsonl')
        self.cases = [ev.seed(self.registry, {'date': DAY}, c) for c in
                      [dict(key='s1', street='Rua AA', municipality='Canoas', lat=-29.898964, lon=-51.135298, received='04:00', people=2),
                       dict(key='s2', street='Rua A. L. Costa', municipality='Canoas', lat=-29.898047, lon=-51.132157, received='03:00', people=3)]]
        self.service = SupervisorService(self.registry, lambda: [], None, Supervisor(ev.ScriptedAgent()).client, CFG)

    def test_events_do_not_break_world_model_read(self):
        self.service.tick(NOW)
        self.assertEqual(len(self.registry.read()), 2)
        self.assertEqual(Registry(self.registry.path).read(self.cases[0]['case_id'])['version'], 1)

    def test_accept_callback_then_next_tick_resolves_with_delta(self):
        tick = self.service.tick(NOW)
        alert = tick['alerts'][0]
        self.assertEqual((alert['kind'], alert['action'], len(alert['case_ids'])), ('stale_send', 'trigger_callback', 2))
        done = self.service.decide(alert['alert_id'], 'accept', 'op', NOW)
        self.assertEqual(done['status'], 'accepted')
        self.assertEqual(done['decision']['execution']['summary_pt'], '2 retornos solicitados')
        self.assertEqual(self.registry.read(self.cases[0]['case_id'])['status'], 'callback_requested')
        second = self.service.tick(DAY+'T12:30:00-03:00')
        self.assertEqual(second['rechecks'][0]['outcome'], 'resolved')
        self.assertEqual(second['rechecks'][0]['delta'], {'before': 2, 'after': 0, 'removed_case_ids': sorted(alert['case_ids'])})
        self.assertEqual(second['alerts'], [])
        self.assertEqual(self.service.state()['alerts'][alert['alert_id']]['outcome'], 'resolved')
        third = self.service.tick(DAY+'T13:00:00-03:00')
        self.assertEqual(third['rechecks'], [])  # resolved alerts are not re-checked forever

    def test_still_open_when_action_does_not_change_the_world(self):
        pick = lambda p: {'alerts': [{'finding_id': p['findings'][0]['id'], 'why_pt': 'Há 2 pedidos parados.', 'action': 'reprioritise'}]}
        service = SupervisorService(self.registry, lambda: [], None, Scripted(pick), CFG)
        alert = service.tick(NOW)['alerts'][0]
        self.assertEqual(alert['action'], 'reprioritise')
        done = service.decide(alert['alert_id'], 'accept', 'op', NOW)
        self.assertEqual(len(done['decision']['execution']['results']), 2)
        second = service.tick(DAY+'T12:30:00-03:00')
        recheck = second['rechecks'][0]
        self.assertEqual((recheck['outcome'], recheck['delta']['before'], recheck['delta']['after']), ('still_open', 2, 2))
        self.assertEqual(second['alerts'], [])  # no duplicate alert for a still-open accepted one
        self.assertEqual(service.ticks(DAY)['counts']['still_open'], 1)

    def test_dismiss_suppresses_same_finding_until_new_subject(self):
        alert = self.service.tick(NOW)['alerts'][0]
        self.service.decide(alert['alert_id'], 'dismiss', 'op', NOW)
        self.assertEqual(self.service.tick(DAY+'T12:30:00-03:00')['alerts'], [])
        ev.seed(self.registry, {'date': DAY}, dict(key='s3', street='Rua AA', municipality='Canoas', lat=-29.898, lon=-51.135, received='02:00', people=1))
        self.assertEqual(len(self.service.tick(DAY+'T13:00:00-03:00')['alerts']), 1)

    def test_open_alert_is_not_duplicated_and_decision_is_once(self):
        alert = self.service.tick(NOW)['alerts'][0]
        self.assertEqual(self.service.tick(DAY+'T12:30:00-03:00')['alerts'], [])
        self.service.decide(alert['alert_id'], 'dismiss', 'op', NOW)
        from app.engines.world_model.registry import Conflict
        with self.assertRaises(Conflict): self.service.decide(alert['alert_id'], 'accept', 'op', NOW)
        with self.assertRaises(KeyError): self.service.decide('al-0000000000', 'accept', 'op', NOW)
        with self.assertRaises(ValueError): self.service.decide(alert['alert_id'], 'approve', 'op', NOW)

    def test_failed_execution_leaves_alert_open(self):
        from app.engines.world_model.registry import Conflict
        alert = self.service.tick(NOW)['alerts'][0]
        for c in self.cases:
            fresh = self.registry.read(c['case_id'])
            self.registry.action(c['case_id'], 'request_callback', fresh['version'], 'someone', human=True)
        with self.assertRaises(Conflict): self.service.decide(alert['alert_id'], 'accept', 'op', NOW)
        self.assertEqual(self.service.state()['alerts'][alert['alert_id']]['status'], 'open')

    def test_series_runs_every_interval_and_ticks_by_day(self):
        ticks = self.service.run(DAY+'T10:00:00-03:00', DAY+'T12:00:00-03:00')
        self.assertEqual([t['replay_time'][11:16] for t in ticks], ['10:00', '10:30', '11:00', '11:30', '12:00'])
        self.assertEqual(len(self.service.ticks(DAY)['ticks']), 5)
        self.assertEqual(self.service.ticks('2024-05-09')['ticks'], [])

    def test_alert_cites_only_numbers_of_its_finding(self):
        for t in self.service.run(DAY+'T10:00:00-03:00', DAY+'T12:00:00-03:00'):
            self.assertEqual(ev.uncited(t), 0)


class EvalTests(unittest.TestCase):
    def test_offline_eval_is_perfect_and_rejects_inventing_agent(self):
        r = ev.evaluate(False)
        self.assertEqual((r['scenarios'], r['fp'], r['fn'], r['uncited_numbers']), (10, 0, 0, 0))
        self.assertEqual(r['loops_correct'], r['loops'])
        self.assertEqual(r['subjects_exact'], 10)
        self.assertEqual(r['inventing_agent']['supervisor_check'], 'deterministic_only')


class HttpTests(unittest.TestCase):
    def setUp(self):
        from app.web.server import create_server
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.server = create_server('127.0.0.1', 0, sample=True, registry_path=self.tmp.path/'events.jsonl')
        for c in [dict(key='s1', street='Rua AA', municipality='Canoas', lat=-29.898964, lon=-51.135298, received='04:00', people=2)]:
            ev.seed(self.server.supervisor.registry, {'date': DAY}, c)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        self.addCleanup(self.close)

    def close(self):
        self.conn.close(); self.server.shutdown(); self.server.server_close()

    def call(self, method, path, body=None, headers=None):
        h = {'Content-Type': 'application/json', **(headers or {})}
        self.conn.request(method, path, json.dumps(body) if body is not None else None, h if body is not None else {})
        r = self.conn.getresponse()
        return r.status, json.loads(r.read())

    def test_tick_list_accept_and_recheck_over_http(self):
        status, data = self.call('POST', '/api/supervisor/tick', {'replay_time': NOW})
        self.assertEqual(status, 200)
        self.assertEqual(data['new_ticks'][0]['supervisor_check'], 'deterministic_only')  # sample mode: no model
        alert = data['alerts'][0]
        status, listing = self.call('GET', f'/api/supervisor/ticks?date={DAY}')
        self.assertEqual((status, len(listing['ticks']), listing['counts']['open']), (200, 1, 1))
        status, accepted = self.call('POST', f"/api/supervisor/alerts/{alert['alert_id']}", {'decision': 'accept', 'actor': 'op', 'replay_time': NOW})
        self.assertEqual((status, accepted['status']), (200, 'accepted'))
        status, _ = self.call('POST', f"/api/supervisor/alerts/{alert['alert_id']}", {'decision': 'accept', 'actor': 'op'})
        self.assertEqual(status, 409)
        status, data = self.call('POST', '/api/supervisor/tick', {'replay_time': DAY+'T12:30:00-03:00'})
        self.assertEqual(data['new_ticks'][0]['rechecks'][0]['outcome'], 'resolved')
        self.assertEqual(data['counts']['resolved'], 1)

    def test_bad_requests_and_cross_origin(self):
        self.assertEqual(self.call('GET', '/api/supervisor/ticks')[0], 400)
        self.assertEqual(self.call('GET', '/api/supervisor/ticks?date=hoje')[0], 400)
        self.assertEqual(self.call('POST', '/api/supervisor/tick', {'replay_time': 'agora'})[0], 400)
        self.assertEqual(self.call('POST', '/api/supervisor/tick', {'replay_time': '2024-05-08T12:00:00'})[0], 400)
        self.assertEqual(self.call('POST', '/api/supervisor/alerts/al-0123456789', {'decision': 'accept', 'actor': 'op'})[0], 404)
        self.assertEqual(self.call('POST', '/api/supervisor/tick', {'replay_time': NOW}, {'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.call('GET', '/api/supervisor/nope')[0], 404)

    def test_ui_assets_and_existing_routes_still_served(self):
        self.conn.request('GET', '/v2/supervisor.js')
        r = self.conn.getresponse(); body = r.read().decode()
        self.assertEqual(r.status, 200)
        self.assertIn('DeskSupervisor', body)
        self.conn.request('GET', '/v2')
        self.assertIn('supervisor-panel', self.conn.getresponse().read().decode())
        self.assertEqual(self.call('GET', '/api/resources')[0], 200)


if __name__ == '__main__':
    unittest.main()
