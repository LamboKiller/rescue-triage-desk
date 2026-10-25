"""Mission behavior tests; synthetic operational attestations are explicit."""
import copy
import json
import time
import unittest
from pathlib import Path
from tests.support import Scratch

DAY = '2024-05-08'


def make_case(cid='a', people=3, lon=-51.18, text='Pedido de socorro.'):
    from app.fleet import screen
    c = {'case_id':cid, 'message_id':cid, 'version':1, 'text':text,
         'received_at':DAY+'T10:00:00-03:00', 'replay_time':DAY+'T12:00:00-03:00',
         'status':'proposed', 'location_confirmed':True,
         'position':{'lat':-29.92, 'lon':lon, 'position_kind':'street_reference'},
         'fields':{'people':{'value':people}},
         'hazards':{'depth_band':'d_0_6_to_1_2', 'depth_m':0.8, 'depth_observed_date':DAY},
         'result':{'decision':'SEND_CANDIDATE', 'priority':10, 'questions':[]}}
    screen(c)
    return c


def inventory(capacity=6, asset='irb', count=1):
    return [{'id':'test-boat-'+str(i), 'asset':asset, 'capacity':capacity,
             'capacity_basis':'rescue_passengers_after_crew_and_equipment',
             'source':'synthetic test boat manifest', 'observed_date':DAY,
             'available':True, 'synthetic':True,
             'attestations':{'stretcher_capable':True}} for i in range(count)]


class Client:
    def __init__(self, output): self.output=output; self.calls=[]
    def call(self, role, system, payload, deadline):
        self.calls.append((role,json.loads(payload)))
        if isinstance(self.output,Exception): raise self.output
        return self.output, {'role':role,'status':'ok'}


class NeedsTests(unittest.TestCase):
    def test_exact_spans_unknown_tags_and_groups(self):
        from app.agents.needs import validate
        messages=['Na casa da frente: 3 pessoas. Há uma gestante.']
        result=validate({'needs':[{'tag':'pregnant','quote':'gestante','message_index':0},
            {'tag':'weapon','quote':'gestante','message_index':0}],
            'count_by_group':[{'quote':'casa da frente: 3 pessoas','message_index':0,
                               'group_quote':'casa da frente','count_quote':'3'}]},messages)
        self.assertEqual([n['tag'] for n in result['needs']],['pregnant'])
        self.assertEqual(result['count_by_group'][0]['people'],3)
        with self.assertRaises(ValueError):
            validate({'needs':[{'tag':'infant','quote':'inventado','message_index':0}]},messages)

    def test_fallback_and_cache_once_per_message_version(self):
        from app.agents.needs import NeedsExtractor
        client=Client(TimeoutError()); extractor=NeedsExtractor(client)
        c=make_case(text='Minha mãe está acamada, a água está subindo.')
        first=extractor.extract(c,deadline=time.monotonic()+5)
        self.assertEqual(first['needs_check'],'deterministic_only')
        self.assertEqual({n['tag'] for n in first['needs']},{'stretcher_or_bedridden','water_rising'})
        extractor.extract(dict(c,version=2),deadline=time.monotonic()+5)
        self.assertEqual(len(client.calls),1)
        c['text']+=' Bebê no colo.'
        self.assertIn('infant',{n['tag'] for n in extractor.extract(c)['needs']})
        self.assertEqual(len(client.calls),2)

    def test_history_negation_and_visible_rejection(self):
        from app.agents.needs import NeedsExtractor
        c=make_case(text='Não há bebê.');c['messages']=[{'text':'Precisa de oxigênio.'},{'text':c['text']}]
        r=NeedsExtractor().extract(c)
        self.assertIn('medical_urgent',{n['tag'] for n in r['needs']})
        self.assertNotIn('infant',{n['tag'] for n in r['needs']})
        r=NeedsExtractor(Client({'needs':[{'tag':'infant','quote':'falso','message_index':0}]})).extract(c)
        self.assertEqual(r['needs_check'],'deterministic_only')
        self.assertGreater(r['validator_rejections'],0)

    def test_groups_include_front_and_rear_house_without_summing_overlap(self):
        from app.agents.needs import NeedsExtractor
        r=NeedsExtractor().extract(make_case(text='Casa da frente: 4 pessoas; casa dos fundos: 2 pessoas.'))
        self.assertEqual([g['people'] for g in r['count_by_group']],[4,2])

    def test_keyword_quotes_preserve_unicode_offsets(self):
        from app.agents.needs import NeedsExtractor
        text='Straße: a a\u0301gua está subindo; pessoa grávida.'
        r=NeedsExtractor().extract(make_case(text=text))
        pregnant=next(n for n in r['needs'] if n['tag']=='pregnant')
        self.assertEqual(pregnant['quote'],'grávida')


