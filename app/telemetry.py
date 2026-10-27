"""Independent append-only GPS journal. Never writes crew reports or mission state.

OsmAnd speed is knots; internal speed is m/s. Uncertain fixes are retained for
audit only. Histories and derived counters are partitioned by unit AND source.
"""
import copy
import hashlib
import json
import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

FRESH_SECONDS = 600
SUPPORT_GAP_SECONDS = 120
TRACKING_ACCURACY_M = 30
ARRIVAL_RADIUS_M = 60


def tracking_route(mission):
    if mission.get('tracking_eligible') is False: return False
    return all(s.get('tracking_eligible') is not False and
               (s.get('mode') != 'water' or s.get('grid_verified') is True and s.get('fallback') is False)
               for s in mission.get('segments', []))


def arrival_pair(fixes, target):
    pair = fixes[-2:]
    return (len(pair) == 2 and 0 < pair[1]['timestamp'] - pair[0]['timestamp'] <= SUPPORT_GAP_SECONDS
            and all(f['accuracy'] <= TRACKING_ACCURACY_M and
                    metres([f['lon'], f['lat']], target) + f['accuracy'] <= ARRIVAL_RADIUS_M for f in pair))


def metres(a, b):
    r=math.pi/180
    v=math.sin((a[1]-b[1])*r/2)**2+math.cos(a[1]*r)*math.cos(b[1]*r)*math.sin((a[0]-b[0])*r/2)**2
    return 12742000*math.asin(min(1,math.sqrt(v)))


def epoch(value):
    try: result=float(value)
    except (ValueError,TypeError):
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None: raise ValueError('Horário sem fuso.')
        result=dt.timestamp()
    if not math.isfinite(result): raise ValueError('Horário inválido.')
    return result


def project(p, line):
    """Nearest segment, perpendicular distance, chainage and total (metres)."""
    best=(float('inf'),0); total=0
    for a,b in zip(line,line[1:]):
        scale=111320*math.cos(p[1]*math.pi/180)
        x,y=(b[0]-a[0])*scale,(b[1]-a[1])*111320
        px,py=(p[0]-a[0])*scale,(p[1]-a[1])*111320
        t=max(0,min(1,(px*x+py*y)/(x*x+y*y))) if x*x+y*y else 0
        length=metres(a,b); d=math.hypot(px-t*x,py-t*y)
        if d<best[0]: best=(d,total+t*length)
        total+=length
    return best[0],best[1],total


def mission_project(p,mission):
    """Sum only planned legs: grid shore/snap gaps are never invented connectors."""
    segments=mission.get('segments')
    if not segments: return project(p,mission.get('polyline',[]))
    best=(float('inf'),0); total=0
    for segment in segments:
        off,along,length=project(p,segment['polyline'])
        if off<best[0]: best=(off,total+along)
        total+=length
    return best[0],best[1],total


