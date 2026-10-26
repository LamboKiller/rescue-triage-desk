"""N5 REUNITE: candidate matcher, privacy redaction, human-only decisions, notes, routes."""
import importlib.util
import io
import json
import unittest
from pathlib import Path
from app.config import ROOT
from app.reunite import matcher, records, routes
from app.reunite.service import Reunite
from tests.support import Scratch

spec = importlib.util.spec_from_file_location('run_reunite', ROOT / 'eval/run_reunite.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

T0 = '2024-05-06T10:00:00-03:00'
SEARCH = {'case_id': 'c1', 'message_id': 'm1', 'received_at': T0, 'location_confirmed': False,
          'text': 'Procuro minha mae Rosa Maria Teixeira, 77 anos, morava na Rua Bela Vista 88 apto 12, CEP 91000-000. Fone 51 98765-4321, rosa.filha@exemplo.com'}
SHELTER = {'kind': 'delivered', 'value': 1, 'shelter_id': 'S1', 'seq': 1, 'at': '2024-05-07T08:00:00-03:00', 'case_id': 'c2',
           'quote': 'Deu entrada no abrigo dona Rosa Maria Teixeira, 77 anos, retirada da Rua Bela Vista'}
PLACES = {'S1': {'lat': -29.9, 'lon': -51.1, 'municipality': 'Canoas'}}
CASES = [SEARCH, {'case_id': 'c2', 'text': 'Familia ilhada na Rua Bela Vista', 'received_at': T0}]


def service(path=None):
    return Reunite(None, None, path)


class ReuniteTests(unittest.TestCase):
    def test_eval_precision_and_no_auto_confirm(self):
        out = ev.run()
        self.assertEqual(out['top1_precision'], '6/6')
        self.assertEqual(out['abstain_correct'], '6/6')
        self.assertEqual(out['auto_confirms'], 0)

    def test_personal_data_redacted_and_street_number_kept(self):
        rec = records.missing_from_case(SEARCH)
        blob = json.dumps(rec, ensure_ascii=False)
        for secret in ('98765-4321', 'rosa.filha@exemplo.com', '91000-000', 'apto 12'):
            self.assertNotIn(secret, blob)
        self.assertIn('Rua Bela Vista 88', rec['quote'])
        self.assertEqual(rec['names'], ['Rosa Maria Teixeira'])

    def test_no_identity_inference_from_uncued_or_partial_names(self):
        self.assertEqual(records.names('o Sarandi foi alagado e Porto Alegre parou'), [])
        self.assertEqual(records.names('moro na Rua Bela Vista e preciso de barco'), [])
        self.assertIsNone(records.missing_from_case({'case_id': 'x', 'received_at': T0, 'text': 'Procuro noticias sobre a enchente em geral.'}))

    def test_candidate_requires_human_and_never_confirmed_status(self):
        view = service().view(sources_kw()['asof'], **{k: v for k, v in sources_kw().items() if k != 'asof'})
        self.assertEqual(len(view['candidates']), 1)
        c = view['candidates'][0]
        self.assertEqual((c['status'], c['requires_human']), ('candidate', True))
        self.assertTrue(any(e['kind'] == 'name' and e['strength'] == 'full' for e in c['evidence']))
        with self.assertRaises(PermissionError):
            service().decide(c['id'], 'confirm', 'ana', **{k: v for k, v in sources_kw().items() if k != 'asof'})

    def test_confirm_writes_notes_to_both_cases_and_persists(self):
        tmp = Scratch(); self.addCleanup(tmp.cleanup)
        if True:
            path = Path(tmp.name) / 'reunite.jsonl'
            svc = service(path)
            kw = {k: v for k, v in sources_kw().items() if k != 'asof'}
            cid = svc.view(**kw)['candidates'][0]['id']
            svc.decide(cid, 'confirm', 'operadora Ana', human=True, **kw)
            self.assertEqual(len(svc.notes('c1')), 1)
            self.assertEqual(len(svc.notes('c2')), 1)
            self.assertNotIn('98765', json.dumps(svc.events))
            again = service(path)
            self.assertEqual(len(again.notes('c1')), 1)
            self.assertEqual(again.view(**kw)['candidates'], [])
            with self.assertRaises(ValueError):
                again.decide(cid, 'reject', 'ana', human=True, **kw)

    def test_reject_removes_pair_without_notes(self):
        tmp = Scratch(); self.addCleanup(tmp.cleanup)
        if True:
            svc = service(Path(tmp.name) / 'r.jsonl')
            kw = {k: v for k, v in sources_kw().items() if k != 'asof'}
            cid = svc.view(**kw)['candidates'][0]['id']
            svc.decide(cid, 'reject', 'ana', human=True, **kw)
            self.assertEqual(svc.notes('c1'), [])
            self.assertEqual(svc.view(**kw)['candidates'], [])

    def test_no_hindsight_asof(self):
        kw = {k: v for k, v in sources_kw().items() if k != 'asof'}
        self.assertEqual(service().view('2024-05-06T20:00:00-03:00', **kw)['candidates'], [])
        self.assertEqual(len(service().view('2024-05-08T00:00:00-03:00', **kw)['candidates']), 1)

    def test_replay_counts_exclude_future_source_records(self):
        kw = {k: v for k, v in sources_kw().items() if k != 'asof'}
        self.assertEqual(service().view(T0, **kw)['counts'], {'missing': 1, 'found': 0})

    def test_first_name_alone_is_weak_and_cannot_make_a_candidate(self):
        m = records.missing_from_case({**SEARCH, 'text': 'Procuro minha mae Rosa.'})
        f = records.found_from_shelter({**SHELTER, 'quote': 'Deu entrada dona Rosa.'})
        self.assertEqual(matcher.match([m], [f]), [])

    def test_age_conflict_and_far_place_exclude(self):
        m = records.missing_from_case(SEARCH)
        f = records.found_from_shelter({**SHELTER, 'quote': SHELTER['quote'].replace('77', '30')}, PLACES['S1'])
        self.assertEqual(matcher.match([m], [f]), [])
        far = records.found_from_shelter(SHELTER, {'lat': -33.0, 'lon': -53.0, 'municipality': 'Rio Grande'})
        m2 = {**m, 'lat': -29.9, 'lon': -51.1}
        self.assertEqual(matcher.match([m2], [far]), [])

    def test_matcher_not_on_triage_path(self):
        for rel in ('app/pipeline.py', 'app/engines/world_model/registry.py', 'app/feedback.py'):
            self.assertNotIn('reunite', (ROOT / rel).read_text(encoding='utf-8'), rel)

    def test_routes_get_post_and_origin_guard(self):
        svc = service()
        svc.registry = type('R', (), {'read': lambda self: CASES})()
        svc.shelters = type('S', (), {'shelters': type('H', (), {'store': type('T', (), {'events': [SHELTER]})(), 'places': lambda self, now: PLACES})()})()
        sent = []
        h = Fake('/api/reunite', sent)
        routes.handle(h, svc, 'GET')
        self.assertEqual(sent[0][0], 200)
        self.assertEqual(len(sent[0][1]['candidates']), 1)
        pid = sent[0][1]['candidates'][0]['id']
        bad = Fake('/api/reunite', sent, body={'pair_id': pid, 'action': 'confirm', 'actor': 'x'}, origin='http://evil.example')
        routes.handle(bad, svc, 'POST')
        self.assertEqual(sent[-1][0], 403)
        self.assertEqual(svc.notes('c1'), [])
        ok = Fake('/api/reunite', sent, body={'pair_id': pid, 'action': 'confirm', 'actor': 'Ana'})
        routes.handle(ok, svc, 'POST')
        self.assertEqual(sent[-1][0], 200)
        self.assertEqual(len(svc.notes('c2')), 1)

    def test_ui_asset_whitelisted_and_small(self):
        self.assertIn("/v2/reunite.js", (ROOT / 'app/web/routes_v2.py').read_text(encoding='utf-8'))
        self.assertLessEqual((ROOT / 'app/web/v2/reunite.js').stat().st_size, 6144)
        self.assertIn('reunite.js', (ROOT / 'app/web/v2/index.html').read_text(encoding='utf-8'))


def sources_kw():
    return {'asof': None, 'cases': CASES, 'shelter_events': [SHELTER], 'places': PLACES}


class Fake:
    def __init__(self, path, sent, body=None, origin=None):
        raw = json.dumps(body).encode() if body is not None else b''
        self.path, self.rfile = path, io.BytesIO(raw)
        self.headers = {'Content-Length': str(len(raw)), 'Content-Type': 'application/json', 'Host': 'localhost:8000'}
        if origin:
            self.headers['Origin'] = origin
        self.sent = sent

    def send_json(self, status, payload):
        self.sent.append((status, payload))


if __name__ == '__main__':
    unittest.main()
