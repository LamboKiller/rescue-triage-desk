import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from support import Scratch
from test_core import ROWS, TIME
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline
from run import create_server
from tools.generate_messages import generate


class FakeSource:
    def streets(self, timeout=120):
        return ROWS


class FakeLLM:
    """TEST ONLY: scripted provider responses; never imported by runtime."""
    def __init__(self, fail_role=None):
        self.roles = []
        self.fail_role = fail_role

    def call(self, role, system, payload, deadline):
        self.roles.append(role)
        assert 'UNTRUSTED DATA' in system
        assert '[EMAIL REDIGIDO]' in payload
        if role == self.fail_role:
            raise TimeoutError('test only')
        # New intake contract: the model returns {field: exact quote}; code derives values.
        quotes = {'people': '3 pessoas', 'street': 'Rua das Flores', 'number': 'número 20',
                  'municipality': 'Porto Alegre'}
        if role == 'intake':
            quotes['elderly'] = 'uma idosa inventada'
        out = {'objections': [{'field': 'elderly', 'reason': 'unsupported', 'quote': ''}]} if role == 'critic' else quotes
        return out, {'role': role, 'model': 'TEST-ONLY-FakeLLM', 'receipt': 'TEST-ONLY', 'seconds': 0,
                     'route_kind': 'test'}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.registry = Registry(Path(self.tmp.name)/'events.jsonl')

    def request(self):
        return {'replay_time': TIME, 'messages': [{'message_id': 'judge-demo',
            'text': '3 pessoas na Rua das Flores, número 20, Porto Alegre. '+'demo'+'@'+'example.org'}]}

    def test_fake_llm_revision_and_no_pii(self):
        llm = FakeLLM()
        result = Pipeline(self.registry, source=FakeSource(), client=llm).run(self.request())
        c = result['cases'][0]
        self.assertEqual(llm.roles, ['intake', 'critic', 'revision'])
        self.assertNotIn('elderly', c['fields'])
        self.assertEqual(c['unsupported'][0]['reason'], 'unsupported_quote')
        self.assertEqual(c['result']['decision'], 'SEND_CANDIDATE')
        self.assertIn('[EMAIL REDIGIDO]', c['text'])
        self.assertNotIn('example.org', self.registry.path.read_text(encoding='utf-8'))
        self.assertEqual(c['status'], 'proposed')

    def test_hazard_review_is_validated_advisory_after_location(self):
        class HazardLLM(FakeLLM):
            def call(self,role,system,payload,deadline):
                if role!='hazard_critic':return super().call(role,system,payload,deadline)
                self.roles.append(role)
                data=json.loads(payload)
                assert 'case_summary' not in data and 'message' not in data
                assert data['facts'] and data['proposed_asset']
                fact='fleet:'+data['proposed_asset']
                assert any(f['id']==fact for f in data['facts'])
                return {'objections':[{'fact_ids':[fact],'text_pt':'Verifique as cautelas locais.',
                                       'severity':'warn'}],'brief_pt':'Requer revisão humana.'},{'role':role}
        llm=HazardLLM()
        with patch('app.geo.hydro.hydro_conflict', return_value={'reason':'synthetic conflict'}):
            c=Pipeline(self.registry,source=FakeSource(),client=llm).run(self.request())['cases'][0]
        self.assertEqual(llm.roles[-1],'hazard_critic')
        self.assertEqual(c['hazard_critic'],c['hazard_review'])
        self.assertEqual(c['hazard_review']['objections'][0]['severity'],'warn')
        self.assertEqual(c['hazard_unsupported'],0)
        self.assertEqual(c['result']['decision'],'SEND_CANDIDATE')

    def test_failed_advisory_critic_preserves_validated_decision(self):
        result = Pipeline(self.registry, source=FakeSource(), client=FakeLLM('critic')).run(self.request())
        self.assertFalse(result['partial'])
        c = result['cases'][0]
        self.assertTrue(c['complete'])
        self.assertFalse(c['review_degraded'])
        self.assertTrue(any('indisponível' in w for w in c['agent_warnings']))
        self.assertEqual(c['agents']['critic'], 'failed')
        self.assertEqual(c['fields']['people']['value'], 3)
        self.assertEqual(c['result']['decision'], 'SEND_CANDIDATE')
        self.assertFalse(c['errors'])

    def test_offline_no_network_and_not_precomputed(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            p = Pipeline(self.registry, sample=True, source=FakeSource())
            result = p.run(self.request())
        c = result['cases'][0]
        self.assertEqual(result['mode'], 'sample_offline')
        self.assertEqual(c['agents']['intake'], 'unavailable (offline)')
        self.assertEqual(c['fields']['people']['value'], 3)
        req = self.request()
        req['messages'][0]['message_id'] = 'changed'
        req['messages'][0]['text'] = req['messages'][0]['text'].replace('3 pessoas', '6 pessoas')
        self.assertEqual(p.run(req)['cases'][0]['fields']['people']['value'], 6)

    def test_max_messages_and_invalid_payloads(self):
        p = Pipeline(self.registry, sample=True, source=FakeSource())
        req = self.request()
        req['messages'] *= 16
        with self.assertRaisesRegex(ValueError, '15'):
            p.run(req)
        for request in [[], {}, {'replay_time': '2024-05-06', 'messages': [{'text': 'a'}]}]:
            with self.assertRaises(ValueError):
                p.run(request)

    def test_deadline_returns_partial(self):
        class SlowFakeLLM:
            def call(self, *args):
                time.sleep(.12)
                raise TimeoutError('fake')
        start = time.monotonic()
        result = Pipeline(self.registry, source=FakeSource(), client=SlowFakeLLM(), budget_seconds=.03).run(self.request())
        self.assertLess(time.monotonic()-start, .3)
        self.assertTrue(result['partial'])
        self.assertEqual(result['cases'][0]['result']['decision'], 'REVIEW_REQUIRED')
        self.assertEqual(result['cases'][0]['route']['id'], 'agent_failure')
        time.sleep(.15)  # Drain the bounded test worker before scratch cleanup.
        self.assertEqual(len(self.registry.read()), 1)

    def test_source_failure_is_honest(self):
        class BrokenSource:
            def streets(self, timeout=120):
                raise ConnectionError('do not expose provider body')
        result = Pipeline(self.registry, sample=True, source=BrokenSource()).run(self.request())
        self.assertTrue(result['partial'])
        self.assertEqual(result['cases'][0]['result']['decision'], 'REVIEW_REQUIRED')
        self.assertEqual(result['cases'][0]['route']['id'], 'agent_failure')

    def test_slow_source_cannot_exceed_response_deadline(self):
        class SlowSource:
            def streets(self, timeout=120):
                time.sleep(.15)
                return ROWS
        start = time.monotonic()
        result = Pipeline(self.registry, sample=True, source=SlowSource(), budget_seconds=.03).run(self.request())
        self.assertLess(time.monotonic()-start, .3)
        self.assertTrue(result['partial'])
        self.assertEqual(result['cases'][0]['result']['decision'], 'REVIEW_REQUIRED')
        self.assertEqual(result['cases'][0]['route']['id'], 'agent_failure')
        time.sleep(.17)

    def test_generator_deterministic_and_no_identifiers(self):
        rows = [{**ROWS[0], 'any_in_water_2024-05-06': '1'}]
        a, truth = generate(101, 15, rows)
        self.assertEqual((a, truth), generate(101, 15, rows))
        self.assertNotEqual(a, generate(7, 15, rows)[0])
        self.assertEqual(len({x['template_family'] for x in truth}), 15)
        for m in a:
            self.assertTrue(m['synthetic'])
            self.assertEqual(m['text'], __import__('app.redact', fromlist=['redact']).redact(m['text']))

    def test_http_run_queue_action_and_stale_version(self):
        p = Pipeline(self.registry, sample=True, source=FakeSource())
        server = create_server('127.0.0.1', 0, sample=True, pipeline=p)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(cleanup)
        base = f'http://127.0.0.1:{server.server_port}'
        def post(path, body):
            req = urllib.request.Request(base+path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        result = post('/run', self.request())
        self.assertEqual(len(result['cases']), 1)
        with urllib.request.urlopen(base+'/api/cases') as r:
            c = json.load(r)['cases'][0]
        route = '/api/cases/'+c['case_id']+'/actions'
        action = {'action': 'confirm_location', 'expected_version': 1, 'actor': 'test-operator'}
        self.assertEqual(post(route, action)['version'], 2)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            post(route, action)
        self.assertEqual(caught.exception.code, 409)
        with urllib.request.urlopen(base+'/api/health') as r:
            self.assertTrue(json.load(r)['SAMPLE_MODE'])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            post('/run', {'replay_time': TIME, 'messages': self.request()['messages']*16})
        self.assertEqual(caught.exception.code, 400)
        print(f'HTTP self-check port={server.server_port}: POST /run 200; GET /api/cases 200; action version 1 to 2; stale 409')
