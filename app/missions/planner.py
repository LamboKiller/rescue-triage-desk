"""Deterministic radius, resource, capacity and stop-order planning."""
import copy
import hashlib
import json
import math
from datetime import date
from app.agents.needs import NeedsExtractor
from app.fleet import document, rule_input
from app.fleet.evaluator import evaluate

LIFE = ('structural_risk','medical_urgent','water_rising','infant','stretcher_or_bedridden')
PASSENGER_ROLES = {'passenger_transport','conditional_passenger_transport',
                   'medical_transport',
                   'technical_and_medical_extraction','passenger_transport_at_verified_landing_site'}


def day_value(day):
    if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:
        raise ValueError('Informe a data ISO YYYY-MM-DD.')
    return day


def distance(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(a['lat'],a['lon'],b['lat'],b['lon']))
    x=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742000*math.asin(min(1,math.sqrt(x)))


def point(case):
    p=case.get('position') or {}
    if all(type(p.get(k)) in (int,float) and math.isfinite(p[k]) for k in ('lat','lon')) and -90<=p['lat']<=90 and -180<=p['lon']<=180:
        return {k:p[k] for k in ('lat','lon')}
    return None


def tags(case):
    return {n['tag'] for n in case.get('operational_needs',{}).get('needs',[])}


def safety(case):
    return min((LIFE.index(t) for t in tags(case) if t in LIFE),default=len(LIFE))


def ordered(cases):
    remaining=list(cases);out=[]
    while remaining:
        best=min(safety(c) for c in remaining)
        pool=[c for c in remaining if safety(c)==best]
        nxt=min(pool,key=lambda c:(distance(point(out[-1]),point(c)) if out and point(out[-1]) and point(c) else 0,c['case_id']))
        out.append(nxt);remaining.remove(nxt)
    return out


def eligible_cases(cases,day,extractor=None,deadline=None):
    day_value(day);out=[];extractor=extractor or NeedsExtractor()
    for current in cases:
        if current.get('status','proposed') not in ('proposed','PARTIAL','human_approved'): continue
        # A historical proposal cannot approve a later current message version.
        if any(current.get(k,'9999')[:10]>day for k in ('received_at','replay_time')): continue
        case=copy.deepcopy(current)
        if case.get('result',{}).get('decision') not in ('SEND','SEND_CANDIDATE'): continue
        case['operational_needs']=extractor.extract(case,deadline)
        out.append(case)
    return out


def inventory_units(inventory,day,asset=None):
    if not isinstance(inventory,list): raise ValueError('Inventário deve ser uma lista de recursos.')
    ids=[u.get('id') for u in inventory if isinstance(u,dict)]
    if len(ids)!=len(inventory) or any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Inventário exige identificadores únicos.')
    return [u for u in inventory if (asset is None or u.get('asset')==asset) and u.get('available') is True
            and isinstance(u.get('source'),str) and u['source'].strip()
            and isinstance(u.get('observed_date'),str) and u['observed_date']<=day
            and day_value(u['observed_date'])]


def known_capacity(unit):
    n=unit.get('capacity')
    return n if type(n) is int and n>0 and unit.get('capacity_basis')=='rescue_passengers_after_crew_and_equipment' else None


def allows(case,unit,day=None):
    if unit.get('type'):
        from app.fleet.allocation import allocate
        if not allocate(case,[unit],day or case['replay_time'][:10])['top3']: return False
    asset=unit.get('asset');doc=document()
    if asset not in doc['assets'] or doc['assets'][asset]['role'] not in PASSENGER_ROLES: return False
    rows={r['asset']:r for r in case.get('fleet',[])}
    if asset not in rows or rows[asset]['verdict']=='unsafe': return False
    band=(case.get('hazards') or {}).get('depth_band','unknown')
    if doc['depth_table'].get(asset,{}).get(band,'caution')=='unsafe': return False
    if asset in case.get('hazard_blocks',[]): return False
    for objection in (case.get('hazard_review') if isinstance(case.get('hazard_review'),dict) else {}).get('objections',[]):
        if objection.get('severity')=='block' and ('fleet:'+asset in objection.get('fact_ids',[]) or not any(i.startswith('fleet:') for i in objection.get('fact_ids',[]))):
            return False
    need=tags(case)
    if need & {'wheelchair','stretcher_or_bedridden'} and unit.get('attestations',{}).get('stretcher_capable') is not True: return False
    inputs=rule_input(case)
    for tag,key in [('wheelchair','wheelchair'),('stretcher_or_bedridden','bedridden'),('infant','infants'),('animals','pets')]:
        if tag in need: inputs[key]=max(inputs.get(key,0),1)
    inputs['assigned_assets']={asset:unit.get('attestations',{})}
    return evaluate(doc,inputs)['assets'][asset]['status']!='unsafe'


def choices(cases,inventory,day):
    units=inventory_units(inventory,day)
    usable={}
    for u in units:
        if all(allows(c,u,day) for c in cases): usable.setdefault(u['asset'],[]).append(u)
    return usable


