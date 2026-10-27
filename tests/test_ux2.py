"""UX2: dispatch / undo API (checks gate, mission creation, undo window), replay + new-emergency intake contracts."""
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import Scratch
from tests.test_missions import DAY, inventory, make_case


class UxServerCase(unittest.TestCase):
    def setUp(self):
        from app.web.server import create_server
        self.tmp = Scratch(); self.addCleanup(self.tmp.cleanup)
        self.server = create_server('127.0.0.1', 0, sample=True, registry_path=Path(self.tmp.name)/'events.jsonl', inventory=inventory())
        self.addCleanup(self.server.server_close)
        p = patch('app.missions.service.replay_cases', side_effect=lambda cases, day: cases)
        p.start(); self.addCleanup(p.stop)
        self.case = self.server.missions.registry.ingest(make_case())
        t = threading.Thread(target=self.server.serve_forever, daemon=True); t.start()
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None, headers=None):
        import http.client
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        try:
            conn.request('GET' if body is None else 'POST', path, None if body is None else json.dumps(body),
                         headers or {'Content-Type': 'application/json'})
            r = conn.getresponse(); return r.status, json.loads(r.read())
        finally:
            conn.close()

    def checks_for(self, row, done=True):
        # the UI groups codes into <=5 plain checks; here one check per group is enough to exercise the gate
        codes = [x['code'] for x in row['confirmation_checklist']]
        return [dict(key='tudo', text_pt='Conferi tudo', codes=codes, done=done)]

    def pick(self):
        code, a = self.request(f"/api/cases/{self.case['case_id']}/assets?date={DAY}")
        self.assertEqual(code, 200, a)
        self.assertTrue(a['top3'])
        return a['top3'][0]


class DispatchTests(UxServerCase):
    def body(self, row, **kw):
        base = dict(case_id=self.case['case_id'], unit_id=row['id'], date=DAY, actor='operador-teste',
                    checks=self.checks_for(row), caution_acknowledged=True)
        base.update(kw); return base

    def test_unticked_check_blocks_and_nothing_changes(self):
        row = self.pick()
        code, r = self.request('/api/ux/dispatch', self.body(row, checks=self.checks_for(row, done=False)))
        self.assertEqual(code, 400, r); self.assertIn('Faltam checagens', r['error'])
        self.assertFalse(self.server.missions.registry.read(self.case['case_id'])['status'].startswith('ASSIGNED'))

    def test_codes_not_covered_are_refused(self):
        row = self.pick()
        code, r = self.request('/api/ux/dispatch', self.body(row, checks=[dict(key='x', codes=[], done=True)]))
        if row['confirmation_checklist']:
            self.assertEqual(code, 400, r)

    def test_dispatch_creates_mission_saves_checks_then_undo_restores(self):
        row = self.pick()
        code, d = self.request('/api/ux/dispatch', self.body(row))
        self.assertEqual(code, 200, d)
        self.assertEqual(d['state'], 'dispatched'); self.assertTrue(d['checks'][0]['done'])
        status = self.server.missions.registry.read(self.case['case_id'])['status']
        self.assertTrue(status.startswith('ASSIGNED:'), status)
        code, m = self.request('/api/missions/' + d['mission_id'])
        self.assertEqual((code, m['status']), (200, 'assigned'))
        code, lst = self.request('/api/ux/dispatches?case_id=' + self.case['case_id'])
        self.assertEqual(lst['dispatches'][0]['dispatch_id'], d['dispatch_id'])
        self.assertEqual(code, 200)
        self.assertEqual(self.request('/api/ux/dispatch', self.body(row))[0], 409)  # already in a mission
        code, u = self.request('/api/ux/undo', dict(dispatch_id=d['dispatch_id'], actor='operador-teste'))
        self.assertEqual(code, 200, u); self.assertEqual(u['state'], 'undone')
        self.assertEqual(self.request('/api/missions/' + d['mission_id'])[1]['status'], 'cancelled')
        self.assertFalse(self.server.missions.registry.read(self.case['case_id'])['status'].startswith('ASSIGNED'))
        self.assertEqual(self.request('/api/ux/undo', dict(dispatch_id=d['dispatch_id'], actor='x'))[0], 409)

    def test_undo_window_expires(self):
        row = self.pick()
        code, d = self.request('/api/ux/dispatch', self.body(row)); self.assertEqual(code, 200, d)
        self.server.RequestHandlerClass  # keep server alive
        rec = self.server.ux.records[d['dispatch_id']]
        rec['undo_until'] = 0
        code, u = self.request('/api/ux/undo', dict(dispatch_id=d['dispatch_id'], actor='x'))
        self.assertEqual(code, 409); self.assertIn('Prazo', u['error'])

    def test_actor_required_unknown_case_and_origin(self):
        row = self.pick()
        self.assertEqual(self.request('/api/ux/dispatch', dict(self.body(row), actor=''))[0], 400)
        self.assertEqual(self.request('/api/ux/dispatch', dict(self.body(row), case_id='nope'))[0], 404)
        self.assertEqual(self.request('/api/ux/dispatch', self.body(row), {'Content-Type': 'application/json', 'Origin': 'https://elsewhere.invalid'})[0], 403)
        self.assertEqual(self.request('/api/ux/undo', dict(dispatch_id='nope', actor='x'))[0], 404)


