"""Human-only mission updates, revalidated under the journal lock."""
import copy
from app.engines.world_model.registry import Conflict
from app.fleet.assets import replay_inventory
from app.fleet.allocation import validate_confirmations
from app.redact import redact
from .chaining import propose, priority, eligible, travel
from .planner import eligible_cases, fingerprint
from .actions import reserved_units


def snapshot(service,day):
    from app.resources import inventory
    return inventory(service.registry,replay_inventory(service.allocation_inventory,day))


def chain(service,mid,radius_km=1.0,_cases=None,_units=None):
    plan=service.detail(mid,_cases)
    from app.geo.routing import FleetDistance
    adapter=getattr(service,'routing_distance',FleetDistance)(plan['date'])
    units=snapshot(service,plan['date']) if _units is None else _units
    unit=next((u for u in units if u['id']==plan['units'][0]['id']),None)
    if unit is None: raise Conflict('Unidade ausente do inventário atual.')
    cases=eligible_cases(service.registry.read() if _cases is None else _cases,plan['date'])
    result=propose(plan,cases,unit,adapter,radius_km)
    cache=getattr(service,'reroute_cache',{})
    for p in result['proposals']:
        # All inserted cases retain their own allocator confirmation checklist.
        checks=[]
        for stop in p['stops']:
            c=next((c for c in cases if c['case_id']==stop['case_id']),None)
            if c:
                checked=eligible(c,unit,plan['date'],adapter)
                if checked:
                    checks += [{**x,'code':c['case_id']+':'+x['code']} for x in checked[0]['confirmation_checklist']]
        p['confirmation_checklist']=checks;p['id']=fingerprint(p)
        cache[p['id']]=copy.deepcopy(p)
    service.reroute_cache=dict(list(cache.items())[-512:])
    return result


def reroutes(service,day):
    from app.geo.routing import FleetDistance
    from .planner import day_value
    day_value(day);cases=service.registry.read();occupied=reserved_units(cases)
    units=snapshot(service,day);adapter=getattr(service,'routing_distance',FleetDistance)(day)
    result=[]
    mids=sorted({c['mission_id'] for c in cases if c.get('status','').startswith('ASSIGNED:')})
    for mid in mids:
        if service.detail(mid)['date']!=day: continue
        for p in chain(service,mid)['proposals']:
            c=next(c for c in cases if c['case_id']==p['case_id'])
            if p['priority_class']!='P1' or p['id'] in getattr(service,'reroute_declined',set()): continue
            free=[]
            for u in units:
                if u['id'] in occupied or not u.get('available'): continue
                check=eligible(c,u,day,adapter)
                if check and u.get('capacity',0) and (c['fields']['people']['value'] or u['capacity'])<=u['capacity']-u.get('current_load',0):
                    leg=travel(adapter,u.get('base_location'),c.get('position'),u)
                    if leg: free.append({'unit_id':u['id'],'eta_minutes':round(leg['eta_seconds']/60,3),'travel':leg,'facts':check[1]})
            p=copy.deepcopy(p);p['next_free_minutes']=min(f['eta_minutes'] for f in free) if free else None
            k=str(p['next_free_minutes']) if free else 'indisponível'
            p['text_pt']=f"desviar {p['unit_snapshot']['id']} para {p['case_id']}: +{p['mission_delay_minutes']} min para a missão atual, chega em {p['arrival_minutes']} min vs próxima unidade livre em {k} min"
            p['number_sources']={'mission_delay_minutes':'travel_facts; baseline adapter legs',
                'arrival_minutes':'travel_facts; adapter ETA sum','next_free_minutes':'eligible free unit adapter ETA minimum'}
            p['free_unit_travel_facts']=free
            if p.get('planning_estimate_only') or any(f['travel'].get('planning_estimate_only') for f in free):
                from .chaining import UNPROVEN_WATER_PT
                p['text_pt']+=' — '+UNPROVEN_WATER_PT
            result.append(p)
    return {'date':day,'alerts':result,'human_approval_required':True,'auto_applied':False}


