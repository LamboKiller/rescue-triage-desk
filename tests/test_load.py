"""Load harness checks use fresh synthetic text and a real loopback desk."""
import json
import unittest
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from support import Scratch
from tools import load_test as load


class LoadTests(unittest.TestCase):
    def test_seed_and_workload_mix(self):
        rows = load.generate(300, seed=19)
        self.assertEqual(rows, load.generate(300, seed=19))
        self.assertNotEqual(rows, load.generate(300, seed=20))
        self.assertEqual(len({r['message_id'] for r in rows}), 300)
        for kind, count in [('repost', 30), ('injection', 15), ('volunteer', 15), ('not_rescue', 15)]:
            self.assertEqual(sum(r['kind'] == kind for r in rows), count)
        by_id = {r['message_id']: r for r in rows}
        for row in rows:
            self.assertTrue(row['synthetic'])
            if row['kind'] == 'repost':
                self.assertEqual(row['text'], by_id[row['repost_of']]['text'])

    def test_no_dev_set_overlap(self):
        # Only the public development set; never inspect protected review sets.
        rows = load.generate(1000, seed=41)
        dev = Path(load.ROOT/'eval/realistic_dev.jsonl')
        texts = set()
        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'text' and isinstance(item, str):
                        texts.add(' '.join(item.casefold().split()))
                    else:
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        for line in dev.read_text(encoding='utf-8-sig').splitlines():
            collect(json.loads(line))
        self.assertTrue(texts, 'overlap check must inspect actual development texts')
        self.assertFalse(texts & {' '.join(r['text'].casefold().split()) for r in rows})

    def test_percentiles_and_failure_classification(self):
        self.assertEqual(load.percentile([1, 2, 3, 4], 50), 2.5)
        self.assertEqual(load.percentile([1, 2, 3, 4], 95), 3.85)
        self.assertIsNone(load.percentile([], 95))
        case = {'result': {'decision': 'SEND_CANDIDATE'}, 'checks': {'found': False}}
        self.assertTrue(load.unsafe(case))
        self.assertFalse(load.unsafe({**case, 'checks': {'found': True}}))
        cases = [dict(failure_kind=k) for k in ['TIMEOUT', 'provider_refused', 'agent_failure']]
        self.assertEqual(load.classify(cases), dict(TIMEOUT=1, provider_refused=1, agent_failure=1))

    def test_schedule_seed_and_guard(self):
        a = load.arrivals(burst=300, rate=30, minutes=10, seed=7)
        self.assertEqual(a, load.arrivals(burst=300, rate=30, minutes=10, seed=7))
        self.assertEqual(a[:300], [0.] * 300)
        self.assertTrue(all(0 < t < 600 for t in a[300:]))
        self.assertTrue(540 < len(a) < 660)
        with self.assertRaises(ValueError):
            load.arrivals(burst=-1)

    def test_multiple_accepted_runs_are_all_tracked(self):
        # A queued server must not cause an accepted batch to be treated as lost.
        deliveries = {}
        reject = False
        slow_probe = 0.
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def send(self, code, value):
                body = json.dumps(value).encode()
                self.send_response(code)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if reject:
                    self.send(400, {'error': 'execução ativa'})
                    return
                run_id = str(len(deliveries))
                deliveries[run_id] = value['messages']
                self.send(202, {'run_id': run_id})
            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path.endswith('/events'):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    self.wfile.write(b'data: {"stage":"done"}\n\n')
                elif path.startswith('/api/runs/'):
                    run_id = path.rsplit('/', 1)[1]
                    cases = [dict(m, case_id=m['message_id'], result={'decision': 'CALLBACK'})
                             for m in deliveries[run_id]]
                    self.send(200, {'status': 'complete' if len(deliveries) >= 2 else 'running',
                                    'result': {'cases': cases}})
                elif path == '/api/cases':
                    time.sleep(slow_probe)
                    self.send(200, {'cases': []})
                else:
                    self.send(200, {})
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = load.measure(f'http://127.0.0.1:{server.server_port}', load.generate(2), [0., 0.],
                                  batch_size=1, max_minutes=.04, sample_seconds=.05)
            self.assertEqual(report['persisted'], 2)
            self.assertEqual(report['dropped'], 0)
            reject = True
            refused = load.measure(f'http://127.0.0.1:{server.server_port}', load.generate(4), [0.] * 4,
                                   batch_size=1, max_minutes=.02, sample_seconds=.1)
            self.assertTrue(all(r['attempts'] > 0 for r in refused['messages']))
            self.assertEqual(refused['pending'], 4)
            self.assertEqual(refused['dropped'], 0)
            self.assertTrue(refused['guard_hit'])
            reject, slow_probe = False, .7
            responsive = load.measure(f'http://127.0.0.1:{server.server_port}', load.generate(1), [0.],
                                      max_minutes=.04, sample_seconds=5)
            self.assertLess(responsive['messages'][0]['submitted_seconds'], .5,
                            'UI probes must not serialize the arrival sender')
        finally:
            server.shutdown()
            server.server_close()

    def test_offline_mini_run_writes_report_and_detects_hidden_pending(self):
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        report = load.run_offline(Path(scratch.name), count=4, seed=7, latency_scale=.001,
                                  max_minutes=1, sample_seconds=.05)
        self.assertEqual(report['generated'], 4)
        self.assertEqual(report['decided'], 4)
        self.assertEqual(report['dropped'], 0)
        self.assertEqual(report['unsafe_proxy'], 0)
        self.assertGreater(report['sse']['events'], 0)
        self.assertEqual(report['sse']['errors'], 0)
        self.assertGreater(report['memory']['peak_rss_bytes'], 0)
        self.assertTrue(report['latency_source'].endswith('LIVEFIX6_LATENCY.json'))
        self.assertTrue(Path(report['report_json']).exists())
        self.assertTrue(Path(report['report_markdown']).exists())
        self.assertTrue(report['backlog'])
        # SURGE: accept-and-queue keeps every attempted message visible (the pre-SURGE desk hid them).
        self.assertEqual(report['graceful_degradation']['hidden_pending_peak'], 0)
        self.assertEqual(report['graceful_degradation']['pending_without_label_or_age'], 0)


if __name__ == '__main__':
    unittest.main()