class IntakeAndReplayContracts(UxServerCase):
    def test_new_emergency_and_batch_use_real_intake(self):
        msgs = [dict(text='Familia presa no telhado na Rua das Flores, 120, agua subindo, 2 criancas', received_at=DAY + 'T09:00:00-03:00', message_id='ux-' + str(i)) for i in range(3)]
        msgs[1]['text'] = 'Idosa acamada sem energia na Rua das Acacias 45, 1 pessoa'; msgs[2]['text'] = 'Cachorro preso em casa na Av. Brasil 300'
        code, r = self.request('/api/intake', dict(replay_time=DAY + 'T23:59:59-03:00', messages=msgs))
        self.assertEqual(code, 202, r); self.assertEqual(r['accepted'], 3)
        code, q = self.request('/api/queue')
        self.assertEqual(code, 200); self.assertGreaterEqual(q['total_accepted'], 3)
        import time
        for _ in range(60):  # let the workers finish so the scratch dir can be removed on Windows
            q = self.request('/api/queue')[1]
            if q['queued'] + q['running'] == 0: break
            time.sleep(0.5)
        time.sleep(0.5)

    def test_cases_accept_hour_precise_replay_time(self):
        for hhmm in ('06:00', '23:59'):
            code, r = self.request(f'/api/cases?replay_time={DAY}T{hhmm}:00-03:00')
            self.assertEqual(code, 200, r)


class StaticAssetTests(UxServerCase):
    def raw(self, path, headers=None):
        import http.client
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=30)
        try:
            conn.request('GET', path, None, headers or {})
            r = conn.getresponse(); return r.status, dict(r.getheaders()), r.read()
        finally:
            conn.close()

    def test_new_modules_served_with_etag_304_and_gzip(self):
        import gzip
        for name in ('meios.js', 'routeview.js', 'replay.js', 'intake.js'):
            status, h, body = self.raw('/v2/' + name, {'Accept-Encoding': 'gzip'})
            self.assertEqual(status, 200, name)
            self.assertEqual(h.get('Content-Encoding'), 'gzip', name)
            self.assertIn(b"'use strict'", gzip.decompress(body))
            status, _, _ = self.raw('/v2/' + name, {'If-None-Match': h['ETag']})
            self.assertEqual(status, 304, name)
        self.assertEqual(self.raw('/v2/..%2Fserver.py')[0], 404)
        self.assertEqual(self.raw('/v2/not_a_module.js')[0], 404)

    def test_index_loads_new_modules_in_order(self):
        html = self.raw('/v2')[2].decode('utf-8')
        order = [html.index(f'/v2/{n}.js') for n in ('replay', 'app', 'intake')]
        self.assertEqual(order, sorted(order))  # replay before app (iso() used at first refresh), intake after app (needs DeskApp)
        self.assertLess(html.index('/v2/meios.js'), html.index('/v2/app.js'))


if __name__ == '__main__':
    unittest.main()
