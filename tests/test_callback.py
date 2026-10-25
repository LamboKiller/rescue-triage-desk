"""Callback agent: open items, planner validator, reply loop, simulator guardrails and HTTP contract (offline, no network)."""
import contextlib
import io
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from tests.support import Scratch
from app.callback import planner, simulator
from app.callback.items import compute_items, diff_items
from app.callback.service import CallbackService
from app.engines.world_model.registry import Registry, Conflict
from app.pipeline import Pipeline

T0 = '2024-05-06T13:00:00-03:00'


def ids(items):
    return [i['id'] for i in items]


def case(fields=None, **extra):
    base = {'case_id': 'c1', 'version': 1, 'fields': fields or {}, 'checks': {'found': False}, 'landmark_check': None,
            'routing_flags': {}, 'route': {'id': 'incomplete'}, 'result': {'decision': 'CALLBACK', 'location_confidence': 'insuficiente'}}
    base.update(extra)
    return base


def f(value, quote=None):
    return {'value': value, 'quote': quote or str(value)}


class Scripted:
    def __init__(self, output=None, error=None):
        self.output, self.error, self.calls = output, error, 0

    def call(self, role, system, payload, deadline):
        self.calls += 1
        if self.error:
            raise self.error
        return self.output, {'role': role, 'status': 'ok'}


class ItemTests(unittest.TestCase):
    def test_no_location_no_people_orders_location_first(self):
        items = compute_items(case({}))
        self.assertEqual(ids(items)[:4], ['loc.municipality', 'loc.place', 'loc.number', 'people.count'])
        self.assertTrue(all(i['blocking'] for i in items))
        self.assertTrue(all(i['evidence'] for i in items))

    def test_complete_case_has_only_refining_items(self):
        c = case({'people': f(3, '3 pessoas'), 'municipality': f('Canoas'), 'street': f('Rua A'), 'number': f('10')},
                 checks={'found': True}, result={'decision': 'SEND_CANDIDATE'})
        items = compute_items(c)
        self.assertEqual(ids(items), ['vuln.unknown'])
        self.assertFalse(items[0]['blocking'])

    def test_conflict_stale_rescued_duplicate_and_derived(self):
        base = {'people': f(3), 'municipality': f('Canoas'), 'street': f('Rua A'), 'number': f('10'), 'elderly': f(1)}
        c = case(base, checks={'found': True}, stale=True,
                 contradictions=[{'field': 'people', 'previous': f(3), 'reply': f(5), 'quote': 'somos 5'}],
                 result={'decision': 'REPORTED_RESCUED', 'conflicting_counts': True, 'people_derived': True},
                 duplicates=[{'case_id': 'x', 'score': .95, 'reasons': ['same_street_number']}])
        got = {i['id']: i for i in compute_items(c)}
        self.assertEqual(set(got), {'people.conflict', 'stale.contact', 'rescue.unconfirmed', 'people.derived', 'dup.suspected'})
        self.assertFalse(got['rescue.unconfirmed']['resolvable_by_reply'])
        self.assertFalse(got['dup.suspected']['resolvable_by_reply'])
        self.assertEqual(got['people.conflict']['evidence'][0]['previous'], 3)

    def test_out_of_area_replaces_location_items(self):
        c = case({'people': f(2), 'municipality': f('Curitiba'), 'number': f('4')}, routing_flags={'out_of_area': True})
        self.assertEqual(ids(compute_items(c))[0], 'area.out_of_area')
        self.assertNotIn('loc.place', ids(compute_items(c)))

    def test_injection_and_incomplete_analysis_never_ask(self):
        for c in (case({'people': f(2)}, routing_flags={'injection': True}), case({}, route={'id': 'agent_failure'})):
            items = compute_items(c)
            self.assertEqual(len(items), 1)
            self.assertFalse(items[0]['ask'])
            self.assertEqual(planner.plan(items)['questions'], [])

    def test_diff_counts_only_asked_resolvable_items(self):
        before = compute_items(case({}))
        d = diff_items(before, before[:1], asked={'loc.municipality', 'loc.place'})
        self.assertEqual(d['resolved'], ['loc.place'])
        self.assertEqual((d['resolvable_before'], d['resolved_ratio']), (2, .5))
        self.assertEqual(d['remaining'], ['loc.municipality'])

