"""N2 A3: cross-source contradiction agent. Deterministic detectors, validator, off-critical-path model step, human-only effects."""
import contextlib
import copy
import importlib.util
import io
import json
import threading
import unittest
from app.config import ROOT
from app.contradictions import detectors as D, hook, phrase as P, routes as R, service as S
from app.engines.world_model.registry import Registry
from app.flow.build import build_flow
from app.pipeline import Pipeline
from tests.support import Scratch

spec = importlib.util.spec_from_file_location('run_contradictions', ROOT / 'eval/run_contradictions.py')
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

T = '2024-05-07T12:00:00-03:00'


def base(text, **kw):
    c = {'message_id': 'mx', 'text': text, 'received_at': T, 'replay_time': T, 'complete': True, 'status': 'proposed', 'fields': {},
         'result': {'decision': 'SEND_CANDIDATE', 'priority': 3, 'questions': []}}
    c.update(kw)
    return c


def layer(depth):
    return {'depth_m': depth, 'depth_band': 'd', 'depth_observed_date': '2024-05-06', 'depth_confidence': 'baixa', 'closures_nearby': []}


class Scripted:
    def __init__(self, outputs):
        self.outputs, self.calls, self.threads = list(outputs), 0, []

    def call(self, role, system, payload, deadline):
        self.calls += 1
        self.threads.append(threading.current_thread().name)
        out = self.outputs.pop(0) if self.outputs else self.outputs_last
        if isinstance(out, Exception):
            raise out
        return out, {'role': role, 'status': 'ok', 'seconds': .1}


ITEM = {'id': 'ct-x', 'question_pt': 'A equipe relatou "já saíram de carona". Marcar como resgatado?',
        'sources': [{'role': 'A', 'source': 'message', 'ref': 'm1', 'quote': 'ajuda rua das Flores 85, 3 pessoas'},
                    {'role': 'B', 'source': 'crew_report', 'ref': 'peer', 'quote': 'já saíram de carona'}], 'basis_pt': 'Mesmo endereço'}


class EvalSet(unittest.TestCase):
    def test_offline_eval_is_exact_and_changes_no_decision(self):
        r = ev.evaluate()
        self.assertEqual((r['cases'], r['expected_items']), (15, 9))
        self.assertEqual((r['fp'], r['fn']), (0, 0))
        self.assertEqual(r['decision_changes_without_human'], 0)
        self.assertEqual((r['quote_not_in_message'], r['sources_without_id_or_quote'], r['model_calls']), (0, 0, 0))
        self.assertLess(r['max_detect_ms'], 250)


