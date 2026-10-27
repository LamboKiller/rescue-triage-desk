"""UXP: lean /api/cases, case detail, ETag, mode endpoint, supervisor default day, friendly errors."""
import contextlib
import http.client
import io
import json
import threading
import unittest
from unittest.mock import patch

from support import Scratch


class UXPTests(unittest.TestCase):
    def setUp(self):
        from app.web.server import create_server
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.server = create_server('127.0.0.1', 0, sample=True, registry_path=self.tmp.path / 'events.jsonl')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        self.addCleanup(self.conn.close)
        body = json.dumps({'replay_time': '2024-05-08T18:00:00-03:00', 'messages': [
            {'text': 'Somos 3 pessoas na Rua dos Andradas, 120, Porto Alegre. Precisamos de resgate.'}]})
        with patch('app.pipeline.ROOT', self.tmp.path), contextlib.redirect_stdout(io.StringIO()):
            self.get('POST', '/run', body)

    def get(self, method, path, body=None, headers=None):
        h = {'Content-Type': 'application/json', **(headers or {})}
        self.conn.request(method, path, body, h)
        r = self.conn.getresponse()
        data = r.read()
        return r.status, r, (json.loads(data) if data and r.getheader('Content-Type', '').startswith('application/json') else data)

    def test_summary_is_lean_and_detail_is_full(self):
        _, _, lean = self.get('GET', '/api/cases')
        _, _, full = self.get('GET', '/api/cases?full=1')
        c, f = lean['cases'][0], full['cases'][0]
        self.assertTrue(c['summary'])
        for k in ('facts', 'hazard_facts', 'hazards', 'incident_state'):
            self.assertNotIn(k, c)
        self.assertEqual({a['asset'] for a in c['fleet']}, {a['asset'] for a in f['fleet']})
        self.assertLessEqual(set(c['fleet'][0]), {'asset', 'label_pt', 'verdict'})
        self.assertEqual(c['live_priority'], f['live_priority'])
        self.assertLess(len(json.dumps(lean)), len(json.dumps(full)))
        status, _, detail = self.get('GET', '/api/cases/' + c['case_id'])
        self.assertEqual(status, 200)
        self.assertEqual(detail['facts'], f['facts'])
        self.assertIn('live_priority', detail)

    def test_etag_revalidation(self):
        _, r, _ = self.get('GET', '/api/cases')
        tag = r.getheader('ETag')
        self.assertTrue(tag)
        status, r2, body = self.get('GET', '/api/cases', headers={'If-None-Match': tag})
        self.assertEqual(status, 304)
        self.assertEqual(body, b'')

    def test_mode_endpoint_declares_sample_offline(self):
        status, _, m = self.get('GET', '/api/mode')
        self.assertEqual(status, 200)
        self.assertEqual(m['mode'], 'sample_offline')
        self.assertIn('sem agentes', m['label_pt'])
        self.assertIn('gate', m)

    def test_supervisor_without_date_defaults_instead_of_failing(self):
        status, _, body = self.get('GET', '/api/supervisor/ticks')
        self.assertEqual(status, 200, body)

    def test_friendly_errors(self):
        status, _, body = self.get('GET', '/api/cases/nao-existe')
        self.assertEqual(status, 404)
        self.assertIn('Atualize', body['error'])
        status, _, body = self.get('GET', '/api/missions/proposals')
        self.assertEqual(status, 400)
        self.assertIn('AAAA-MM-DD', body['error'])


if __name__ == '__main__':
    unittest.main()
