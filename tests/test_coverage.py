"""Coverage safety, arithmetic, cache invalidation and offline HTTP regressions."""
import copy
import http.client
import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.coverage import build,CoverageService
from tests.test_allocation import case,unit,DAY
from tests.support import Scratch


class CoverageTests(unittest.TestCase):
    def request(self):
        c=case();c['result']['priority']=35;return c

    def test_authored_scenarios(self):
        from eval.run_coverage import evaluate
        out=evaluate();self.assertEqual(out['correct'],10);self.assertEqual(out['suggestions_without_cited_cases'],0)

    def test_suggestion_labels_are_portuguese_utf8(self):
        out=build([self.request()],[],DAY)
        self.assertIn('célula',out['cells'][0]['label_pt'])
        self.assertIn('Sugestão: pedir reforço',out['suggestions'][0]['text_pt'])

    def test_unknown_and_conflicting_counts(self):
        for value in (None,-1,True):
            c=self.request();c['fields']['people']['value']=value
            r=build([c],[],DAY)['cells'][0]
            self.assertEqual((r['people_known'],r['people_unknown_cases']),(0,1))
        c=self.request();c['result']['conflicting_counts']=True
        self.assertEqual(build([c],[],DAY)['cells'][0]['people_unknown_cases'],1)

    def test_open_date_location_and_life_safety(self):
        c=self.request();c['result']['priority']=1;c['operational_needs']={'needs':[{'tag':'water_rising'}]}
        self.assertEqual(build([c],[],DAY)['cells'][0]['life_safety_count'],1)
        for status in ('dispatched','ASSIGNED:m','reported_rescued','cancelled'):
            d=copy.deepcopy(c);d['status']=status;self.assertFalse(build([d],[],DAY)['cells'])
        c['received_at']='2024-05-09T10:00:00-03:00';self.assertFalse(build([c],[],DAY)['cells'])
        c=self.request();c.pop('position');self.assertEqual(build([c],[],DAY)['unlocated_case_ids'],['a'])
        c=self.request();c['status']='human_approved';c['result']['decision']='CALLBACK'
        self.assertTrue(build([c],[],DAY)['cells'])

    def test_all_units_not_just_ranked_three(self):
        units=[unit(str(i),base_location={'lat':-29.92+i*.0001,'lon':-51.18}) for i in range(5)]
        def metric(a,b):
            return dict(distance_m=10,eta_seconds=1 if a['lat']>-29.91965 else 500,basis_pt='estimativa')
        cell=build([self.request()],units,DAY,distance_fn=metric)['cells'][0]
        self.assertEqual(cell['best']['unit_id'],'4')

    def test_fallback_and_heterogeneous_cell(self):
        c=self.request();r=build([c],[unit()],DAY)
        self.assertIn('Linha reta',r['cells'][0]['best']['basis_pt'])
        d=copy.deepcopy(c);d['case_id']='b';d['fields']['disabled']={'value':1}
        r=build([c,d],[unit(stretcher=False)],DAY)
        cell=r['cells'][0];self.assertTrue(cell['gap']);self.assertIsNotNone(cell['best'])
        self.assertEqual(cell['gap_case_ids'],['b']);self.assertEqual(set(r['suggestions'][0]['case_ids']),{'a','b'})

    def test_config_and_no_hindsight(self):
        for value in (0,-1,float('nan'),True):
            with self.assertRaises(ValueError):build([],[],DAY,value)
        u=unit(observed_date='2024-05-09');self.assertTrue(build([self.request()],[u],DAY)['cells'][0]['gap'])
        with self.assertRaises(ValueError):build([],[],'2024-5-8')

    def test_snapshot_cache_and_inventory_registry_invalidation(self):
        from app.engines.world_model.registry import Registry
        tmp=Scratch();self.addCleanup(tmp.cleanup)
        registry=Registry(tmp.path/'events.jsonl')
        c=self.request()
        with registry.locked():registry._append({'kind':'ingest','case_id':'a','case':c,'version':1,'provenance':'coverage-1'})
        fleet=SimpleNamespace(registry=registry,allocation_inventory=[])
        service=CoverageService(fleet)
        # Patch only the local routing adapter; coverage never invokes a model.
        with patch('app.coverage.AsyncDistance.for_unit',return_value={'reachable':False}) as adapter:
            first=service.view(DAY);self.assertTrue(first['cells'][0]['gap'])
            first['cells'].clear();self.assertTrue(service.view(DAY)['cells'])
            fleet.allocation_inventory=[unit()]
            self.assertFalse(service.view(DAY)['cells'][0]['gap'])
            with registry.locked():registry._append({'kind':'analysis','case_id':'a','case':dict(c,status='dispatched',version=2),'version':2,'provenance':'coverage-2'})
            self.assertFalse(service.view(DAY)['cells'])
    def test_unit_breakdown_and_replay_date(self):
        from app.engines.world_model.registry import Registry
        from app.unit_status import UnitStatusService
        tmp=Scratch();self.addCleanup(tmp.cleanup)
        registry=Registry(tmp.path/'events.jsonl');c=self.request()
        with registry.locked():registry._append({'kind':'ingest','case_id':'a','case':c,'version':1,'provenance':'coverage-unit'})
        fleet=SimpleNamespace(registry=registry,allocation_inventory=[unit()]);service=CoverageService(fleet)
        UnitStatusService(registry,lambda:fleet.allocation_inventory).report('boat',dict(
            text='O motor quebrou.',actor='crew',source='crew',received_at='2024-05-09T10:00:00-03:00'))
        with patch('app.coverage.AsyncDistance.for_unit',return_value={'reachable':False}) as adapter:
            self.assertFalse(service.view(DAY)['cells'][0]['gap'])
            self.assertTrue(service.view('2024-05-09')['cells'][0]['gap'])

    def test_http_api_validation_and_static(self):
        from app.web.server import create_server
        tmp=Scratch();self.addCleanup(tmp.cleanup)
        server=create_server('127.0.0.1',0,sample=True,registry_path=tmp.path/'events.jsonl',inventory=[])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for path,code in [('/api/coverage?date='+DAY,200),('/api/coverage',400),
                    ('/api/coverage?date=2024-5-8',400),('/api/coverage?date='+DAY+'&date='+DAY,400),
                    ('/api/coverage?date='+DAY+'&other=1',400),('/v2/coverage.js',200)]:
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                try:
                    conn.request('GET',path);response=conn.getresponse();body=response.read()
                    self.assertEqual(response.status,code,path)
                    if path=='/api/coverage?date='+DAY:self.assertEqual(json.loads(body)['cells'],[])
                finally:conn.close()
        finally:server.shutdown();server.server_close();thread.join()

    def test_small_batch_latency(self):
        from app.fleet.assets import demo_inventory
        cases=[dict(self.request(),case_id=str(i)) for i in range(23)]
        start=time.monotonic();build(cases,demo_inventory(),DAY)
        self.assertLess(time.monotonic()-start,1)