class PlannerTests(unittest.TestCase):
    def plan(self,cases,inv=None,**kw):
        from app.missions.planner import propose
        return propose(cases,DAY,inventory() if inv is None else inv,**kw)

    def test_capacity_split_every_case_once_and_life_safety(self):
        from app.missions.planner import check_plan
        cases=[make_case('a'),make_case('b',lon=-51.181,text='Parede vai desabar.'),make_case('c')]
        plans=self.plan(cases)
        self.assertEqual(len(plans),2)
        self.assertEqual(sorted(s['case_id'] for p in plans for s in p['stops']),['a','b','c'])
        self.assertEqual(plans[0]['stops'][0]['case_id'],'b')
        for p in plans:
            self.assertFalse(check_plan(p,cases,inventory()))
            self.assertLessEqual(p['people'],p['capacity']*p['trips'])

    def test_single_case_overflow_has_explicit_trip_loads(self):
        p=self.plan([make_case(people=14)])[0]
        self.assertEqual(p['trips'],3)
        self.assertEqual([t['people'] for t in p['trip_loads']],[6,6,2])

    def test_scarce_inventory_only_reserves_units_needed(self):
        p=self.plan([make_case(people=2)],inventory(6,count=3))[0]
        self.assertEqual(p['asset_count'],1)
        self.assertEqual(p['capacity'],6)

    def test_future_observation_and_duplicate_ids_are_rejected(self):
        c=make_case();c['hazards']['depth_observed_date']='2024-05-09'
        self.assertTrue(self.plan([c])[0]['blocking_reasons'])
        with self.assertRaises(ValueError): self.plan([c,c])

    def test_block_far_unknown_and_missing_capacity(self):
        a,b=make_case('a'),make_case('b',lon=-51.2)
        self.assertEqual(len(self.plan([a,b])),2)
        a['fleet']=[dict(r,verdict='unsafe') if r['asset']=='irb' else r for r in a['fleet']]
        self.assertIsNone(self.plan([a])[0]['asset'])
        p=self.plan([b],inventory(None))[0]
        self.assertIsNone(p['capacity']);self.assertTrue(p['blocking_reasons'])
        b['hazards']['depth_band']='unknown'
        self.assertTrue(any('profundidade' in r.lower() for r in self.plan([b])[0]['blocking_reasons']))

    def test_need_requires_litter_and_injection_blocks(self):
        c=make_case(text='Pessoa em cadeira de rodas.')
        inv=inventory();inv[0]['attestations']['stretcher_capable']=False
        self.assertIsNone(self.plan([c],inv)[0]['asset'])
        c['routing_flags']={'injection':True}
        self.assertTrue(self.plan([c])[0]['blocking_reasons'])

    def test_replay_and_diameter_and_nearest_neighbour(self):
        a,b,c=make_case('a'),make_case('b',lon=-51.185),make_case('c',lon=-51.19)
        self.assertEqual(len(self.plan([a,b,c],inventory(20))),2)
        c['received_at']='2024-05-09T00:00:00Z'
        self.assertNotIn('c',[s['case_id'] for p in self.plan([a,c]) for s in p['stops']])
        p=self.plan([a,make_case('b',lon=-51.184),make_case('c',lon=-51.181)],inventory(20))[0]
        self.assertEqual([s['case_id'] for s in p['stops']],['a','c','b'])

    def test_independent_math_veto_and_order_checks(self):
        from app.missions.planner import check_plan
        cases=[make_case('a'),make_case('b',text='Precisa de insulina.')]
        p=self.plan(cases)[0];p['people']=1
        self.assertTrue(check_plan(p,cases,inventory()))
        p=self.plan(cases)[0];p['stops'].reverse()
        self.assertTrue(check_plan(p,cases,inventory()))
        p=self.plan(cases)[0];p['asset']='road_ambulance'
        self.assertTrue(check_plan(p,cases,inventory()))


