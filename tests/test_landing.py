"""Landing/disembark planner: queue, ranking, shelters with room, ambulance card, note validator, reversible choice, HTTP routes. Offline."""
import http.client
import json
import threading
import unittest
from pathlib import Path
from tests.support import Scratch

NOW = '2024-05-08T12:00:00-03:00'




class EvalSet(unittest.TestCase):
    def test_offline_eval_12_of_12_no_safety_violation(self):
        from eval.run_landing import evaluate
        r = evaluate()
        self.assertEqual(r['cases'], 12)
        self.assertEqual([x for x in r['results'] if x['failures'] or x['safety_violations']], [])
        self.assertEqual((r['passed'], r['safety_violations']), (12, 0))


class Queue(unittest.TestCase):
    def ev(self, kind, at, people=None):
        return {'kind': kind, 'landing_id': 'L', 'at': at, 'people': people} if people else {'kind': kind, 'landing_id': 'L', 'at': at}

    def test_waiting_is_arrived_minus_unloaded_and_future_reports_invisible(self):
        from app.landing import queue
        evs = [self.ev('arrival', '2024-05-08T09:00:00-03:00', 60), self.ev('unloaded', '2024-05-08T10:00:00-03:00', 20), self.ev('arrival', '2024-05-08T18:00:00-03:00', 500)]
        s = queue.state(evs, 'L', 30, NOW)
        self.assertEqual((s['people_waiting'], s['congested']), (40, True))
        self.assertEqual(queue.state(evs, 'L', 50, NOW)['congested'], False)

    def test_no_reports_means_unknown_not_empty_and_boat_without_count_is_flagged(self):
        from app.landing import queue
        s = queue.state([], 'L', 30, NOW)
        self.assertFalse(s['has_reports']);self.assertIn('desconhecida', s['basis_pt'])
        s = queue.state([self.ev('arrival', '2024-05-08T11:00:00-03:00')], 'L', 30, NOW)
        self.assertEqual((s['boats_without_count'], s['people_waiting']), (1, 0))

    def test_saturation_report_expires(self):
        from app.landing import queue
        e = [self.ev('full', '2024-05-08T07:00:00-03:00')]
        self.assertFalse(queue.state(e, 'L', 30, NOW)['reported_full'])
        self.assertTrue(queue.state(e, 'L', 30, '2024-05-08T08:30:00-03:00')['reported_full'])

    def test_validate_rejects_bad_reports(self):
        from app.landing import queue
        ok = {'at': NOW, 'actor': 'ana', 'people': 5}
        self.assertEqual(queue.validate('L', 'unloaded', ok, {'L'})['people'], 5)
        for kind, raw, known in [('unloaded', {'at': NOW, 'actor': 'ana'}, {'L'}), ('arrival', {**ok, 'people': 0}, {'L'}), ('full', {**ok, 'actor': ' '}, {'L'}),
                                 ('full', {**ok, 'source': 'citizen'}, {'L'}), ('bogus', ok, {'L'}), ('full', {'at': 'x', 'actor': 'a'}, {'L'})]:
            with self.assertRaises(ValueError): queue.validate('L', kind, raw, known)
        with self.assertRaises(KeyError): queue.validate('Z', 'full', ok, {'L'})


class Points(unittest.TestCase):
    def test_derived_points_are_labelled_and_capacity_is_estimate(self):
        from app.landing import points
        pts = points.load_points([{'shelter_id': 'S1', 'label': 'Abrigo X', 'lat': -29.9, 'lon': -51.1, 'municipality': 'Canoas'}])
        self.assertTrue(pts)
        for p in pts:
            self.assertIn(p['source_kind'], points.SOURCE_LABELS);self.assertTrue(p['source_label'])
            if p['source_kind'] != 'roads_launch_points': self.assertEqual(p['capacity_basis'], 'estimate')
        self.assertEqual(len({p['landing_id'] for p in pts}), len(pts))

    def test_roads_file_wins_when_present(self):
        from app.landing import points
        tmp = Scratch();self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / 'launch_points.csv').write_text('id,name,lat,lon,capacity_per_hour\n7,Rampa A,-29.9,-51.2,25\n8,Rampa B,,,\n', encoding='utf-8')
        old = points.ROADS_DIR;points.ROADS_DIR = Path(tmp.name);self.addCleanup(setattr, points, 'ROADS_DIR', old)
        pts = points.load_points()
        self.assertEqual([(p['landing_id'], p['capacity_per_hour'], p['capacity_basis']) for p in pts], [('R7', 25, 'roads_file')])


