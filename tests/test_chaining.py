"""Chaining arithmetic and durable, reversible human approval regressions."""
import copy
import unittest
from pathlib import Path
from tests.support import Scratch
from eval.run_chaining import prepare, SyntheticAdapter, evaluate, DAY
from app.missions.chaining import propose, priority
from app.missions import reroutes
from app.missions.service import MissionService
from app.engines.world_model.registry import Registry, Conflict


class ChainingTests(unittest.TestCase):
    def test_twelve_offline_scenarios(self):
        r=evaluate();self.assertEqual(r['correct'],12)
        self.assertEqual((r['capacity_violations'],r['auto_applied_changes']),(0,0))

    def test_adapter_only_and_no_eta_no_proposal(self):
        p,cs,u=prepare({'cases':[{}]})
        result=propose(p,cs,u,lambda a,b:300)
        self.assertEqual(result['proposals'],[])

    def test_life_safety_precedes_routine_and_numeric_score_is_not_class(self):
        p,cs,u=prepare({'cases':[{'id':'routine'},{'id':'urgent'}]})
        cs[1]['operational_needs']['needs']=[{'tag':'medical_urgent','quote':'urgente'}]
        cs[1]['result']['priority']=50
        self.assertEqual(priority(cs[1]),0)
        r=propose(p,cs,u,SyntheticAdapter())
        self.assertEqual(r['proposals'][0]['case_id'],'urgent')

    def test_added_minutes_delays_and_determinism(self):
        p,cs,u=prepare({'cases':[{}]})
        a=propose(p,cs,u,SyntheticAdapter());b=propose(p,cs,u,SyntheticAdapter())
        self.assertEqual(a,b);r=a['proposals'][0]
        self.assertIn('home',r['delays']);self.assertGreaterEqual(r['arrival_minutes'],0)
        self.assertTrue(r['facts']);self.assertTrue(r['requires_on_scene_confirmation'])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=Scratch();self.addCleanup(self.tmp.cleanup)
        self.registry=Registry(Path(self.tmp.name)/'events.jsonl')
        plan,cs,u=prepare({'cases':[{'priority':'P1'}]})
        home=copy.deepcopy(cs[0]);home['message_id']='original';home['text']='Casa original aguardando.'
        home['fields']['people']['value']=2;home['priority_class']='P2';home['position']=plan['stops'][0]['point']
        home=self.registry.ingest(home);extra=self.registry.ingest(cs[0]);self.extra=extra['case_id'];self.home=home['case_id']
        plan['stops'][0].update(case_id=self.home,requirements={'needs':[],'needs_check':'deterministic_only'})
        plan.update(proposal_id='m',blocking_reasons=[],asset='irb',people=2,capacity=6,trips=1,asset_count=1)
        plan.pop('expected_versions');plan.pop('status');plan.pop('mission_id')
        home.update(status='ASSIGNED:m',mission_id='m',mission=plan,version=2,
                    mission_before={'status':'proposed','approved_asset':None,'caution_acknowledgement':None})
        home['actions'].append({'action':'approve_mission','mission_id':'m','mission':copy.deepcopy(plan),'version':2})
        with self.registry.locked():
            self.registry._append({'schema_version':1,'kind':'approve_mission','projections':[home]})
        u.update(status='available',available=True)
        self.service=MissionService(self.registry,[u]);self.service.routing_distance=SyntheticAdapter

    def proposal(self): return reroutes.chain(self.service,'m')['proposals'][0]
    def request(self,p):
        return {'actor':'test operator','expected_versions':p['expected_versions'],'caution_acknowledged':True,
                'confirm_on_scene_departure':True,'checklist_confirmations':{x['code']:True for x in p['confirmation_checklist']}}

    def test_reroute_numbers_free_unit_and_read_only_decline(self):
        free=copy.deepcopy(self.service.inventory[0]);free['id']='free'
        self.service.allocation_inventory.append(free)
        before=self.registry.path.read_bytes();r=reroutes.reroutes(self.service,DAY)['alerts'][0]
        self.assertIsNotNone(r['next_free_minutes']);self.assertIn('vs próxima unidade livre',r['text_pt'])
        self.assertTrue(r['number_sources']);self.assertEqual(before,self.registry.path.read_bytes())
        reroutes.decide(self.service,r['id'],'decline',{})
        self.assertFalse(reroutes.reroutes(self.service,DAY)['alerts'])
        self.assertEqual(before,self.registry.path.read_bytes())

    def test_requires_explicit_confirmation_and_no_auto_apply(self):
        p=self.proposal();request=self.request(p);request.pop('confirm_on_scene_departure')
        before=self.registry.path.read_bytes()
        with self.assertRaises(Conflict): reroutes.decide(self.service,p['id'],'approve',request)
        self.assertEqual(before,self.registry.path.read_bytes())

    def test_approval_reopen_and_undo_are_versioned(self):
        p=self.proposal();r=reroutes.decide(self.service,p['id'],'approve',self.request(p))
        self.assertEqual(r['status'],'assigned');self.assertEqual(len(r['stops']),2)
        self.assertEqual(self.registry.read(self.extra)['version'],2)
        reopened=MissionService(Registry(self.registry.path),self.service.inventory)
        self.assertEqual(reopened.detail('m')['last_update_id'],p['id'])
        reroutes.decide(reopened,p['id'],'undo',{'actor':'test','expected_versions':r['expected_versions']})
        self.assertEqual(self.registry.read(self.extra)['status'],'proposed')
        self.assertEqual(self.registry.read(self.extra)['version'],3)
        self.assertEqual(len(reopened.detail('m')['stops']),1)

    def test_stale_case_and_stale_unit_write_nothing(self):
        p=self.proposal();request=self.request(p)
        self.registry.action(self.extra,'confirm_location',1,'test',human=True)
        before=self.registry.path.read_bytes()
        with self.assertRaises(Conflict): reroutes.decide(self.service,p['id'],'approve',request)
        self.assertEqual(before,self.registry.path.read_bytes())
        p=self.proposal();request=self.request(p);self.service.allocation_inventory[0]['status']='out_of_service'
        with self.assertRaises(Conflict): reroutes.decide(self.service,p['id'],'approve',request)
        self.assertEqual(before,self.registry.path.read_bytes())

    def test_invalid_radius(self):
        for radius in (0,-1,21,float('nan')):
            with self.assertRaises(ValueError): reroutes.chain(self.service,'m',radius)


if __name__=='__main__': unittest.main()