class BriefTests(unittest.TestCase):
    def test_unsupported_numbers_fall_back_and_one_call(self):
        from app.missions.brief import explain
        from app.missions.planner import propose
        p=propose([make_case()],DAY,inventory())[0]
        client=Client({'brief_pt':'Levar 99 pessoas.'})
        out=explain(p,client,time.monotonic()+5)
        self.assertEqual(out['brief_check'],'deterministic_only')
        self.assertNotIn('99',out['crew_brief_pt'])
        self.assertEqual(len(client.calls),1)
        self.assertEqual(client.calls[0][0],'mission_brief')


class RegistryMissionTests(unittest.TestCase):
    def setUp(self):
        from app.engines.world_model.registry import Registry
        self.tmp=Scratch();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'events.jsonl';self.registry=Registry(self.path)
        self.cases=[self.registry.ingest(make_case(cid)) for cid in ('a','b')]
        from app.missions.planner import propose
        self.plan=propose(self.cases,DAY,inventory())[0]

    def approve(self,**kwargs):
        c=self.cases[0]
        return self.registry.action(c['case_id'],'approve_mission',c['version'],'test',human=True,
            mission=self.plan,mission_inventory=inventory(),caution_acknowledged=True,**kwargs)

    def test_atomic_durable_and_reversible(self):
        from app.engines.world_model.registry import Registry
        approved=self.approve();mid=self.plan['proposal_id']
        self.assertEqual(approved['status'],'ASSIGNED:'+mid)
        reread=Registry(self.path)
        self.assertTrue(all(c['status']=='ASSIGNED:'+mid and c['version']==2 for c in reread.read()))
        versions={c['case_id']:c['version'] for c in reread.read()}
        restored=reread.action(approved['case_id'],'cancel_mission',2,'test',human=True,
                              mission_id=mid,expected_versions=versions)
        self.assertEqual(restored['status'],'proposed')
        self.assertTrue(all(c['version']==3 for c in reread.read()))
        self.assertEqual(len(self.path.read_text(encoding='utf-8').splitlines()),4)

    def test_human_stale_and_bad_math_write_nothing(self):
        from app.engines.world_model.registry import Conflict
        c=self.cases[0];before=self.path.read_bytes()
        with self.assertRaises(PermissionError):
            self.registry.action(c['case_id'],'approve_mission',1,'model',mission=self.plan)
        self.plan['people']=99
        with self.assertRaises(Conflict): self.approve()
        self.assertEqual(before,self.path.read_bytes())
        from app.missions.planner import propose
        self.plan=propose(self.cases,DAY,inventory())[0]
        self.registry.action(self.cases[1]['case_id'],'request_callback',1,'test',human=True)
        with self.assertRaises(Conflict): self.approve()
        self.assertEqual(self.registry.read(c['case_id'])['version'],1)

    def test_active_mission_cannot_merge_or_overwrite_action(self):
        from app.engines.world_model.registry import Conflict
        c=self.approve()
        for action in ('dispatch','request_callback','merge','unmerge'):
            with self.assertRaises(Conflict):
                self.registry.action(c['case_id'],action,2,'test',human=True,
                    target_case_id=self.cases[1]['case_id'],target_expected_version=2)

    def test_assigned_case_requires_cancellation_before_new_analysis_or_reply(self):
        from app.engines.world_model.registry import Conflict
        c=self.approve();updated=copy.deepcopy(c);updated['text']='Nova observação.'
        updated['messages']=[{'text':'Nova observação.','received_at':c['received_at']}]
        with self.assertRaises(Conflict): self.registry.ingest(updated)
        with self.assertRaises(Conflict): self.registry.append_reply(c['case_id'],2,updated)

    def test_cancel_rejects_stale_member_without_partial_restore(self):
        from app.engines.world_model.registry import Conflict
        c=self.approve();versions={x['case_id']:2 for x in self.cases}
        versions[self.cases[1]['case_id']]=1;before=self.path.read_bytes()
        with self.assertRaises(Conflict):
            self.registry.action(c['case_id'],'cancel_mission',2,'test',human=True,
                mission_id=self.plan['proposal_id'],expected_versions=versions)
        self.assertEqual(self.path.read_bytes(),before)

    def test_race_same_inventory_exactly_one_approval(self):
        import concurrent.futures
        from app.missions.planner import propose
        from app.engines.world_model.registry import Conflict
        plans=[propose([c],DAY,inventory())[0] for c in self.cases]
        def approve(p):
            try:
                self.registry.action(p['stops'][0]['case_id'],'approve_mission',1,'test',human=True,
                    mission=p,mission_inventory=inventory(),caution_acknowledged=True)
                return True
            except Conflict: return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(approve,plans)),1)