def decide(service,pid,action,request):
    if action=='decline':
        if pid not in getattr(service,'reroute_cache',{}): raise KeyError(pid)
        service.reroute_declined=getattr(service,'reroute_declined',set())|{pid}
        return {'id':pid,'status':'declined','auto_applied':False}
    actor=request.get('actor')
    if not isinstance(actor,str) or not actor.strip() or len(actor)>120: raise ValueError('Identifique o operador.')
    with service.registry.locked():
        cases,_=service.registry._read()
        if action=='undo':
            members=[c for c in cases.values() if c.get('mission',{}).get('last_update_id')==pid]
            if not members: raise Conflict('Atualização não é mais a versão atual.')
            expected=request.get('expected_versions')
            if expected!={c['case_id']:c['version'] for c in members}: raise Conflict('Versões alteradas.')
            before=members[0]['mission_update_before'];projections=[]
            if set(before)!={c['case_id'] for c in members} or any(c['version']!=before[c['case_id']]['version']+1 for c in members):
                raise Conflict('Retorno ou alteração posterior ao desvio; não é possível desfazer sem revisão.')
            for c in members:
                old=copy.deepcopy(before[c['case_id']]);old['version']=c['version']+1
                old['actions']=c['actions']+[{'action':'undo_mission_update','actor':redact(actor.strip()),'mission_id':c['mission_id'],'update_id':pid,'version':old['version']}]
                projections.append(old)
            service.registry._append({'schema_version':1,'kind':'mission_update','actor':redact(actor.strip()),'update_id':pid,'reverses':pid,'projections':projections})
            return {'status':'reverted','id':pid}
        cached=getattr(service,'reroute_cache',{}).get(pid)
        if not cached: raise Conflict('Proposta expirada.')
        from app.resources import read_unlocked
        stored=read_unlocked(service.registry);stored_ids={u['id'] for u in stored}
        units=stored+[u for u in replay_inventory(service.allocation_inventory,cached['date']) if u['id'] not in stored_ids]
        fresh=chain(service,cached['mission_id'],cached['radius_km'],list(cases.values()),units)
        p=next((p for p in fresh['proposals'] if p['id']==pid),None)
        if not p or request.get('expected_versions')!=p['expected_versions']: raise Conflict('Proposta alterada; revise versões, carga e regras.')
        if request.get('confirm_on_scene_departure') is not True: raise Conflict('Confirme explicitamente a saída da equipe em cena/com pessoas a bordo.')
        if request.get('caution_acknowledged') is not True: raise Conflict('Revise todas as cautelas.')
        validate_confirmations(p['confirmation_checklist'],request.get('checklist_confirmations',{}))
        plan=service.detail(p['mission_id'],list(cases.values()));before={cid:copy.deepcopy(cases[cid]) for cid in p['expected_versions']}
        plan['stops']=[s for s in plan['stops'] if s.get('done')]+copy.deepcopy(p['stops'])
        for index,s in enumerate(plan['stops'],1): s['order']=index
        from .planner import trip_loads
        loads=trip_loads(plan['stops'],plan['units'])
        plan.update(last_update_id=pid,people=sum(s['people'] for s in plan['stops']),trip_loads=loads,
                    trips=max((t['trip'] for t in loads),default=1),mission_update=p,
                    distance_m=round(sum(t['distance_m'] for t in p['travel_facts']),3),
                    distance_inputs=copy.deepcopy(p['travel_facts']),
                    distance_basis='Adaptador de deslocamento; posição documentada ou base; ETA estimada.')
        projections=[]
        for cid in p['expected_versions']:
            c=copy.deepcopy(cases[cid])
            if cid not in {s['case_id'] for s in service.detail(p['mission_id'],list(cases.values()))['stops']}:
                c['mission_before']={k:copy.deepcopy(c.get(k)) for k in ('status','approved_asset','caution_acknowledgement')}
            c.update(status='ASSIGNED:'+p['mission_id'],mission_id=p['mission_id'],mission=copy.deepcopy(plan),mission_update_before=before,version=c['version']+1)
            c['actions'].append({'action':'update_mission','mission_id':p['mission_id'],'update_id':pid,'version':c['version'],'actor':redact(actor.strip()),'on_scene_departure_confirmed':True,'checklist_confirmations':copy.deepcopy(request.get('checklist_confirmations',{}))})
            projections.append(c)
        service.registry._append({'schema_version':1,'kind':'mission_update','update_id':pid,'mission_id':p['mission_id'],'actor':redact(actor.strip()),'projections':projections})
        return service.detail(p['mission_id'],list(service.registry._read()[0].values()))