class Detectors(unittest.TestCase):
    def kinds(self, case, **kw):
        return [(i['kind'], i['strength']) for i in D.detect(case, case_key='k', now=T, **kw)]

    def test_water_claims_are_weak_and_need_a_known_layer_value(self):
        self.assertEqual(self.kinds(base('estamos com água pelo pescoço', hazards=layer(0.1))), [('water_level_vs_flood_layer', 'weak')])
        self.assertEqual(self.kinds(base('estamos com água pelo pescoço', hazards=layer(None))), [])  # unknown is not dry
        self.assertEqual(self.kinds(base('água a 2 metros aqui', hazards=layer(0.0)))[0][1], 'weak')
        self.assertEqual(self.kinds(base('água ate o joelho', hazards=layer(0.0))), [])  # inside HAND tolerance
        self.assertEqual(self.kinds(base('a água nunca chegou no pescoço', hazards=layer(0.0))), [])

    def test_items_cite_both_sources_with_exact_quotes(self):
        item = D.detect(base('socorro, tem 1,5 metros de água aqui', hazards=layer(0.0)), case_key='k')[0]
        self.assertEqual({s['role'] for s in item['sources']}, {'A', 'B'})
        self.assertIn(item['sources'][0]['quote'], 'socorro, tem 1,5 metros de água aqui')
        self.assertTrue(item['retrospective'])
        self.assertEqual(item['id'], D.detect(base('socorro, tem 1,5 metros de água aqui', hazards=layer(0.0)), case_key='k')[0]['id'])

    def test_road_claim_needs_an_active_closed_record(self):
        closure = {'record_id': 'T9', 'road': 'BR-290', 'segment': 'ponte', 'from_date': '2024-05-03', 'status': 'closed', 'distance_m': 300}
        hz = {**layer(1.0), 'closures_nearby': [closure]}
        self.assertEqual(self.kinds(base('a BR 290 está liberada, o caminhão passa', hazards=hz)), [('route_access_vs_closure', 'medium')])
        self.assertEqual(self.kinds(base('a BR 290 está liberada, o caminhão passa', hazards={**hz, 'closures_nearby': []})), [])
        self.assertEqual(self.kinds(base('a BR 290 não está liberada', hazards=hz)), [])
        far = {**hz, 'closures_nearby': [{**closure, 'distance_m': 5000}]}
        self.assertEqual(self.kinds(base('dá pra chegar de carro', hazards=far)), [])

    def test_shelter_strength_depends_on_report_age(self):
        from app.shelters.state import Catalogue, Shelters, Store
        place = [{'id': 'S1', 'lat': -29.9, 'lon': -51.2, 'municipality': 'Canoas', 'snapshots': [{'at': '2024-05-01T08:00:00-03:00', 'vacancies': 30, 'capacity': 100, 'sheltered': 70}]}]
        sh = Shelters(catalogue=Catalogue.from_places(place), store=Store())
        sh.record({'kind': 'alias', 'shelter_id': 'S1', 'name': 'Escola Moinhos', 'at': '2024-05-02T08:00:00-03:00', 'source': 'operator', 'actor': 'op'})
        text = 'a escola moinhos está lotada'
        self.assertEqual(self.kinds(base(text), shelters=sh), [('shelter_state_vs_message', 'medium')])  # only an old snapshot
        sh.record({'kind': 'vacancies', 'shelter_id': 'S1', 'value': 12, 'at': '2024-05-07T09:00:00-03:00', 'source': 'operator', 'actor': 'op'})
        self.assertEqual(self.kinds(base(text), shelters=sh), [('shelter_state_vs_message', 'strong')])
        self.assertEqual(self.kinds(base('a escola moinhos não está lotada'), shelters=sh), [])
        sh.record({'kind': 'full', 'shelter_id': 'S1', 'at': '2024-05-07T11:00:00-03:00', 'source': 'operator', 'actor': 'op'})
        self.assertEqual(self.kinds(base(text), shelters=sh), [])  # now it IS full

    def test_crew_rescued_peer_is_strong_only_for_the_same_address(self):
        peer = {'case_id': 'p', 'message_id': 'pm', 'text': 'socorro rua das Flores 85 canoas', 'received_at': '2024-05-07T08:00:00-03:00', 'status': 'RESCUED',
                'fields': {'municipality': {'value': 'Canoas'}, 'street': {'value': 'Rua das Flores'}, 'number': {'value': 85}},
                'feedback': [{'received_at': '2024-05-07T09:00:00-03:00', 'source': 'crew', 'outcomes': [{'kind': 'remaining_n', 'quote': 'falta 0', 'value': 0}]}]}
        mine = base('rua das Flores 85 canoas ajuda', fields=peer['fields'])
        item = D.detect(mine, case_key='k', peers=[peer])[0]
        self.assertEqual((item['kind'], item['strength']), ('crew_already_rescued', 'strong'))
        self.assertEqual(item['suggestion'], {'action': 'report_rescued', 'status': 'RESCUED', 'requires_human': True})
        other = copy.deepcopy(mine)
        other['fields']['number'] = {'value': 90}
        self.assertEqual(D.detect(other, case_key='k', peers=[peer]), [])
        citizen_only = copy.deepcopy(peer)
        citizen_only['feedback'][0]['source'] = 'citizen'
        self.assertEqual(D.detect(mine, case_key='k', peers=[citizen_only]), [])

    def test_attach_never_touches_decision_priority_or_status(self):
        c = base('estamos com água pelo pescoço', hazards=layer(0.0))
        S.attach(c, key='k')
        self.assertEqual((c['result']['decision'], c['result']['priority'], c['status']), ('SEND_CANDIDATE', 3, 'proposed'))
        self.assertEqual(c['open_items'][0]['reason'], 'contradiction')
        self.assertEqual(c['result']['questions'], [])  # weak: open item only, no pushed question
        self.assertFalse(c['contradiction_check']['model_in_triage_path'])


