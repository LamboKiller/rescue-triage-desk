"""MS: medical lane + shelter capacity/needs routing. Offline, no model calls, no network."""
import json
import tempfile
import unittest
from pathlib import Path

NOW = '2024-05-08T12:00:00-03:00'


def case(cid, text, received='2024-05-08T08:00:00-03:00', decision='SEND'):
    return {'case_id': cid, 'message_id': cid, 'version': 1, 'text': text, 'received_at': received, 'replay_time': NOW,
            'status': 'proposed', 'fields': {'people': {'value': 3}}, 'result': {'decision': decision, 'priority': 1}}


class MedicalLane(unittest.TestCase):
    def test_scan_gives_exact_quotes_and_negation_only_for_injuries(self):
        from app.agents.needs import scan_medical
        rows = scan_medical(['Minha mãe usa oxigênio e o filho é diabético. Não há feridos. Estamos sem insulina.'])
        got = {(r['medical_need'], r['quote']) for r in rows}
        self.assertIn(('oxygen', 'oxigênio'), got)
        self.assertIn(('insulin', 'diabético'), got)
        self.assertIn(('insulin', 'insulina'), got)  # lacking a drug IS the need
        self.assertFalse([r for r in rows if r['medical_need'] == 'wound_trauma'])
        for r in rows: self.assertIn(r['quote'], 'Minha mãe usa oxigênio e o filho é diabético. Não há feridos. Estamos sem insulina.')

    def test_each_class_detected(self):
        from app.agents.needs import scan_medical
        samples = {'oxygen': 'precisa de cilindro de oxigênio', 'dialysis': 'faz hemodiálise toda terça', 'insulin': 'depende de insulina',
                   'pregnancy_labor': 'a bolsa estourou', 'bedridden': 'meu avô está acamado', 'newborn': 'bebê de 3 dias',
                   'wound_trauma': 'ele está sangrando muito', 'medication_other': 'acabou o medicamento controlado'}
        for need, text in samples.items():
            self.assertIn(need, {r['medical_need'] for r in scan_medical([text])}, need)
        self.assertEqual(scan_medical(['A água subiu até a porta.']), [])

    def test_table_is_declared_and_labelled_estimate(self):
        from app.priority import MEDICAL_TIME_TO_HARM, MEDICAL_BASIS
        from app.agents.needs import MEDICAL_NEEDS
        self.assertEqual(set(MEDICAL_TIME_TO_HARM), set(MEDICAL_NEEDS))
        self.assertIn('estimativa operacional', MEDICAL_BASIS)
        for row in MEDICAL_TIME_TO_HARM.values():
            lo, hi = row['hours']
            self.assertTrue(0 < lo <= hi)

    def test_reason_shown_with_zero_points_and_decision_untouched(self):
        from app.priority import queue
        c = case('m', 'Meu pai precisa de oxigênio, estamos no telhado.')
        before = dict(c['result'])
        out = queue([c], NOW)[0]
        reasons = [r for r in out['live_priority']['reasons'] if r.get('medical_need')]
        self.assertEqual(reasons[0]['medical_need'], 'oxygen')
        self.assertEqual(reasons[0]['points'], 0)
        self.assertIn('oxigênio', reasons[0]['reason_pt'])
        self.assertEqual(out['result']['decision'], before['decision'])
        self.assertEqual(out['medical']['time_to_harm_hours'], [1, 6])

    def test_medical_queue_orders_by_remaining_window_and_filters(self):
        from app.priority import medical_queue
        cases = [case('dial', 'Ele faz hemodiálise e está ilhado.', '2024-05-08T07:00:00-03:00'),
                 case('o2', 'Idosa com oxigênio em casa.', '2024-05-08T07:00:00-03:00'),
                 case('none', 'Casa alagada, quatro pessoas.', '2024-05-08T01:00:00-03:00'),
                 case('ins', 'Precisa de insulina.', '2024-05-08T07:00:00-03:00')]
        order = [c['case_id'] for c in medical_queue(cases, NOW)]
        self.assertEqual(order, ['o2', 'ins', 'dial'])

    def test_waiting_past_window_is_flagged_not_hidden(self):
        from app.priority import queue
        out = queue([case('o2', 'Tem insuficiência, usa oxigênio.', '2024-05-08T01:00:00-03:00')], NOW)[0]
        self.assertTrue(out['medical']['window_exceeded'])

    def test_dispatch_card_has_medical_line_with_fact(self):
        from app.dispatch_card import build_card
        card = build_card(case('c', 'Gestante com contrações, na laje.'))
        self.assertTrue([l for l in card['lines'] if l.startswith('Necessidade médica: Gestante em trabalho de parto')])
        self.assertTrue([f for f in card['facts_used'] if f['path'] == 'medical.pregnancy_labor' and 'contrações' in f['value']])

    def test_non_medical_case_unchanged(self):
        from app.priority import queue
        out = queue([case('x', 'Água na altura da janela.')], NOW)[0]
        self.assertIsNone(out['medical'])
        self.assertFalse([r for r in out['live_priority']['reasons'] if r.get('medical_need')])


