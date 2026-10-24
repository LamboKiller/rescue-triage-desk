import concurrent.futures
import json
import re
import tempfile
import unittest
from support import Scratch
from pathlib import Path
from app.agents.spans import validate
from app.decide import decide, timestamp
from app.geo.streets import normalize, lookup
from app.redact import redact
from app.engines.world_model.registry import Registry, Conflict

TIME = '2024-05-06T14:00:00-03:00'
ROWS = [{'display_name': 'Rua das Flores', 'municipality': 'Porto Alegre',
         'any_in_water_2024-05-06': '1', 'any_in_water_2024-05-08': '0'}]


def case(mid='demo', text='3 pessoas', at=TIME):
    return {'message_id': mid, 'text': text, 'received_at': at, 'synthetic': True,
            'result': {'priority': 1, 'decision': 'SEND_CANDIDATE'}}


class PrivacyTests(unittest.TestCase):
    def test_identifiers(self):
        # Construct test identifiers at runtime so the repository has no PII-looking fixtures.
        cpf = '.'.join(['123', '456', '789'])+'-'+'01'
        phone = '('+'51'+') '+'9'+'1234'+'-'+'5678'
        output = redact(cpf+' '+phone+' '+'demo'+'@'+'example.org')
        self.assertIn('[CPF REDIGIDO]', output)
        self.assertIn('[TELEFONE REDIGIDO]', output)
        self.assertIn('[EMAIL REDIGIDO]', output)
        self.assertNotIn('1234', output)
        self.assertEqual(redact('número 120, 3 pessoas FONE-TESTE-A'), 'número 120, 3 pessoas FONE-TESTE-A')
        with self.assertRaises(ValueError) as invalid:
            timestamp('demo'+'@'+'example.org')
        self.assertNotIn('example.org', str(invalid.exception))

    def test_spans(self):
        fields, rejected = validate({'fields': {'people': {'value': 3, 'quote': '3 PESSOAS'},
            'elderly': {'value': 1, 'quote': 'uma idosa'},
            'risk_words': {'value': 'água', 'quote': 'AGUA'}}}, '3 pessoas na água')
        self.assertEqual(set(fields), {'people', 'risk_words'})
        self.assertEqual(rejected[0]['field'], 'elderly')

    def test_malformed_values(self):
        fields, rejected = validate({'fields': {'people': {'value': True, 'quote': '3'},
             'number': {'value': {'evil': 1}, 'quote': '3'}}}, '3 pessoas')
        self.assertFalse(fields)
        self.assertEqual(len(rejected), 2)

    def test_valid_quote_cannot_support_invented_count_or_location(self):
        fields, rejected = validate({'fields': {
            'people': {'value': 999, 'quote': '3 pessoas'},
            'street': {'value': 'Rua das Flores', 'quote': 'Rua dos Andradas'},
            'number': {'value': '99', 'quote': 'número 20'}}},
            '3 pessoas na Rua dos Andradas, número 20')
        self.assertFalse(fields)
        self.assertEqual(len(rejected), 3)


class GeoDecisionTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize('R. das FLÔRES'), normalize('Rua Flores'))
        self.assertEqual(normalize('Av. dos Açores'), normalize('Avenida Açores'))

    def test_no_future_water_and_unknown_publication(self):
        loc = lookup(ROWS, 'R. Flores', 'PORTO ALEGRE', TIME)
        self.assertTrue(loc['found'])
        self.assertEqual(loc['observed_date'], '2024-05-06')
        self.assertTrue(loc['retrospective_water_overlap'])
        self.assertIsNone(loc['in_water_by_date'])
        self.assertIsNone(lookup(ROWS, 'Rua Flores', 'Porto Alegre', '2024-05-05T12:00:00-03:00')['observed_date'])
        self.assertFalse(lookup(ROWS, 'Rua Flores', 'Canoas', TIME)['found'])

    def test_rules(self):
        f = {k: {'value': v} for k, v in {'people': 3, 'number': '20', 'municipality': 'Porto Alegre'}.items()}
        loc = {'found': True, 'in_water_by_date': None}
        self.assertEqual(decide(f, loc, TIME, TIME)['decision'], 'SEND_CANDIDATE')
        del f['number']
        self.assertEqual(decide(f, loc, TIME, TIME)['decision'], 'CALLBACK')
        f['cross_street'] = {'value': 'Rua desconhecida'}
        self.assertEqual(decide(f, loc, TIME, TIME, cross_location={'found': False})['decision'], 'CALLBACK')
        self.assertEqual(decide(f, loc, TIME, TIME, cross_location={'found': True})['decision'], 'SEND_CANDIDATE')
        f['conflicting_counts'] = {'value': True}
        self.assertEqual(decide(f, loc, TIME, TIME, cross_location={'found': True})['decision'], 'CALLBACK')
        f['already_rescued'] = {'value': True}
        self.assertEqual(decide(f, loc, TIME, TIME)['decision'], 'REPORTED_RESCUED')

    def test_no_total_is_not_a_conflict(self):
        # "estou com meus dois bebes": children known, total not given -> ask the count, don't claim a conflict.
        f = {k: {'value': v} for k, v in {'children': 2, 'number': '20', 'municipality': 'Porto Alegre'}.items()}
        r = decide(f, {'found': True}, TIME, TIME)
        self.assertFalse(r['conflicting_counts'])
        self.assertIn('Quantas pessoas precisam de resgate?', r['questions'])
        f['people'] = {'value': 1}
        self.assertTrue(decide(f, {'found': True}, TIME, TIME)['conflicting_counts'])

    def test_failure_future_time(self):
        f = {k: {'value': v} for k, v in {'people': 1, 'number': '20', 'municipality': 'Porto Alegre'}.items()}
        loc = {'found': True}
        self.assertEqual(decide(f, loc, TIME, TIME, complete=False)['decision'], 'CALLBACK')
        self.assertEqual(decide(f, loc, TIME, '2024-05-07T12:00:00-03:00')['decision'], 'CALLBACK')
        f['already_rescued'] = {'value': True}
        f['risk_words'] = {'value': 'telhado'}
        future = decide(f, loc, TIME, '2024-05-07T12:00:00-03:00')
        self.assertEqual(future['decision'], 'CALLBACK')
        self.assertEqual(future['priority'], 0)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'events.jsonl'
        self.r = Registry(self.path)

    def test_duplicate_and_mutation_conflicts_retained(self):
        first = self.r.ingest(case())
        self.assertEqual(first, self.r.ingest(case()))
        changed = self.r.ingest(case(text='4 pessoas'))
        self.assertEqual(changed['version'], 2)
        self.assertEqual(len(changed['facts']), 2)
        self.assertEqual(changed['facts'][0]['text'], '3 pessoas')

    def test_stale_retained_and_rebuild(self):
        first = self.r.ingest(case(at='2024-05-07T14:00:00-03:00'))
        self.r.ingest(case(text='2 pessoas', at=TIME))
        read = Registry(self.path).read(first['case_id'])
        self.assertEqual(read['text'], '3 pessoas')
        self.assertEqual(len(read['facts']), 2)
        self.assertEqual(read, self.r.read(first['case_id']))

    def test_human_transition_gate_and_versions(self):
        c = self.r.ingest(case())
        cid = c['case_id']
        with self.assertRaises(PermissionError):
            self.r.action(cid, 'confirm_location', 1, 'demo')
        with self.assertRaises(ValueError):
            self.r.action(cid, 'approve_dispatch', 1, 'demo', human=True)
        with self.assertRaises(ValueError):
            self.r.action(cid, 'dispatch', 1, 'demo', human=True)
        c = self.r.action(cid, 'confirm_location', 1, 'demo', human=True)
        self.assertEqual(c['version'], 2)
        with self.assertRaises(Conflict):
            self.r.action(cid, 'approve_dispatch', 1, 'demo', human=True)
        for action, status in [('approve_dispatch', 'human_approved'), ('dispatch', 'dispatched'), ('field_confirm', 'field_confirmed')]:
            c = self.r.action(cid, action, c['version'], 'demo', human=True)
            self.assertEqual(c['status'], status)

    def test_edit_invalidates_approval(self):
        c = self.r.ingest(case())
        c = self.r.action(c['case_id'], 'confirm_location', 1, 'demo', human=True)
        c = self.r.action(c['case_id'], 'approve_dispatch', 2, 'demo', human=True)
        c = self.r.ingest(case(text='agora 5 pessoas'))
        self.assertFalse(c['location_confirmed'])
        self.assertEqual(c['status'], 'proposed')

    def test_replay_reanalysis_does_not_return_later_evidence(self):
        initial = {**case(), 'replay_time': '2024-05-08T14:00:00-03:00'}
        c = self.r.ingest(initial)
        earlier = {**case(), 'replay_time': TIME}
        c = self.r.ingest(earlier)
        self.assertEqual(c['replay_time'], TIME)
        self.assertEqual(c['version'], 2)
        self.assertEqual(self.r.ingest(earlier)['version'], 2)

    def test_ten_concurrent_writers_zero_lost(self):
        def writer(i):
            r = Registry(self.path)
            for j in range(10):
                item = case(mid='shared', text=f'observação {i}:{j}')
                r.ingest(item)
                r.ingest(item)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(writer, range(10)))
        c = self.r.read()[0]
        self.assertEqual(c['version'], 100)
        self.assertEqual(len(c['facts']), 100)
        self.assertEqual(len(self.path.read_text(encoding='utf-8').splitlines()), 100)

    def test_two_competing_actions(self):
        c = self.r.ingest(case())
        def action(_):
            try:
                self.r.action(c['case_id'], 'confirm_location', 1, 'demo', human=True)
                return 'ok'
            except Conflict:
                return 'conflict'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(action, range(2))), ['conflict', 'ok'])


if __name__ == '__main__':
    unittest.main()