def trip_loads(stops,units):
    if not units or any(known_capacity(u) is None for u in units) or any(type(s['people']) is not int or s['people']<1 for s in stops): return []
    remaining=[[s['case_id'],s['people']] for s in stops];out=[];trip=1
    while remaining:
        for unit in units:
            seats=known_capacity(unit);loads=[]
            while seats and remaining:
                cid,n=remaining[0];take=min(seats,n);loads.append({'case_id':cid,'people':take})
                seats-=take;remaining[0][1]-=take
                if remaining[0][1]==0: remaining.pop(0)
            if loads: out.append({'trip':trip,'unit_id':unit['id'],'capacity':known_capacity(unit),
                                  'people':sum(x['people'] for x in loads),'loads':loads})
        trip+=1
    return out


def build_plan(cases,day,inventory,radius_m):
    cases=ordered(cases);options=choices(cases,inventory,day)
    # Known capacity beats unverified capacity; asset id is a stable tie breaker.
    asset=min(options,key=lambda a:(not any(known_capacity(u) for u in options[a]),a),default=None)
    counts=[c.get('fields',{}).get('people',{}).get('value') for c in cases]
    people=sum(counts) if all(type(n) is int and n>0 for n in counts) else None
    pool=sorted(options.get(asset,[]),key=lambda u:(-(known_capacity(u) or 0),u['id']))
    known=[u for u in pool if known_capacity(u) is not None]
    units=[];seats=0
    for unit in known:
        units.append(unit);seats+=known_capacity(unit)
        if people is None or seats>=people: break
    if not units and pool: units=pool[:1]
    capacity=sum(known_capacity(u) for u in units) if units and all(known_capacity(u) is not None for u in units) else None
    stops=[];total_distance=0;block=[]
    for i,c in enumerate(cases):
        p=point(c);prev=point(cases[i-1]) if i else p
        leg=round(distance(prev,p),3) if p and prev else None
        if leg is not None: total_distance+=leg
        stops.append({'order':i+1,'case_id':c['case_id'],'expected_version':c['version'],
                      'point':p,'people':counts[i],'requirements':c['operational_needs'],
                      'access':copy.deepcopy({k:v for k,v in (c.get('hazards') or {}).items() if k.startswith('depth_')}),
                      'fleet_checks':[copy.deepcopy(r) for r in c.get('fleet',[]) if r['asset']==asset],
                      'safety_rank':safety(c),'distance_from_previous_m':leg})
        if p is None: block.append('Confirmar ponto do caso '+c['case_id']+'.')
        if not c.get('location_confirmed'): block.append('Confirmar localização do caso '+c['case_id']+'.')
        if (c.get('hazards') or {}).get('depth_band','unknown')=='unknown': block.append('Confirmar profundidade e acesso do caso '+c['case_id']+'.')
        if (c.get('hazards') or {}).get('depth_observed_date','')>day: block.append('Observação de profundidade posterior à data do plano.')
        if c.get('routing_flags',{}).get('injection') or c.get('result',{}).get('conflicting_counts') or c.get('open_items'):
            block.append('Revisão humana necessária: instruções suspeitas ou dados em conflito no caso '+c['case_id']+'.')
        if any(c.get(k,'9999')[:10]>day for k in ('received_at','replay_time')): block.append('Mensagem posterior à data do plano.')
    if not units: block.append('Informar inventário datado e recurso permitido pelas regras para todos os casos.')
    if capacity is None: block.append('Confirmar capacidade de passageiros após equipe e equipamento; não há capacidade documentada.')
    if people is None: block.append('Confirmar contagem de pessoas; há contagem ausente ou inválida.')
    trips=(people+capacity-1)//capacity if people is not None and capacity else None
    pairs=[{'a':a['case_id'],'b':b['case_id'],'distance_m':round(distance(point(a),point(b)),3)} for i,a in enumerate(cases) for b in cases[i+1:] if point(a) and point(b)]
    if any(p['distance_m']>radius_m for p in pairs): block.append('Casos excedem o raio de agrupamento.')
    plan={'date':day,'radius_m':radius_m,'stops':stops,'asset':asset,'asset_count':len(units) if units else None,
          'units':copy.deepcopy(units),'people':people,'capacity':capacity,'trips':trips,
          'trip_loads':trip_loads(stops,units),'distance_m':round(total_distance,3),
          'distance_basis':'haversine; stop-to-stop straight lines; no launch or destination assumed',
          'distance_inputs':pairs,'blocking_reasons':list(dict.fromkeys(block)),
          'why_group_pt':['Proximidade verificada entre todos os pontos do grupo.' if len(cases)>1 else 'Pedido individual; sem agrupamento com outro incidente.',
                          'Mesmo tipo de recurso permitido para todos os acessos; vetos preservados.' if asset else 'Compatibilidade e disponibilidade do recurso aguardam confirmação.',
                          'Prioridade de risco de vida, seguida de vizinho mais próximo; contagens não deduplicadas.'],
          'human_approval_required':True,'synthetic':any(c.get('synthetic') for c in cases) or any(u.get('synthetic') for u in units)}
    plan['proposal_id']=fingerprint(plan)
    return plan


