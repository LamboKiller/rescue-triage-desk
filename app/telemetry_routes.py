"""Small HTTP adapter and approved-mission route snapshot integration."""
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from app.telemetry import epoch


def safe_snapshot(mission):
    """Old cached snapshots also need proof; never promote a pre-fix route journal."""
    import copy
    from app.telemetry import tracking_route
    mission = copy.deepcopy(mission)
    if not tracking_route(mission) or mission.get('water') and not mission.get('segments'):
        mission.setdefault('preview_segments', mission.get('segments', []))
        mission['segments'], mission['polyline'] = [], []
        mission['tracking_eligible'] = False
    return mission


class ApprovedRoutes:
    def __init__(self,status,missions,telemetry):
        self.status=status; self.missions=missions; self.telemetry=telemetry
        self.cache={e['key']:safe_snapshot(e['mission']) for e in telemetry.events() if e['kind']=='mission_route'}

    def __call__(self):
        with self.telemetry.lock: return self._view()

    def at(self,now):
        with self.telemetry.lock: return self._view(now)

    def _view(self,now=None):
        result=[]
        events=self.status.journal()
        cases=None
        if now is not None:
            from app.handover.replay import snapshot
            iso=datetime.fromtimestamp(now,timezone.utc).isoformat()
            history=snapshot(self.status.registry,iso)
            events=[json.loads(s) for s in history.path.read_text().splitlines()]
            cases=history.read()
            states={u['unit_id']:u for u in self.status.view(iso,_events=events)['units']}
        else:
            states={u['unit_id']:u for u in self.status.view()['units']}
        for e in events:
            if e.get('kind')!='approve_mission': continue
            mid=e['mission_id']
            try: plan=self.missions.detail(mid,_cases=cases) if cases is not None else self.missions.detail(mid)
            except KeyError: continue
            if plan['status']!='assigned': continue
            for unit in plan['units']:
                key=mid+':'+unit['id']
                state=states.get(unit['id'],{})
                if state.get('mission_id')!=mid: continue
                if key not in self.cache:
                    from app.geo.routing import case_route, water_leg, BOATS
                    cursor=dict(unit); line=[]; segments=[]; preview=[]; valid=True; reviews=[]
                    for index,stop in enumerate(plan['stops']):
                        if not stop.get('point'): valid=False; break
                        # Freeze approved stop coordinates; later case edits cannot move a mission's route.
                        case={'case_id':stop['case_id'],'position':stop['point']}
                        if index and unit.get('type',unit.get('asset')) in BOATS:
                            water=water_leg(cursor['base_location'],stop['point'],plan['date'],vehicle=unit)
                            route=dict(reachable=water.get('km') is not None,land=None,water=water)
                        else:
                            route=case_route(case,cursor,plan['date'])
                        reviews.extend(route.get('review_pt',[]))
                        if not route.get('reachable'): valid=False
                        for mode,leg in [('land',route.get('land',route)),('water',route.get('water'))]:
                            reviews.extend((leg or {}).get('review_pt',[]))
                            coords=(leg or {}).get('polyline',[])
                            if len(coords)<2: continue
                            segment=dict(mode=mode,polyline=coords,basis=leg.get('basis'),
                                         fallback=leg.get('fallback',False),grid_verified=leg.get('grid_verified'))
                            segment['tracking_eligible'] = mode!='water' or leg.get('fallback') is False and leg.get('grid_verified') is True
                            preview.append(segment)
                            if not segment['tracking_eligible']: valid=False; continue
                            if line and line[-1]!=coords[0]:
                                reviews.append('Ligação entre pernas estimada na margem/associação à malha; confirmar acesso. ETA soma apenas pernas planejadas.')
                            line.extend(coords if not line else coords[1:]); segments.append(segment)
                        cursor['base_location']=stop['point']
                    if not valid or len(line)<2:
                        reviews.append('Rota não comprovada: sem ETA/progresso; simulador não movimenta esta missão.')
                    # Simulator-only: the land geometry proven BEFORE the first unproven leg. Never ETA/progress/arrival input.
                    proven=[]
                    for seg in preview:
                        if not seg['tracking_eligible']: break
                        proven.append(seg)
                    if valid: proven=[]
                    if proven: reviews.append('Simulador move só até o fim da geometria comprovada (trecho em terra); trecho na água não comprovado: sem ETA/progresso.')
                    mission=dict(mission_id=mid,unit_id=unit['id'],approved_at=epoch(e['at']),
                        case_ids=[s['case_id'] for s in plan['stops']],stops=plan['stops'],polyline=line if valid else [],segments=segments if valid else [],
                        preview_segments=preview,proven_prefix_segments=proven,tracking_eligible=valid and len(line)>1,
                        route_label_pt='Rota planejada estimada para missão aprovada; camadas retrospectivas, confiança baixa; confirmar acesso',
                        review_pt=list(dict.fromkeys(reviews)),water=any(s['mode']=='water' for s in segments))
                    with self.telemetry.lock:
                        self.telemetry._append(dict(kind='mission_route',key=key,mission=mission))
                    self.cache[key]=mission
                result.append(dict(self.cache[key],status=state.get('status','assigned')))
        return result