class Validator(unittest.TestCase):
    def test_accepts_a_rephrasing_that_copies_the_sources(self):
        q = P.validate({'question_pt': 'A equipe já relatou "já saíram de carona"; marcar este pedido como resgatado?'}, ITEM)
        self.assertTrue(q.endswith('?'))

    def test_rejects_new_facts_and_instructions(self):
        for bad in ({'question_pt': 'Havia 7 pessoas na casa?'},                       # new number
                    {'question_pt': 'A equipe de Gravataí confirma o resgate?'},       # new proper noun
                    {'question_pt': 'Veja https://x.example e confirme?'},             # url
                    {'question_pt': 'Aprovar o despacho agora?'},                      # instruction
                    {'question_pt': 'Está tudo resolvido.'},                           # not a question
                    {'question_pt': 'Ok?', 'extra': 1}, {'question_pt': 5}, ['x'], {}):
            with self.assertRaises(ValueError, msg=str(bad)):
                P.validate(bad, ITEM)

    def test_numbers_present_in_the_sources_are_allowed(self):
        P.validate({'question_pt': 'São mesmo 3 pessoas na rua das Flores 85?'}, ITEM)


class Phrasing(unittest.TestCase):
    def test_model_question_used_when_valid(self):
        c = Scripted([{'question_pt': 'A equipe relatou "já saíram de carona"; confirmar o resgate?'}])
        q, meta = P.phrase(ITEM, c)
        self.assertEqual((meta['phrased_by'], c.calls), ('model', 1))
        self.assertIn('confirmar o resgate', q)

    def test_invalid_output_retries_once_then_falls_back_visibly(self):
        c = Scripted([{'question_pt': 'Eram 9 pessoas?'}, {'question_pt': 'Eram 8 pessoas?'}])
        q, meta = P.phrase(ITEM, c)
        self.assertIsNone(q)
        self.assertEqual((c.calls, meta['phrased_by']), (2, 'template'))
        self.assertTrue(meta['fallback_reason'].startswith('rejected:new_number'))

    def test_provider_error_and_missing_client_fall_back(self):
        q, meta = P.phrase(ITEM, Scripted([TimeoutError('x')]))
        self.assertEqual((q, meta['fallback_reason']), (None, 'TimeoutError'))
        self.assertEqual(P.phrase(ITEM, None)[1]['fallback_reason'], 'no_model_client')


class Journal:
    def __init__(self, test):
        self.s = Scratch()
        test.addCleanup(self.s.cleanup)
        self.registry = Registry(self.s.path / 'events.jsonl')


