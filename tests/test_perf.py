"""PERF: behavior, invalidation and generous interaction bounds (no providers)."""
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
from tests.support import Scratch


class Perf(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)

    def test_local_csv_cached_detached_and_invalidated(self):
        import app.data.source as source
        root = Path(self.tmp.name)
        (root / 'data').mkdir()
        path = root / 'data/streets_flood.csv'
        path.write_text('display_name,municipality\nRua Azul,Canoas\n', encoding='utf-8')
        with patch.object(source, 'ROOT', root), patch.object(source.csv, 'DictReader', wraps=source.csv.DictReader) as reader:
            local = source.LocalSource()
            first = local.streets()
            first[0]['display_name'] = 'mutated'
            self.assertEqual(local.streets()[0]['display_name'], 'Rua Azul')
            self.assertEqual(reader.call_count, 1)
            path.write_text('display_name,municipality\nRua Verde,Canoas\n', encoding='utf-8')
            self.assertEqual(local.streets()[0]['display_name'], 'Rua Verde')
            self.assertEqual(reader.call_count, 2)

    def test_queue_projection_does_not_copy_histories(self):
        from app.engines.world_model.registry import Registry
        from tests.test_missions import make_case
        reg = Registry(Path(self.tmp.name) / 'events.jsonl')
        c = reg.ingest(make_case())
        self.assertTrue(callable(getattr(reg, 'queue_view', None)), 'Registry needs a compact detached queue projection')
        rows = reg.queue_view()
        self.assertNotIn('facts', rows[0])
        self.assertNotIn('agents', rows[0])
        self.assertEqual(rows[0]['version_count'], 1)
        from app.priority import queue
        full = queue(reg.read())[0]
        compact = queue(rows)[0]
        self.assertEqual(compact['live_priority'], full['live_priority'])
        self.assertEqual(compact['medical'], full['medical'])
        self.assertLess(len(json.dumps(rows)), len(json.dumps(reg.read())) / 2)
        rows[0]['result']['priority'] = -100
        self.assertEqual(reg.read(c['case_id'])['result']['priority'], 10)
        reg.action(c['case_id'], 'confirm_location', c['version'], 'tester', human=True)
        self.assertEqual(reg.queue_view()[0]['version'], 2)

    def test_analysis_context_keeps_messages_without_agent_histories(self):
        from app.engines.world_model.registry import Registry
        from tests.test_missions import make_case
        reg = Registry(Path(self.tmp.name) / 'context.jsonl')
        case = make_case(text='Minha mae precisa de oxigenio.')
        case['agents'] = {'receipt': 'bulky ' * 1000}
        stored = reg.ingest(case)
        self.assertTrue(callable(getattr(reg, 'analysis_context', None)), 'Pipeline needs compact peer and credibility snapshots')
        peers, history = reg.analysis_context()
        self.assertEqual(peers[0]['fields'], stored['fields'])
        self.assertEqual(history[0]['text'], stored['facts'][0]['text'])
        self.assertNotIn('agents', peers[0])
        self.assertNotIn('facts', peers[0])
        peers[0]['fields']['people']['value'] = -100
        self.assertEqual(reg.read(stored['case_id'])['fields']['people']['value'], 3)

    def test_deadline_does_not_load_advisory_catalogue(self):
        from app.contradictions.hook import after_decision
        from types import SimpleNamespace
        with patch('app.contradictions.hook.shelters', side_effect=AssertionError('cold CSV on timeout')):
            self.assertEqual(after_decision(SimpleNamespace(), [{'complete': False}]), [])

    def test_street_patterns_reused_and_changed_catalogue_seen(self):
        from app.agents import baseline
        self.assertTrue(callable(getattr(baseline, '_street_patterns', None)), 'Street patterns must be retained beyond re module eviction')
        rows = [{'display_name': 'Rua Violeta', 'municipality': 'Canoas'}]
        baseline.extract('Rua Violeta em Canoas', rows)
        with patch.object(baseline.re, 'compile', wraps=baseline.re.compile) as compile_:
            baseline.extract('Rua Violeta em Canoas', rows)
            self.assertEqual(compile_.call_count, 0)
        rows[0]['display_name'] = 'Rua Laranja'
        self.assertEqual(baseline.extract('Rua Laranja em Canoas', rows)['fields']['street']['value'], 'Rua Laranja')

    def test_address_index_reused_and_inplace_edits_invalidate(self):
        from app.geo import incident
        self.assertTrue(callable(getattr(incident, 'prepared_index', None)), 'Address catalogue must be indexed once')
        rows = [{'display_name': 'Rua Jade', 'municipality': 'Canoas'}]
        a = incident.prepared_index(rows, [])
        self.assertIs(a, incident.prepared_index([dict(rows[0])], []))
        rows[0]['display_name'] = 'Rua Topazio'
        b = incident.prepared_index(rows, [])
        self.assertIsNot(a, b)
        self.assertTrue(b.hits('Rua Topazio', b.streets))
        self.assertFalse(b.hits('Rua Jade', b.streets))

    def test_offline_pipeline_warm_with_slack(self):
        from app.engines.world_model.registry import Registry
        from app.pipeline import Pipeline
        import contextlib
        import io
        pipeline = Pipeline(Registry(Path(self.tmp.name) / 'events.jsonl'), sample=True)
        req = {'replay_time': '2024-05-06T14:00:00-03:00', 'messages': [
            {'message_id': 'perf-test', 'text': '3 pessoas na Rua Azul, Canoas, agua subindo.'}]}
        with contextlib.redirect_stdout(io.StringIO()):
            first = pipeline.run(req)
            start = time.monotonic()
            second = pipeline.run(req)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(first['cases'][0]['result']['decision'], second['cases'][0]['result']['decision'])

    def test_warmup_is_background_and_reports_failure(self):
        from app.web.warmup import Warmup
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            release.wait(3)
        start = time.monotonic()
        warm = Warmup({'slow': slow, 'bad': lambda: 1 / 0})
        self.assertLess(time.monotonic() - start, .5)
        self.assertTrue(entered.wait(1))
        self.assertFalse(warm.snapshot()['ready'])
        release.set()
        warm.thread.join(3)
        state = warm.snapshot()
        self.assertFalse(state['ready'])
        self.assertEqual(state['tasks']['bad']['error'], 'ZeroDivisionError')

    def test_geometry_preparation_restores_collection_after_failure(self):
        import gc
        from app.web import warmup
        self.assertTrue(callable(getattr(warmup, '_routing_data', None)), 'Heavy preparation needs scoped collection management')
        enabled, thresholds = gc.isenabled(), gc.get_threshold()
        try:
            with patch.object(warmup, '_routing_data', side_effect=ValueError('synthetic preparation error')):
                with self.assertRaises(ValueError): warmup._routing()
            self.assertEqual(gc.isenabled(), enabled)
            self.assertGreaterEqual(gc.get_threshold()[2], thresholds[2])
        finally:
            gc.set_threshold(*thresholds)

    def test_landing_transfer_cold_search_returns_pending(self):
        from app.geo import routing
        from types import SimpleNamespace
        entered, release = threading.Event(), threading.Event()
        calls = []
        def route(*args):
            calls.append(args)
            entered.set()
            release.wait(3)
            return {'reachable': True, 'land_km': 2}
        router = SimpleNamespace(route=route)
        option = {'lat': -29.9, 'lon': -51.2, 'warnings_pt': [], 'ambulance': {'status': 'draft'},
                  'shelters': [{'lat': -29.91, 'lon': -51.21, 'label': 'Teste'}]}
        start = time.monotonic()
        try:
            routing.landing_transfers([option], '2024-05-06', router, background=True)
            self.assertLess(time.monotonic() - start, .5)
            self.assertTrue(option['shelters'][0]['land_route']['pending'])
            self.assertFalse(option['shelters'][0]['land_route']['reachable'])
            self.assertTrue(entered.wait(1))
        finally:
            release.set()
        worker = routing._LAND_THREAD
        if worker:
            worker.join(3)
        routing.landing_transfers([option], '2024-05-06', router, background=True)
        self.assertEqual(option['shelters'][0]['land_route']['land_km'], 2)
        self.assertEqual(len(calls), 1)
        routing.landing_transfers([option], '2024-05-08', router, background=True)
        self.assertTrue(option['shelters'][0]['land_route']['pending'])
        worker = routing._LAND_THREAD
        if worker:
            worker.join(3)


if __name__ == '__main__': unittest.main()