def places():
    from app.shelters.state import Catalogue
    return Catalogue.from_places([
        {'id': 'A', 'lat': -29.915, 'lon': -51.18, 'municipality': 'Canoas', 'snapshots': [{'at': '2024-05-08T06:00:00', 'vacancies': 12, 'capacity': 50, 'sheltered': 38}]},
        {'id': 'B', 'lat': -29.95, 'lon': -51.18, 'municipality': 'Canoas', 'snapshots': [{'at': '2024-05-08T06:00:00'}]}])


def shelters():
    from app.shelters.state import Shelters, Store
    return Shelters(places(), Store())


def ev(kind, sid='A', at='2024-05-08T09:00:00-03:00', **k):
    return {'kind': kind, 'shelter_id': sid, 'at': at, 'source': k.pop('source', 'operator'), 'actor': 'op', **k}


def row(S, sid, now=NOW):
    return next(s for s in S.state(now) if s['shelter_id'] == sid)


class ShelterState(unittest.TestCase):
    def test_snapshot_is_labelled_pre_existing_and_unknown_stays_unknown(self):
        S = shelters()
        a, b = row(S, 'A'), row(S, 'B')
        self.assertEqual((a['remaining'], a['capacity_basis']), (12, 'snapshot'))
        self.assertIn('pré-existente', a['origin_label'])
        self.assertFalse(b['capacity_known'])
        self.assertIsNone(b['remaining'])
        self.assertIn('desconhecida', b['capacity_note_pt'])

    def test_report_supersedes_older_snapshot_and_deliveries_decrement(self):
        S = shelters()
        S.record(ev('vacancies', value=40))
        self.assertEqual(row(S, 'A')['remaining'], 40)
        S.record(ev('delivered', value=5, at='2024-05-08T10:00:00-03:00', source='crew'))
        S.record(ev('delivered', value=3, at='2024-05-08T11:00:00-03:00', source='crew'))
        a = row(S, 'A')
        self.assertEqual((a['remaining'], a['delivered_total']), (32, 8))
        self.assertEqual(a['capacity_basis'], 'operator_minus_deliveries')

    def test_deliveries_before_reading_are_not_double_counted(self):
        S = shelters()
        S.record(ev('delivered', value=5, at='2024-05-08T08:00:00-03:00'))
        S.record(ev('vacancies', value=20, at='2024-05-08T09:00:00-03:00'))
        self.assertEqual(row(S, 'A')['remaining'], 20)

    def test_full_report_and_overbooking(self):
        S = shelters()
        S.record(ev('full'))
        a = row(S, 'A')
        self.assertTrue(a['full'])
        S2 = shelters()
        S2.record(ev('vacancies', value=3))
        S2.record(ev('delivered', value=5, at='2024-05-08T10:00:00-03:00'))
        self.assertEqual(row(S2, 'A')['remaining'], 0)
        self.assertIn('excedido', row(S2, 'A')['capacity_note_pt'])

    def test_events_after_the_replay_clock_are_invisible(self):
        S = shelters()
        S.record(ev('full', at='2024-05-08T18:00:00-03:00'))
        self.assertFalse(row(S, 'A', NOW)['full'])
        self.assertTrue(row(S, 'A', '2024-05-08T19:00:00-03:00')['full'])
        self.assertEqual(S.state('2024-05-07'), [])

    def test_total_capacity_alone_is_not_remaining(self):
        S = shelters()
        S.record(ev('capacity', 'B', value=60))
        S.record(ev('delivered', 'B', value=10, at='2024-05-08T10:00:00-03:00'))
        b = row(S, 'B')
        self.assertIsNone(b['remaining'])
        self.assertEqual(b['remaining_max'], 50)
        self.assertIn('ocupação prévia desconhecida', b['capacity_note_pt'])

    def test_validation_rejects_bad_reports(self):
        S = shelters()
        for bad in [ev('vacancies', value=-1), ev('vacancies', 'ZZZ', value=3), ev('vacancies', value='9'), ev('delivered', value=0),
                    ev('attr', attr='health_support', value='yes'), ev('access', value='maybe'), {**ev('full'), 'actor': ' '}, {**ev('full'), 'source': 'rumor'},
                    {**ev('full'), 'at': 'ontem'}, ev('wipe')]:
            with self.assertRaises(ValueError, msg=str(bad)): S.record(bad)

    def test_persistence_roundtrip(self):
        from app.shelters.state import Shelters, Store
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'e.jsonl'
            S = Shelters(places(), Store(path))
            S.record(ev('vacancies', value=7))
            S2 = Shelters(places(), Store(path))
            self.assertEqual(row(S2, 'A')['remaining'], 7)

    def test_real_list_loads_and_has_snapshot_capacities(self):
        from app.shelters.state import Shelters, Store
        S = Shelters(store=Store())
        st = S.state('2024-05-10')
        self.assertGreater(len(st), 100)
        self.assertTrue(any(s['capacity_known'] for s in st) and any(not s['capacity_known'] for s in st))
        self.assertEqual(S.state('2024-05-01'), [])  # list begins 8 May: nothing is invented before that