class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.items = compute_items(case({}))

    def test_templates_are_minimum_ordered_and_pass_the_validator(self):
        out = planner.plan(self.items)
        self.assertEqual((out['source'], out['agent']['status']), ('templates', 'offline'))
        self.assertIn('offline', out['fallback_reason'])
        self.assertLessEqual(len(out['questions']), 3)
        self.assertEqual(len(out['questions']), 2)  # location group, people group
        self.assertEqual(out['questions'][0]['item_ids'][0], 'loc.municipality')
        planner.validate_plan({'questions': [{'text': q['text_pt'], 'items': q['item_ids']} for q in out['questions']]}, self.items)

    def test_non_blocking_items_ride_along_or_are_deferred(self):
        c = case({'people': f(2), 'municipality': f('Canoas')}, result={'decision': 'CALLBACK'})
        out = planner.plan(compute_items(c))
        self.assertEqual([q['item_ids'] for q in out['questions']], [['loc.place', 'loc.number']])
        self.assertEqual(out['deferred'], ['vuln.unknown'])  # blocking exists elsewhere; people group has no blocking item

    def test_validator_rejects_invented_facts_and_bad_mapping(self):
        base = {'text': 'Qual é a rua e o município?', 'items': ['loc.municipality', 'loc.place', 'loc.number']}
        bad = [dict(base, text='Vocês são 12 pessoas?'), dict(base, text='Fica na Rua Aurora?'), dict(base, text='São cinco pessoas?'),
               dict(base, text='É o "Mercado Central"?'), dict(base, items=['loc.zzz']), dict(base, items=[]), dict(base, text='Sem pergunta.'),
               dict(base, text='Veja http://x.example?')]
        for q in bad:
            with self.assertRaises(ValueError, msg=q):
                planner.validate_plan({'questions': [q]}, self.items)
        with self.assertRaises(ValueError):  # blocking items uncovered
            planner.validate_plan({'questions': [dict(base, items=['loc.municipality'])]}, self.items)
        with self.assertRaises(ValueError):  # more than three questions
            planner.validate_plan({'questions': [dict(base, text='Pergunta %d?' % n) for n in range(4)]}, self.items)
        with self.assertRaises(ValueError):
            planner.validate_plan({'questions': [base], 'extra': 1}, self.items)

    def test_validator_allows_text_quoted_from_evidence(self):
        c = case({'people': f(3), 'municipality': f('Canoas'), 'landmark': f('perto do mercado', 'perto do mercado')},
                 result={'decision': 'CALLBACK', 'location_confidence': 'insuficiente'})
        items = [i for i in compute_items(c) if i['id'] == 'loc.place']
        q = {'text': 'Você disse "perto do mercado": qual é a rua?', 'items': ['loc.place']}
        out = planner.validate_plan({'questions': [q]}, items)
        self.assertEqual(out[0]['item_ids'], ['loc.place'])

    def test_model_plan_accepted_when_valid(self):
        ok = {'questions': [{'text': 'Qual é o endereço (rua, número e município)?', 'items': ['loc.municipality', 'loc.place', 'loc.number']},
                            {'text': 'Quantas pessoas precisam de resgate?', 'items': ['people.count']}]}
        client = Scripted(ok)
        out = planner.plan(self.items, client)
        self.assertEqual((out['source'], out['agent']['status'], client.calls), ('model', 'ok', 1))

    def test_rejected_or_failing_model_falls_back_visibly(self):
        bad = Scripted({'questions': [{'text': 'Vocês são 7 pessoas?', 'items': ['people.count']}]})
        out = planner.plan(self.items, bad)
        self.assertEqual((out['source'], bad.calls), ('templates', 2))  # one short retry
        self.assertIn('validador rejeitou', out['fallback_reason'])
        down = planner.plan(self.items, Scripted(error=RuntimeError('x')))
        self.assertEqual(down['source'], 'templates')
        self.assertIn('RuntimeError', down['fallback_reason'])
        self.assertGreaterEqual(len(down['questions']), 1)


