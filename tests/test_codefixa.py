"""Independent synthetic regressions for the CODEFIXA audit acceptance targets."""
import io
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from tests.support import Scratch
from app.engines.world_model.registry import Registry
from app.landing import note
from app.telemetry import Telemetry
from app.telemetry_routes import ApprovedRoutes
from app.unit_status import UnitStatusService
from app.redact import redact, redact_data


class HandoffTests(unittest.TestCase):
    def test_number_reassignment_and_uncited_clearance_never_render(self):
        plan = dict(case_id='synthetic', people=3, medical=[])
        option = dict(label='Pier', distance={'m': 100, 'label_pt': 'estimated'}, warnings_pt=['Acesso desconhecido'],
                      ambulance=None, shelters=[dict(label='Shelter', room_pt='20 vagas')])
        for text in ('20 pessoas resgatadas.', '3 pessoas; acesso seguro.'):
            with self.subTest(text=text):
                client = NS(call=lambda *args: ({'note_pt': text}, {}))
                result = note.write(plan, option, client)
                self.assertEqual(result['note_source'], 'deterministic')
                self.assertNotIn(text, result['note_pt'])
                self.assertIn('Acesso desconhecido', result['note_pt'])

    def test_preview_tracks_current_shelter_and_choice_without_model_calls(self):
        from app.landing.service import LandingService
        plan = dict(case_id='synthetic', people=3, medical=[], options=[dict(landing_id='pier', label='Pier',
                    distance={'m': 100, 'label_pt': 'estimated'}, warnings_pt=[], ambulance=None,
                    shelters=[dict(shelter_id='first', label='First', room_pt='10 vagas'),
                              dict(shelter_id='second', label='Second', room_pt='20 vagas')])])
        client = NS(call=unittest.mock.Mock(side_effect=AssertionError('preview must not call model')))
        svc = LandingService(NS(read=lambda _: {'version': 1}), NS(shelters=NS(state=lambda _: [])),
                             client=client, points=[])
        svc.choice_of = lambda *args: {'landing_id': 'pier', 'shelter_id': 'second'}
        with patch('app.landing.planner.plan', side_effect=lambda *args: plan):
            first = svc.view('synthetic', '2024-05-08T12:00:00Z')
            self.assertEqual(first['handoff']['facts']['abrigo'], 'Second')
            plan['options'][0]['shelters'][1]['room_pt'] = '0 vagas'
            second = svc.view('synthetic', '2024-05-08T12:00:00Z', expand=True)
        self.assertEqual(second['handoff']['facts']['vagas'], '0 vagas')
        self.assertIn('0 vagas', second['handoff']['note_pt'])
        client.call.assert_not_called()


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch(); self.addCleanup(self.tmp.cleanup)
        self.reg = Registry(self.tmp.path / 'events.jsonl')
        self.svc = UnitStatusService(self.reg, lambda: [{'id': 'a'}, {'id': 'b'}])

    def assign(self, mid, hour, uid='a'):
        plan = dict(units=[dict(id=uid)], stops=[dict(case_id=mid)], eta_seconds=60)
        self.reg._append(dict(kind='approve_mission', mission_id=mid, at=f'2024-05-08T{hour}:00:00Z',
                              projections=[dict(mission=plan)]))

    def report(self, mid, hour, uid='a'):
        return self.svc.report(uid, dict(mission_id=mid, received_at=f'2024-05-08T{hour}:00:00Z',
                               actor='synthetic operator', status='on_scene'))

    def test_old_report_is_retained_as_conflict_without_overwriting_new_assignment(self):
        self.assign('old', '10'); self.assign('new', '11'); self.assign('other', '11', 'b')
        event = self.report('old', '12')
        self.assertFalse(event['applied'])
        self.assertEqual(event['conflict']['active_mission_id'], 'new')
        self.assertEqual(self.svc.journal()[-1]['event_id'], event['event_id'])
        rows = {r['unit_id']: r for r in self.svc.view('2024-05-08T13:00:00Z')['units']}
        self.assertEqual((rows['a']['mission_id'], rows['a']['status']), ('new', 'assigned'))
        self.assertEqual(rows['b']['mission_id'], 'other')

    def test_late_delivery_uses_event_time_and_cancellation_rejects_current_report(self):
        self.assign('old', '10'); self.assign('new', '12')
        self.assertTrue(self.report('old', '11')['applied'])
        self.assertEqual(self.svc.view('2024-05-08T13:00:00Z')['units'][0]['mission_id'], 'new')
        self.reg._append(dict(kind='cancel_mission', mission_id='new', at='2024-05-08T13:00:00Z', projections=[]))
        self.assertFalse(self.report('new', '14')['applied'])

    def test_preview_paths_do_not_spend_model_budget(self):
        from app.missions.service import MissionService
        from tests.test_missions import make_case, inventory
        client = NS(call=unittest.mock.Mock(side_effect=AssertionError('preview model call')))
        case = make_case()
        self.reg._append(dict(kind='ingest', case_id='a', provenance='a:1', version=1, case=case))
        svc = MissionService(self.reg, inventory(), client)
        with patch('app.missions.service.replay_cases', side_effect=lambda cases, day: cases):
            self.assertTrue(svc.proposals('2024-05-08')['proposals'])
        with patch('app.fleet.snapshot.read', return_value=(case, [])), patch('app.fleet.allocation.allocate', return_value={'top3': []}):
            self.assertEqual(svc.assets('a', '2024-05-08')['top3'], [])
        client.call.assert_not_called()

    def test_chain_eta_rejects_fallback_water(self):
        from app.missions.chaining import travel
        raw = dict(reachable=True, distance_m=1000, eta_seconds=300,
                   route={'water': dict(fallback=True, grid_verified=False)})
        self.assertIsNone(travel(lambda a,b: raw, {'lat': -30, 'lon': -51}, {'lat': -30, 'lon': -50.99}, {'type': 'barco_aluminio'}))


class GpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch(); self.addCleanup(self.tmp.cleanup)
        self.now = 100000
        self.plan = dict(mission_id='m', unit_id='a', approved_at=0, status='en_route',
                         stops=[dict(case_id='c', point=dict(lat=-30, lon=-51))],
                         polyline=[[-51.01, -30], [-51, -30]])
        self.s = Telemetry(self.tmp.path / 'gps.jsonl', lambda: ['a'], lambda: [self.plan], clock=lambda: self.now)
        self.s.bind('device', 'a', 'synthetic operator')

    def fixes(self, times, accuracy=8):
        for at in times:
            self.s.ingest(dict(id='device', lat=-30, lon=-51, timestamp=at, speed=4, accuracy=accuracy))
        return self.s.view()['units'][0]

    def test_stale_fixes_produce_no_current_proposal_eta_or_progress(self):
        row = self.fixes([90000, 90010])
        self.assertFalse(row['fresh']); self.assertIsNone(row['arrival_proposal'])
        self.assertIsNone(row['eta_seconds']); self.assertNotIn('progress_pct', row)

    def test_accuracy_and_supporting_gap_gate_current_proposals(self):
        row = self.fixes([99998, 99999], accuracy=100)
        self.assertIsNone(row['arrival_proposal']); self.assertIsNone(row['eta_seconds'])

    def test_gap_between_supporting_fixes_is_bounded(self):
        row = self.fixes([99000, 99999])
        self.assertIsNone(row['arrival_proposal']); self.assertIsNone(row['eta_seconds'])

    def test_freshness_accuracy_and_gap_boundaries(self):
        row = self.fixes([99280, 99400], accuracy=30)
        self.assertIsNotNone(row['eta_seconds'])
        # Both fixes must be current, not just the latest one.
        self.assertIsNone(row['arrival_proposal'])
        self.now += 1
        self.assertIsNone(self.s.view()['units'][0]['eta_seconds'])

    def test_new_mission_and_other_unit_cannot_reuse_prior_mission_fixes(self):
        self.fixes([99998, 99999])
        self.plan.update(mission_id='new', approved_at=100000)
        row = self.s.view()['units'][0]
        self.assertIsNone(row['arrival_proposal']); self.assertIsNone(row['eta_seconds'])
        self.plan['unit_id'] = 'b'
        row = next(r for r in self.s.view()['units'] if r['unit_id'] == 'a')
        self.assertIsNone(row['mission_id']); self.assertIsNone(row['arrival_proposal'])

    def test_current_proposal_exports_timestamps_accuracy_and_mission(self):
        row = self.fixes([99998, 99999])
        proposal = row['arrival_proposal']
        self.assertEqual(proposal['mission_id'], 'm')
        self.assertEqual([e['timestamp'] for e in proposal['evidence']], [99998, 99999])
        self.assertEqual([e['accuracy'] for e in proposal['evidence']], [8, 8])

    def test_fallback_water_never_exports_tracking_segments_even_after_restart(self):
        plan = dict(status='assigned', date='2024-05-08', units=[dict(id='a', type='boat', base_location=dict(lat=-30, lon=-51.01))],
                    stops=self.plan['stops'])
        status = NS(journal=lambda: [dict(kind='approve_mission', mission_id='m', at='2024-05-08T00:00:00Z')],
                    view=lambda: {'units': [dict(unit_id='a', mission_id='m')]})
        fallback = dict(polyline=self.plan['polyline'], fallback=True, grid_verified=False, basis='straight_line_water', review_pt=['NO_WATER_PATH'])
        adapter = ApprovedRoutes(status, NS(detail=lambda _: plan), self.s)
        with patch('app.geo.routing.case_route', return_value=dict(reachable=True, land=None, water=fallback)):
            route = adapter()[0]
        self.assertEqual(route['segments'], []); self.assertEqual(route['polyline'], [])
        self.assertTrue(route['preview_segments']); self.assertIn('NO_WATER_PATH', route['review_pt'])
        adapter = ApprovedRoutes(status, NS(detail=lambda _: plan), self.s)
        self.assertEqual(adapter()[0]['segments'], [])