class Planner(unittest.TestCase):
    def run_item(self, **patch):
        import eval.run_landing as rl
        lines = [json.loads(l) for l in (Path(rl.ROOT) / 'eval/landing_set.jsonl').read_text(encoding='utf-8').splitlines()]
        base = patch.pop('base');it = next(x for x in lines if x['id'] == base)
        it.update(patch)
        svc, S = rl.build(it)
        return svc, svc.view(it['id'], it['now'])

    def test_distance_function_is_pluggable(self):
        import eval.run_landing as rl
        lines = [json.loads(l) for l in (Path(rl.ROOT) / 'eval/landing_set.jsonl').read_text(encoding='utf-8').splitlines()]
        it = next(x for x in lines if x['id'] == 'full-shelter-skipped')
        svc, _ = rl.build(it)
        svc.distance_fn = lambda a, b: {'m': 100000 if b['landing_id'] == 'L1' else 10, 'basis': 'road', 'label_pt': 'rota'}
        v = svc.view(it['id'], it['now'])
        self.assertEqual(v['options'][0]['distance']['basis'], 'road')
        self.assertEqual(v['options'][0]['landing_id'], 'L2')

    def test_every_option_labels_distance_and_capacity(self):
        _, v = self.run_item(base='full-shelter-skipped')
        self.assertEqual(len(v['options']), 3)
        for o in v['options']:
            self.assertIn('linha reta', o['distance']['label_pt']);self.assertEqual(o['capacity_per_hour']['label_pt'], 'estimativa')
        self.assertTrue(v['human_choice_required']);self.assertFalse(v['auto_dispatched'])

    def test_ambulance_card_has_who_what_where_and_quotes(self):
        _, v = self.run_item(base='medical-gets-ambulance-card')
        a = v['options'][0]['ambulance']
        self.assertEqual(a['who']['people'], 4);self.assertEqual(a['what']['medical'][0]['quote'], 'oxigênio')
        self.assertEqual((a['where']['pickup'], a['where']['destination']), ('L1', v['options'][0]['shelters'][0]['label']))
        self.assertIn('nada foi acionado', a['status'])

    def test_unknown_people_count_is_not_invented(self):
        import eval.run_landing as rl
        lines = [json.loads(l) for l in (Path(rl.ROOT) / 'eval/landing_set.jsonl').read_text(encoding='utf-8').splitlines()]
        it = next(x for x in lines if x['id'] == 'medical-gets-ambulance-card');it['case']['people'] = None
        svc, _ = rl.build(it)
        a = svc.view(it['id'], it['now'])['options'][0]['ambulance']
        self.assertIsNone(a['who']['people']);self.assertIn('desconhecida', a['who']['people_note'])
        self.assertIn('número desconhecido', a['text_pt'])


class Note(unittest.TestCase):
    def setUp(self):
        import eval.run_landing as rl
        lines = [json.loads(l) for l in (Path(rl.ROOT) / 'eval/landing_set.jsonl').read_text(encoding='utf-8').splitlines()]
        it = next(x for x in lines if x['id'] == 'medical-gets-ambulance-card')
        self.svc, _ = rl.build(it);self.it = it
        self.v = self.svc.view(it['id'], it['now']);self.opt = self.v['options'][0]

    def fake(self, text):
        class C:
            def call(s, role, system, payload, deadline): return {'note_pt': text}, {}
        return C()

    def test_template_is_labelled_deterministic(self):
        from app.landing import note
        n = note.write(self.v, self.opt)
        self.assertEqual(n['note_source'], 'deterministic');self.assertIn('sem IA', n['note_label_pt']);self.assertIn('«oxigênio»', n['note_pt'])

    def test_model_prose_never_replaces_the_field_bound_template(self):
        from app.landing import note
        good = 'Desembarque em L1; 4 pessoas; necessidade «oxigênio»; ambulância aguardando aprovação.'
        self.assertEqual(note.write(self.v, self.opt, self.fake(good))['note_source'], 'deterministic')
        bad_num = good.replace('4 pessoas', '40 pessoas')
        r = note.write(self.v, self.opt, self.fake(bad_num))
        self.assertEqual(r['note_source'], 'deterministic');self.assertNotIn('40 pessoas', r['note_pt'])
        r = note.write(self.v, self.opt, self.fake('Desembarque em L1; 4 pessoas; precisa de ajuda médica.'))
        self.assertIn('«oxigênio»', r['note_pt'])

    def test_model_failure_falls_back_visibly(self):
        from app.landing import note
        class Boom:
            def call(s, *a): raise RuntimeError('502')
        r = note.write(self.v, self.opt, Boom())
        self.assertEqual(r['note_source'], 'deterministic');self.assertIn('sem IA', r['note_label_pt'])


