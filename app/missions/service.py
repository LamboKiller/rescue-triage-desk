"""Proposal lifecycle. Browser submissions select server-computed, versioned plans."""
import copy
import threading
import time
from app.agents.needs import NeedsExtractor
from app.engines.world_model.registry import Conflict
from .actions import reserved_units
from .brief import explain
from .planner import propose, fingerprint, day_value


def replay_cases(cases,day):
    from app.geo.hazards import assess, STREET_POSITION
    from app.fleet import screen
    from .planner import point
    prepared=[]
    for c in cases:
        c=copy.deepcopy(c);p=point(c)
        original={r['asset']:r for r in c.get('fleet',[])}
        if p and (c.get('position') or {}).get('position_kind') in ('landmark',STREET_POSITION):
            c['hazards']=assess(p['lat'],p['lon'],day,(c.get('position') or {}).get('position_kind','unknown'))
        else: c['hazards']={}
        screen(c)
        for i,row in enumerate(c['fleet']):
            if original.get(row['asset'],{}).get('verdict')=='unsafe': c['fleet'][i]=original[row['asset']]
        prepared.append(c)
    return prepared


class MissionService:
    def __init__(self,registry,inventory=None,client=None,radius_m=600):
        self.registry=registry;self.inventory=copy.deepcopy(inventory or [])
        from app.fleet.assets import normalize
        self.inventory=[normalize(u) if isinstance(u,dict) and 'type' in u else u for u in self.inventory]
        self.allocation_inventory=self.inventory
        self.client=client;self.extractor=NeedsExtractor(client);self.radius_m=radius_m
        self.cache={};self.briefs={};self.lock=threading.Lock()
        self.allocation_briefs={}

    def assets(self,case_id,day):
        from app.resources import inventory
        from app.fleet.assets import normalize, RULE_TYPES
        from app.fleet.allocation import allocate, explain as explain_allocation, prepare_mission_case, allocation_plan_checks
        from .planner import eligible_cases, build_plan
        day_value(day)
        with self.lock:
            from app.fleet.snapshot import read as allocation_snapshot
            c,units=allocation_snapshot(self,case_id,day)
            prepared=eligible_cases([c],day,self.extractor,time.monotonic()+90)
            if prepared: c=prepared[0]
            result=allocate(c,units,day,distance_fn=self.routing_distance(day) if hasattr(self,'routing_distance') else None)
            key=fingerprint(result)
            if key not in self.allocation_briefs:
                self.allocation_briefs[key]=explain_allocation(result,self.client,time.monotonic()+90)
                if len(self.allocation_briefs)>128:
                    self.allocation_briefs={key:self.allocation_briefs[key]}
            result.update(copy.deepcopy(self.allocation_briefs[key]))
            for row in result['top3']:
                row['approval_blockers']=list(row['approval_holds'])
                if not prepared:
                    row['approval_blockers'].append('Caso não é candidato SEND disponível nesta data.')
                    continue
                u=next(u for u in units if u['id']==row['id'])
                plan=build_plan([prepare_mission_case(c,u,day)],day,[u],self.radius_m)
                allocation_plan_checks(plan,row)
                plan['allocation_selection']={'case_id':case_id,'unit_id':u['id'],'rank':row['rank'],'override_reason':None,
                    'confirmation_checklist':copy.deepcopy(row['confirmation_checklist']),'checklist_confirmations':{}}
                plan['proposal_id']=fingerprint(plan)
                row['approval_blockers']+=plan['blocking_reasons']
                row['proposal_id']=plan['proposal_id']
                row['expected_versions']={case_id:c['version']}
                self.cache[plan['proposal_id']]=copy.deepcopy(plan)
            if len(self.cache)>2048:
                keep={r.get('proposal_id') for r in result['top3']}
                self.cache={k:v for k,v in self.cache.items() if k in keep}
            return result

    def proposals(self,day):
        day_value(day)
        with self.lock:
            cases=self.registry.read();reserved=reserved_units(cases)
            from app.resources import inventory
            available=[u for u in inventory(self.registry,self.inventory) if u['id'] not in reserved]
            deadline=time.monotonic()+240
            plans=propose(replay_cases(cases,day),day,available,self.radius_m,self.extractor,deadline)
            for p in plans:
                p['replay_screened']=True;p['proposal_id']=fingerprint(p)
                pid=p['proposal_id']
                if pid not in self.briefs: self.briefs[pid]=explain(p,self.client,deadline)
                p.update(self.briefs[pid]);self.cache[pid]=copy.deepcopy(p)
            if len(self.cache)>2048:
                keep={p['proposal_id'] for p in plans};self.cache={k:v for k,v in self.cache.items() if k in keep}
                self.briefs={k:v for k,v in self.briefs.items() if k in keep}
            return {'date':day,'proposals':plans,'inventory_units':len(available),
                    'inventory_note_pt':'Capacidades somente do inventário documentado; valores ausentes exigem confirmação.',
                    'status_basis':'current human status; only current analyses/messages available by replay day'}

    def approve(self,request,case_id=None):
        if not isinstance(request,dict): raise ValueError('Envie um objeto JSON.')
        pid=request.get('proposal_id');plan=copy.deepcopy(self.cache.get(pid)) if isinstance(pid,str) else None
        if plan is None: raise Conflict('Proposta desconhecida ou expirada; gere e revise uma nova proposta.')
        if 'allocation_selection' in plan:
            from app.redact import redact
            selection=plan['allocation_selection']
            reason=request.get('override_reason')
            if selection['rank']>1 and (not isinstance(reason,str) or not reason.strip() or len(reason)>500):
                raise ValueError('Justifique a escolha fora da primeira posição.')
            from app.fleet.allocation import validate_confirmations
            confirmations=copy.deepcopy(request.get('checklist_confirmations',{}))
            validate_confirmations(selection.get('confirmation_checklist',[]),confirmations)
            for answer in confirmations.values():
                if isinstance(answer,dict): answer['override_reason']=redact(answer['override_reason'].strip())
            selection['checklist_confirmations']=confirmations
            selection['override_reason']=redact(reason.strip()) if isinstance(reason,str) else None
            plan['proposal_id']=fingerprint(plan)
        expected={s['case_id']:s['expected_version'] for s in plan['stops']}
        supplied=request.get('expected_versions')
        if not isinstance(supplied,dict) or supplied!=expected or any(type(v) is not int for v in supplied.values()):
            raise Conflict('Versões do grupo ausentes ou alteradas; revise a proposta.')
        cid=case_id or plan['stops'][0]['case_id']
        if cid not in expected: raise Conflict('Caso não pertence à proposta.')
        if case_id and request.get('expected_version')!=expected[cid]: raise Conflict('Versão do caso alterada.')
        self.registry.action(cid,'approve_mission',expected[cid],request.get('actor'),human=True,
            mission=plan,mission_inventory=__import__('app.resources',fromlist=['inventory']).inventory(self.registry,
                __import__('app.fleet.assets',fromlist=['replay_inventory']).replay_inventory(self.allocation_inventory,plan['date'])
                if 'allocation_selection' in plan else self.inventory),caution_acknowledged=request.get('caution_acknowledged',False))
        return self.detail(plan['proposal_id'])

    def cancel(self,mid,request,case_id=None):
        detail=self.detail(mid);versions=request.get('expected_versions')
        if not isinstance(versions,dict): raise ValueError('Informe expected_versions de todos os casos.')
        cid=case_id or next((s['case_id'] for s in detail['stops'] if not s.get('done')),detail['stops'][0]['case_id'])
        if cid not in versions: raise ValueError('Versão do caso ausente.')
        if case_id and request.get('expected_version')!=versions[cid]: raise Conflict('Versão do caso alterada.')
        self.registry.action(cid,'cancel_mission',versions[cid],request.get('actor'),human=True,
                             mission_id=mid,expected_versions=versions)
        return self.detail(mid)

    def feedback(self,mid,request,feedback_service):
        detail=self.detail(mid)
        cid=request.get('case_id')
        if detail['status']!='assigned' or cid not in {s['case_id'] for s in detail['stops']}:
            raise Conflict('Selecione uma parada da missao ativa.')
        return feedback_service.submit(cid,request,mid)

    def detail(self,mid,_cases=None):
        cases=self.registry.read() if _cases is None else _cases;events=[a for c in cases for a in c.get('actions',[])
            if a.get('mission_id')==mid and a.get('action')=='approve_mission']
        if not events:
            if mid in self.cache: return {**copy.deepcopy(self.cache[mid]),'mission_id':None,'status':'proposed'}
            raise KeyError(mid)
        current=next((c.get('mission') for c in cases if c.get('mission_id')==mid and c.get('mission')),None)
        plan=copy.deepcopy(current or events[0]['mission']);ids={s['case_id'] for s in plan['stops']}
        members=[c for c in cases if c['case_id'] in ids]
        cancelled=any(a.get('mission_id')==mid and a.get('action')=='cancel_mission' for c in members for a in c.get('actions',[]))
        done={c['case_id'] for c in members if any(a.get('action')=='field_feedback' and a.get('mission_id')==mid and a.get('stop_done') for a in c.get('actions',[]))}
        status='cancelled' if cancelled else 'done' if len(done)==len(ids) else 'assigned' if all(c.get('status')=='ASSIGNED:'+mid or c['case_id'] in done for c in members) else 'invalidated'
        for stop in plan['stops']: stop['done']=stop['case_id'] in done
        return {**plan,'mission_id':mid,'status':status,'expected_versions':{c['case_id']:c['version'] for c in members},
                'blocking_reasons':(['Caso alterado após atribuição; revisar o grupo com o operador.'] if status=='invalidated' else plan['blocking_reasons'])}