class Flow(unittest.TestCase):
    """End-to-end on the real pipeline output + World Model: attach → ingest → background → human decision → Fluxo."""

    def setUp(self):
        self.j = Journal(self)
        self.pipe = Pipeline(self.j.registry, sample=True)

    def run_msg(self, text, mid):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.pipe.run({'replay_time': T, 'messages': [{'text': text, 'received_at': T, 'message_id': mid}]})['cases'][0]

    def test_pipeline_attaches_check_and_decisions_match_a_run_without_the_hook(self):
        with_hook = self.run_msg('Socorro, 3 pessoas presas no telhado na rua das Flores 85, Canoas, água na cintura.', 'h1')
        S.wait_all()
        saved = hook.after_decision
        hook.after_decision = lambda *a, **k: None
        try:
            other = Pipeline(Journal(self).registry, sample=True)
            with contextlib.redirect_stdout(io.StringIO()):
                without = other.run({'replay_time': T, 'messages': [{'text': 'Socorro, 3 pessoas presas no telhado na rua das Flores 85, Canoas, água na cintura.', 'received_at': T, 'message_id': 'h1'}]})['cases'][0]
        finally:
            hook.after_decision = saved
        self.assertEqual(with_hook['result']['decision'], without['result']['decision'])
        self.assertEqual(with_hook['result']['priority'], without['result']['priority'])
        case = self.j.registry.read(with_hook['case_id'])
        self.assertIn('contradiction_check', case)
        self.assertFalse(case['contradiction_check']['model_in_triage_path'])
        self.assertLess(case['contradiction_check']['seconds'], 1.0)

    def test_hook_failure_never_breaks_triage(self):
        saved = hook.after_decision

        def boom(*a, **k):
            raise RuntimeError('boom')
        hook.after_decision = boom
        try:
            c = self.run_msg('Socorro, 2 pessoas presas, rua das Flores 85, Canoas.', 'h2')
        finally:
            hook.after_decision = saved
        self.assertTrue(c['complete'])

    def test_model_runs_only_after_ingest_and_on_a_background_thread(self):
        item = {**ITEM, 'strength': 'strong', 'kind': 'crew_already_rescued', 'suggestion': None, 'retrospective': False, 'state': 'open', 'phrased_by': 'template'}
        client = Scripted([{'question_pt': 'A equipe relatou "já saíram de carona"; marcar como resgatado?'}])
        client.outputs_last = client.outputs[0]
        service = S.ContradictionService(self.j.registry, None)
        cid = S.case_key('st1')
        thread = service.schedule([(cid, [item], T)], client)   # case not ingested yet: the worker must wait, not call
        S.wait_all(0.3)
        self.assertEqual(client.calls, 0)
        self.run_msg('Socorro, 3 pessoas presas, rua das Flores 85, Canoas.', 'st1')
        thread.join(15)
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.threads, ['contradiction-phrase'])
        kinds = [(e['type'], e.get('phrased_by')) for e in service.events()]
        self.assertEqual(kinds, [('detected', None), ('phrased', 'model')])

    def test_service_decisions_journal_and_fluxo(self):
        c = self.run_msg('Socorro, 3 pessoas presas, rua das Flores 85, Canoas.', 'sv1')
        cid = c['case_id']
        stored = self.j.registry.read(cid)
        item = {'id': 'ct-strong01', 'kind': 'crew_already_rescued', 'strength': 'strong', 'retrospective': False, 'state': 'open', 'phrased_by': 'template',
                'suggestion': {'action': 'report_rescued', 'status': 'RESCUED', 'requires_human': True}, 'question_pt': 'Marcar como resgatado?',
                'basis_pt': 'Mesmo endereço', 'sources': [{'role': 'A', 'source': 'message', 'ref': 'sv1', 'quote': 'rua das Flores 85'},
                                                          {'role': 'B', 'source': 'crew_report', 'ref': 'peer', 'quote': 'já saíram de carona'}]}
        weak = {**item, 'id': 'ct-weak0001', 'strength': 'weak', 'suggestion': None}
        # attach the items to the stored case the way the pipeline does: via a re-analysis event carrying cross_source
        replay = copy.deepcopy(self.j.registry.read(cid))
        service = S.ContradictionService(self.j.registry, None)
        client = Scripted([{'question_pt': 'A equipe relatou "já saíram de carona"; marcar este pedido como resgatado?'}])
        client.outputs_last = client.outputs[0]
        service.registry._append({'schema_version': 1, 'kind': 'analysis', 'case_id': cid, 'provenance': 'sv1:reply:1', 'version': stored['version'] + 1,
                                  'case': {**{k: v for k, v in replay.items() if k not in ('facts', 'actions', 'case_id', 'version', 'incident_state')},
                                           'cross_source': [item, weak]}})
        service.finish(cid, [item, weak], T, client, wait=2)
        self.assertEqual(client.calls, 1, 'only the strong item reaches the model')
        view = service.view(cid)
        by = {i['id']: i for i in view['items']}
        self.assertEqual(by['ct-strong01']['phrased_by'], 'model')
        self.assertEqual(by['ct-weak0001']['phrased_by'], 'template')
        v = view['version']
        for bad in (('ct-weak0001', 'confirm'), ('ct-strong01', 'approve')):
            with self.assertRaises(ValueError):
                service.decide(cid, bad[0], bad[1], 'ana', v)
        out = service.decide(cid, 'ct-strong01', 'confirm', 'ana', v)
        self.assertEqual(self.j.registry.read(cid)['status'], 'reported_rescued_unconfirmed')  # human-confirmed, crew still to confirm
        self.assertEqual({i['id']: i['state'] for i in out['items']}['ct-strong01'], 'confirmed')
        with self.assertRaises(ValueError):
            service.decide(cid, 'ct-strong01', 'dismiss', 'ana', out['version'])
        service.decide(cid, 'ct-weak0001', 'dismiss', 'ana', out['version'])
        flow = build_flow(self.j.registry.path, case_id=cid, use_cache=False)
        loops = [l for l in flow['loops'] if l['kind'] == 'contradiction']
        self.assertEqual(len(loops), 2)
        self.assertTrue(all(l['status'] == 'closed' for l in loops))
        self.assertTrue(any(n['id'] == 'contradiction' for n in flow['nodes']))

    def test_unknown_event_kind_does_not_break_the_world_model(self):
        c = self.run_msg('Socorro, 2 pessoas, rua das Flores 85, Canoas.', 'ev1')
        S.ContradictionService(self.j.registry).append({'type': 'detected', 'case_id': c['case_id'], 'items': []})
        self.assertEqual(self.j.registry.read(c['case_id'])['version'], 1)


