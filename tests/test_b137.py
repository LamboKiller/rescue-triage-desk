import contextlib
import copy
import io
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.support import Scratch
from app.duplicates import candidate
from app.agents.duplicate_reviewer import run as review
from app.engines.world_model.registry import Registry, Conflict
from app.pipeline import Pipeline
from app.runs import RunStore
from app.stats import build_stats, flooded_area

TIME='2024-05-06T12:00:00-03:00'


def case(mid='a', people=3):
    return {'message_id':mid,'case_id':mid,'text':'Socorro 3 pessoas Rua Brasil 10 Canoas',
            'received_at':TIME,'replay_time':TIME,'fields':{k:{'value':v} for k,v in
             {'street':'Rua Brasil','number':'10','municipality':'Canoas','people':people}.items()},
            'result':{'priority':6,'decision':'SEND_CANDIDATE','people_derived':people,'questions':[]},
            'calls':[],'hazard_facts':[{'id':mid,'text_pt':mid}], 'status':'proposed'}


class DuplicateTests(unittest.TestCase):
    def test_blocks_and_time(self):
        a,b=case(),case('b')
        self.assertIn('same_street_number',candidate(a,b)['reasons'])
        b['received_at']='2024-05-07T12:00:00-03:00'
        self.assertIsNone(candidate(a,b))
        b['received_at']='2024-05-07T00:00:00-03:00'
        self.assertIsNotNone(candidate(a,b))

    def test_landmark_and_normalized_text(self):
        a,b=case(),case('b')
        a['fields']={};b['fields']={}
        a['text']='SOCORRO! Pessoas ilhadas';b['text']='socorro pessoas ilhadas'
        self.assertEqual(candidate(a,b)['token_overlap'],1)
        a['text']='um';b['text']='outro'
        for c in (a,b): c['landmark_check']={'status':'resolved','matched':{'osm_id':'node:1'}}
        self.assertEqual(candidate(a,b)['reasons'],['same_resolved_osm_id'])

    def test_proximity_requires_profile_and_no_number_conflict(self):
        a,b=case(),case('b');a['text']='um';b['text']='dois'
        for c in (a,b):c['position']={'lat':-30,'lon':-51,'position_kind':'street_centroid'}
        b['fields']['number']['value']='90'
        self.assertIsNone(candidate(a,b))
        a['fields'].pop('number');b['fields'].pop('number')
        self.assertIn('street_points_150m_profile_overlap',candidate(a,b)['reasons'])
        b['position']['lat']=-31
        self.assertIsNone(candidate(a,b))

    def test_review_rejects_wrong_message_quote(self):
        class Client:
            def call(self,*args):return self.output,{'role':args[0]}
        client=Client();a,b=case(),case('b');b['text']='Outra mensagem'
        client.output={'verdict':'same','evidence':[{'case':'A','quote':'Socorro'},{'case':'B','quote':'Socorro'}],'reason_pt':'Mesmo local'}
        with self.assertRaises(ValueError):review(client,a,b,time.monotonic()+1)
        client.output['evidence'][1]['quote']='Outra'
        self.assertEqual(review(client,a,b,time.monotonic()+1)[0]['verdict'],'same')
        client.output['evidence'].pop()
        with self.assertRaises(ValueError):review(client,a,b,time.monotonic()+1)


class RegistryMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=Scratch();self.addCleanup(self.tmp.cleanup)
        self.registry=Registry(Path(self.tmp.name)/'events.jsonl')
        self.a=self.registry.ingest(case());self.b=self.registry.ingest(case('b',5))

    def merge(self):
        return self.registry.action(self.a['case_id'],'merge',1,'test',human=True,
                target_case_id=self.b['case_id'],target_expected_version=1)

    def test_reversible_union_conflicting_count(self):
        merged=self.merge()
        self.assertEqual(merged['version'],2)
        self.assertEqual(len(merged['messages']),2)
        self.assertEqual(len(merged['facts']),2)
        self.assertTrue({'a','b'} <= {f['id'] for f in merged['hazard_facts']})
        self.assertEqual(len(merged['fleet']),20)
        self.assertNotIn('people',merged['fields'])
        self.assertTrue(merged['result']['conflicting_counts'])
        self.assertEqual(merged['open_items'][0]['field'],'people')
        self.assertEqual(self.registry.read(self.b['case_id'])['status'],'MERGED_INTO:'+self.a['case_id'])
        restored=self.registry.action(self.a['case_id'],'unmerge',2,'test',human=True)
        self.assertEqual(restored['fields'],self.a['fields'])
        self.assertEqual(restored['version'],3)
        self.assertEqual(self.registry.read(self.b['case_id'])['fields'],self.b['fields'])
        self.assertEqual(self.registry.read(self.b['case_id'])['version'],3)

    def test_stale_and_human_gates(self):
        with self.assertRaises(PermissionError):self.registry.action(self.a['case_id'],'merge',1,'bot')
        with self.assertRaises(Conflict):self.registry.action(self.a['case_id'],'merge',1,'human',human=True,target_case_id=self.b['case_id'],target_expected_version=9)
        self.assertEqual(self.registry.read(self.a['case_id'])['version'],1)
        self.merge()
        with self.assertRaises(Conflict):self.registry.ingest(case('b',9))
        with self.assertRaises(Conflict):self.registry.action(self.b['case_id'],'request_callback',2,'human',human=True)

    def test_concurrent_merge_only_one_wins(self):
        results=[]
        def worker():
            try:self.merge();results.append('ok')
            except Conflict:results.append('conflict')
        threads=[threading.Thread(target=worker) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(results,['ok','conflict'])


class StatsTests(unittest.TestCase):
    def test_area_union_and_holes(self):
        def feature(rings):return {'geometry':{'type':'Polygon','coordinates':rings}}
        outer=[[0,0],[1,0],[1,1],[0,1],[0,0]]
        hole=[[.25,.25],[.75,.25],[.75,.75],[.25,.75],[.25,.25]]
        full=flooded_area([feature([outer])])
        self.assertEqual(flooded_area([feature([outer]),feature([outer])]),full)
        self.assertAlmostEqual(flooded_area([feature([outer,hole])])/full,.75,places=3)

    def test_stats_unknowns_groups_and_metrics(self):
        a=case();a['calls']=[{'role':'critic','model':'nemotron','status':'ok','seconds':2},
                            {'role':'intake','status':'failed','seconds':10}]
        a['agents']={'critic':{'objections':[{}]},'revision':{}}
        a['unsupported']=[{}];a['routing_flags']={'injection':True}
        layers={k:{'features':[]} for k in ('flood','pumps','closures')}
        mapped={'cases':[{'case_id':'a','hazards':{'depth_band':'unknown'},'fleet_summary':{'options':[{'asset':'irb','verdict':'caution'}]}}], 'layers':layers}
        with patch('app.stats.map_data',return_value=mapped):result=build_stats('2024-05-06',[a])
        self.assertEqual(result['people_waiting']['people']['known_total'],3)
        self.assertEqual(result['people_waiting']['children']['unknown_cases'],1)
        self.assertEqual(result['asset_demand']['only_asset'],{'irb':1})
        self.assertEqual(sum(result['asset_demand']['only_group'].values()),1)
        self.assertEqual(result['agent_metrics']['p90_seconds'],10)
        self.assertEqual(result['agent_metrics']['failures'],1)
        self.assertEqual(result['agent_metrics']['critic_objections'],1)
        self.assertEqual(result['agent_metrics']['revisions'],1)
        self.assertEqual(result['agent_metrics']['injections_detected'],1)
        with patch('app.stats.map_data',return_value={'cases':[],'layers':layers}):
            self.assertEqual(build_stats('2024-05-05',[a])['open_cases'],0)
        with self.assertRaises(ValueError):build_stats('bad',[a])


class RunTests(unittest.TestCase):
    def test_async_pipeline_and_eviction(self):
        tmp=Scratch();self.addCleanup(tmp.cleanup)
        pipeline=Pipeline(Registry(Path(tmp.name)/'events.jsonl'),sample=True)
        store=RunStore(limit=2)
        with contextlib.redirect_stdout(io.StringIO()):
            for i in range(3):
                run=store.start(pipeline,{'replay_time':TIME,'messages':[{'message_id':str(i),'text':'Socorro 3 pessoas Rua Brasil 10 Canoas'}]})
                if i==0:first=run['run_id']
                stream=''.join(store.events(run['run_id']))
                self.assertIn('event: done',stream)
                for stage in ('received','location_started','location_done','checks_done','decision'):
                    self.assertIn('event: '+stage,stream)
                result=store.read(run['run_id'])
                self.assertEqual(result['status'],'complete')
                self.assertEqual(result['result']['run_id'],run['run_id'])
                self.assertEqual(len(result['result']['cases']),1)
        self.assertIsNone(store.read(first))
        self.assertEqual(len(store.runs),2)

    def test_failure_and_active_run(self):
        class Broken:
            run_lock=threading.Lock()
            def _run(self,*args,**kwargs):raise RuntimeError('boom')
        pipeline=Broken();store=RunStore()
        pipeline.run_lock.acquire()
        with self.assertRaises(ValueError):store.start(pipeline,{'replay_time':TIME,'messages':[{'text':'x'}]})
        pipeline.run_lock.release()
        run=store.start(pipeline,{'replay_time':TIME,'messages':[{'text':'x'}]})
        self.assertIn('event: error',''.join(store.events(run['run_id'])))
        self.assertEqual(store.read(run['run_id'])['status'],'failed')

    def test_event_client_metadata(self):
        from app.runs import EventClient
        class Client:
            def call(self,*args):return {},{'model':'nemotron','receipt':'receipt-1','seconds':.2}
        events=[]
        client=EventClient(Client(),lambda stage,**data:events.append((stage,data)))
        client.call('intake','','',time.monotonic()+1)
        self.assertEqual(events[0][0],'intake_started')
        self.assertEqual(events[1][1]['receipt'],'receipt-1')


class HttpTests(unittest.TestCase):
    def test_async_sse_stats_duplicates_and_actions(self):
        import http.client
        from run import create_server
        tmp=Scratch();self.addCleanup(tmp.cleanup)
        server=create_server(host='127.0.0.1',port=0,sample=True,registry_path=Path(tmp.name)/'events.jsonl')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def request(method,path,body=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=15)
            conn.request(method,path,json.dumps(body) if body is not None else None,{'Content-Type':'application/json'})
            response=conn.getresponse();data=response.read();status=response.status;mime=response.getheader('Content-Type');conn.close()
            return status,mime,data
        body={'async':True,'replay_time':TIME,'messages':[{'message_id':str(i),'text':'Socorro 3 pessoas Rua dos Andradas 120 Porto Alegre'+(', urgente, casa alagada subindo rapido' if i else '')} for i in range(2)]}
        with contextlib.redirect_stdout(io.StringIO()):
            status,_,data=request('POST','/run',body)
            self.assertEqual(status,202);rid=json.loads(data)['run_id']
            status,mime,data=request('GET','/api/runs/'+rid+'/events')
            self.assertEqual(status,200);self.assertTrue(mime.startswith('text/event-stream'))
            self.assertIn(b'event: done',data)
            status,_,data=request('GET','/api/runs/'+rid)
            result=json.loads(data);self.assertEqual(result['status'],'complete')
            a,b=result['result']['cases']
            status,_,data=request('GET','/api/cases/'+a['case_id']+'/duplicates')
            self.assertEqual(status,200);self.assertEqual(json.loads(data)['duplicates'][0]['case_id'],b['case_id'])
            status,_,data=request('POST','/api/cases/'+a['case_id']+'/actions',{'action':'merge','expected_version':1,'actor':'test','target_case_id':b['case_id'],'target_expected_version':1})
            self.assertEqual(status,200)
            status,_,data=request('GET','/api/stats?date=2024-05-06')
            self.assertEqual(status,200);self.assertEqual(json.loads(data)['open_cases'],1)
            status,_,data=request('POST','/api/cases/'+a['case_id']+'/actions',{'action':'unmerge','expected_version':2,'actor':'test'})
            self.assertEqual(status,200)
        self.assertEqual(request('GET','/api/stats?date=bad')[0],400)
        self.assertEqual(request('GET','/api/stats?date=2024-05-06&date=2024-05-07')[0],400)
        self.assertEqual(request('GET','/api/runs/missing')[0],404)
        self.assertEqual(request('GET','/api/cases/missing/duplicates')[0],404)


if __name__=='__main__':unittest.main()
