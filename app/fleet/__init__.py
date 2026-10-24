"""Conservative fleet screening; never an authorization to dispatch."""
import json
import re
from functools import lru_cache
from app.config import ROOT
from app.agents.counts import folded
from .evaluator import evaluate, SEVERITY

LABELS = ['Carro particular','SUV / 4x4','Caminhão de alta capacidade de transposição','Caminhão de bombeiros',
          'Ambulância rodoviária','Veículo anfíbio','Trator','Barco de alumínio com motor','Bote inflável de resgate',
          'Bote rígido inflável','Canoa a remo','Moto aquática com prancha','Aerobarco','Helicóptero com guincho',
          'Helicóptero somente pouso','Drone de busca','Drone de carga','Voluntário a pé na água','Equipe de águas rápidas','Cavalo']

@lru_cache(maxsize=1)
def document():
    return json.loads((ROOT/'data/fleet/dispatch_rules.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def translations():
    return json.loads((ROOT/'data/fleet/reasons_pt.json').read_text(encoding='utf-8'))


def rule_input(case):
    fields=case.get('fields',{})
    def value(key):
        item=fields.get(key,{})
        return item.get('value') if isinstance(item,dict) else None
    text=re.sub(r'[^\w\s]',' ',folded(case.get('text','')))
    text=' '.join(text.split())
    c={'mission':'rescue','location_type':'unknown','assigned_assets':{}}
    for dest,src in [('people_count','people'),('children','children'),('elderly','elderly'),('pets','pets'),('disabled','disabled')]:
        v=value(src)
        if type(v) is int and v>=0 and (dest!='people_count' or v>0): c[dest]=v
    # Presence proves at least one; absent text never proves zero. Demographics overlap.
    for dest,pattern in [('infants',r'\bbebes?\b|\bde colo\b|\brecem[ -]nascid'),
                         ('wheelchair',r'cadeira de rodas|cadeirante'),
                         ('bedridden',r'acamad|nao anda|nao caminha')]:
        if re.search(pattern,text): c[dest]=1
    # The extraction schema's disabled field includes bedridden people. Require litter conservatively.
    if c.get('disabled',0)>0: c['bedridden']=max(c.get('bedridden',0),c['disabled'])
    if re.search(r'\btelhado\b|\blaje\b',text): c['location_type']='rooftop'
    elif re.search(r'\bandar\b|segundo piso',text): c['location_type']='building_upper_floor'
    elif ((case.get('landmark_check') or {}).get('matched') or {}).get('category'): c['location_type']='public_building'
    if 'people_count' in c and any(c.get(k,0)>c['people_count'] for k in ('children','infants','elderly','wheelchair','bedridden')):
        c['reported_people_count']=c.pop('people_count')
        c['count_conflict']=True
    h=case.get('hazards') or {}
    c['hazards']={'depth_m':h.get('depth_m'),'depth_confidence':'low' if h.get('depth_m') is not None else 'unknown',
        'hazards_current':None,'inside_flood_extent':h.get('in_flood_any'),'extent_date_matches':None,
        'nearby_road_closure':True if h.get('closures_nearby') else None,'route_closed':None,
        'pump_station_outage':True if any(p.get('status')=='Inoperante' for p in h.get('pumps_nearby',[])) else None,
        'post_outage_reassessment':None,'current':'unknown','debris':'unknown','electricity':'unknown',
        'overhead_clearance':None,'night':None,'duplicate_check_complete':None,
        'shelter_distance_m': min((p['distance_km']*1000 for p in h.get('nearest_shelters',[])),default=None)}
    return c


def screen(case):
    inputs=rule_input(case); raw=evaluate(document(),inputs); out=[]; pt=translations()
    for (asset,result),label in zip(raw['assets'].items(),LABELS):
        out.append({'asset':asset,'label_pt':label,'verdict':result['status'],
                    'reasons_pt':list(dict.fromkeys(pt[r] for r in result['matched_rules'])),
                    'rule_ids':result['matched_rules'],'source_ids':result['source_ids']})
    out.sort(key=lambda r:(SEVERITY[r['verdict']],len(r['rule_ids'])))
    case['fleet']=out
    case['fleet_summary']={'options':[{'asset':r['asset'],'label_pt':r['label_pt'],'verdict':r['verdict']} for r in out if r['verdict']!='unsafe'],
                           'unsafe_assets':[r['asset'] for r in out if r['verdict']=='unsafe'],
                           'human_approval_required':True,'depth_band':raw['depth_band'],
                           'brief_pt':'Opções para revisão humana; disponibilidade, equipe, rota e transferência exigem verificação.'}
    # A separate fact per asset binds veto explanations to the actual screened proposal.
    facts=list((case.get('hazards') or {}).get('facts',[]))
    case['hazard_facts']=facts
    for r in out:
        facts.append({'id':'fleet:'+r['asset'],'text_pt':r['label_pt']+' ('+r['asset']+'): '+r['verdict']+'. '+' '.join(r['reasons_pt']),
                      'source':'data/fleet/dispatch_rules.json#'+','.join(r['rule_ids'])})
    return case
