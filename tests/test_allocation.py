"""Synthetic allocation regressions; never calls a live provider."""
import json
import unittest

from app.fleet import document
from tests.test_missions import make_case, Client

DAY = '2024-05-08'


def case(**changes):
    c = make_case()
    c['hazards'].update(depth_confidence='high', hazards_current=True,
        inside_flood_extent=True, extent_date_matches=True, current='still',
        electricity='isolated', debris='clear', night=False,
        overhead_clearance=True, duplicate_check_complete=True,
        nearby_road_closure=False, route_closed=False, pump_station_outage=False)
    c['hazards'].update(changes)
    return c


def unit(uid='boat', kind='bote_inflavel', **changes):
    from app.fleet.assets import RULE_TYPES
    u = dict(id=uid, type=kind, asset=RULE_TYPES[kind], capacity_people=6,capacity_source='[SIMULADO] manifesto',
        draft_m=0.2, max_wading_depth_m=None, stretcher=True, medical_crew=True,
        night_ok=True, pets_ok=True, base_location={'lat':-29.92,'lon':-51.18},
        base='[SIMULADO] base', crew='[SIMULADO] equipe', status='available',
        last_report_at=DAY+'T10:00:00-03:00', observed_date=DAY,
        source='[SIMULADO]', synthetic=True, current_load=0,
        attestations={k:True for k in document()['verification_fields']})
    u.update(changes)
    return u