class MissionAPITests(unittest.TestCase):
    def setUp(self):
        import threading
        from unittest.mock import patch
        from app.web.server import create_server
        self.tmp=Scratch();self.addCleanup(self.tmp.cleanup)
        self.server=create_server('127.0.0.1',0,sample=True,registry_path=Path(self.tmp.name)/'events.jsonl',inventory=inventory())
        self.addCleanup(self.server.server_close)
        self.patch=patch('app.missions.service.replay_cases',side_effect=lambda cases,day:cases)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.case=self.server.missions.registry.ingest(make_case())
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.shutdown)

    def request(self,path,body=None,headers=None):
        import http.client
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=20)
        try:
            conn.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),
                         headers or {'Content-Type':'application/json'})
            r=conn.getresponse();return r.status,json.loads(r.read())
        finally: conn.close()

    def test_endpoints_versions_cancel_and_existing_routes(self):
        code,response=self.request('/api/missions/proposals?date='+DAY)
        self.assertEqual(code,200);p=response['proposals'][0]
        self.assertFalse(p['blocking_reasons']);self.assertEqual(p['brief_check'],'deterministic_only')
        body={'proposal_id':p['proposal_id'],'actor':'test','expected_versions':{self.case['case_id']:1},'caution_acknowledged':True}
        code,mission=self.request('/api/missions',body)
        self.assertEqual(code,200,mission);self.assertEqual(mission['status'],'assigned')
        mid=mission['mission_id']
        self.assertEqual(self.request('/api/missions/'+mid)[1]['status'],'assigned')
        self.assertEqual(self.request('/api/missions',body)[0],409)
        cancel={'action':'cancel_mission','mission_id':mid,'actor':'test','expected_version':2,'expected_versions':mission['expected_versions']}
        self.assertEqual(self.request('/api/cases/'+self.case['case_id']+'/actions',cancel)[0],200)
        self.assertEqual(self.request('/api/missions/'+mid)[1]['status'],'cancelled')
        self.assertEqual(self.request('/api/cases')[0],200)

    def test_date_origin_missing_inventory_and_unknown_routes(self):
        for path in ('/api/missions/proposals','/api/missions/proposals?date=no','/api/missions/proposals?date='+DAY+'&date='+DAY):
            self.assertEqual(self.request(path)[0],400)
        self.assertEqual(self.request('/api/missions/unknown')[0],404)
        self.assertEqual(self.request('/api/missions',{}, {'Content-Type':'application/json','Origin':'https://elsewhere.invalid'})[0],403)
        self.server.missions.inventory=[]
        p=self.request('/api/missions/proposals?date='+DAY)[1]['proposals'][0]
        self.assertTrue(p['blocking_reasons']);self.assertIsNone(p['capacity'])