class PrivacyTests(unittest.TestCase):
    def test_four_raw_pii_escape_attempts_are_redacted_and_typed_osm_is_preserved(self):
        contact = '51987654321'
        for text in ('telefone: '+contact, 'id: '+contact, json.dumps({'unexpected_prose': contact}),
                     json.dumps({'message_id': contact})):
            with self.subTest(text=text): self.assertNotIn(contact, redact(text))
        value = dict(osm_id='12000000001', candidate_id='osm:node:12000000001',
                     text='id: '+contact, message_id=contact, unexpected_prose=contact)
        result = redact_data(value)
        self.assertEqual(result['osm_id'], value['osm_id'])
        self.assertEqual(result['candidate_id'], value['candidate_id'])
        for key in ('text', 'message_id', 'unexpected_prose'): self.assertNotIn(contact, result[key])

    def test_external_contact_ids_are_pseudonymized_before_trace_and_storage(self):
        from app.pipeline import validate_request
        _, messages = validate_request(dict(replay_time='2024-05-08T12:00:00Z', messages=[
            dict(message_id='51987654321', text='Pedido sintético'), dict(message_id='51987654322', text='Outro pedido sintético')]))
        ids = [m['message_id'] for m in messages]
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(all(mid.startswith('external-') for mid in ids))
        self.assertEqual([redact_data({'message_id': mid})['message_id'] for mid in ids], ids)


class BoundaryTests(unittest.TestCase):
    def test_exposed_operator_cannot_use_missing_origin_or_actor_as_authority(self):
        from app.operator_boundary import operator_allowed
        handler = NS(server=NS(server_address=('0.0.0.0', 8080)), client_address=('127.0.0.1', 50123),
                     headers={'Host': 'localhost:8080'})
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(operator_allowed(handler))
            handler.headers['Origin'] = 'http://localhost:8080'
            self.assertFalse(operator_allowed(handler))
        handler.headers.pop('Origin')
        with patch.dict('os.environ', {'RESCUE_OPERATOR_TOKEN': 'synthetic-test-token'}, clear=True):
            self.assertFalse(operator_allowed(handler))
            handler.headers['Authorization'] = 'Bearer synthetic-test-token'
            self.assertTrue(operator_allowed(handler))

    def test_server_entry_points_default_to_loopback(self):
        import inspect
        import run
        from app.web.server import create_server
        self.assertEqual(inspect.signature(run.create_server).parameters['host'].default, '127.0.0.1')
        self.assertEqual(inspect.signature(create_server).parameters['host'].default, '127.0.0.1')

    def test_http_exposed_no_origin_fake_actor_gets_403_before_action(self):
        import http.client
        import threading
        import run
        tmp = Scratch(); self.addCleanup(tmp.cleanup)
        pipeline = NS(registry=Registry(tmp.path / 'http.jsonl'))
        server = run.create_server('0.0.0.0', 0, sample=True, pipeline=pipeline)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            with patch.dict('os.environ', {}, clear=True):
                conn.request('POST', '/api/cases/fake/actions', json.dumps(dict(actor='invented operator', action='approve_mission')),
                             {'Content-Type': 'application/json'})
                response = conn.getresponse()
                self.assertEqual(response.status, 403); response.read()
            self.assertFalse(pipeline.registry.path.exists())
        finally:
            conn.close(); server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