class AllocationTests(unittest.TestCase):
    def allocate(self,c=None,units=None,**kwargs):
        from app.fleet.allocation import allocate
        return allocate(c or case(), units if units is not None else [unit()], DAY, **kwargs)

    def test_stretcher_and_reused_rules_block_jet_ski(self):
        c=case();c['fields']['disabled']={'value':1}
        r=self.allocate(c,[unit('jet','jet_ski',stretcher=False),unit()])
        self.assertEqual(r['top3'][0]['id'],'boat')
        self.assertIn('R060',r['ineligible'][0]['reason_codes'])
        self.assertTrue(r['top3'][0]['fact_ids'])

    def test_over_capacity_computes_two_trips(self):
        c=case();c['fields']['people']['value']=9
        r=self.allocate(c)['top3'][0]
        self.assertEqual((r['trips'],r['capacity_people']),(2,6))
        self.assertIn('MULTI_TRIP',r['reason_codes'])

    def test_unknown_deep_stale_depth_never_proposes_truck(self):
        for hazards in ({'depth_m':None},{'depth_m':1.4},{'depth_m':.4,'depth_confidence':'low'},
                        {'depth_m':.4,'depth_observed_date':'2024-05-09'}):
            r=self.allocate(case(**hazards),[unit('truck','caminhao_alto',max_wading_depth_m=.9)])
            self.assertFalse(r['top3'])
            self.assertTrue(r['ineligible'][0]['blocking_reasons'])

    def test_draft_night_pets_status_and_rules(self):
        for c,u,code in [(case(depth_m=.1),unit(),'DRAFT_LIMIT'),
            (case(night=True),unit(night_ok=False),'NIGHT_REQUIRED'),
            (case(),unit(status='out_of_service'),'UNAVAILABLE'),
            (case(electricity='live'),unit(),'R020')]:
            with self.subTest(code=code):
                r=self.allocate(c,[u]);self.assertFalse(r['top3'])
                self.assertIn(code,r['ineligible'][0]['reason_codes'])
        c=case();c['fields']['pets']={'value':1}
        self.assertFalse(self.allocate(c,[unit(pets_ok=False)])['top3'])

    def test_ambulance_only_dry_and_helicopter_request_only(self):
        ambulance=unit('ambulance','ambulancia',draft_m=None,max_wading_depth_m=0)
        self.assertFalse(self.allocate(units=[ambulance])['top3'])
        self.assertEqual(self.allocate(case(depth_m=0,inside_flood_extent=False),[ambulance])['top3'][0]['id'],'ambulance')
        c=case(water_rising=True);c['text']='Pessoas no telhado, agua subindo.'
        r=self.allocate(c,[unit('heli','helicoptero')])
        self.assertFalse(r['top3']);self.assertEqual(r['requests'][0]['type'],'helicoptero')
        self.assertFalse(self.allocate(units=[unit('heli','helicoptero')])['requests'])

    def test_ranking_is_computed_distance_pluggable_load_tiebreak(self):
        near=unit('near');far=unit('far',base_location={'lat':-29.95,'lon':-51.18})
        r=self.allocate(units=[far,near])
        self.assertEqual(r['top3'][0]['id'],'near')
        self.assertIn('estimativa',r['distance_basis_pt'])
        r=self.allocate(units=[far,near],distance_fn=lambda a,b: 10)
        self.assertEqual(r['top3'][0]['id'],'far')
        near['current_load']=1
        self.assertEqual(self.allocate(units=[near,unit('idle')])['top3'][0]['id'],'idle')

    def test_missing_capacity_and_injection_hold(self):
        self.assertIn('CAPACITY_UNKNOWN',[x['code'] for x in self.allocate(units=[unit(capacity_people=None)])['top3'][0]['confirmation_checklist']])
        c=case();c['routing_flags']={'injection':True}
        r=self.allocate(c);self.assertTrue(r['top3'][0]['approval_holds']);self.assertEqual(r['decision'],'REVIEW_REQUIRED')

    def test_explainer_rejects_invented_numbers_assets_and_citations(self):
        from app.fleet.allocation import explain
        r=self.allocate()
        for output in ({'comparisons':[{'asset_id':'ghost','reason_code':'MULTI_TRIP','fact_id':'fake','tradeoff_quote':'9 viagens'}]},
                       {'comparisons':[{'asset_id':'boat','reason_code':'CAPACITY','fact_id':'allocation:boat','tradeoff_quote':'99 lugares'}]}):
            result=explain(r,Client(output))
            self.assertEqual(result['explanation_check'],'deterministic_only')
            self.assertIn('fallback_reason',result)
        row=r['top3'][0];reason=row['reasons'][0]
        client=Client({'comparisons':[{'asset_id':row['id'],'reason_code':reason['code'],
            'fact_id':reason['fact_ids'][0],'tradeoff_quote':reason['text_pt']}]})
        self.assertEqual(explain(r,client)['explanation_check'],'model_reviewed')
        self.assertEqual(client.calls[0][0],'fleet_allocation')

    def test_demo_is_explicit_and_attributes_validated(self):
        from app.fleet.assets import demo_inventory, normalize
        self.assertTrue(all(u['source']=='[SIMULADO]' and u['synthetic'] for u in demo_inventory()))
        with self.assertRaises(ValueError): normalize(unit(capacity_people=-1))
        with self.assertRaises(ValueError): normalize(unit(night_ok='yes'))
        from app.resources import validate
        self.assertEqual(validate(unit())['capacity'],6)

    def test_human_selection_override_event_and_atomic_revalidation(self):
        from tests.support import Scratch
        from app.engines.world_model.registry import Registry, Conflict
        from app.missions.service import MissionService
        scratch=Scratch();self.addCleanup(scratch.cleanup)
        registry=Registry(scratch.path/'events.jsonl')
        c=case();c['actions']=[]
        registry._append({'schema_version':1,'kind':'analysis','case':c,'case_id':'a','version':1,'provenance':'a'})
        service=MissionService(registry,[unit('a'),unit('b')])
        options=service.assets('a',DAY)
        row=options['top3'][1]
        request=dict(proposal_id=row['proposal_id'],expected_versions={'a':1},actor='test',caution_acknowledged=True,
            checklist_confirmations={x['code']:True for x in row['confirmation_checklist']})
        with self.assertRaises(ValueError): service.approve(request)
        request['override_reason']='Equipe conhece o acesso lateral.'
        detail=service.approve(request)
        self.assertEqual(detail['units'][0]['id'],'b')
        event=registry.read('a')['actions'][-1]
        self.assertEqual(event['mission']['allocation_selection']['override_reason'],request['override_reason'])
        self.assertEqual(registry.read('a')['approved_asset'],'irb')
        with self.assertRaises(Conflict): service.approve(request)

    def test_capability_change_between_proposal_and_approval_is_blocked(self):
        from tests.support import Scratch
        from app.engines.world_model.registry import Registry, Conflict
        from app.missions.service import MissionService
        from app.resources import register
        scratch=Scratch();self.addCleanup(scratch.cleanup)
        registry=Registry(scratch.path/'events.jsonl');c=case(night=True);c['actions']=[]
        registry._append({'schema_version':1,'kind':'analysis','case':c,'case_id':'a','version':1,'provenance':'a'})
        service=MissionService(registry,[unit()])
        row=service.assets('a',DAY)['top3'][0]
        register(registry,dict(actor='test',unit=unit(night_ok=False),expected_version=0))
        self.assertFalse(service.assets('a',DAY)['top3'])
        with self.assertRaises(Conflict):
            service.approve(dict(proposal_id=row['proposal_id'],expected_versions={'a':1},actor='test',caution_acknowledged=True,
                checklist_confirmations={x['code']:True for x in row['confirmation_checklist']}))
        self.assertEqual(registry.read('a')['status'],'proposed')

    def test_route_maximum_not_only_case_depth_blocks_land(self):
        r=self.allocate(case(depth_m=.4,route_max_depth_m=1.1),[unit('truck','caminhao_alto',max_wading_depth_m=.9)])
        self.assertFalse(r['top3']);self.assertIn('WADING_LIMIT',r['ineligible'][0]['reason_codes'])

    def test_road_eta_adapter_supplies_computed_metric_and_label(self):
        r=self.allocate(units=[unit('a'),unit('b',base_location={'lat':-29.94,'lon':-51.18})],
            distance_fn=lambda a,b: {'distance_m':1200,'eta_seconds':60 if a['lat']<-29.93 else 300,
                                    'basis_pt':'ETA viária estimada pelo adaptador local.'})
        self.assertEqual(r['top3'][0]['id'],'b')
        self.assertEqual(r['top3'][0]['eta_seconds'],60)
        self.assertIn('viária',r['top3'][0]['distance_basis_pt'])

    def test_existing_mission_planning_also_respects_typed_unit_limits(self):
        from app.missions.planner import propose
        from app.fleet.assets import normalize
        c=case(night=True)
        plans=propose([c],DAY,[normalize(unit(night_ok=False))])
        self.assertIsNone(plans[0]['asset'])
        self.assertTrue(plans[0]['blocking_reasons'])

    def test_incomplete_boat_has_cited_checks_but_unknown_land_stays_blocked(self):
        c=case(depth_m=0, depth_confidence='low', night=None)
        c['hazard_review']='deterministic_only'
        r=self.allocate(c,[unit(night_ok=None,draft_m=None,last_report_at=None),unit('truck','caminhao_alto',max_wading_depth_m=.9)])
        row=r['top3'][0]
        self.assertEqual(row['id'],'boat')
        self.assertTrue(row['confirmation_checklist'])
        self.assertIn('DEPTH_UNVERIFIED',[x['code'] for x in row['confirmation_checklist']])
        self.assertTrue(all(x['fact_ids'] and x['text_pt'] for x in row['confirmation_checklist']))
        self.assertEqual(r['ineligible'][0]['id'],'truck')
        self.assertIn('REPORT_DATE',[x['code'] for x in row['confirmation_checklist']])
        ranked=self.allocate(case(night=None),[unit('unconfirmed',night_ok=None),unit('confirmed')])
        self.assertEqual(ranked['top3'][0]['id'],'confirmed')

    def test_each_open_check_must_be_ticked_or_overridden_and_recorded(self):
        from tests.support import Scratch
        from app.engines.world_model.registry import Registry
        from app.missions.service import MissionService
        scratch=Scratch();self.addCleanup(scratch.cleanup)
        registry=Registry(scratch.path/'events.jsonl');c=case(depth_m=None,night=None);c['actions']=[]
        registry._append({'schema_version':1,'kind':'analysis','case':c,'case_id':'a','version':1,'provenance':'a'})
        service=MissionService(registry,[unit()]);row=service.assets('a',DAY)['top3'][0]
        request=dict(proposal_id=row['proposal_id'],expected_versions={'a':1},actor='test',caution_acknowledged=True)
        with self.assertRaises(ValueError): service.approve(request)
        for bad in ({}, {x['code']:False for x in row['confirmation_checklist']},
                    {x['code']:{'override_reason':' '} for x in row['confirmation_checklist']}):
            request['checklist_confirmations']=bad
            with self.assertRaises(ValueError): service.approve(request)
        request['checklist_confirmations']={x['code']:True for x in row['confirmation_checklist']}
        code=next(iter(request['checklist_confirmations']))
        request['checklist_confirmations'][code]={'override_reason':'Acesso conferido pela equipe no local.'}
        approved=service.approve(request)
        selection=approved['allocation_selection']
        self.assertEqual(selection['checklist_confirmations'],request['checklist_confirmations'])
        self.assertEqual(selection['confirmation_checklist'],row['confirmation_checklist'])
        self.assertEqual(registry.read('a')['actions'][-1]['mission']['allocation_selection'],selection)

    def test_rule_cache_invalidates_on_unit_case_and_day_changes(self):
        from unittest.mock import patch
        import app.fleet.allocation as module
        module._evaluate_cached.cache_clear()
        with patch.object(module,'evaluate',wraps=module.evaluate) as evaluator:
            self.allocate();count=evaluator.call_count
            self.allocate();self.assertEqual(evaluator.call_count,count)
            self.allocate(case(electricity='live'));self.assertGreater(evaluator.call_count,count)
            self.assertFalse(self.allocate(units=[unit(status='assigned')])['top3'])
            self.assertFalse(module.allocate(case(),[unit()], '2024-05-07')['top3'])

    def test_sample_registry_resolved_locations_have_candidates_offline(self):
        from app.config import ROOT
        from app.engines.world_model.registry import Registry
        from app.missions.service import MissionService
        from app.fleet.assets import demo_inventory
        from app.missions.planner import point
        from tests.support import Scratch
        scratch=Scratch();self.addCleanup(scratch.cleanup)
        registry=Registry(scratch.path/'events.jsonl')
        sample=ROOT/'runtime/events.jsonl'
        if sample.exists(): registry.path.write_bytes(sample.read_bytes())
        else:
            from app.pipeline import Pipeline
            request=json.loads((ROOT/'examples/input_01.json').read_text(encoding='utf-8'))
            Pipeline(registry,sample=True).run(request)
        service=MissionService(registry);service.allocation_inventory=demo_inventory()
        resolved=[c for c in registry.read() if point(c)]
        self.assertTrue(resolved)
        for c in resolved:
            with self.subTest(case_id=c['case_id']):
                result=service.assets(c['case_id'],'2024-05-06')
                self.assertTrue(result['top3'])
                self.assertTrue(all(r['eligible'] and not r['blocking_reasons'] for r in result['top3']))

    def test_eval_twenty_scenarios_and_no_unsafe_proposals(self):
        from eval.run_allocation import evaluate
        r=evaluate();self.assertEqual((r['correct'],r['scenarios'],r['unsafe_proposals']),(23,23,0))

    def test_api_assets_and_demo_resources(self):
        import threading
        import urllib.request
        from tests.support import Scratch
        from app.web.server import create_server
        from app.engines.world_model.registry import Registry
        scratch=Scratch();self.addCleanup(scratch.cleanup)
        registry=Registry(scratch.path/'events.jsonl');c=case();c['actions']=[]
        registry._append({'schema_version':1,'kind':'analysis','case':c,'case_id':'a','version':1,'provenance':'a'})
        server=create_server('127.0.0.1',0,sample=True,registry_path=registry.path)
        self.assertEqual(server.missions.inventory,[])
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        root='http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(root+'/api/cases/a/assets?date='+DAY,timeout=10) as response:
            r=json.load(response)
        self.assertTrue(r['human_approval_required']);self.assertEqual(r['case_version'],1)
        with urllib.request.urlopen(root+'/api/resources',timeout=10) as response: r=json.load(response)
        self.assertTrue(r['typed_resources']);self.assertTrue(all(u['synthetic'] for u in r['typed_resources']))
        with urllib.request.urlopen(root+'/v2/fleet.js',timeout=10) as response:
            self.assertIn(b'DeskFleet',response.read())


if __name__=='__main__': unittest.main()