def handle(h,service,method):
    url=urlsplit(h.path); path=url.path
    if path=='/api/telemetry/osmand' and method=='GET' and hasattr(h,'server'):
        from app.operator_boundary import guard_operator
        if not guard_operator(h,device=True): return
    try:
        origin=h.headers.get('Origin')
        if origin and urlsplit(origin).netloc!=h.headers.get('Host'):
            return h.send_json(403,{'error':'Origem não permitida.'})
        query=parse_qs(url.query,keep_blank_values=True)
        if any(len(v)!=1 for v in query.values()): raise ValueError('Parâmetro duplicado.')
        query={k:v[0] for k,v in query.items()}
        if method=='GET' and path=='/api/telemetry':
            return h.send_json(200,service.view())
        if method=='GET' and path=='/api/telemetry/missions':
            if not service.sample: return h.send_json(403,{'error':'Demo somente em sample.'})
            return h.send_json(200,{'missions':service.missions_fn(),'bindings':dict(service.bindings)})
        data=query
        if method=='POST' and not (path=='/api/telemetry/osmand' and h.headers.get('Content-Length','0')=='0' and query):
            size=int(h.headers.get('Content-Length','0'))
            if not 0<size<=64000: raise ValueError('Corpo ausente ou maior que 64 KB.')
            h.connection.settimeout(10); raw=h.rfile.read(size)
            if len(raw)!=size: raise ValueError('Corpo incompleto.')
            content=h.headers.get('Content-Type','').split(';')[0]
            if content=='application/json': data=json.loads(raw.decode('utf-8'))
            elif path=='/api/telemetry/osmand' and content=='application/x-www-form-urlencoded':
                form=parse_qs(raw.decode('utf-8'),keep_blank_values=True)
                if any(len(v)!=1 for v in form.values()): raise ValueError('Parâmetro duplicado.')
                data={**query,**{k:v[0] for k,v in form.items()}}
            else: return h.send_json(415,{'error':'Use JSON ou formulário OsmAnd.'})
        if path=='/api/telemetry/osmand' and method in ('GET','POST'):
            return h.send_json(200,service.ingest(data))
        if path=='/api/telemetry/positions' and method=='POST':
            batch=data.get('positions') if isinstance(data,dict) else data
            if not isinstance(batch,list) or not 1<=len(batch)<=100: raise ValueError('Envie de 1 a 100 posições.')
            # Independent outcomes are explicit: malformed rows never hide accepted ones.
            results=[]
            for row in batch:
                try: results.append(service.ingest(row))
                except (ValueError,TypeError,KeyError,OverflowError): results.append({'status':'rejected','reason':'invalid_fix'})
            return h.send_json(200,{'results':results})
        if path=='/api/telemetry/bindings' and method=='POST' and isinstance(data,dict):
            return h.send_json(200,service.bind(data['device'],data['unit_id'],data['actor']))
        return h.send_json(404,{'error':'Rota de telemetria não encontrada.'})
    except (ValueError,TypeError,KeyError,UnicodeError,OverflowError):
        return h.send_json(400,{'error':'Telemetria inválida; confira dispositivo, coordenadas, precisão e horário.'})