class Service(unittest.TestCase):
    def setUp(self):
        import eval.run_landing as rl
        lines = [json.loads(l) for l in (Path(rl.ROOT) / 'eval/landing_set.jsonl').read_text(encoding='utf-8').splitlines()]
        self.it = next(x for x in lines if x['id'] == 'full-shelter-skipped')
        self.svc, _ = rl.build(self.it)

    def test_choice_follow_suggestion_then_override_requires_reason_and_revoke(self):
        s, id_ = self.svc, self.it['id'];at = NOW
        e = s.choose(id_, {'landing_id': 'L1', 'shelter_id': 'SB', 'actor': 'ana', 'at': at})
        self.assertFalse(e['override'])
        with self.assertRaises(ValueError): s.choose(id_, {'landing_id': 'L2', 'shelter_id': 'SB', 'actor': 'ana', 'at': at})
        e = s.choose(id_, {'landing_id': 'L2', 'shelter_id': 'SB', 'actor': 'ana', 'at': at, 'override_reason': 'rampa mais segura'})
        self.assertTrue(e['override']);self.assertEqual(e['suggested_landing_id'], 'L1')
        self.assertEqual(s.view(id_, at)['choice']['landing_id'], 'L2')
        s.choose(id_, {'actor': 'ana', 'at': '2024-05-08T12:30:00-03:00', 'revoke': True})
        self.assertIsNone(s.view(id_, '2024-05-08T13:00:00-03:00')['choice'])
        self.assertEqual(s.view(id_, at)['choice']['landing_id'], 'L2')  # replay before the revoke still shows the choice

    def test_unknown_landing_or_actor_rejected(self):
        with self.assertRaises(ValueError): self.svc.choose(self.it['id'], {'landing_id': 'ZZ', 'actor': 'ana', 'at': NOW, 'override_reason': 'x'})
        with self.assertRaises(ValueError): self.svc.choose(self.it['id'], {'landing_id': 'L1', 'actor': '', 'at': NOW})
        with self.assertRaises(KeyError): self.svc.view('nope', NOW)

    def test_preview_and_expand_never_call_model(self):
        calls = []
        class C:
            def call(s, *a): calls.append(1);return {'note_pt': 'x'}, {}
        self.svc.client = C()
        self.svc.view(self.it['id'], NOW);self.assertEqual(calls, [])
        self.svc.view(self.it['id'], NOW, expand=True);self.assertEqual(len(calls), 0)

    def test_events_persist_in_own_jsonl(self):
        from app.landing.service import LandingService
        tmp = Scratch();self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / 'landing_events.jsonl'
        s = LandingService(self.svc.registry, self.svc.shelters, p, None, self.svc.access_fn, None, self.svc.points)
        s.report('L1', 'arrival', {'actor': 'ana', 'at': NOW, 'people': 9})
        again = LandingService(self.svc.registry, self.svc.shelters, p, None, self.svc.access_fn, None, self.svc.points)
        self.assertEqual(again.store.events[0]['people'], 9)