class Telemetry:
    def __init__(self,path,inventory_fn,missions_fn,clock=time.time,sample=False):
        self.path=Path(path); self.inventory_fn=inventory_fn; self.missions_fn=missions_fn
        self.clock=clock; self.sample=sample; self.lock=threading.RLock()
        self.bindings={}; self.pending={}; self.last={}; self.history=defaultdict(lambda:deque(maxlen=120))
        for event in self.events(): self._apply(event)

    def events(self):
        if not self.path.exists(): return []
        with self.path.open(encoding='utf-8') as f:
            for line in f:
                if line.strip(): yield json.loads(line)

    def _apply(self,e):
        if e['kind']=='binding':
            self.bindings[e['device']]=e['unit_id']; self.pending.pop(e['device'],None)
        elif e['kind']=='fix':
            self.last[(e['device'],e['source'])]=e['timestamp']
            if not e.get('unit_id'): self.pending[e['device']]=e
            elif e['confidence']=='normal': self.history[(e['unit_id'],e['source'])].append(e)

    def _append(self,e):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(e,ensure_ascii=False,separators=(',',':'))+'\n')
        self._apply(e)

    def bind(self,device,unit_id,actor):
        if not isinstance(device,str) or not device.strip() or len(device)>120: raise ValueError('Dispositivo inválido.')
        if unit_id not in self.inventory_fn(): raise ValueError('Unidade desconhecida.')
        if not isinstance(actor,str) or not actor.strip() or len(actor)>120: raise ValueError('Identifique o operador.')
        with self.lock:
            if device in self.bindings and self.bindings[device]!=unit_id: raise ValueError('Dispositivo já vinculado; revisar registro.')
            if any(d!=device and u==unit_id for d,u in self.bindings.items()): raise ValueError('Unidade já possui dispositivo.')
            e=dict(kind='binding',device=device,unit_id=unit_id,actor=actor,at=self.clock(),source='operator')
            self._append(e); return e

    def ingest(self,data):
        if not isinstance(data,dict): raise ValueError('Posição inválida.')
        device=data.get('id'); source=data.get('source','gps')
        if not isinstance(device,str) or not device.strip() or len(device)>120: raise ValueError('Dispositivo inválido.')
        if source not in ('gps','simulated') or source=='simulated' and not self.sample: raise ValueError('Simulação somente em sample.')
        lat,lon=float(data['lat']),float(data['lon']); at=epoch(data.get('timestamp',self.clock()))
        speed=float(data.get('speed',0))*0.514444; bearing=float(data.get('bearing',0)); accuracy=float(data.get('accuracy',0))
        if not all(math.isfinite(v) for v in (lat,lon,speed,bearing,accuracy)) or not -90<=lat<=90 or not -180<=lon<=180 or speed<0 or accuracy<0 or not 0<=bearing<=360: raise ValueError('Coordenadas ou precisão inválidas.')
        if at>self.clock() or at<0: raise ValueError('Horário futuro ou inválido.')
        with self.lock:
            if at<=self.last.get((device,source),-1): return {'status':'ignored','reason':'out_of_order'}
            e=dict(kind='fix',device=device,unit_id=self.bindings.get(device),timestamp=at,lat=lat,lon=lon,
                speed_mps=speed,bearing=bearing,accuracy=accuracy,source=source,confidence='low' if accuracy>200 else 'normal')
            e['fix_id']='gps-'+hashlib.sha256(json.dumps(e,sort_keys=True).encode()).hexdigest()[:16]
            if e['unit_id'] and e['confidence']=='normal' and speed<=0.5:
                prior=self.history[(e['unit_id'],source)]
                anchor=prior[-1].get('stationary_start') if prior else None
                if anchor and metres([lon,lat],[anchor['lon'],anchor['lat']])<=60:
                    e['stationary_start']=dict(anchor)
                else:
                    e['stationary_start']={k:e[k] for k in ('fix_id','timestamp','lat','lon','source')}
            self._append(e)
            return dict(status='pending' if not e['unit_id'] else 'low_confidence' if accuracy>200 else 'accepted',fix_id=e['fix_id'])

    def view(self,now=None):
        replay=now is not None
        now=self.clock() if now is None else epoch(now)
        with self.lock:
            plans=self.missions_fn.at(now) if replay and hasattr(self.missions_fn,'at') else self.missions_fn()
            missions={m['unit_id']:m for m in plans if m.get('approved_at',0)<=now}
            rows=[]
            for (uid,source),history in self.history.items():
                fixes=[f for f in history if f['timestamp']<=now]
                if not fixes: continue
                fix=fixes[-1]; age=max(0,now-fix['timestamp']); m=missions.get(uid)
                row=dict(unit_id=uid,source=source,fix=copy.deepcopy(fix),age_seconds=round(age),fresh=age<=600,
                    trail=copy.deepcopy(fixes[-10:]),status=m.get('status','assigned') if m else 'unknown',mission_id=m['mission_id'] if m else None,
                    eta_seconds=None,eta_label_pt='ETA indisponível; estimativa exige rota e velocidade observada',arrival_proposal=None,alerts=[])
                if m:
                    row['route_label_pt']=m.get('route_label_pt','Rota planejada estimada; confirmar acesso')
                    row['route_review_pt']=m.get('review_pt',[])
                    valid=[f for f in fixes if f['timestamp']>=m.get('approved_at',0)]
                    line=m.get('polyline',[]); stops=m.get('stops',[])
                    current = [f for f in valid if now-f['timestamp'] <= FRESH_SECONDS]
                    support_ok = bool(current and current[-1]['accuracy'] <= TRACKING_ACCURACY_M and
                                      (len(valid) < 2 or valid[-1]['timestamp']-valid[-2]['timestamp'] <= SUPPORT_GAP_SECONDS))
                    if row['fresh'] and support_ok and tracking_route(m) and len(line)>1 and stops:
                        p=[fix['lon'],fix['lat']]; off,along,total=mission_project(p,m)
                        row.update(on_route_distance_m=round(off),progress_pct=round(100*along/total,1) if total else 0)
                        # Stop selection advances only after two nearby fixes; no mission/status mutation.
                        next_index=0
                        for i,stop in enumerate(stops):
                            target=stop.get('point')
                            if not target: break
                            target=[target['lon'],target['lat']]
                            near=arrival_pair(current,target)
                            if near:
                                row['arrival_proposal']=dict(status='confirmation_required',label_pt='chegou? Confirmar com operador/equipe',
                                    case_id=stop['case_id'],mission_id=m['mission_id'],fix_ids=[f['fix_id'] for f in current[-2:]],
                                    as_of=now,fresh=True,evidence=[{k:f[k] for k in ('fix_id','timestamp','accuracy','source')} for f in current[-2:]])
                                next_index=i; break
                            # A previously witnessed arrival can select the following stop.
                            arrived=any(arrival_pair(valid[j:j+2],target) for j in range(len(valid)-1))
                            if not arrived: next_index=i; break
                            next_index=min(i+1,len(stops)-1)
                        stop=stops[next_index]; target=[stop['point']['lon'],stop['point']['lat']]
                        target_along=mission_project(target,m)[1]; remaining=max(0,target_along-along)
                        observed=[f['speed_mps'] for f in current[-5:] if f['accuracy']<=TRACKING_ACCURACY_M]
                        speed=sum(observed)/len(observed)
                        if speed<0.3 and len(valid)>1:
                            a,b=valid[-2:]; dt=b['timestamp']-a['timestamp']
                            speed=metres([a['lon'],a['lat']],[b['lon'],b['lat']])/dt if dt>0 else 0
                        if speed>=0.3:
                            speed=max(0.5,min(25,speed)); row['eta_seconds']=round(remaining/speed)
                            row['eta_label_pt']=f"~{math.ceil(row['eta_seconds']/60)} min (estimativa; velocidade observada limitada a 0,5–25 m/s)"
                        row.update(next_stop=stop['case_id'],remaining_m=round(remaining))
                        recent=valid[-3:]
                        if len(recent)==3 and all(mission_project([f['lon'],f['lat']],m)[0]-f['accuracy']>300 for f in recent):
                            row['alerts'].append(self._finding('gps_off_route','fora da rota',m,source,recent))
                    # A sourced stationary-history alert does not assert route progress or arrival.
                    anchor=fix.get('stationary_start')
                    p=[fix['lon'],fix['lat']]
                    away=bool(stops) and all(metres(p,[s['point']['lon'],s['point']['lat']])>60+fix['accuracy'] for s in stops if s.get('point'))
                    if row['fresh'] and valid and anchor and fix['timestamp']-max(anchor['timestamp'],m.get('approved_at',0))>900 and away:
                        row['alerts'].append(self._finding('gps_stopped','parado longe da parada',m,source,[anchor,fix]))
                    if now-max(fix['timestamp'],m.get('approved_at',0))>600 and row['status'] in ('en_route','assigned','returning'):
                        row['alerts'].append(self._finding('gps_no_signal','sem sinal',m,source,[fix]))
                rows.append(row)
            # An approved departure with no fix is also visible to the supervisor.
            for uid,m in missions.items():
                if not any(r['unit_id']==uid for r in rows) and now-m.get('approved_at',now)>600 and m.get('status') in ('assigned','en_route','returning'):
                    rows.append(dict(unit_id=uid,source='gps',fix=None,trail=[],age_seconds=None,fresh=False,status=m['status'],mission_id=m['mission_id'],eta_seconds=None,arrival_proposal=None,
                        alerts=[self._finding('gps_no_signal','sem sinal desde a missão',m,'gps',[])]))
            return dict(as_of=now,units=rows,pending=[dict(device=d,timestamp=f['timestamp'],confidence=f['confidence']) for d,f in self.pending.items()],bindings=dict(self.bindings))

    @staticmethod
    def _finding(kind,label,m,source,fixes):
        fid=f"{kind}:{m['mission_id']}:{m['unit_id']}:{source}"
        evidence=[copy.deepcopy(f) for f in fixes]+[{'mission_id':m['mission_id'],'approved_at':m.get('approved_at'),'source':source}]
        text=f"{'[SIMULADO] ' if source=='simulated' else ''}{label}: {m['unit_id']}; missão {m['mission_id']}; fixes: {', '.join(f['fix_id'] for f in fixes) or 'nenhum'}; confirmar contato com equipe."
        return dict(id=fid,kind=kind,case_ids=m.get('case_ids',[]),resource_ids=[m['unit_id']],mission_ids=[m['mission_id']],numbers={},severity=90,
            allowed_actions=['acknowledge_unit'],default_action='acknowledge_unit',facts=[{'id':fid,'text_pt':text}],evidence=evidence)

    def findings(self,now):
        return [a for row in self.view(now)['units'] for a in row['alerts']]