class LoopBase(unittest.TestCase):
    def setUp(self):
        s = Scratch()
        self.addCleanup(s.cleanup)
        self.pipe = Pipeline(Registry(s.path/'events.jsonl'), sample=True)
        self.log = s.path/'log.jsonl'

    def ingest(self, text, mid):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.pipe.run({'replay_time': T0, 'messages': [{'text': text, 'received_at': T0, 'message_id': mid}]})['cases'][0]

    def service(self, records=None, client=None):
        return CallbackService(self.pipe.registry, self.pipe, client, self.log, records if records is not None else {})

    def reply(self, service, cid, body):
        with contextlib.redirect_stdout(io.StringIO()):
            return service.reply(cid, body)


class LoopTests(LoopBase):
    RECORD = {'t1': {'message_id': 't1', 'citizen_replies': {'loc.municipality': 'Estamos em Canoas.', 'loc.place': 'É na Avenida Getúlio Vargas.',
                                                              'loc.number': 'Número 410.', 'people.count': 'Somos 3 pessoas.'}}}
    TEXT = 'Socorro, 3 pessoas presas no telhado, água subindo.'

    def test_real_reply_merges_reevaluates_and_diffs(self):
        c = self.ingest(self.TEXT, 'real-1')
        svc = self.service()
        view = svc.view(c['case_id'])
        self.assertEqual(view['decision'], 'CALLBACK')
        self.assertFalse(view['simulator_available'])
        out = self.reply(svc, c['case_id'], {'text': 'Canoas, Avenida Getúlio Vargas, número 410.', 'expected_version': 1})
        self.assertFalse(out['simulated'])
        self.assertFalse(out['reply_text'].startswith(simulator.PREFIX))
        self.assertEqual((out['diff']['version']['before'], out['diff']['version']['after']), (1, 2))
        self.assertEqual((out['diff']['decision']['before'], out['diff']['decision']['after'], out['diff']['decision']['changed']),
                         ('CALLBACK', 'SEND_CANDIDATE', True))
        self.assertEqual(out['diff']['items']['resolved'], ['loc.municipality', 'loc.place', 'loc.number'])
        self.assertIn('municipality', [x['field'] for x in out['diff']['fields_changed']])
        self.assertEqual(self.pipe.registry.read(c['case_id'])['version'], 2)
        self.assertIn('"simulated": false', self.log.read_text(encoding='utf-8'))

    def test_simulated_reply_is_labelled_and_answers_only_what_was_asked(self):
        c = self.ingest(self.TEXT, 't1')
        svc = self.service(self.RECORD)
        self.assertTrue(svc.view(c['case_id'])['simulator_available'])
        out = self.reply(svc, c['case_id'], {'simulated': True})
        self.assertTrue(out['simulated'])
        self.assertTrue(out['reply_text'].startswith('[SIMULADO] '))
        self.assertNotIn('Somos 3', out['reply_text'])  # people were already known: not asked, not volunteered
        self.assertEqual(out['diff']['decision']['after'], 'SEND_CANDIDATE')
        self.assertIn(simulator.PREFIX.strip(), self.pipe.registry.read(c['case_id'])['messages'][-1]['text'])

    def test_simulator_refuses_cases_without_truth_and_when_disabled(self):
        c = self.ingest(self.TEXT, 'real-2')
        with self.assertRaises(ValueError):
            self.reply(self.service(self.RECORD), c['case_id'], {'simulated': True})
        self.assertEqual(self.pipe.registry.read(c['case_id'])['version'], 1)
        c2 = self.ingest(self.TEXT+' ', 't1')
        with patch.dict('os.environ', {'CALLBACK_SIMULATOR': '0'}):
            with self.assertRaises(ValueError):
                self.reply(self.service(self.RECORD), c2['case_id'], {'simulated': True})
        self.assertFalse(simulator.available({'synthetic': True, 'message_id': 'x'}, {}))

    def test_stale_version_and_empty_reply_rejected(self):
        c = self.ingest(self.TEXT, 'real-3')
        svc = self.service()
        with self.assertRaises(Conflict):
            self.reply(svc, c['case_id'], {'text': 'Canoas', 'expected_version': 9})
        for body in ({}, {'text': '  '}, {'text': 5}):
            with self.assertRaises(ValueError):
                self.reply(svc, c['case_id'], body)
        with self.assertRaises(KeyError):
            svc.view('nope')

    def test_plan_is_cached_per_version_and_uses_the_agent_when_online(self):
        c = self.ingest(self.TEXT, 'real-4')
        ok = {'questions': [{'text': 'Qual é o endereço (rua, número e município)?', 'items': ['loc.municipality', 'loc.place', 'loc.number']}]}
        client = Scripted(ok)
        svc = self.service(client=client)
        first = svc.view(c['case_id'])
        svc.view(c['case_id'])
        self.assertEqual((first['plan']['source'], client.calls), ('model', 1))
        svc.view(c['case_id'], refresh=True)
        self.assertEqual(client.calls, 2)
        extra = Scripted({'questions': ok['questions']+[{'text': 'Há crianças, idosos ou pessoas acamadas aí?', 'items': ['vuln.unknown']}]})
        out = planner.plan(compute_items(self.pipe.registry.read(c['case_id'])), extra)
        self.assertEqual(out['source'], 'templates')  # non-blocking item in a group with nothing blocking is deferred, not asked


