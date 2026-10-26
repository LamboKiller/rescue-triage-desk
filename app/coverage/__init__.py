"""Deterministic demand coverage. Estimates never authorize dispatch."""
import copy
import hashlib
import json
import math
from collections import OrderedDict
from app.fleet.allocation import allocate, inputs_for
from app.fleet.assets import normalize, replay_inventory, RULE_TYPES
from app.missions.planner import day_value, point, safety


def build(cases, inventory, day, threshold_minutes=30, distance_fn=None):
    day_value(day)
    if type(threshold_minutes) not in (int, float) or not math.isfinite(threshold_minutes) or threshold_minutes <= 0:
        raise ValueError('Limiar deve ser positivo.')
    units=[normalize(u) for u in replay_inventory(inventory,day)
           if u.get('type') in RULE_TYPES or u.get('asset') in RULE_TYPES.values()]
    units=[u for u in units if u['available'] and u['status']=='available']
    cells={};unlocated=[]
    for c in sorted(cases,key=lambda c:c['case_id']):
        status=c.get('status','proposed');result=c.get('result',{})
        if status not in ('proposed','PARTIAL','human_approved'): continue
        if result.get('decision') not in ('SEND','SEND_CANDIDATE') and status!='human_approved': continue
        if any(c.get(k,'9999')[:10]>day for k in ('received_at','replay_time')): continue
        p=point(c)
        if not p:
            unlocated.append(c['case_id']);continue
        # Fixed local equal-distance grid, 1 km at RS latitude; no invented bairro boundaries.
        dx=1000/(111320*math.cos(math.radians(-30)));dy=1000/111320
        x=math.floor(p['lon']/dx);y=math.floor(p['lat']/dy);key=f'{x}:{y}'
        w,s=x*dx,y*dy;e,n=w+dx,s+dy
        cell=cells.setdefault(key,dict(id=key,label_pt='célula '+key,case_ids=[],people_known=0,
            people_unknown_cases=0,life_safety_count=0,p1_count=0,gap_case_ids=[],unknown_eta_case_ids=[],
            cases=[],geometry={'type':'Polygon','coordinates':[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}))
        life=safety(c)<5
        score=result.get('priority');p1=life or c.get('priority_class')=='P1' or score=='P1' or (type(score) in (int,float) and score>=30)
        cell['case_ids'].append(c['case_id']);cell['life_safety_count']+=life;cell['p1_count']+=p1
        people=inputs_for(c,day).get('people_count')
        if people is None or result.get('conflicting_counts'):
            cell['people_unknown_cases']+=1
        else: cell['people_known']+=people
        candidates=[]
        # Groups of at most three preserve every eligible row despite allocator top3 output.
        for offset in range(0,len(units),3):
            plan=allocate(c,units[offset:offset+3],day,distance_fn=distance_fn)
            for row in plan['top3']:
                eta=row['eta_seconds'];basis=row['distance_basis_pt']
                if eta is None and row['distance_m'] is not None:
                    eta=row['distance_m']/ (10000/3600)
                    basis='Linha reta; estimativa a 10 km/h assumidos, sem rota comprovada.'
                candidates.append(dict(unit_id=row['id'],eta_seconds=eta,basis_pt=basis,
                    fact_ids=row['fact_ids'],confirmation_required=bool(row['confirmation_checklist']),synthetic=row['synthetic']))
        known=[r for r in candidates if r['eta_seconds'] is not None]
        best=min(known,key=lambda r:(r['eta_seconds'],r['unit_id']),default=None)
        unknown=any(r['eta_seconds'] is None for r in candidates)
        gap=bool(p1 and (not candidates or best is not None and best['eta_seconds']>threshold_minutes*60 or best is None))
        if unknown: cell['unknown_eta_case_ids'].append(c['case_id'])
        if gap: cell['gap_case_ids'].append(c['case_id'])
        cell['cases'].append(dict(case_id=c['case_id'],best=best,eligible_unit_ids=[r['unit_id'] for r in candidates],gap=gap))
    suggestions=[]
    for cell in cells.values():
        cell['open_cases']=len(cell['case_ids']);cell['gap']=bool(cell['gap_case_ids'])
        cell['severity']='gap' if cell['gap'] else 'unknown' if cell['unknown_eta_case_ids'] else 'covered'
        bests=[r['best'] for r in cell['cases'] if r['best'] is not None]
        cell['best']=min(bests,key=lambda r:(r['eta_seconds'],r['unit_id']),default=None)
        if cell['gap']:
            affected=[r for r in cell['cases'] if r['gap']]
            timed=[r['best']['eta_seconds'] for r in affected if r['best']]
            # A near unit for one request must never hide an uncovered request in its cell.
            eta=f'~{math.ceil(max(timed)/60)} min (estimativa)' if timed else 'ETA desconhecido / sem unidade elegível'
            text=(f'Cobertura insuficiente em {cell["label_pt"]}: {cell["open_cases"]} pedidos '
                  f'({cell["p1_count"]} P1); {len(affected)} sem cobertura no limiar; meio mais próximo para esses pedidos: {eta}. '
                  'Sugestão: pedir reforço (Defesa Civil / cidade vizinha). Decisão humana; nada foi acionado.')
            suggestions.append(dict(cell_id=cell['id'],text_pt=text,case_ids=cell['case_ids'],
                gap_case_ids=cell['gap_case_ids'],fact_ids=['case:'+cid for cid in cell['case_ids']],human_approval_required=True))
    return dict(date=day,threshold_minutes=threshold_minutes,cells=list(cells.values()),suggestions=suggestions,
        unlocated_case_ids=unlocated,human_approval_required=True,
        note_pt='Cobertura estimada por pedido, sem reserva de capacidade; confirmar rota, disponibilidade e acesso. Pessoas a confirmar não são zero.',
        geojson={'type':'FeatureCollection','features':[dict(type='Feature',geometry=c['geometry'],properties={
            'id':c['id'],'severity':c['severity'],'label':f'{c["open_cases"]} pedidos · {c["severity"]} · estimativa'}) for c in cells.values()]})


class CoverageService:
    def __init__(self, fleet_service, threshold_minutes=30):
        self.distances=AsyncDistance();self.fleet=fleet_service;self.threshold=threshold_minutes;self.cache=OrderedDict();self.snapshot=None

    def view(self, day):
        day_value(day)
        from app.resources import read_unlocked
        from app.missions.actions import reserved_units
        registry=self.fleet.registry
        with registry.locked():
            stat=registry.path.stat() if registry.path.exists() else None
            version=(stat.st_mtime_ns,stat.st_size,stat.st_ctime_ns) if stat else None
            if self.snapshot is None or self.snapshot[0]!=version:
                cases=list(registry._read()[0].values());stored=read_unlocked(registry)
                from app.unit_status import UnitStatusService
                journal=UnitStatusService(registry,lambda:[])._journal()
                self.snapshot=(version,cases,stored,reserved_units(cases),journal)
            _,cases,stored,reserved,journal=self.snapshot
            ids={u['id'] for u in stored}
            units=copy.deepcopy(stored+[u for u in self.fleet.allocation_inventory if u['id'] not in ids])
        from app.unit_status import UnitStatusService
        statuses=UnitStatusService(registry,lambda:units).view(day+'T23:59:59-03:00',_events=journal)
        unavailable={r['unit_id']:r for r in statuses['units'] if r['status'] not in ('unknown','available')}
        for u in units:
            if u['id'] in unavailable: u.update(status='out_of_service',available=False)
            if u['id'] in reserved: u.update(status='assigned',available=False)
        inventory_version=hashlib.sha256(json.dumps(units,sort_keys=True).encode()).hexdigest()
        key=(version,inventory_version,day,self.threshold,self.distances.revision)
        if key not in self.cache:
            from types import SimpleNamespace
            distance=SimpleNamespace(for_unit=lambda base,target,unit:self.distances.for_unit(base,target,unit,day))
            self.cache[key]=build(cases,units,day,self.threshold,distance)
            if len(self.cache)>16: self.cache.popitem(last=False)
        return copy.deepcopy(self.cache[key])


class AsyncDistance:
    """Bounded local routing queue; pending/failure uses allocator's labelled fallback."""
    def __init__(self):
        import queue
        import threading
        self.queue=queue.Queue(maxsize=256);self.results=OrderedDict();self.pending=set()
        self.revision=0;self.lock=threading.Lock();self.worker=None

    def for_unit(self,base,target,unit,day):
        import threading
        key=json.dumps([day,base,target,unit],sort_keys=True)
        with self.lock:
            if key in self.results:return copy.deepcopy(self.results[key])
            if key not in self.pending and not self.queue.full():
                self.pending.add(key);self.queue.put((key,day,copy.deepcopy(base),copy.deepcopy(target),copy.deepcopy(unit)))
                if self.worker is None:
                    self.worker=threading.Thread(target=self._work,daemon=True);self.worker.start()
        return dict(reachable=False,review_pt=['Roteamento local pendente; ETA de cobertura em linha reta.'])

    def _work(self):
        from app.geo.routing import FleetDistance,router_ready
        while True:
            key,day,base,target,unit=self.queue.get()
            try:
                result=FleetDistance(day).for_unit(base,target,unit)
            except (OSError,ValueError,KeyError,TypeError):
                result={'reachable':False,'review_pt':['Rota local indispon?vel; confirmar acesso.']}
            with self.lock:
                self.pending.discard(key)
                # A loading graph is temporary. Do not freeze that fallback in the cache.
                if result.get('reachable') or router_ready():
                    self.results[key]=result
                    if len(self.results)>1024:self.results.popitem(last=False)
                self.revision+=1
            self.queue.task_done()