class ReportText(unittest.TestCase):
    def setUp(self):
        self.S = shelters()
        self.S.record(ev('alias', name='Ginásio Tesourinha'))

    def svc(self):
        from app.shelters.service import ShelterService
        return ShelterService(shelters=self.S)

    def test_full_by_name(self):
        r = self.svc().report({'text': 'Abrigo Ginásio Tesourinha lotado', 'actor': 'op', 'at': NOW})
        self.assertEqual([e['kind'] for e in r['recorded']], ['full'])
        self.assertTrue(row(self.S, 'A')['full'])

    def test_vacancies_and_delivery_text_decrements(self):
        s = self.svc()
        s.report({'text': 'Ginásio Tesourinha: 40 vagas', 'actor': 'op', 'at': '2024-05-08T09:00:00-03:00'})
        r = s.report({'text': 'entregues 5 no abrigo Ginásio Tesourinha', 'actor': 'equipe', 'source': 'crew', 'at': '2024-05-08T10:00:00-03:00'})
        self.assertEqual(r['recorded'][0]['value'], 5)
        self.assertEqual(row(self.S, 'A')['remaining'], 35)

    def test_unresolved_shelter_is_not_guessed(self):
        r = self.svc().report({'text': 'abrigo Escola Inexistente lotado', 'actor': 'op', 'at': NOW})
        self.assertEqual(r['recorded'], [])
        self.assertIn('não foi identificado', r['unresolved'])
        self.assertFalse(row(self.S, 'A')['full'])

    def test_feedback_hook_records_only_with_named_shelter(self):
        s = self.svc()
        self.assertIsNotNone(s.ingest_feedback('Equipe: entregues 4 no abrigo Ginásio Tesourinha', 'equipe', '2024-05-08T11:00:00-03:00', 'c1', 'm1'))
        self.assertEqual(row(self.S, 'A')['delivered_total'], 4)
        self.assertIsNone(s.ingest_feedback('entregues 4 pessoas', 'equipe', '2024-05-08T11:00:00-03:00'))
        self.assertIsNone(s.ingest_feedback(None, None, None))

    def test_attributes_and_access_text(self):
        s = self.svc()
        s.report({'text': 'Ginásio Tesourinha tem posto médico e aceita animais, acesso alagado', 'actor': 'op', 'at': NOW})
        a = row(self.S, 'A')
        self.assertTrue(a['attributes']['health_support']['value'])
        self.assertTrue(a['attributes']['animals_ok']['value'])
        self.assertEqual(a['reported_access']['value'], 'flooded')


