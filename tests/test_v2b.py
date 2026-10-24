import copy
import http.client
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from support import Scratch
from app.config import ROOT
from app.geo.depth import DepthGrid, band, depth_data, lookup, lonlat_to_utm22s, utm22s_to_lonlat
from app.geo.hazards import assess
from app.fleet import document, screen, rule_input
from app.fleet.evaluator import check_examples, evaluate
from app.agents import hazard_critic
from app.engines.world_model.registry import Registry, Conflict
from eval.run_hazard_eval import prepare, evaluate as hazard_eval
from run import create_server


class DepthTests(unittest.TestCase):
    def test_real_samples_and_replay(self):
        a=lookup(-51.171,-29.994,'2024-05-08')
        self.assertAlmostEqual(a['depth_m'],2.72,places=2)
        self.assertLessEqual(a['depth_distance_m'],60)
        self.assertEqual(a['depth_band'],'d_gt_2_5')
        self.assertEqual(a['depth_confidence'],'baixa — estimativa HAND ±1 m, retrospectiva')
        for lon,lat in [(-51.1999541,-30.0266244),(-51.19,-29.925)]:
            unknown=lookup(lon,lat,'2024-05-08')
            self.assertIsNone(unknown['depth_m']);self.assertEqual(unknown['depth_status'],'desconhecida')
        from app.geo.depth import grid
        with patch('app.geo.depth.grid',wraps=grid) as load:
            a=lookup(-51.171,-29.994,'2024-05-06')
            self.assertEqual(set(a['depth_by_date']),{'2024-05-06'})
            self.assertEqual([c.args[0] for c in load.call_args_list],['2024-05-06'])
        self.assertIsNone(lookup(-51.171,-29.994,'2024-05-05')['depth_m'])

    def test_radius_and_nearest_valid_not_deepest(self):
        x,y=lonlat_to_utm22s(-51,-30)
        # First cell no-data, second is closest valid, third is deeper but farther away.
        h={'width':3,'height':1,'pixel_m':20,'origin_x':x-10,'origin_y':y+10}
        g=DepthGrid(h,b'\xff\xff\x64\x00\xe8\x03')
        self.assertEqual(g.nearest(-51,-30),{'depth_m':1,'distance_m':20})
        self.assertIsNone(g.nearest(-51,-30,19)['depth_m'])
        self.assertEqual(g.nearest(-51,-30,20)['depth_m'],1)
        self.assertIsNone(g.nearest(-50,-30)['depth_m'])

    def test_band_edges_and_inverse(self):
        self.assertEqual([band(x) for x in (None,0,.15,.3,.6,1.2,2.5,2.51)],
                         ['unknown','d_lt_0_15','d_0_15_to_0_3','d_0_3_to_0_6','d_0_6_to_1_2','d_1_2_to_2_5','d_1_2_to_2_5','d_gt_2_5'])
        lon,lat=utm22s_to_lonlat(*lonlat_to_utm22s(-51.2,-30.02))
        self.assertAlmostEqual(lon,-51.2,places=5);self.assertAlmostEqual(lat,-30.02,places=5)

    def test_aggregation_max_and_date(self):
        h={'width':5,'height':5,'pixel_m':20,'origin_x':500000,'origin_y':6700000}
        data=b'\xff\xff'*24+b'\x2c\x01'
        with patch('app.geo.depth.grid',return_value=DepthGrid(h,data)):
            from app.geo.depth import aggregated
            aggregated.cache_clear()
            cells=aggregated('test')
            self.assertEqual(len(cells),1);self.assertEqual(cells[0][3],3)
            aggregated.cache_clear()
        early=depth_data('2024-05-05','-52,-31,-50,-29')
        self.assertEqual(early['cells'],[]);self.assertIsNone(early['observation_date'])
        with self.assertRaises(ValueError):depth_data('2024-05-08','nan,-31,-50,-29')

    def test_flood_accumulation(self):
        a=assess(-30.022194,-51.2198891,'2024-05-08','landmark')
        self.assertTrue(a['flood_by_date']['2024-05-06']);self.assertTrue(a['in_flood_any'])
        self.assertNotIn('2024-05-08',assess(-30.022194,-51.2198891,'2024-05-06','landmark')['flood_by_date'])
        self.assertTrue(any('cobertura, não recessão' in f['text_pt'] for f in a['facts']))


