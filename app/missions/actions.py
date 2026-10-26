"""Atomic mission projections, called exclusively inside Registry.action's lock."""
import copy
from app.engines.world_model.registry import Conflict
from app.redact import redact
from .planner import check_plan


def reserved_units(cases,exclude=None):
    return {u['id'] for c in cases if c.get('status','').startswith('ASSIGNED:')
            and c.get('mission_id')!=exclude for u in (c.get('mission') or {}).get('units',[])}


def apply(registry,cases,case,action,actor,plan,inventory,mission_id,versions,caution,event_at=None):
    actor=redact(actor.strip())
    from app.decide import timestamp
    from app.unit_status import clock
    at=event_at or clock()
    timestamp(at)
    if event_at and timestamp(at)<timestamp(case['received_at']):
        raise ValueError('Ação anterior ao pedido; confira o relógio do replay.')
    if action=='approve_mission':
        if not isinstance(plan,dict) or not isinstance(inventory,list):
            raise ValueError('Informe proposta calculada e inventário documentado.')
        from app.resources import read_unlocked
        stored=read_unlocked(registry);ids_stored={u['id'] for u in stored}
        inventory=stored+[u for u in inventory if u['id'] not in ids_stored]
        from app.unit_status import overlay_inventory
        inventory=overlay_inventory(registry,inventory,locked=True)
        reasons=check_plan(plan,list(cases.values()),inventory)
        if reasons: raise Conflict(' '.join(reasons))
        ids=[s['case_id'] for s in plan['stops']]
        if case['case_id'] not in ids: raise Conflict('Caso não pertence à proposta.')
        if any(cases[s['case_id']]['version']!=s['expected_version'] for s in plan['stops']):
            raise Conflict('Versão de um caso alterada; gerar nova proposta.')
        occupied=reserved_units(cases.values())
        if any(u['id'] in occupied for u in plan['units']): raise Conflict('Recurso já reservado por outra missão.')
        if caution is not True: raise Conflict('Reconheça as cautelas e requisitos da missão antes de aprovar.')
        mission_id=plan['proposal_id']
        if any(a.get('mission_id')==mission_id and a.get('action')=='approve_mission' for c in cases.values() for a in c.get('actions',[])):
            raise Conflict('Proposta já utilizada; gerar uma nova proposta.')
        projections=[]
        for cid in ids:
            c=copy.deepcopy(cases[cid]);before={k:copy.deepcopy(c.get(k)) for k in ('status','approved_asset','caution_acknowledgement')}
            c.update(status='ASSIGNED:'+mission_id,mission_id=mission_id,mission=copy.deepcopy(plan),
                     mission_before=before,mission_stop_done=False,version=c['version']+1,approved_asset=plan['asset'],
                     caution_acknowledgement={'asset':plan['asset'],'acknowledged':True,'actor':actor,'mission_id':mission_id})
            c['actions'].append({'action':action,'actor':actor,'version':c['version'],
                                'mission_id':mission_id,'mission':copy.deepcopy(plan),'cautions_acknowledged':True,'at':at})
            projections.append(c)
    else:
        if not isinstance(mission_id,str) or case.get('status')!='ASSIGNED:'+mission_id:
            raise Conflict('Caso sem esta missão ativa.')
        plan=case['mission'];ids=[s['case_id'] for s in plan['stops']]
        if not isinstance(versions,dict) or set(versions)!=set(ids): raise ValueError('Informe expected_versions de todos os casos da missão.')
        for cid in ids:
            c=cases.get(cid)
            if not c or (c.get('status')!='ASSIGNED:'+mission_id and not c.get('mission_stop_done')) or type(versions[cid]) is not int or c['version']!=versions[cid]:
                raise Conflict('Caso da missão alterado; revise todas as versões antes de cancelar.')
        projections=[]
        for cid in ids:
            if any(a.get('action')=='field_feedback' and a.get('mission_id')==mission_id and a.get('stop_done') for a in cases[cid].get('actions',[])):
                continue
            c=copy.deepcopy(cases[cid])
            if not c.get('mission_stop_done'): c.update(c['mission_before'])
            c['version']+=1
            for k in ('mission_id','mission','mission_before'): c.pop(k,None)
            c['actions'].append({'action':action,'actor':actor,'version':c['version'],'mission_id':mission_id,'at':at})
            projections.append(c)
    registry._append({'schema_version':1,'kind':action,'at':at,'case_id':case['case_id'],
                      'actor':actor,'mission_id':mission_id,'projections':projections})
    return copy.deepcopy(registry._read()[0][case['case_id']])