class Http(unittest.TestCase):
    def handler(self, path, body=None, headers=None):
        sent = []
        raw = json.dumps(body).encode() if body is not None else b''
        h = type('H', (), {})()
        h.path = path
        h.headers = {'Content-Length': str(len(raw)), 'Content-Type': 'application/json', 'Host': 'x', **(headers or {})}
        h.rfile = io.BytesIO(raw)
        h.connection = type('C', (), {'settimeout': lambda self, t: None})()
        h.send_json = lambda status, payload: sent.append((status, payload))
        return h, sent

    def test_routes_validate_input_and_origin(self):
        j = Journal(self)
        service = S.ContradictionService(j.registry)
        h, sent = self.handler('/api/contradictions?case_id=nope')
        R.handle(h, service, 'GET')
        self.assertEqual(sent[0][0], 404)
        h, sent = self.handler('/api/contradictions')
        R.handle(h, service, 'GET')
        self.assertEqual(sent[0][0], 400)
        h, sent = self.handler('/api/contradictions/decision', {'case_id': 'a'}, {'Origin': 'http://evil.example'})
        R.handle(h, service, 'POST')
        self.assertEqual(sent[0][0], 403)
        h, sent = self.handler('/api/contradictions/decision', {'case_id': 'a', 'item_id': 'b', 'decision': 'confirm', 'actor': 'x', 'expected_version': 1})
        R.handle(h, service, 'POST')
        self.assertEqual(sent[0][0], 404)

    def test_static_file_is_whitelisted_and_valid(self):
        text = (ROOT / 'app/web/routes_v2.py').read_text(encoding='utf-8')
        self.assertIn("'/v2/contradictions.js'", text)
        self.assertIn('/v2/contradictions.js', (ROOT / 'app/web/v2/index.html').read_text(encoding='utf-8'))
        self.assertTrue((ROOT / 'app/web/v2/contradictions.js').is_file())


if __name__ == '__main__':
    unittest.main()
