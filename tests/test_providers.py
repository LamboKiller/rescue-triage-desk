"""Contract tests with stdlib mocks. These are not live-service evidence."""
import io
import json
import time
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest.mock import patch
from support import Scratch
from app.llm.nightshift import Nightshift, first_json
from app.data.zetaris import Zetaris, identifier
from app.data.s3 import S3
from tools.prepare_data import Index, in_polygon, indexed_ring, ring_index


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)

    def test_nightshift_request_and_trace(self):
        captures = []
        def fake(req, timeout):
            captures.append((req, timeout))
            return Response(json.dumps({'choices': [{'message': {'content': 'answer\n```json\n{"fields": {}}\n```'}}],
                      'meterless': {'routed_model': 'actual-test-model', 'receipt_id': 'test-receipt',
                                    'winning_route': {'kind': 'cloud'}}}).encode())
        path = Path(self.tmp.name)/'trace.jsonl'
        with patch.dict('os.environ', {'NIGHTSHIFT_API_KEY': 'TEST-ONLY-SECRET'}), patch('urllib.request.urlopen', side_effect=fake):
            client = Nightshift(path)
            client.start_message('synthetic-provider-test')
            result, meta = client.call('intake', 'test', {'text': 'fictional'}, time.monotonic()+200)
        req, timeout = captures[0]
        body = json.loads(req.data)
        self.assertEqual(body['model'], 'nvidia/nemotron-3.5-lightning-30b-a3b')
        self.assertEqual(body['max_tokens'], 2000)
        self.assertNotIn('chat_template_kwargs', body)
        self.assertNotIn('/no_think', req.data.decode())
        self.assertEqual(req.get_header('Meterless-app'), 'rescue-triage-desk')
        self.assertEqual(req.get_header('Meterless-scope'), 'user')
        self.assertEqual(timeout, 180)
        self.assertEqual(meta['model'], 'actual-test-model')
        self.assertEqual(meta['receipt'], 'test-receipt')
        self.assertEqual(meta['message_id'], 'synthetic-provider-test')
        self.assertEqual(len(client.message_calls()), 1)
        self.assertIn('seconds', meta)
        self.assertNotIn('TEST-ONLY-SECRET', path.read_text())
        self.assertEqual(result, {'fields': {}})

    def test_nightshift_502_three_attempts(self):
        path = Path(self.tmp.name)/'trace.jsonl'
        error = urllib.error.HTTPError('http://fake', 502, 'test', {}, None)
        with patch.dict('os.environ', {'NIGHTSHIFT_API_KEY': 'TEST-ONLY'}), patch('time.sleep'), patch('urllib.request.urlopen', side_effect=error) as call:
            client = Nightshift(path)
            client.start_message('synthetic-retries')
            with self.assertRaises(RuntimeError):
                client.call('intake', 'test', {}, time.monotonic()+180)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(len(client.message_calls()), 3)
        self.assertEqual(len(path.read_text().splitlines()), 3)

    def test_json_unwrap(self):
        self.assertEqual(first_json('words ```json\n[{"a":1}]\n```'), [{'a': 1}])
        with self.assertRaises(ValueError):
            first_json('no JSON')

    def test_zetaris_contract_strings_and_fresh_ids(self):
        seen = []
        def fake(req, timeout):
            seen.append(req)
            return Response(b'{"headers":["name"],"data":[["value"]],"total":1}')
        with patch.dict('os.environ', {'ZETARIS_API_KEY': 'TEST-ONLY'}), patch('urllib.request.urlopen', side_effect=fake):
            self.assertEqual(Zetaris().rows('streets_flood_v1'), [{'name': 'value'}])
            Zetaris().rows('streets_flood_v1')
        for request in seen:
            body = json.loads(request.data)
            uuid.UUID(body['queryId'])
            uuid.UUID(request.get_header('X-request-id'))
            self.assertEqual(body['source'], 'SqlEditor')
            self.assertEqual(request.get_header('X-org-id'), '1')
        self.assertNotEqual(seen[0].get_header('X-request-id'), seen[1].get_header('X-request-id'))
        with self.assertRaises(ValueError):
            identifier('table; DROP')

    def test_s3_signing_and_path_style(self):
        seen = []
        def fake(req, timeout):
            seen.append(req)
            return Response(b'ok')
        with patch.dict('os.environ', {'S3_ACCESS_KEY': 'TEST-ACCESS', 'S3_SECRET_KEY': 'TEST-SECRET'}), patch('urllib.request.urlopen', side_effect=fake):
            self.assertEqual(S3().put('a space.csv', b'demo'), b'ok')
            S3().get('a space.csv')
        self.assertTrue(seen[0].full_url.endswith('/oah-data/a%20space.csv'))
        auth = seen[0].get_header('Authorization')
        self.assertIn('AWS4-HMAC-SHA256 Credential=TEST-ACCESS/', auth)
        self.assertIn('/us-east-1/s3/aws4_request', auth)
        self.assertNotIn('TEST-SECRET', auth)
        self.assertEqual(seen[1].get_method(), 'GET')

    def test_polygon_holes_and_indexed_ray_casting(self):
        outer = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        hole = [[.4, .4], [.6, .4], [.6, .6], [.4, .6], [.4, .4]]
        index = Index()
        index.add({'type': 'Polygon', 'coordinates': [outer, hole]}, 'test')
        self.assertEqual(index.values((.2, .2)), {'test'})
        self.assertFalse(index.values((.5, .5)))
        self.assertFalse(index.values((2, 2)))
        for x, y in [(.1, .1), (.5, .5), (-.1, .5), (.9, .9)]:
            self.assertEqual(bool(index.values((x, y))), in_polygon(x, y, [outer, hole]))
