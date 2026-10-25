import json
import time
import unittest
import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from app.agents import location
from app.llm.nightshift import Nightshift, first_json, invalid_head
from support import Scratch
from test_providers import Response
from test_l1 import place, REPLAY
from app.agents.location_tools import LocationTools


class LocationFixTests(unittest.TestCase):
    def test_location_parser_shapes(self):
        answer = {'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}
        raw = json.dumps(answer)
        for text in ('Here: '+raw+' done', '{} '+raw, '```json\n'+raw+'\n```'):
            self.assertEqual(first_json(text, location_shape=True), answer)
        tool = {'tool': 'check_text', 'args': {}, 'why_quote': 'Resgate'}
        self.assertEqual(first_json(json.dumps(tool)+' '+raw, location_shape=True), tool)
        for text in ('{"result":'+raw+'}', '{"answer":'+raw+'}', '{"answer":{', '{}'):
            with self.assertRaises(ValueError):
                first_json(text, location_shape=True)

    def test_provider_trace_head_only_for_failed_parse_and_short_retry(self):
        with contextlib.ExitStack() as stack:
            scratch = Scratch()
            stack.callback(scratch.cleanup)
            path = Path(scratch.name)/'trace.jsonl'
            outputs = iter(['bad 123456789 private-key-value',
                            '{"answer":{"candidate_id":null,"precision":"area","evidence":[]}}'])
            requests = []
            def respond(req, timeout):
                requests.append(json.loads(req.data))
                return Response(json.dumps({'choices': [{'message': {'content': next(outputs)}}]}).encode())
            with patch.dict('os.environ', {'NIGHTSHIFT_API_KEY': 'private-key-value'}), \
                    patch('urllib.request.urlopen', side_effect=respond), patch('time.sleep'), \
                    contextlib.redirect_stdout(io.StringIO()):
                Nightshift(path).call('location_agent', location.SYSTEM, '{}', time.monotonic()+20)
            events = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertIn('invalid_head', events[0])
            self.assertNotIn('invalid_head', events[1])
            self.assertNotIn('123456789', path.read_text())
            self.assertNotIn('private-key-value', path.read_text())
            self.assertLess(len(requests[1]['messages'][0]['content']), len(location.SYSTEM))
            for request in requests:
                self.assertTrue(request['stream'])
                self.assertEqual(request['max_tokens'], 6000)
                self.assertNotIn('chat_template_kwargs', request)

    def test_provider_limit_default_and_configuration(self):
        for configured, expected in ((None, 2), ('1', 1)):
            env = dict(os.environ)
            env.pop('NIGHTSHIFT_MAX_CONCURRENCY', None)
            if configured:
                env['NIGHTSHIFT_MAX_CONCURRENCY'] = configured
            result = subprocess.check_output([sys.executable, '-B', '-c',
                'from app.llm.nightshift import CALL_SLOTS; print(CALL_SLOTS._value)'], env=env)
            self.assertEqual(int(result), expected)

    def test_invalid_head_masks_identifiers_and_credentials(self):
        with patch.dict('os.environ', {'NIGHTSHIFT_API_KEY': 'private-key-value'}):
            head = invalid_head('private-key-value 123456789 bearer other-secret '+('x'*300))
        self.assertLessEqual(len(head), 160)
        for secret in ('private-key-value', '123456789', 'other-secret'):
            self.assertNotIn(secret, head)

    def test_compact_last_result_only(self):
        candidates = [dict(candidate_id=str(i), name='N'*500, city='C'*500, kind='street',
                           private='SECRET'*2000) for i in range(12)]
        payload = location.step_prompt('Message', 'Canoas', [
            {'result_id': 'old', 'candidates': candidates},
            {'result_id': 't2', 'why_quote': 'Message', 'candidates': candidates}], 1)
        self.assertLess(len(payload), 2100)
        data = json.loads(payload)
        self.assertEqual(len(data['candidates']), 8)
        self.assertNotIn('SECRET', payload)
        self.assertNotIn('old', payload)
        self.assertTrue(all(len(line.split(' | ')) == 4 for line in data['candidates']))

    def test_failed_second_step_downgrades_and_checks_city(self):
        for cities, expected in ((['Canoas'], True), (['Porto Alegre'], False),
                                 (['Canoas', 'Porto Alegre'], False)):
            text = 'Resgate na Escola Aurora.'
            tools = LocationTools([], [place('Escola Aurora', city=c) for c in cities], text, REPLAY)
            class Client:
                calls = 0
                def call(self, role, system, payload, deadline):
                    self.calls += 1
                    if self.calls == 1:
                        return {'tool': 'search_landmark', 'args': {'name': 'Aurora'},
                                'why_quote': 'Escola Aurora'}, {}
                    raise RuntimeError('invalid JSON')
            if cities == ['Porto Alegre']:
                text += ' Em Canoas.'
                tools = LocationTools([], [place('Escola Aurora', city=c) for c in cities], text, REPLAY)
            client = Client()
            out, _ = location.run(client, text, '', time.monotonic()+10, tools=tools)
            self.assertTrue(out['fallback'])
            self.assertEqual(out['answer']['precision'], 'area')
            self.assertEqual(bool(out['candidate']), expected)
            self.assertEqual(client.calls, 2)

    def test_three_requests_maximum(self):
        tools = LocationTools([], [], 'Resgate urgente.', REPLAY)
        class Client:
            calls = 0
            def call(self, role, system, payload, deadline):
                self.calls += 1
                return {'tool': 'check_text', 'args': {'quote': 'Resgate'}, 'why_quote': 'Resgate'}, {}
        client = Client()
        out, _ = location.run(client, tools.text, '', time.monotonic()+10, tools=tools)
        self.assertLessEqual(client.calls, 3)
        self.assertTrue(out['fallback'])