def group(**k):
    return {'point': {'lat': -29.92, 'lon': -51.18}, 'people': 4, 'medical': [], 'animals': False, 'case_ids': ['c'], **k}


def acc(mapping):
    return lambda lat, lon, day: {'state': mapping.get((round(lat, 3)), 'unknown'), 'source': 'test', 'reason_pt': 'teste'}


class Router(unittest.TestCase):
    def test_full_never_offered_even_if_only_one(self):
        from app.shelters import router
        S = shelters()
        S.record(ev('full'))
        S.record(ev('full', 'B'))
        r = router.recommend(group(), S.state(NOW), '2024-05-08', acc({}))
        self.assertEqual(r['recommendations'], [])
        self.assertEqual(r['excluded_total'], 2)
        self.assertIn('Nenhum abrigo elegível', r['message_pt'])

    def test_flooded_dropped_when_alternative_kept_and_warned_when_none(self):
        from app.shelters import router
        S = shelters()
        r = router.recommend(group(), S.state(NOW), '2024-05-08', acc({-29.915: 'flooded'}))
        self.assertEqual([x['shelter_id'] for x in r['recommendations']], ['B'])
        r = router.recommend(group(), S.state(NOW), '2024-05-08', acc({-29.915: 'flooded', -29.95: 'flooded'}))
        self.assertTrue(r['only_flooded_access'])
        self.assertTrue(all(x['warnings_pt'] for x in r['recommendations']))

    def test_unknown_access_is_never_described_as_dry(self):
        from app.shelters import router
        r = router.recommend(group(), shelters().state(NOW), '2024-05-08', acc({}))
        for x in r['recommendations']:
            self.assertEqual(x['access']['state'], 'unknown')
            self.assertTrue([c for c in x['confirm_pt'] if 'não significa seco' in c])

    def test_crew_flooded_report_vs_dry_layer_is_conflict(self):
        from app.shelters import router
        S = shelters()
        S.record(ev('access', value='flooded', source='crew'))
        r = router.recommend(group(), S.state(NOW), '2024-05-08', acc({-29.915: 'dry'}))
        top = next(x for x in r['recommendations'] if x['shelter_id'] == 'A')
        self.assertEqual(top['access']['state'], 'conflict')
        self.assertTrue([w for w in top['warnings_pt'] if 'diverge' in w])

    def test_medical_need_prefers_reported_health_support_and_asks_when_unknown(self):
        from app.shelters import router
        S = shelters()
        S.record(ev('attr', 'B', attr='health_support', value=True))
        med = [{'medical_need': 'oxygen', 'quote': 'oxigênio', 'hours_low': 1, 'hours_high': 6}]
        r = router.recommend(group(medical=med), S.state(NOW), '2024-05-08', acc({}))
        self.assertEqual(r['recommendations'][0]['shelter_id'], 'B')
        a = next(x for x in r['recommendations'] if x['shelter_id'] == 'A')
        self.assertTrue([c for c in a['confirm_pt'] if 'apoio de saúde' in c])

    def test_pets_need(self):
        from app.shelters import router
        S = shelters()
        S.record(ev('attr', attr='animals_ok', value=False))
        r = router.recommend(group(animals=True), S.state(NOW), '2024-05-08', acc({}))
        self.assertEqual(r['recommendations'][0]['shelter_id'], 'B')

    def test_too_small_is_ranked_below_fitting_and_says_split(self):
        from app.shelters import router
        S = shelters()  # A has 12 vacancies
        r = router.recommend(group(people=30), S.state(NOW), '2024-05-08', acc({}))
        a = next(x for x in r['recommendations'] if x['shelter_id'] == 'A')
        self.assertTrue([w for w in a['warnings_pt'] if 'dividir' in w])
        self.assertEqual(r['recommendations'][0]['shelter_id'], 'B')

    def test_human_choice_flag_and_top3_cap(self):
        from app.shelters import router
        r = router.recommend(group(), shelters().state(NOW), '2024-05-08', acc({}))
        self.assertTrue(r['human_choice_required'])
        self.assertLessEqual(len(r['recommendations']), 3)

    def test_no_point_no_ranking(self):
        from app.shelters import router
        r = router.recommend(group(point=None), shelters().state(NOW), '2024-05-08')
        self.assertEqual(r['recommendations'], [])

    def test_service_recommend_from_registry_cases(self):
        from app.shelters.service import ShelterService
        c = case('c1', 'Mãe com oxigênio e dois cachorros.')
        c['position'] = {'lat': -29.92, 'lon': -51.18, 'position_kind': 'street_reference'}
        svc = ShelterService(shelters=shelters(), access_fn=acc({}))
        r = svc.recommend(NOW, ['c1'], cases=[c])
        self.assertEqual(r['group']['people'], 3)
        self.assertTrue(r['group']['animals'])
        self.assertEqual(r['group']['medical'][0]['medical_need'], 'oxygen')
        with self.assertRaises(KeyError): svc.recommend(NOW, ['nope'], cases=[c])

    def test_real_layer_returns_known_state_vocabulary(self):
        from app.shelters import router
        a = router.layer_access(-29.92, -51.18, '2024-05-08')
        self.assertIn(a['state'], ('dry', 'flooded', 'unknown'))
        self.assertTrue(a['retrospective'])
        self.assertEqual(router.layer_access(-29.92, -51.18, '2024-05-01')['state'], 'unknown')