class FleetTests(unittest.TestCase):
    def test_frozen_reference_examples(self):
        doc=copy.deepcopy(document());doc['examples']=json.loads((ROOT/'data/fleet/examples.json').read_text(encoding='utf-8'))
        self.assertEqual(check_examples(doc),8)
        for example in doc['examples']:
            out=evaluate(doc,example['input'])
            self.assertEqual({a:r['status'] for a,r in out['assets'].items()},example['expected_statuses'])
            for r in out['assets'].values():
                self.assertEqual(r['status'],max((c['status'] for c in r['constraints']),key={'suitable':0,'caution':1,'unsafe':2}.get))

    def test_mapping_mobility_infants_and_unknowns(self):
        case={'text':'3 pessoas, bebê de colo, uma pessoa não caminha em cadeira de rodas no telhado.',
              'fields':{'people':{'value':3},'children':{'value':1},'elderly':{'value':1},'disabled':{'value':1},'pets':{'value':2}}}
        r=rule_input(case)
        self.assertEqual([r[k] for k in ('people_count','children','elderly','disabled','pets','infants','wheelchair','bedridden')],[3,1,1,1,2,1,1,1])
        self.assertEqual(r['location_type'],'rooftop')
        for k in ('current','debris','electricity'):self.assertEqual(r['hazards'][k],'unknown')
        self.assertIsNone(r['hazards']['overhead_clearance']);self.assertEqual(r['assigned_assets'],{})
        out=screen(case);pwc=next(a for a in out['fleet'] if a['asset']=='pwc_sled')
        self.assertEqual(pwc['verdict'],'unsafe');self.assertIn('R060',pwc['rule_ids'])
        self.assertTrue(any('maca fixada' in r for r in pwc['reasons_pt']))
        self.assertTrue(out['fleet_summary']['human_approval_required'])
        self.assertTrue(all(a['verdict']!='unsafe' for a in out['fleet_summary']['options']))
        self.assertEqual(rule_input({'text':'no segundo piso','fields':{}})['location_type'],'building_upper_floor')
        for text in ('bebês','recém-nascido','de colo'):
            self.assertEqual(rule_input({'text':text})['infants'],1)
        self.assertNotIn('infants',rule_input({'text':'socorro'}))


class CriticTests(unittest.TestCase):
    def setUp(self):
        self.facts=[{'id':'F3','text_pt':'Profundidade estimada 2.70 m.','source':'grid'}]
        self.output={'objections':[{'fact_ids':['F3'],'text_pt':'Água de 2,7 m exige revisão.','severity':'block'}],
                     'brief_pt':'Recurso exige revisão.'}

    def test_supported_numbers_and_unknown_ids(self):
        review,n=hazard_critic.validate(self.output,self.facts,{})
        self.assertEqual(n,0);self.assertEqual(len(review['objections']),1)
        self.output['objections'][0]['fact_ids']=['F999']
        review,n=hazard_critic.validate(self.output,self.facts,{})
        self.assertEqual(review['objections'],[]);self.assertEqual(n,1)

    def test_invented_numbers_and_brief(self):
        self.output['objections'][0]['text_pt']='Água de 99 m.'
        self.output['brief_pt']='Envie 77 barcos.'
        review,n=hazard_critic.validate(self.output,self.facts,{})
        self.assertEqual(review,{'objections':[],'brief_pt':''});self.assertEqual(n,2)
        self.output['objections'][0]['text_pt']='Há 3 pessoas.';self.output['brief_pt']='Há 3 pessoas.'
        _,n=hazard_critic.validate(self.output,self.facts,{'people':{'value':3}});self.assertEqual(n,0)

    def test_written_numbers_are_checked(self):
        self.output['objections'][0]['text_pt']='Envie noventa e nove barcos.'
        review,n=hazard_critic.validate(self.output,self.facts,{})
        self.assertEqual(review['objections'],[]);self.assertEqual(n,1)
        self.output['objections'][0]['text_pt']='Há três pessoas.'
        _,n=hazard_critic.validate(self.output,self.facts,{'people':{'value':3}})
        self.assertEqual(n,0)
        self.output['objections'][0]['text_pt']='Água de -2.7 m.'
        review,n=hazard_critic.validate(self.output,self.facts,{})
        self.assertEqual(review['objections'],[]);self.assertEqual(n,1)

    def test_failure_deadline_and_no_upgrade(self):
        class Fail:
            def call(self,*args):raise TimeoutError()
        case={'text':'socorro','result':{'decision':'REVIEW_REQUIRED'},'fleet_summary':{'options':[]}}
        original=copy.deepcopy(case['result']);hazard_critic.attach(case,Fail(),time.monotonic()+1)
        self.assertEqual(case['hazard_review'],'indisponível');self.assertEqual(case['result'],original)
        with self.assertRaises(TimeoutError):hazard_critic.run(Fail(),'socorro',case,time.monotonic()-1)

    def test_offline_eval_balance_truth_and_wiring(self):
        items=[json.loads(l) for l in (ROOT/'eval/hazard_set.jsonl').read_text(encoding='utf-8').splitlines()]
        truth=json.loads((ROOT/'eval/hazard_truth.json').read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(items),12);self.assertEqual(sum(t['should_block'] for t in truth.values()),6)
        for item in items:
            c=prepare(item); selected=next(r for r in c['fleet'] if r['asset']==item['proposed_asset'])
            self.assertEqual(selected['verdict']=='unsafe',truth[item['message_id']]['should_block'])
            if item['message_id']=='hazard-mathias':self.assertIsNone(c['hazards']['depth_m'])
        result=hazard_eval(items,truth,offline=True)
        self.assertEqual(result['block_recall'],1);self.assertEqual(result['false_block_rate'],0)
        self.assertEqual(result['citation_validity'],1);self.assertEqual(result['unsupported'],0)
        self.assertEqual(result['mode'],'offline_wiring_only')


class GateAndApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=Scratch();self.addCleanup(self.tmp.cleanup)
        self.registry=Registry(Path(self.tmp.name)/'events.jsonl')
        base={'message_id':'asset-gate','text':'3 pessoas','received_at':'2024-05-08T12:00:00-03:00',
              'result':{'decision':'SEND_CANDIDATE','priority':3},
              'fleet':[{'asset':'irb','label_pt':'Bote','verdict':'caution','reasons_pt':['Confirme equipe.'],'rule_ids':['R004'],'source_ids':['POLICY']},
                       {'asset':'road_ambulance','label_pt':'Ambulância','verdict':'unsafe','reasons_pt':['Água impede entrada.'],'rule_ids':['R035'],'source_ids':['NWS']}]}
        self.case=self.registry.ingest(base)
        self.case=self.registry.action(self.case['case_id'],'confirm_location',1,'operador',human=True)

    def test_asset_and_caution_gates_rebuild_and_reset(self):
        cid=self.case['case_id']
        with self.assertRaises(ValueError):self.registry.action(cid,'approve_dispatch',2,'operador',human=True)
        for kwargs in ({'asset':'road_ambulance'},{'asset':'unknown'},{'asset':'irb'}):
            with self.assertRaises(Conflict):self.registry.action(cid,'approve_dispatch',2,'operador',human=True,**kwargs)
        c=self.registry.action(cid,'approve_dispatch',2,'operador',human=True,asset='irb',caution_acknowledged=True)
        self.assertEqual(c['approved_asset'],'irb');self.assertTrue(c['caution_acknowledgement']['acknowledged'])
        self.assertEqual(Registry(self.registry.path).read(cid),c)
        c=self.registry.action(cid,'dispatch',3,'operador',human=True)
        self.assertEqual(c['status'],'dispatched')
        fresh=copy.deepcopy(self.case);fresh['text']='agora 4 pessoas';fresh.pop('facts');fresh.pop('actions')
        c=self.registry.ingest(fresh)
        self.assertIsNone(c['approved_asset']);self.assertIsNone(c['caution_acknowledgement'])

    def test_http_unsafe_409_and_depth_bounds(self):
        server=create_server('127.0.0.1',0,sample=True,registry_path=self.registry.path)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join,2);self.addCleanup(server.shutdown)
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=20);self.addCleanup(conn.close)
        path='/api/cases/'+self.case['case_id']+'/actions'
        payload={'action':'approve_dispatch','asset':'road_ambulance','expected_version':2,'actor':'operador'}
        conn.request('POST',path,json.dumps(payload),{'Content-Type':'application/json'})
        response=conn.getresponse();self.assertEqual(response.status,409);self.assertIn('inseguro',json.loads(response.read())['error'])
        for query in ('date=2024-05-08','date=bad&bbox=-52,-31,-50,-29','date=2024-05-08&bbox=nan,-31,-50,-29',
                      'date=2024-05-08&date=2024-05-06&bbox=-52,-31,-50,-29'):
            conn.request('GET','/api/depth?'+query);res=conn.getresponse();self.assertEqual(res.status,400);res.read()
        conn.request('GET','/api/depth?date=2024-05-08&bbox=-52,-31,-50,-29')
        res=conn.getresponse();body=res.read();self.assertEqual(res.status,200)
        self.assertLess(len(body),3000000);data=json.loads(body)
        self.assertLessEqual(len(data['cells']),50000);self.assertEqual(data['cell_m'],100)
        self.assertTrue(all(len(c)==4 for c in data['cells']));self.assertEqual(data['observation_date'],'2024-05-08')
        conn.request('GET','/api/depth?date=2024-05-06&bbox=-52,-31,-50,-29')
        res=conn.getresponse();self.assertEqual(json.loads(res.read())['observation_date'],'2024-05-06')

if __name__=='__main__':unittest.main()
