"""Offline insertion proposals. All spatial arithmetic belongs to the distance adapter."""
import copy
import math
from .planner import point, safety, fingerprint
from app.fleet.allocation import allocate
from app.fleet.assets import normalize


def priority(case):
    value=case.get('priority_class',(case.get('result') or {}).get('priority'))
    # The desk's numeric priority is a score, not a P1/P2 class.
    # Quote-backed life-safety needs form P1 when no explicit class exists.
    return 0 if value=='P1' or safety(case)<5 else 1 if value=='P2' else 2


def count(case):
    n=case.get('fields',{}).get('people',{}).get('value')
    return n if type(n) is int and n>0 else None


def travel(adapter,a,b,unit):
    if not a or not b: return None
    raw=adapter.for_unit(a,b,unit) if hasattr(adapter,'for_unit') else adapter(a,b)
    if not isinstance(raw,dict) or raw.get('reachable') is False: return None
    if any(type(raw.get(k)) not in (int,float) or not math.isfinite(raw[k]) or raw[k]<0
           for k in ('distance_m','eta_seconds')): return None
    return copy.deepcopy(raw)


def eligible(case,unit,day,adapter):
    if case.get('open_items') or not case.get('location_confirmed') or not point(case): return None
    if case.get('routing_flags',{}).get('injection'): return None
    # Only this mission's reservation is released for the rules evaluation.
    unit=dict(unit,status='available',available=True)
    result=allocate(case,[unit],day,distance_fn=adapter)
    row=next(iter(result['top3']),None)
    return (row,result['facts']) if row and not row['approval_holds'] else None


def arrivals(stops,origin,unit,adapter):
    elapsed=0;out={};legs=[]
    for stop in stops:
        leg=travel(adapter,origin,stop.get('point'),unit)
        if leg is None: return None
        elapsed+=leg['eta_seconds'];out[stop['case_id']]=elapsed;legs.append(leg);origin=stop['point']
    return elapsed,out,legs


def propose(plan,cases,unit,adapter,radius_km=1.0,limit=2):
    if type(radius_km) not in (int,float) or not math.isfinite(radius_km) or not 0<radius_km<=20:
        raise ValueError('Raio deve estar entre 0 e 20 km.')
    unit=normalize(unit);cap=unit['capacity_people'];pending=[copy.deepcopy(s) for s in plan['stops'] if not s.get('done')]
    answer={'mission_id':plan['mission_id'],'radius_km':radius_km,
        'radius_basis_pt':'Distância pelo adaptador até uma parada da rota (filtro conservador).',
        'human_approval_required':True,'auto_applied':False,'proposals':[],'excluded':[]}
    if plan.get('status')!='assigned' or len(plan['units'])!=1 or not cap or not pending or unit['status']=='out_of_service': return answer
    # Completed pickups may still be aboard: reserve them until unloading is documented.
    load=max(unit['current_load'],sum(s.get('people') or cap for s in plan['stops'] if s.get('done')))
    for s in pending: load+=s['people'] if type(s.get('people')) is int and s['people']>0 else cap
    answer.update(capacity=cap,reserved_people=load,spare_capacity=max(0,cap-load))
    origin=unit.get('current_location') or unit.get('base_location')
    answer['origin_basis_pt']='Última posição documentada, ou base; ETA estimada, confirmar posição da equipe.'
    baseline=arrivals(pending,origin,unit,adapter)
    if baseline is None or load>=cap: return answer
    route=list(pending);previous=baseline
    candidates=sorted((c for c in cases if c['case_id'] not in {s['case_id'] for s in plan['stops']}),key=lambda c:(priority(c),safety(c),c['case_id']))
    for _ in range(min(limit,2)):
        options=[]
        for c in candidates:
            n=count(c);reserve=n or cap
            if load+reserve>cap:
                answer['excluded'].append({'case_id':c['case_id'],'reserved_people':reserve,
                    'unknown_count':n is None,'reason':'Capacidade reservada integralmente para contagem desconhecida.' if n is None else 'Capacidade excedida.'})
                continue
            check=eligible(c,unit,plan['date'],adapter)
            if not check: continue
            near=[travel(adapter,s['point'],point(c),unit) for s in pending]
            if not any(t and t['distance_m']<=radius_km*1000 for t in near): continue
            stop={'case_id':c['case_id'],'expected_version':c['version'],'point':point(c),'people':n,'priority_rank':priority(c),
                'requirements':c.get('operational_needs',{}),'safety_rank':safety(c),'done':False}
            for index in range(len(route)+1):
                # A routine addition may never delay a planned life-safety/P1 stop.
                if any((priority(c),safety(c))>(s.get('priority_rank',0 if s.get('safety_rank',5)<5 else 2),s.get('safety_rank',5)) for s in route[index:]): continue
                changed=route[:index]+[stop]+route[index:];timing=arrivals(changed,origin,unit,adapter)
                if timing is None: continue
                delta=max(0,timing[0]-previous[0])
                options.append(((priority(c),safety(c),delta,c['case_id'],index),c,changed,timing,check,stop))
        if not options: break
        _,c,route,timing,check,stop=min(options,key=lambda x:x[0]);load+=count(c)
        row,facts=check
        proposal={'case_id':c['case_id'],'people':count(c),'reserved_people':load,
            'priority_class':'P1' if priority(c)==0 else 'P2',
            'added_minutes':round(max(0,timing[0]-previous[0])/60,3),
            'arrival_minutes':round(timing[1][c['case_id']]/60,3),
            'mission_delay_minutes':round(max(0,timing[0]-baseline[0])/60,3),
            'delays':{s['case_id']:round(max(0,timing[1][s['case_id']]-baseline[1][s['case_id']])/60,3) for s in pending},
            'stops':copy.deepcopy(route),'travel_facts':timing[2],'facts':facts,
            'confirmation_checklist':row['confirmation_checklist'],
            'requires_on_scene_confirmation':True,
            'on_scene_note_pt':'Confirmar explicitamente antes de afastar equipe em cena ou com pessoas a bordo.',
            'expected_versions':{**plan['expected_versions'],**{s['case_id']:s['expected_version'] for s in route if s['case_id'] not in plan['expected_versions']}},
            'unit_snapshot':unit,'mission_id':plan['mission_id'],'date':plan['date'],
            'radius_km':radius_km,'human_approval_required':True,'auto_applied':False}
        proposal['id']=fingerprint(proposal);answer['proposals'].append(proposal)
        candidates=[x for x in candidates if x['case_id']!=c['case_id']];previous=timing
    return answer