class Routes(unittest.TestCase):
    class H:
        def __init__(self, path, body=None, origin=None):
            import io
            self.path = path
            raw = json.dumps(body).encode() if body is not None else b''
            self.headers = {'Content-Length': str(len(raw)), 'Content-Type': 'application/json', 'Host': 'x:1', **({'Origin': origin} if origin else {})}
            self.rfile = io.BytesIO(raw)
            self.connection = type('C', (), {'settimeout': lambda s, t: None})()
            self.sent = None
        def send_json(self, code, payload): self.sent = (code, payload)

    def test_get_post_and_origin_guard(self):
        from app.shelters import routes
        from app.shelters.service import ShelterService
        svc = ShelterService(shelters=shelters())
        h = self.H('/api/shelters?date=2024-05-08');routes.handle(h, svc, 'GET')
        self.assertEqual(h.sent[0], 200);self.assertEqual(h.sent[1]['summary']['total'], 2)
        h = self.H('/api/shelters/reports', {'kind': 'full', 'shelter_id': 'A', 'actor': 'op', 'at': NOW});routes.handle(h, svc, 'POST')
        self.assertEqual(h.sent[0], 200);self.assertTrue(row(svc.shelters, 'A')['full'])
        h = self.H('/api/shelters/reports', {'kind': 'full', 'shelter_id': 'B', 'actor': 'op', 'at': NOW}, origin='http://evil.example');routes.handle(h, svc, 'POST')
        self.assertEqual(h.sent[0], 403);self.assertFalse(row(svc.shelters, 'B')['full'])
        h = self.H('/api/shelters/reports', {'kind': 'full', 'shelter_id': 'nope', 'actor': 'op', 'at': NOW});routes.handle(h, svc, 'POST')
        self.assertEqual(h.sent[0], 400)
        h = self.H('/api/shelters?date=ontem');routes.handle(h, svc, 'GET')
        self.assertEqual(h.sent[0], 400)


class EvalGate(unittest.TestCase):
    def test_shelter_eval_is_clean(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'eval'))
        from run_shelters import evaluate
        r = evaluate()
        self.assertEqual(r['cases'], 12)
        self.assertEqual((r['never_list_violations'], r['full_recommended'], r['flooded_recommended_with_dry_alternative'], r['unknown_capacity_unlabelled']), (0, 0, 0, 0))
        self.assertEqual(r['top1_correct'], 12, [x for x in r['results'] if x['failures']])


if __name__ == '__main__':
    unittest.main()
