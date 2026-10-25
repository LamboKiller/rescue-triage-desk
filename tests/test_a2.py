"""Place-memory approval, evidence and replay safety; no providers."""
import time
import unittest
from support import Scratch
from pathlib import Path
from unittest.mock import patch

from app.agents.location import locate
from app.engines.world_model.registry import Registry, Conflict
from app.memory.service import PlaceMemory


def place(pid='11', name='Mercado Aurora', city='Canoas'):
    return dict(osm_type='way', osm_id=pid, name=name, municipality=city,
                category='shop:supermarket', lat='-29.92', lon='-51.18',
                curated_aliases=[], alt_names='', street='', neighbourhood='')


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Registry(Path(self.tmp.name)/'world.jsonl')
        self.rows = [place(), place('22', 'Mercado Horizonte')]
        self.memory = PlaceMemory(self.registry, self.rows)
        self.catalogue = patch('app.memory.service.catalogue', return_value=self.rows)
        self.catalogue.start()
        self.addCleanup(self.catalogue.stop)
        self.clock = patch('app.memory.service.now', return_value='2024-05-07T10:00:00Z')
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def confirm(self, mid='one', phrase='mercadinho das flores'):
        case = self.registry.ingest(dict(message_id=mid, text=f'Estamos no {phrase}, em Canoas.',
            received_at='2024-05-06T10:00:00Z', replay_time='2024-05-07T12:00:00Z',
            fields={'landmark': {'value': 'Mercado Aurora', 'quote': phrase}},
            landmark_check={'matched': self.rows[0]}, result={'priority': 1}))
        return self.registry.action(case['case_id'], 'confirm_location', case['version'], 'Maria', human=True)

    def proposal(self):
        self.confirm()
        entries = self.memory.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['status'], 'pending')
        return entries[0]

    def resolve(self, text='Socorro no mercadinho das flores, em Canoas.', replay='2024-05-08T12:00:00Z'):
        return locate([], self.rows, {}, text, replay, None, time.monotonic()+5, memory=self.memory)

    def test_approval_next_message_zero_calls_and_provenance(self):
        p = self.proposal()
        self.assertNotEqual(self.resolve()[3]['location_path'], 'deterministic_alias')
        self.memory.decide(p['id'], 'approve', 'Maria', human=True)
        _, _, landmark, trace, calls = self.resolve()
        self.assertEqual(landmark['matched']['osm_id'], '11')
        self.assertEqual(trace['evidence']['alias_row']['source'], 'learned')
        self.assertIn('caso '+p['evidence_case_id'], trace['memory_note'])
        self.assertEqual(calls, [])
        self.assertEqual(len(self.registry.read()), 1)

    def test_reject_and_revoke_never_repropose_pair(self):
        for decision in ('reject', 'revoke'):
            with self.subTest(decision=decision):
                phrase = 'galpao das violetas' if decision == 'reject' else 'venda das rosas'
                self.confirm(decision, phrase)
                p = self.memory.entries()[-1]
                if decision == 'revoke':
                    self.memory.decide(p['id'], 'approve', 'Maria', human=True)
                self.memory.decide(p['id'], decision, 'Maria', human=True)
                self.confirm(decision+'again', phrase)
                self.assertEqual(len([e for e in self.memory.entries() if e['phrase'] == phrase]), 1)
                self.assertFalse(self.memory.aliases('2024-05-08T12:00:00Z'))

    def test_city_scope_contradiction_and_replay(self):
        p = self.proposal()
        self.memory.decide(p['id'], 'approve', 'Maria', human=True)
        for text in ('No mercadinho das flores.', 'No mercadinho das flores em Porto Alegre.',
                     'No mercadinho das flores em Canoas ou Porto Alegre.',
                     'Moro no mercadinho das flores em Canoas; o pedido é em Porto Alegre.'):
            self.assertNotEqual(self.resolve(text)[3]['location_path'], 'deterministic_alias')
        self.assertNotEqual(self.resolve(replay='2024-05-07T09:59:59Z')[3]['location_path'], 'deterministic_alias')
        with patch('app.memory.service.now', return_value='2024-05-09T10:00:00Z'):
            self.memory.decide(p['id'], 'revoke', 'Maria', human=True)
        self.assertEqual(self.resolve()[3]['location_path'], 'deterministic_alias')
        self.assertNotEqual(self.resolve(replay='2024-05-10T00:00:00Z')[3]['location_path'], 'deterministic_alias')

    def test_curated_wins_and_source_rows_unmodified(self):
        p = self.proposal()
        self.memory.decide(p['id'], 'approve', 'Maria', human=True)
        self.rows[1]['curated_aliases'] = [dict(alias=p['phrase'], municipality='Canoas', note='reviewed')]
        self.assertEqual(self.resolve()[2]['matched']['osm_id'], '22')
        self.assertFalse(self.rows[0].get('learned_aliases'))

    def test_human_only_and_state_transition(self):
        p = self.proposal()
        with self.assertRaises(PermissionError):
            self.memory.decide(p['id'], 'approve', 'agent')
        with self.assertRaises(ValueError):
            self.memory.decide(p['id'], 'approve', '', human=True)
        self.memory.decide(p['id'], 'approve', 'Maria', human=True)
        with self.assertRaises(Conflict):
            self.memory.decide(p['id'], 'reject', 'Maria', human=True)

    def test_exact_quote_only_and_confirmation_required(self):
        c = self.confirm()
        with self.assertRaises(ValueError):
            self.memory.propose(c, 'invented phrase', 'way:11')
        with self.assertRaises(ValueError):
            self.memory.propose({**c, 'location_confirmed': False}, 'mercadinho das flores', 'way:11')

    def test_automatic_capture_without_extracted_nickname(self):
        for phrase in ('prédio violeta da praça', 'MVR da estação'):
            case = self.registry.ingest(dict(message_id=phrase, text=f'Estamos no {phrase}, em Canoas.',
                received_at='2024-05-06T10:00:00Z', fields={},
                landmark_check={'matched': self.rows[0]}, result={'priority': 1}))
            self.registry.action(case['case_id'], 'confirm_location', case['version'], 'Maria', human=True)
            self.assertEqual(self.memory.entries()[-1]['phrase'], phrase)

    def test_pipeline_uses_the_same_registry_memory(self):
        import contextlib
        import io
        from app.data.source import LocalSource
        from app.pipeline import Pipeline
        p = self.proposal()
        self.memory.decide(p['id'], 'approve', 'Maria', human=True)
        rows = self.rows
        class Source(LocalSource):
            def landmarks(self, **kwargs):
                return rows
            def streets(self, **kwargs):
                return []
        with contextlib.redirect_stdout(io.StringIO()):
            case = Pipeline(self.registry, sample=True, source=Source()).run(dict(
                replay_time='2024-05-08T12:00:00Z', messages=[dict(message_id='next',
                text='Socorro, 3 pessoas no mercadinho das flores, em Canoas.',
                received_at='2024-05-08T11:00:00Z')]))['cases'][0]
        self.assertEqual(case['landmark_check']['matched']['osm_id'], '11')
        self.assertIn('memory_note', case['agents']['location'])
        self.assertEqual(case['calls'], [])

    def test_http_memory_controls_and_static_script(self):
        import http.client
        import json
        import threading
        from app.web.server import create_server
        p = self.proposal()
        server = create_server('127.0.0.1', 0, sample=True, registry_path=self.registry.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))

        def request(method, path, body=None, origin=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = origin
            connection.request(method, path, json.dumps(body) if body else None, headers)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result

        self.assertEqual(request('GET', '/api/memory')[0], 200)
        self.assertIn(b'DeskMemory', request('GET', '/v2/memory.js')[1])
        body = dict(id=p['id'], action='approve', actor='Maria')
        self.assertEqual(request('POST', '/api/memory', body, 'https://outside.invalid')[0], 403)
        self.assertEqual(request('POST', '/api/memory', body)[0], 200)
        self.assertEqual(request('POST', '/api/memory', body)[0], 409)
        self.assertEqual(request('GET', '/api/memory?at=bad')[0], 400)
        historic = json.loads(request('GET', '/api/memory?at=2024-05-07T09:00:00Z')[1])
        self.assertEqual(historic['entries'], [])


if __name__ == '__main__':
    unittest.main()