class EvalAndHttpTests(LoopBase):
    def test_eval_set_has_twelve_cases_with_hidden_truth(self):
        records = simulator.load_records()
        self.assertEqual(len(records), 12)
        for r in records.values():
            self.assertTrue(r['synthetic'] and r['truth']['hidden'] is True)

    def test_offline_eval_is_clean(self):
        from eval.run_callback import evaluate
        s = evaluate()['summary']
        self.assertEqual((s['invented_facts_in_questions'], s['unmapped_questions'], s['errors']), (0, 0, []))
        self.assertLessEqual(s['max_questions'], 3)
        self.assertEqual(s['plans_rejected_to_templates'], 5)  # the five scripted flawed plans, all caught by the validator
        self.assertEqual(s['replies_simulated_and_labelled'], '11/11')

    def test_http_contract(self):
        from app.web.server import create_server
        c = self.ingest('Socorro, 3 pessoas presas no telhado, água subindo.', 'cb01')
        server = create_server('127.0.0.1', 0, sample=True, pipeline=self.pipe)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        base = 'http://127.0.0.1:%d' % server.server_port

        def call(path, body=None):
            req = urllib.request.Request(base+path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        code, view = call('/api/cases/%s/callback' % c['case_id'])
        self.assertEqual(code, 200)
        self.assertEqual(view['mode'], 'offline')
        self.assertTrue(view['simulator_available'])
        self.assertLessEqual(len(view['plan']['questions']), 3)
        self.assertEqual(call('/api/cases/nope/callback')[0], 404)
        self.assertEqual(call('/api/cases/%s/callback/reply' % c['case_id'], {'text': ''})[0], 400)
        self.assertEqual(call('/api/cases/%s/callback/reply' % c['case_id'], {'simulated': True, 'expected_version': 7})[0], 409)
        code, out = call('/api/cases/%s/callback/reply' % c['case_id'], {'simulated': True, 'expected_version': 1})
        self.assertEqual(code, 200)
        self.assertTrue(out['simulated'] and out['reply_text'].startswith('[SIMULADO]'))
        self.assertEqual(out['diff']['decision']['after'], 'SEND_CANDIDATE')
        with urllib.request.urlopen(base+'/v2/callback.js') as r:
            self.assertIn(b'DeskCallback', r.read())


if __name__ == '__main__':
    unittest.main()
