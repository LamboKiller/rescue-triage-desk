"""Author-written synthetic chaining scenarios; no provider or network access."""
import copy
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.missions.chaining import propose
from app.missions.planner import distance
from app.fleet import document, screen

DAY='2024-05-08'


class SyntheticAdapter:
    def __init__(self,day=DAY): self.day=day
    def for_unit(self,a,b,unit):
        metres=distance(a,b)
        return {'distance_m':metres,'eta_seconds':metres/2,'reachable':True,
                'basis_pt':'[SIMULADO] linha reta a 7,2 km/h; não é rota operacional'}


def prepare(item):
    u={'id':'boat','type':'bote_inflavel','capacity_people':6,'capacity_source':'[SIMULADO] manifesto',
       'draft_m':.2,'stretcher':True,'medical_crew':True,'night_ok':True,'pets_ok':True,
       'base_location':{'lat':-29.92,'lon':-51.18},'status':'assigned','available':False,
       'observed_date':DAY,'last_report_at':DAY+'T10:00:00-03:00','source':'[SIMULADO]',
       'synthetic':True,'current_load':item.get('onboard',0),'attestations':{k:True for k in document()['verification_fields']}}
    u.update(item.get('unit',{}))
    plan={'mission_id':'m','status':'assigned','date':DAY,'units':[u],
          'expected_versions':{'home':2},'stops':[{'case_id':'home','people':item.get('assigned',2),
          'expected_version':1,'point':{'lat':-29.92,'lon':-51.179},'safety_rank':5,'done':False}]}
    cases=[]
    for i,r in enumerate(item['cases']):
        c={'case_id':r.get('id',str(i)),'message_id':'neighbour-'+str(i),'version':1,
           'text':'Família aguarda embarcação.','received_at':DAY+'T11:00:00-03:00','replay_time':DAY+'T12:00:00-03:00',
           'status':'proposed','location_confirmed':True,'position':{'lat':-29.92,'lon':r.get('lon',-51.176)},
           'fields':{'people':{'value':r.get('people',1)}},
           'hazards':{'depth_m':r.get('depth',.8),'depth_band':'d_0_6_to_1_2','depth_observed_date':DAY,
               'depth_confidence':'high','hazards_current':True,'night':False,'inside_flood_extent':True,
               'current':'still','debris':'clear','electricity':'isolated','overhead_clearance':True,
               'duplicate_check_complete':True,'nearby_road_closure':False,'route_closed':False,'pump_station_outage':False},
           'priority_class':r.get('priority','P2'),'result':{'decision':'SEND_CANDIDATE','priority':10},
           'operational_needs':{'needs':[],'needs_check':'deterministic_only'}}
        if r.get('injection'): c['routing_flags']={'injection':True}
        screen(c);cases.append(c)
    return plan,cases,u


def evaluate():
    rows=[];capacity=auto=0
    for line in Path(__file__).with_name('chaining_set.jsonl').read_text(encoding='utf-8').splitlines():
        item=json.loads(line);p,cs,u=prepare(item);before=copy.deepcopy((p,cs,u))
        result=propose(p,cs,u,SyntheticAdapter(),item.get('radius_km',1))
        proposals=result['proposals'];ok=len(proposals)==item['expected']
        if item.get('first'): ok=ok and proposals[0]['case_id']==item['first']
        if item.get('unknown'): ok=ok and any(x['unknown_count'] and x['reserved_people']==6 for x in result['excluded'])
        for r in proposals:
            capacity+=int(r['reserved_people']>u['capacity_people']);auto+=int(r['auto_applied'])
            ok=ok and r['added_minutes']>=0 and r['arrival_minutes']>=0 and bool(r['travel_facts'])
        ok=ok and (p,cs,u)==before
        rows.append({'id':item['id'],'pass':ok,'proposals':len(proposals)})
    return {'scenarios':len(rows),'correct':sum(r['pass'] for r in rows),'capacity_violations':capacity,
            'auto_applied_changes':auto,'synthetic':True,'results':rows}


if __name__=='__main__':
    result=evaluate();print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['correct']==result['scenarios'] and not result['capacity_violations'] and not result['auto_applied_changes'] else 1)
