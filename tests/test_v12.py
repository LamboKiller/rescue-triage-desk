"""Real snapshot regressions and evaluation/HTTP contract checks."""
import contextlib
import io
import json
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT
from app.data.source import LocalSource, ZetarisSource
from app.geo.landmarks import match, normalize
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline
from app.agents.baseline import extract
from run import create_server
from eval.run_eval import score
from support import Scratch


QUERIES = [
    ('dentro da rodoviaria de porto alegre', 'Porto Alegre', '236479491'),
    ('arena do gremio', 'Porto Alegre', None),
    ('beira-rio', 'Porto Alegre', '4587043'),
    ('mercado publico', 'Porto Alegre', '69749641'),
    ('clinicas', 'Porto Alegre', '126014206'),
    ('parkshopping', 'Canoas', None),
    ('salgado filho', 'Porto Alegre', '5320213'),
    ('zaffari da assis brasil', 'Porto Alegre', None),
    ('hospital de clinicas', 'Porto Alegre', '126014206'),
]


class EvaluationTests(unittest.TestCase):
    def test_baseline_pet_alternatives_require_a_number(self):
        self.assertNotIn('pets', extract('tem gato aqui', [])['fields'])
        self.assertEqual(extract('2 gatos aqui', [])['fields']['pets']['value'], 2)

    def test_revision_landmark_latency_and_failures(self):
        truth = [{'message_id':'a', 'expected_fields':{'people':2}, 'expected_decision':'SEND_CANDIDATE',
                  'expected_landmark':{'status':'resolved', 'osm_type':'way', 'osm_id':'2'}}]
        case = {'message_id':'a', 'fields':{'people':{'value':2}}, 'initial_fields':{'people':{'value':3}},
                'result':{'decision':'SEND_CANDIDATE'}, 'unsupported':[], 'calls':[{}, {}, {}],
                'agents':{'critic':{'objections':[{'field':'people'}]}, 'revision':{'fields':{}}},
                'landmark_check':{'status':'resolved','matched':{'osm_type':'way','osm_id':'2'}},
                'seconds':4, 'complete':True, 'errors':[]}
        result = score([case], truth, 5)
        self.assertEqual(result['landmark_resolution_accuracy'], 1)
        self.assertEqual(result['critic']['changes_correct'], 1)
        self.assertEqual(result['critic']['revisions_changed_field'], 1)
        self.assertEqual(result['p90_seconds_per_message'], 4)
        self.assertEqual(result['failures'], 0)
        case['fields']['people']['value'] = 1
        case['initial_fields']['people']['value'] = 2
        self.assertEqual(score([case], truth, 5)['critic']['changes_wrong'], 1)
        case['initial_fields']['people']['value'] = 3
        self.assertEqual(score([case], truth, 5)['critic']['changes_neutral'], 1)

    def test_intake_ablation_does_not_call_location_or_critic(self):
        class Client:
            def __init__(self):
                self.roles = []

            def call(self, role, system, payload, deadline):
                self.roles.append(role)
                return {'people':'2 pessoas', 'municipality':'Porto Alegre', 'landmark':'Mercado Público'}, {'role':role}

        class Source:
            def streets(self, timeout=120):
                return []

            def landmarks(self, timeout=120):
                return LocalSource().landmarks()

        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        client = Client()
        pipeline = Pipeline(Registry(Path(scratch.name)/'events.jsonl'), source=Source(), client=client)
        with contextlib.redirect_stdout(io.StringIO()):
            output = pipeline.run({'replay_time':'2024-05-06T14:00:00-03:00', 'messages':[{
                'text':'2 pessoas no Mercado Público, Porto Alegre'}]}, ablation='intake')
        self.assertEqual(client.roles, ['intake'])
        self.assertEqual(output['cases'][0]['landmark_check']['status'], 'resolved')

    def test_loader_and_source_use_v3_landmarks(self):
        from tools.load_zetaris import load
        with patch('tools.load_zetaris.Zetaris') as client, patch('tools.load_zetaris.S3') as storage, \
                patch('pathlib.Path.write_text'), contextlib.redirect_stdout(io.StringIO()):
            uploads = {}
            table_count = [0]

            def put(key, payload):
                import csv
                uploads[key] = payload
                table_count[0] = len(list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))))

            storage.return_value.put.side_effect = put
            storage.return_value.get.side_effect = lambda key: uploads[key]
            client.return_value.query.side_effect = lambda sql, **kw: {'data':[[table_count[0]]]}
            counts = load()
            import csv as _csv
            with open(Path(__file__).resolve().parents[1]/'data/landmarks.csv', encoding='utf-8', newline='') as f:
                expected = sum(1 for _ in _csv.DictReader(f))
            self.assertEqual(counts['landmarks_v3'], expected)
            self.assertTrue(all(key.endswith('_v3') for key in counts))
            statements = [c.args[0] for c in client.return_value.query.call_args_list
                          if c.args[0].startswith('CREATE LIGHTNING FILESTORE')]
            self.assertTrue(all('inferSchema "false"' in sql for sql in statements))
        with patch('app.data.source.Zetaris') as client:
            source = ZetarisSource()
            source.landmarks(timeout=3)
            source.streets(timeout=3)
            source.messages(timeout=3)
            self.assertEqual([c.args[0] for c in client.return_value.rows.call_args_list],
                             ['landmarks_v3','streets_flood_v3','messages_seed7_v3'])


class RealLandmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = LocalSource().landmarks()
        cls.streets = LocalSource().streets()

    def test_nine_queries(self):
        for query, city, oid in QUERIES:
            with self.subTest(query=query):
                result = match(self.rows, landmark_quote=query, municipality=city,
                               streets=self.streets, message=query)
                self.assertEqual(result['status'], 'resolved')
                if oid:
                    self.assertEqual(result['matched']['osm_id'], oid)
                if query.startswith('zaffari'):
                    self.assertTrue(all('assis brasil' in normalize(c['street']) for c in result['candidates']))

    def test_three_negative_queries(self):
        self.assertEqual(match(self.rows, 'Observatorio Ficticio Nebulosa Azul',
                               municipality='Porto Alegre')['status'], 'unresolved')
        truth = json.loads((ROOT/'eval/challenge_truth.json').read_text(encoding='utf-8'))
        for target in truth:
            if target.get('expected_landmark', {}).get('status') != 'unresolved':
                continue
            fields = target['expected_fields']
            with self.subTest(message_id=target['message_id']):
                result = match(self.rows, fields['landmark'], municipality=fields['municipality'])
                self.assertNotEqual(result['status'], 'resolved')
                self.assertIsNone(result['matched'])
        self.assertEqual(match(self.rows, 'mercado', municipality='Porto Alegre')['status'], 'ambiguous')

    def test_explicit_subfacility_and_school_names(self):
        result = match(self.rows, 'Banco de Sangue do Hospital de Clínicas', municipality='Porto Alegre')
        self.assertEqual(result['matched']['osm_id'], '4763286051')
        result = match(self.rows, 'Escola Salgado Filho', municipality='Porto Alegre')
        self.assertEqual(result['matched']['osm_id'], '244050553')

    def test_category_and_duplicate_preference(self):
        base = dict(name='Hospital Aurora', alt_names='', municipality='Porto Alegre',
                    category='amenity:hospital', lat='-30', lon='-51', street='Rua Azul')
        rows = [{**base, 'osm_type':'node', 'osm_id':'1'},
                {**base, 'osm_type':'way', 'osm_id':'2', 'lat':'-30.0001'},
                {**base, 'osm_type':'way', 'osm_id':'3', 'lat':'-30.02'}]
        result = match(rows, 'Hospital Aurora', municipality='Porto Alegre')
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual({c['osm_id'] for c in result['candidates']}, {'2', '3'})
        school = {**base, 'name':'Escola Aurora', 'category':'amenity:school', 'osm_id':'4', 'osm_type':'way'}
        result = match(rows+[school], 'Aurora', municipality='Porto Alegre', message='na escola Aurora')
        self.assertEqual(result['matched']['osm_id'], '4')

    def test_http_rodoviaria_and_page(self):
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        pipeline = Pipeline(Registry(Path(scratch.name)/'events.jsonl'), sample=True)
        server = create_server('127.0.0.1', 0, sample=True, pipeline=pipeline)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = 'http://127.0.0.1:'+str(server.server_port)
            with urllib.request.urlopen(base+'/') as response:
                page = response.read().decode('utf-8')
            self.assertTrue("['location','Localização']" in page)
            self.assertTrue('Motivo da decisão' in page)
            body = {'replay_time':'2024-05-06T14:00:00-03:00', 'messages':[{
                'message_id':'synthetic-v12-rodoviaria',
                'text':'socorro estamos dentro da rodoviaria de porto alegre e esta alagando tudo, estou com meus dois bebes'}]}
            request = urllib.request.Request(base+'/run', data=json.dumps(body).encode(),
                                             headers={'Content-Type':'application/json'})
            with contextlib.redirect_stdout(io.StringIO()), urllib.request.urlopen(request) as response:
                case = json.load(response)['cases'][0]
            self.assertEqual(case['landmark_check']['status'], 'resolved')
            self.assertEqual(case['landmark_check']['matched']['osm_id'], '236479491')
            self.assertFalse(any('casa' in q for q in case['result']['questions']))
            self.assertTrue(case['result']['decision_reason'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