class Http(unittest.TestCase):
    def setUp(self):
        from app.web.server import create_server
        from app.shelters.state import Store
        from tests.test_missions import make_case, inventory
        from unittest.mock import patch
        self.tmp = Scratch();self.addCleanup(self.tmp.cleanup)
        self.server = create_server('127.0.0.1', 0, sample=True, registry_path=Path(self.tmp.name) / 'events.jsonl', inventory=inventory())
        self.addCleanup(self.server.server_close)
        self.server.landing.store = Store()  # never write the real runtime file
        pts = [{'landing_id': 'L1', 'label': 'Ponto 1', 'lat': -29.921, 'lon': -51.18, 'municipality': 'x', 'capacity_per_hour': 30, 'capacity_basis': 'estimate',
                'source_kind': 'osm_landmark', 'source_label': 'sintético'}]
        self.server.landing.points = pts
        self.server.landing.access_fn = lambda lat, lon, day: {'state': 'dry', 'source': 'synthetic', 'reason_pt': ''}
        self.server.landing.shelters.access_fn = None
        self.case = self.server.missions.registry.ingest(make_case(text='Meu pai usa oxigênio.'))
        t = threading.Thread(target=self.server.serve_forever, daemon=True);t.start();self.addCleanup(self.server.shutdown)

    def req(self, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=20)
        try:
            c.request('GET' if body is None else 'POST', path, None if body is None else json.dumps(body), {'Content-Type': 'application/json'})
            r = c.getresponse();return r.status, json.loads(r.read())
        finally: c.close()

    def test_get_report_choice_roundtrip(self):
        cid = self.case['case_id'];st, v = self.req('/api/cases/%s/landing?date=2024-05-08' % cid)
        self.assertEqual(st, 200);self.assertEqual(v['options'][0]['landing_id'], 'L1');self.assertTrue(v['options'][0]['ambulance'])
        st, _ = self.req('/api/landing/L1/arrival', {'actor': 'ana', 'at': '2024-05-08T10:00:00-03:00', 'people': 90})
        self.assertEqual(st, 200)
        st, v = self.req('/api/cases/%s/landing?now=2024-05-08T12:00:00-03:00' % cid)
        self.assertTrue(v['options'][0]['congested'])
        st, e = self.req('/api/cases/%s/landing/choice' % cid, {'landing_id': 'L1', 'actor': 'ana', 'at': '2024-05-08T11:00:00-03:00', 'override_reason': 'ok'})
        self.assertEqual(st, 200)
        self.assertEqual(self.req('/api/landing/ZZ/full', {'actor': 'a', 'at': NOW})[0], 404)
        self.assertEqual(self.req('/api/landing/L1/unloaded', {'actor': 'a', 'at': NOW})[0], 400)
        self.assertEqual(self.req('/api/cases/nope/landing?date=2024-05-08')[0], 404)
        self.assertEqual(self.req('/api/cases/%s/landing' % cid)[0], 400)


class RealRoadsLaunchPoints(unittest.TestCase):
    """Regression (Orbit): sample Canoas case got zero options because launch points were ignored and the flood layer drops wet-edge spots."""
    CASE = {'case_id': 'canoas', 'version': 1, 'fields': {'people': {'value': 4}, 'location': {'value': {'lat': -29.894682, 'lon': -51.216051}}},
            'position': {'lat': -29.894682, 'lon': -51.216051}, 'text': 'quatro pessoas'}

    def test_launch_points_loaded_from_graph_for_the_day(self):
        from app.landing import points
        kinds = {p['source_kind'] for p in points.load_points([], '2024-05-06')}
        self.assertEqual(kinds, {'roads_launch_points'})

    def test_wet_edge_launch_point_is_unknown_never_dry(self):
        from app.landing import planner
        pt = {'landing_id': 'RG1', 'label': 'x', 'lat': -29.9, 'lon': -51.2, 'source_kind': 'roads_launch_points', 'source_label': 's', 'municipality': 'Canoas', 'water_edge': True,
              'capacity_per_hour': 30, 'capacity_basis': 'estimate'}
        wet = lambda lat, lon, day: {'state': 'flooded', 'source': 'layer', 'reason_pt': 'alagado'}
        out = planner.plan(self.CASE, NOW, [pt], [], [], wet)
        self.assertTrue(out['options'])
        if True:
            self.assertEqual(out['options'][0]['access']['state'], 'unknown')
        lm = dict(pt, landing_id='L1', source_kind='osm_landmark', water_edge=False)
        self.assertEqual(planner.plan(self.CASE, NOW, [lm], [], [], wet)['options'], [])

    def test_sample_canoas_case_gets_real_options_with_roads(self):
        from app.landing import points, planner
        pts = points.load_points([], '2024-05-06')
        out = planner.plan(self.CASE, '2024-05-06T14:00:00-03:00', pts, [], [])
        self.assertTrue(out['options'], out['review_pt'])
        self.assertEqual(out['options'][0]['source_kind'], 'roads_launch_points')


class UiAssets(unittest.TestCase):
    def test_landing_js_is_served_and_hooked_once_in_meios(self):
        from app.web import routes_v2
        self.assertIn("'/v2/landing.js'", Path(routes_v2.__file__).read_text(encoding='utf-8'))
        root = Path(routes_v2.__file__).parent / 'v2'
        self.assertIn('/v2/landing.js', (root / 'index.html').read_text(encoding='utf-8'))
        app = (root / 'app.js').read_text(encoding='utf-8')
        # UX2: the Meios tab is rendered by meios.js, which opens the existing Desembarque panel on demand (hooked once)
        meios = (root / 'meios.js').read_text(encoding='utf-8')
        self.assertIn("S.tab==='Meios')window.DeskMeios.render", app)
        self.assertEqual(meios.count('DeskLanding'), 1)
        self.assertIn("el('h3','Desembarque')", (root / 'landing.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
