"""Sourced fleet progress. Estimates never move a unit; late events replay by event time."""
import copy
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from app.decide import timestamp
from app.feedback import FeedbackExtractor
from app.derive_count import INJECTION
from app.redact import redact

LABELS = dict(unknown='Sem relato', available='Disponível', assigned='Designado', en_route='A caminho',
              on_scene='No local', returning='Retornando', unloading='Desembarcando', out_of_service='Fora de serviço')
MOVES = dict(unit_departed='en_route', unit_arrived='on_scene', rescued_n='on_scene',
             unit_returning='returning', unit_unloading='unloading', unit_available='available', unit_failed='out_of_service')


def clock():
    return datetime.now(timezone.utc).isoformat()


class UnitStatusService:
    def __init__(self, registry, inventory_fn, extractor=None, grace_min=20, idle_min=40):
        self.registry, self.inventory_fn = registry, inventory_fn
        self.extractor = extractor or FeedbackExtractor()
        if grace_min <= 0 or idle_min <= 0: raise ValueError('Intervalos devem ser positivos.')
        self.grace_min, self.idle_min = grace_min, idle_min
        self.landing_events = lambda: []

    def journal(self):
        with self.registry.locked():
            return self._journal()

    def _journal(self):
        return [json.loads(s) for s in self.registry.path.read_text(encoding='utf-8-sig').splitlines()] if self.registry.path.exists() else []

    def report(self, uid, request):
        if uid not in {u['id'] for u in self.inventory_fn()}: raise KeyError(uid)
        if not isinstance(request, dict): raise ValueError('Envie objeto JSON.')
        if request.get('unit_id', uid) != uid: raise ValueError('Unidade do relato difere da URL.')
        when, actor, source = request.get('received_at'), request.get('actor'), request.get('source', 'operator')
        timestamp(when)
        if not isinstance(actor, str) or not actor.strip() or len(actor)>120: raise ValueError('Identifique quem relatou.')
        if source not in ('crew', 'operator'): raise ValueError('Fonte deve ser crew ou operator.')
        text, button = request.get('text', ''), request.get('status')
        if not isinstance(text, str) or len(text)>12000: raise ValueError('Relato inválido.')
        if button is not None and (source != 'operator' or button not in LABELS or button in ('unknown','assigned')):
            raise ValueError('Botão de estado inválido; designação exige aprovação de missão.')
        if not text.strip() and button is None: raise ValueError('Informe relato ou botão.')
        text = redact(text)
        if INJECTION.search(text): raise ValueError('REVIEW_REQUIRED: instrução suspeita no relato.')
        report = self.extractor.extract(text) if text.strip() else {'outcomes':[], 'feedback_check':'operator_button'}
        mid = request.get('mission_id')
        with self.registry.locked():
            if mid:
                missions = [e for e in self._journal() if e.get('kind')=='approve_mission' and e.get('mission_id')==mid]
                if not missions or uid not in {u['id'] for u in missions[-1]['projections'][0]['mission']['units']}:
                    raise ValueError('Unidade não pertence à missão.')
                if timestamp(when)<timestamp(missions[-1].get('at', clock())): raise ValueError('Relato anterior à designação.')
            event = dict(schema_version=1, kind='unit_status', unit_id=uid, at=when, actor=redact(actor.strip()),
                         source=source, text=text, report=report, button=button, mission_id=mid)
            event['event_id'] = 'us-'+hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()[:16]
            if not any(e.get('event_id')==event['event_id'] for e in self._journal()): self.registry._append(event)
        return event

    @staticmethod
    def estimate(plan, unit, at):
        seconds = plan.get('eta_seconds')
        basis = plan.get('eta_basis_pt', 'ETA do plano (estimativa)')
        if seconds is None:
            seconds = unit.get('eta_seconds')
        if seconds is None:
            base = unit.get('base_location') or unit.get('base_point') or unit.get('base_position')
            target = (plan.get('stops') or [{}])[0].get('point')
            if not base or not target: return None
            from app.missions.planner import distance
            seconds = distance(base, target)/(10_000/3600)
            basis = 'linha reta; velocidade hipotética 10 km/h (estimativa; confirmar com equipe)'
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0: return None
        expected = (timestamp(at)+timedelta(seconds=seconds)).isoformat()
        return {'at':expected, 'basis_pt':basis, 'label_pt':f'esperado no local ~{timestamp(expected).strftime("%H:%M")} (estimativa)'}

    def view(self, now=None, _events=None):
        now = now or clock(); limit = timestamp(now)
        units = {u['id']: {'unit_id':u['id'], 'status':'unknown', 'status_at':None, 'source':None,
                 'source_event':None, 'last_report':None, 'mission_id':None, 'expected':None, 'case_ids':[]} for u in self.inventory_fn()}
        timeline = []
        for n,e in enumerate(self.landing_events()):
            if e.get('unit_id') and e.get('kind') in ('arrival','unloaded'):
                timeline.append((e['at'],n,e['unit_id'],'unloading',e['source'],f'landing:{e.get("event_id",n)}',
                    f"{e['kind']}: {e['landing_id']}",e.get('mission_id'),None,None))
        for n, e in enumerate(self.journal() if _events is None else _events):
            kind = e.get('kind')
            if kind=='approve_mission' and e.get('at'):
                plan = e['projections'][0]['mission']
                for u in plan['units']:
                    timeline.append((e['at'], n, u['id'], 'assigned', 'operator', e.get('mission_id'),
                        'Aprovação humana da missão', e.get('mission_id'), self.estimate(plan,u,e['at']), [s['case_id'] for s in plan['stops']]))
            elif kind=='unit_status':
                # Clause order is meaningful within a report; failure always holds the unit.
                moves = [MOVES[r['kind']] for r in sorted(e['report']['outcomes'], key=lambda r:e['text'].find(r['quote'])) if r['kind'] in MOVES]
                state = 'out_of_service' if 'out_of_service' in moves else e.get('button') or (moves[-1] if moves else None)
                timeline.append((e['at'],n,e['unit_id'],state,e['source'],e['event_id'],e['text'] or LABELS[state],e.get('mission_id'),None,None))
            elif kind=='field_feedback':
                c = e['projections'][0]; f = c['feedback'][-1]
                if f.get('source')!='crew' or f.get('injection'): continue
                # Case-level reports cannot choose one unit in a multi-unit mission.
                assigned = (c.get('mission') or {}).get('units',[])
                if len(assigned)!=1: continue
                moves = [MOVES[r['kind']] for r in sorted(f['outcomes'],key=lambda r:f.get('text','').find(r['quote'])) if r['kind'] in MOVES]
                state = 'out_of_service' if 'out_of_service' in moves else moves[-1] if moves else None
                timeline.append((f['received_at'],n,assigned[0]['id'],state,'crew',f'feedback:{n}',f.get('text',''),c.get('mission_id'),None,None))
        for at,n,uid,state,source,eid,text,mid,expected,cids in sorted(timeline,key=lambda r:(timestamp(r[0]),r[1])):
            if timestamp(at)>limit or uid not in units: continue
            row = units[uid]
            if state:
                # A repair/availability button is required to clear a breakdown.
                if row['status']=='out_of_service' and state!='available':
                    state=None
                else:
                    if state!=row['status']: row['status_since']=at
                    row.update(status=state,status_at=at,source=source,source_event=eid)
            row['last_report']={'at':at,'source':source,'text':text,'event_id':eid}
            if state=='assigned': row.update(mission_id=mid,expected=expected,case_ids=cids)
            elif mid: row['mission_id']=mid
        for row in units.values():
            row['label_pt']=LABELS[row['status']]
            if row['status']=='out_of_service': row['reroute_hint_pt']='Replanejar missão com outro meio; aprovação humana necessária.'
        return {'as_of':now,'units':list(units.values()),'grace_min':self.grace_min,'idle_min':self.idle_min}

    def findings(self, now):
        out=[]
        for row in self.view(now)['units']:
            last, expected = row['last_report'], row['expected']
            silent = row['status'] in ('assigned','en_route') and expected and timestamp(now)>max(timestamp(expected['at']),timestamp(last['at']))+timedelta(minutes=self.grace_min)
            idle = row['status']=='on_scene' and timestamp(now)>timestamp(row['status_since'])+timedelta(minutes=self.idle_min)
            if not silent and not idle: continue
            kind='unit_silent' if silent else 'unit_idle'
            text = f"{'meio sem notícia' if silent else 'meio parado'}: {row['unit_id']}; missão {row['mission_id'] or 'não informada'}; último relato {last['at']} ({last['source']}): {last['text']}. "
            text += f"Esperado {expected['at']} (estimativa: {expected['basis_pt']}); tolerância {self.grace_min} min." if silent else f"No local desde {row['status_since']}; limite {self.idle_min} min."
            fid=kind+':'+hashlib.sha1((row['unit_id']+str(row['source_event'])).encode()).hexdigest()[:8]
            out.append(dict(id=fid,kind=kind,case_ids=row['case_ids'],resource_ids=[row['unit_id']],mission_ids=[row['mission_id']] if row['mission_id'] else [],
                numbers={'grace_min':self.grace_min,'idle_min':self.idle_min},severity=90,allowed_actions=['acknowledge_unit'],default_action='acknowledge_unit',
                facts=[{'id':fid,'text_pt':text}],evidence=[copy.deepcopy(last),{'expected':expected,'mission_id':row['mission_id']}]))
        return out


def overlay_inventory(registry, units, locked=False):
    """Keep a reported breakdown/busy crew out of allocation, including atomic approval."""
    service=UnitStatusService(registry,lambda:units)
    rows={r['unit_id']:r for r in service.view(_events=service._journal() if locked else None)['units']}
    out=copy.deepcopy(units)
    for unit in out:
        row=rows[unit['id']]
        if row['status'] not in ('unknown','available'):
            unit.update(available=False,status='out_of_service' if row['status']=='out_of_service' else 'assigned')
    return out