def fingerprint(plan):
    content={k:v for k,v in plan.items() if k not in ('proposal_id','crew_brief_pt','brief_check','brief_calls','brief_fallback_reason','brief_validator_rejections')}
    return hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()[:24]


def propose(cases,day,inventory,radius_m=600,extractor=None,deadline=None):
    if type(radius_m) not in (int,float) or not math.isfinite(radius_m) or radius_m<=0: raise ValueError('Raio deve ser positivo e finito.')
    if len({c['case_id'] for c in cases})!=len(cases): raise ValueError('Cada caso deve aparecer exatamente uma vez.')
    eligible=eligible_cases(cases,day,extractor,deadline);remaining=ordered(eligible);out=[]
    while remaining:
        group=[remaining.pop(0)]
        for c in list(remaining):
            if point(c) is None or any(point(g) is None or distance(point(c),point(g))>radius_m for g in group): continue
            if (c.get('hazards') or {}).get('depth_band','unknown')=='unknown' or any((g.get('hazards') or {}).get('depth_band','unknown')=='unknown' for g in group): continue
            opts=choices(group+[c],inventory,day)
            if not opts: continue
            known=[sum(known_capacity(u) or 0 for u in units) for units in opts.values() if all(known_capacity(u) is not None for u in units)]
            counts=[g.get('fields',{}).get('people',{}).get('value') for g in group+[c]]
            if not all(type(n) is int and n>0 for n in counts): continue
            if known and sum(counts)>max(known): continue
            group.append(c);remaining.remove(c)
        out.append(build_plan(group,day,inventory,radius_m))
    return out


def check_plan(plan,cases,inventory):
    """Rebuild from authoritative cases/inventory, not numbers supplied by a browser."""
    try:
        if plan.get('replay_screened'):
            from .service import replay_cases
            cases=replay_cases(cases,plan['date'])
        ids=[s['case_id'] for s in plan['stops']]
        if not ids or len(ids)!=len(set(ids)): return ['Cada caso deve aparecer exatamente uma vez.']
        if plan.get('capacity') is not None and plan.get('people') is not None:
            if any(type(plan.get(k)) is not int or plan[k]<1 for k in ('capacity','people','trips')):
                return ['Pessoas, capacidade e viagens devem ser inteiros positivos.']
            if plan['people']>plan['capacity']*plan['trips']: return ['Pessoas excedem capacidade multiplicada pelas viagens.']
            loads=plan.get('trip_loads',[])
            if any(t['people']>t['capacity'] or sum(x['people'] for x in t['loads'])!=t['people'] for t in loads):
                return ['Carga de uma viagem excede capacidade ou diverge das paradas.']
            if sum(t['people'] for t in loads)!=plan['people']: return ['Cargas das viagens não cobrem todas as pessoas.']
        byid={c['case_id']:c for c in cases}
        if any(i not in byid for i in ids): return ['Caso ausente do registro.']
        selected=eligible_cases([byid[i] for i in ids],plan['date'])
        if len(selected)!=len(ids): return ['Caso não é mais candidato SEND disponível nesta data.']
        # Validated model needs stay evidence-bearing; deterministic needs remain a floor.
        from app.agents.needs import validate, texts
        for c in selected:
            supplied=next(s['requirements'] for s in plan['stops'] if s['case_id']==c['case_id'])
            validated=validate(supplied,texts(c))
            if not tags(c)<=set(n['tag'] for n in validated['needs']): return ['Necessidade conhecida foi removida do plano.']
            c['operational_needs']=copy.deepcopy(supplied)
        if 'allocation_selection' in plan:
            from app.fleet.allocation import selected_inventory
            inventory=selected_inventory(plan,selected,inventory)
        fresh=build_plan(selected,plan['date'],inventory,plan['radius_m'])
        if 'allocation_selection' in plan:
            from app.fleet.allocation import allocate, allocation_plan_checks
            row=next(r for r in allocate(selected[0],inventory,plan['date'])['top3'] if r['id']==plan['allocation_selection']['unit_id'])
            allocation_plan_checks(fresh,row)
        reasons=list(fresh['blocking_reasons'])
        labels={'stops':'paradas, requisitos ou versões','asset':'tipo de recurso','asset_count':'quantidade de recursos',
                'units':'inventário','people':'contagem de pessoas','capacity':'capacidade','trips':'quantidade de viagens',
                'trip_loads':'cargas por viagem','distance_m':'distância entre paradas','distance_inputs':'pontos e distâncias'}
        for key,label in labels.items():
            if fresh[key]!=plan.get(key): reasons.append('Plano alterado ou desatualizado: '+label+'.')
        if plan.get('proposal_id')!=fingerprint(plan): reasons.append('Identificador do plano não corresponde aos dados.')
        return list(dict.fromkeys(reasons))
    except (KeyError,TypeError,ValueError,IndexError):
        return ['Plano incompleto ou inválido; gerar nova proposta.']