class MissionClientTests(unittest.TestCase):
    def test_stream_thinking_shared_budget_strict_json_and_one_retry(self):
        import io
        import urllib.error
        from unittest.mock import patch
        from app.missions.client import MissionClient
        self.tmp=Scratch();self.addCleanup(self.tmp.cleanup)
        calls=[]
        def response(req,**kwargs):
            calls.append(json.loads(req.data))
            if len(calls)==1: raise urllib.error.HTTPError('http://local',502,'retry',{},io.BytesIO(b'{}'))
            return io.BytesIO(b'data: {"choices":[{"delta":{"content":"{\\\"needs\\\":[]}"}}],"meterless":{"routed_model":"test","receipt_id":"demo"}}\n\ndata: [DONE]\n')
        with patch('urllib.request.urlopen',side_effect=response),patch('app.missions.client.setting',side_effect=lambda k,d='': 'test-key' if k=='NIGHTSHIFT_API_KEY' else d):
            client=MissionClient(Path(self.tmp.name)/'trace.jsonl')
            output,meta=client.call('needs_extractor','copy exact','{}',time.monotonic()+5)
        self.assertEqual(output,{'needs':[]});self.assertEqual(meta['receipt'],'demo')
        self.assertEqual(len(calls),2)
        self.assertTrue(all(c['stream'] and c['max_tokens']>=6000 and 'enable_thinking' not in c for c in calls))


class MissionServiceTests(unittest.TestCase):
    def setUp(self):
        from app.engines.world_model.registry import Registry
        from app.missions.service import MissionService
        from unittest.mock import patch
        self.tmp=Scratch();self.addCleanup(self.tmp.cleanup)
        self.registry=Registry(Path(self.tmp.name)/'events.jsonl')
        self.case=self.registry.ingest(make_case())
        self.client=Client({'needs':[],'count_by_group':[],'brief_pt':'Revisar o plano com a equipe.'})
        self.service=MissionService(self.registry,inventory(),self.client)
        self.patch=patch('app.missions.service.replay_cases',side_effect=lambda cases,day:cases)
        self.patch.start();self.addCleanup(self.patch.stop)

    def test_needs_and_brief_cached_and_restart_preserves_detail(self):
        from app.missions.service import MissionService
        p=self.service.proposals(DAY)['proposals'][0]
        self.service.proposals(DAY)
        self.assertEqual([c[0] for c in self.client.calls],['needs_extractor','mission_brief'])
        request={'actor':'test','proposal_id':p['proposal_id'],'expected_versions':{self.case['case_id']:1},'caution_acknowledged':True}
        mission=self.service.approve(request)
        self.assertEqual(MissionService(self.registry,inventory()).detail(mission['mission_id'])['status'],'assigned')
        self.assertEqual(self.service.proposals(DAY)['proposals'],[])

    def test_future_inventory_and_current_messages_excluded(self):
        self.service.inventory[0]['observed_date']='2024-05-09'
        p=self.service.proposals(DAY)['proposals'][0]
        self.assertIsNone(p['asset']);self.assertTrue(p['blocking_reasons'])
        self.assertEqual(self.service.proposals('2024-05-07')['proposals'],[])

    def test_real_replay_screening_has_no_future_observations(self):
        self.patch.stop()
        from app.missions.service import replay_cases
        from app.geo.hazards import STREET_POSITION
        c=make_case();c['position']['position_kind']=STREET_POSITION
        screened=replay_cases([c],'2024-05-05')[0]
        self.assertEqual(screened['hazards']['depth_band'],'unknown')
        self.assertIsNone(screened['hazards']['depth_observed_date'])
        self.assertNotIn('2024-05-08',screened['hazards']['flood_by_date'])


class MissionEvalTests(unittest.TestCase):
    def test_offline_eval_safety_and_needs_contract(self):
        from eval.run_missions import evaluate
        metrics=evaluate()
        self.assertEqual(metrics['scenarios'],12)
        self.assertEqual(metrics['crashes'],0)
        self.assertEqual(metrics['capacity_violations'],0)
        self.assertEqual(metrics['blocked_asset_assignments'],0)
        self.assertEqual(metrics['life_safety_first'],1)
        self.assertEqual(metrics['grouping_accuracy'],1)
        self.assertEqual(metrics['needs']['messages'],15)
        self.assertEqual(metrics['needs']['exact_tag_accuracy'],1)
