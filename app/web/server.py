"""Mission-enabled desk entrypoint, retaining all existing server routes.

python -m app.web.server --sample --port 8080 [--inventory path.json]
"""
import argparse
import hashlib
import json
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from app.config import ROOT, load_env, sample_mode, setting
from app.engines.world_model.registry import Registry, Conflict
from app.missions.service import MissionService
from app.pipeline import Pipeline


FRIENDLY={
    'Informe exatamente uma data.':'Informe a data no formato AAAA-MM-DD (ex.: ?date=2024-05-08).',
    'Informe exatamente uma data ISO.':'Informe a data no formato AAAA-MM-DD (ex.: ?date=2024-05-08).',
    'JSON ou parâmetros inválidos.':'Pedido inválido: confira o JSON enviado e os parâmetros (datas em AAAA-MM-DD).',
    'Rota não encontrada.':'Endereço da API não encontrado. Recarregue a página; se persistir, a versão do servidor é outra.',
    'Caso não encontrado.':'Caso não encontrado. Atualize a fila: ele pode ter sido removido ou ainda não foi processado.',
    'Missão não encontrada.':'Missão não encontrada. Atualize as propostas do dia.',
    'Recurso do supervisor não encontrado.':'Endereço do supervisor não encontrado. Use /api/supervisor/ticks?date=AAAA-MM-DD.',
    'Informe um horario.':'Informe um horário ISO com fuso (ex.: 2024-05-08T12:00:00-03:00).',
}


CASE_CACHE={}
HEAVY_CASE_KEYS=('facts','fleet','hazard_facts','hazards','fleet_summary','incident_state')


def _summary(c):
    """Queue-sized view: drops the bulky evidence lists; GET /api/cases/<id> returns the full record."""
    from app.case_summary import project
    return project(c)


def _default_day(registry):
    days=sorted({str(c.get('replay_time') or '')[:10] for c in registry.read() if c.get('replay_time')})
    return days[-1] if days else '2024-05-08'


def _mode_view(server,offline):
    from app import provenance
    runner=getattr(getattr(server,'replay',None),'runner',None)
    replay=bool(runner and getattr(runner,'status','') in ('running','paused'))
    sample=bool(getattr(getattr(server,'pipeline',None),'sample',offline))
    mode='replay' if replay else 'sample_offline' if sample else 'live'
    label={'replay':'REPLAY de execução gravada','sample_offline':'AMOSTRA OFFLINE (regras, sem agentes)','live':'AO VIVO · Nemotron via Nightshift'}[mode]
    gate={}
    try:
        g=json.loads((ROOT/'eval/gate_last.json').read_text(encoding='utf-8'));head=provenance._head()
        gate={'commit':g.get('commit'),'date':g.get('date'),'fast':g.get('fast'),'head':head,
              'pass':all(c.get('pass') for c in (g.get('checks') or {}).values() if isinstance(c,dict)),
              'stale':bool(g.get('commit') and head and g['commit']!=head)}
    except (OSError,ValueError,AttributeError): gate={}
    return {'mode':mode,'label_pt':label,'offline':sample,'gate':gate}


def create_server(host='127.0.0.1',port=8080,sample=None,registry_path=None,pipeline=None,inventory=None,radius_m=600):
    from run import create_server as original_server
    offline=sample_mode() if sample is None else sample
    demo_units=None
    if offline and inventory is None:
        from app.fleet.assets import demo_inventory
        demo_units=demo_inventory()
    registry=pipeline.registry if pipeline else Registry(registry_path or ROOT/'runtime/events.jsonl')
    pipeline=pipeline or Pipeline(registry,sample=offline)
    from app.missions.client import MissionClient
    service=MissionService(registry,inventory,None if offline else pipeline.client or MissionClient(ROOT/'runtime/mission_trace.jsonl'),radius_m)
    if demo_units is not None: service.allocation_inventory=demo_units
    from app.geo.routing import FleetDistance, case_route, day_value as routing_day
    service.routing_distance=FleetDistance
    from app.feedback import FeedbackService
    feedback=FeedbackService(registry,None if offline else __import__('app.missions.client',fromlist=['MissionClient']).MissionClient(ROOT/'runtime/feedback_trace.jsonl'))
    from app.unit_status import UnitStatusService
    from app.unit_status_routes import handle as unit_status_handle
    def unit_interval(name, default):
        try: return max(1, int(setting(name, str(default))))
        except ValueError: return default
    unit_status=UnitStatusService(registry,lambda:__import__('app.resources',fromlist=['inventory']).inventory(registry,service.allocation_inventory),
        feedback.extractor,unit_interval('UNIT_STATUS_GRACE_MIN',20),unit_interval('UNIT_STATUS_IDLE_MIN',40))
    from app.supervisor.service import SupervisorService
    from app.supervisor import routes as supervisor_routes
    from app.resources import inventory as resource_inventory
    supervisor=SupervisorService(registry,lambda:resource_inventory(registry,inventory),service.proposals,
        None if offline else __import__('app.missions.client',fromlist=['MissionClient']).MissionClient(ROOT/'runtime/supervisor_trace.jsonl'))
    supervisor.unit_status=unit_status
    from app.telemetry import Telemetry
    from app.telemetry_routes import ApprovedRoutes, handle as telemetry_handle
    telemetry=Telemetry(registry.path.parent/'telemetry.jsonl',lambda:[u['id'] for u in unit_status.inventory_fn()],lambda:[],sample=offline)
    telemetry.missions_fn=ApprovedRoutes(unit_status,service,telemetry)
    supervisor.telemetry=telemetry
    unit_status.telemetry=telemetry
    from app.redteam.service import RedTeamService, handle as redteam_handle
    redteam=RedTeamService(offline=offline)
    from app.callback.service import CallbackService
    callback_client=None
    if not offline:
        from app.llm.nightshift import Nightshift
        callback_client=pipeline.client or Nightshift(ROOT/'runtime/callback_trace.jsonl')
    callback=CallbackService(registry,pipeline,callback_client,ROOT/'runtime/callback_log.jsonl')
    from app.shelters.service import ShelterService
    from app.shelters import routes as shelter_routes
    shelters=ShelterService(registry,ROOT/'runtime/shelter_events.jsonl')
    from app.reunite.service import Reunite
    reunite=Reunite(registry,shelters,ROOT/'runtime/reunite_events.jsonl')
    from app.contradictions.service import ContradictionService
    from app.contradictions import routes as contradiction_routes
    contradictions=ContradictionService(registry)
    from app.landing.service import LandingService
    from app.landing import routes as landing_routes
    landing=LandingService(registry,shelters,ROOT/'runtime/landing_events.jsonl',callback_client)
    landing.unit_status=unit_status
    unit_status.landing_events=lambda:landing.store.events
    landing.road_routing=True
    from app.volunteers.service import VolunteerService  # F6: volunteer boat intake (pending until a human verifies)
    from app.volunteers import routes as volunteer_routes
    volunteers=VolunteerService(registry.path.parent/'volunteers_events.jsonl',registry,callback_client)
    from app.handover.service import HandoverService  # N4: shift handover; model summary only on demand, never on the triage path
    from app.handover import routes as handover_routes
    handover=HandoverService(registry,ROOT/'runtime/handover_events.jsonl',None if offline else __import__('app.missions.client',fromlist=['MissionClient']).MissionClient(ROOT/'runtime/handover_trace.jsonl'),
        shelters=shelters,supervisor=supervisor,missions=service,volunteers=volunteers,contradictions=contradictions,
        unit_status_fn=lambda now:[{'id':'unit:'+u['unit_id'],'text_pt':f"Unidade {u['unit_id']}: {u['label_pt']}; fonte {u['source'] or 'sem relato'}; horário {u['status_at'] or 'desconhecido'}."} for u in unit_status.view(now)['units']])
    server=original_server(host,port,sample=offline,pipeline=pipeline)
    from app.queue_intake import IntakeQueue, handle_get as intake_get, handle_post as intake_post
    intake=IntakeQueue(pipeline,registry.path.parent/'intake_queue.jsonl')  # accept-and-queue: persisted before the 202
    from app.web.ux_routes import UxDesk, handle as ux_handle  # UX2: one-click dispatch + undo
    ux=UxDesk(registry,service,unit_status,registry.path.parent/'ux_dispatch.jsonl')
    from app.replay import routes as replay_routes
    BaseHandler=server.RequestHandlerClass

    from app.coverage import CoverageService
    coverage=CoverageService(service)

    class Handler(BaseHandler):
        def send_json(self,code,data,*args,**kwargs):
            if code in (400,404) and isinstance(data,dict) and isinstance(data.get('error'),str):
                data={**data,'error':FRIENDLY.get(data['error'],data['error'])}
            return super().send_json(code,data,*args,**kwargs)
        def do_GET(self):
            path=urlsplit(self.path).path
            if intake_get(self,intake,path): return
            if path.startswith('/api/ux/'): return ux_handle(self,ux,'GET')
            if path=='/api/telemetry' or path.startswith('/api/telemetry/'): return telemetry_handle(self,telemetry,'GET')
            if path.startswith('/api/units/'): return unit_status_handle(self,unit_status,'GET')
            if path == '/api/coverage':
                try:
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if set(query)!={'date'} or len(query['date'])!=1: raise ValueError('Informe uma data ISO.')
                    return self.send_json(200,coverage.view(query['date'][0]))
                except (ValueError,TypeError) as exc: return self.send_json(400,{'error':str(exc)})
            if path.startswith('/api/cases/') and path.endswith('/route') and len(path.split('/'))==5:
                try:
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if set(query)!={'unit','date'} or any(len(v)!=1 or not v[0] for v in query.values()):
                        raise ValueError('Informe uma unidade e uma data YYYY-MM-DD.')
                    day=routing_day(query['date'][0])
                    from app.fleet.snapshot import read as routing_snapshot
                    c,units=routing_snapshot(service,path.split('/')[3],day)
                    unit=next((u for u in units if u['id']==query['unit'][0]),None)
                    if unit is None: raise KeyError(query['unit'][0])
                    return self.send_json(200,case_route(c,unit,day))
                except KeyError: return self.send_json(404,{'error':'Caso ou unidade não encontrado.'})
                except (ValueError,TypeError) as exc: return self.send_json(400,{'error':str(exc)})
                except OSError: return self.send_json(503,{'error':'Malha local indisponível; REVISAR acesso.'})
            if path == '/api/handover': return handover_routes.handle(self,handover,'GET')
            if path == '/api/flow':
                from app.flow.routes import handle as flow_handle
                return flow_handle(self,registry,parse_qs(urlsplit(self.path).query,keep_blank_values=True))
            if path.startswith('/api/reunite'):  # N5: on-demand matcher, never on the triage path
                from app.reunite import routes as reunite_routes
                return reunite_routes.handle(self,reunite,'GET')
            if path == '/api/memory':
                from app.memory.routes import handle
                return handle(self,registry,'GET')
            if path.startswith('/api/cases/') and path.endswith('/callback') and len(path.split('/'))==5:
                try:
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    self.send_json(200,callback.view(path.split('/')[3],refresh='refresh' in query,expand='expand' in query));return
                except KeyError: self.send_json(404,{'error':'Caso não encontrado.'});return
                except Exception: self.send_json(500,{'error':'Falha ao montar o retorno.'});return
            if path.startswith('/api/cases/') and path.endswith('/landing') and len(path.split('/'))==5: return landing_routes.handle(self,landing,'GET')
            if path.startswith('/api/cases/') and path.endswith('/assets') and len(path.split('/'))==5:
                try:
                    cid=path.split('/')[3];query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if 'date' in query and len(query['date'])!=1: raise ValueError('Informe exatamente uma data.')
                    c=registry.read(cid)
                    if c is None: raise KeyError(cid)
                    return self.send_json(200,service.assets(cid,query.get('date',[(c.get('replay_time') or c['received_at'])[:10]])[0]))
                except KeyError: return self.send_json(404,{'error':'Caso não encontrado.'})
                except (ValueError,TypeError) as exc: return self.send_json(400,{'error':str(exc)})
            if path.startswith('/api/volunteers'): return volunteer_routes.handle(self,volunteers,'GET',registry.read)
            if path.startswith('/api/contradictions'): return contradiction_routes.handle(self,contradictions,'GET')
            if path.startswith('/api/shelters'): return shelter_routes.handle(self,shelters,'GET')
            if path=='/api/reroutes' or (path.startswith('/api/missions/') and path.endswith('/chain')):
                from app.missions.chain_routes import handle
                return handle(self,service,'GET')
            if path=='/api/mode': return self.send_json(200,_mode_view(server,offline))
            if path=='/api/supervisor/ticks' and 'date=' not in (urlsplit(self.path).query or ''):
                self.path=path+'?date='+_default_day(registry)
            if path.startswith('/api/cases/') and len(path.split('/'))==4 and path.split('/')[3]:
                from app.priority import queue
                c=registry.read(unquote(path.split('/')[3]))
                if c is None:
                    waiting=intake.card_for(unquote(path.split('/')[3]))
                    if waiting: return self.send_json(200,waiting)
                    return self.send_json(404,{'error':'Caso não encontrado. Atualize a fila.'})
                return self.send_json(200,queue([c],c.get('replay_time'))[0])
            if path.startswith('/api/supervisor'): return supervisor_routes.handle(self,supervisor,'GET')
            if path in ('/api/evals','/api/provenance'):
                from app import provenance
                return self.send_json(200,provenance.evals_view() if path=='/api/evals' else provenance.table())
            if path.startswith('/api/redteam'): return redteam_handle(self,redteam,'GET')
            if path.startswith('/api/replay'): return replay_routes.handle(self,server.replay,'GET')
            if path not in ('/api/resources','/api/cases') and not path.startswith('/api/missions'): return super().do_GET()
            try:
                if path=='/api/resources':
                    from app.resources import read
                    from app.fleet import document
                    from app.fleet.assets import normalize, RULE_TYPES
                    self.send_json(200,{'resources':read(registry),'types':{k:v.get('label_pt',k) for k,v in document()['assets'].items()},
                        'verification_fields':document()['verification_fields'],
                        'typed_resources':[normalize(u)
                            for u in resource_inventory(registry,service.allocation_inventory)
                            if u.get('type') in RULE_TYPES]});return
                if path=='/api/cases':
                    from app.priority import queue
                    from app.decide import timestamp
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    clock=None
                    if 'replay_time' in query:
                        if len(query['replay_time'])!=1: raise ValueError('Informe um horario.')
                        clock=query['replay_time'][0];timestamp(clock)
                    registry.detect_stale(clock)
                    st=registry.path.stat() if registry.path.exists() else type('S',(),{'st_mtime_ns':0,'st_size':0})();key=(str(registry.path),st.st_mtime_ns,st.st_size,clock,'full' in query)  # empty desk: queued cards only
                    hit=CASE_CACHE.get('v')
                    def build():
                        cases=queue(registry.read() if 'full' in query else registry.queue_view(),clock)
                        if 'full' not in query: cases=[_summary(c) for c in cases]
                        rows=[((c.get('live_priority') or {}).get('score',0),json.dumps(c,ensure_ascii=False,separators=(',',':'))) for c in cases]
                        CASE_CACHE['v']=(key,rows,time.monotonic());return rows
                    if hit and hit[0]==key: items=hit[1]
                    elif hit and hit[0][0]==key[0] and hit[0][3:]==key[3:] and time.monotonic()-hit[2]<10 and intake.summary(limit=0)['backlog']>0:
                        # Surge: serve the last list (<10 s old) and rebuild once in the background, so polls stay
                        # fast while decisions land. Human actions are version-checked server-side, so this is display-only.
                        items=hit[1]
                        if not CASE_CACHE.get('refreshing'):
                            CASE_CACHE['refreshing']=True
                            def refresh():
                                try: build()
                                except Exception: pass
                                finally: CASE_CACHE['refreshing']=False
                            threading.Thread(target=refresh,daemon=True).start()
                    else: items=build()
                    # Waiting messages are never hidden: provisional 'em fila' cards merge by priority.
                    waiting=intake.card_items('full' in query)
                    if waiting: items=sorted(items+waiting,key=lambda row:-row[0])
                    body=('{"cases":['+','.join(row[1] for row in items)+']}').encode()
                    tag='"'+hashlib.sha1(body).hexdigest()[:20]+'"'
                    if self.headers.get('If-None-Match')==tag:
                        self.send_response(304);self.send_header('ETag',tag);self.send_header('Cache-Control','no-cache');self.end_headers();return
                    self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
                    self.send_header('ETag',tag);self.send_header('Cache-Control','no-cache')
                    self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
                if path=='/api/missions/proposals':
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    if len(query.get('date',[]))!=1: raise ValueError('Informe exatamente uma data.')
                    payload=service.proposals(query['date'][0])
                elif path.startswith('/api/missions/') and len(path.split('/'))==4:
                    payload=service.detail(path.split('/')[3])
                else: raise KeyError(path)
                self.send_json(200,payload)
            except KeyError: self.send_json(404,{'error':'Missão não encontrada.'})
            except (ValueError,TypeError) as exc: self.send_json(400,{'error':str(exc)})
            except Exception: self.send_json(500,{'error':'Falha no planejamento; conferir dados locais.'})

        def do_POST(self):
            path=urlsplit(self.path).path
            from app.operator_boundary import guard_operator
            if not guard_operator(self,device=path in ('/api/telemetry/osmand','/api/telemetry/positions')): return
            if intake_post(self,intake,path): return
            if path.startswith('/api/ux/'): return ux_handle(self,ux,'POST')
            if path=='/api/telemetry' or path.startswith('/api/telemetry/'): return telemetry_handle(self,telemetry,'POST')
            if path == '/api/handover': return handover_routes.handle(self,handover,'POST')
            if path.startswith('/api/units/'): return unit_status_handle(self,unit_status,'POST')
            if path.startswith('/api/reunite'):
                from app.reunite import routes as reunite_routes
                return reunite_routes.handle(self,reunite,'POST')
            if path == '/api/memory':
                from app.memory.routes import handle
                return handle(self,registry,'POST')
            if path.startswith('/api/landing/') or (path.startswith('/api/cases/') and path.endswith('/landing/choice')): return landing_routes.handle(self,landing,'POST')
            if path.startswith('/api/volunteers'): return volunteer_routes.handle(self,volunteers,'POST')
            if path.startswith('/api/contradictions'): return contradiction_routes.handle(self,contradictions,'POST')
            if path.startswith('/api/shelters'): return shelter_routes.handle(self,shelters,'POST')
            if path.startswith('/api/reroutes/'):
                from app.missions.chain_routes import handle
                return handle(self,service,'POST')
            if path.startswith('/api/supervisor'): return supervisor_routes.handle(self,supervisor,'POST')
            if path.startswith('/api/redteam'): return redteam_handle(self,redteam,'POST')
            if path.startswith('/api/replay'): return replay_routes.handle(self,server.replay,'POST')
            case_action=path.startswith('/api/cases/') and path.endswith('/actions')
            case_feedback=path.startswith('/api/cases/') and path.endswith('/feedback') and len(path.split('/'))==5
            case_callback=path.startswith('/api/cases/') and path.endswith('/callback/reply') and len(path.split('/'))==6
            if path!='/api/resources' and not path.startswith('/api/missions') and not case_action and not case_feedback and not case_callback: return super().do_POST()
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256000: raise ValueError('JSON ausente ou maior que 256 KB.')
                self.connection.settimeout(10)
                # Consume the bounded body before a header rejection. Closing with
                # unread request bytes can reset the socket on Windows, losing 403.
                raw=self.rfile.read(length)
                if len(raw)!=length: raise ValueError('JSON incompleto.')
                origin=self.headers.get('Origin')
                if origin and urlsplit(origin).netloc!=self.headers.get('Host'):
                    self.send_json(403,{'error':'Origem não permitida.'});return
                if not self.headers.get('Content-Type','').startswith('application/json'):
                    self.send_json(415,{'error':'Use application/json.'});return
                request=json.loads(raw.decode('utf-8'))
                if not isinstance(request,dict): raise ValueError('Envie um objeto JSON.')
                if path=='/api/resources':
                    from app.resources import register
                    result=register(registry,request)
                elif case_feedback:
                    result=feedback.submit(path.split('/')[3],request)
                    shelters.ingest_feedback(request.get('text'),request.get('actor'),request.get('received_at'),path.split('/')[3],None,request.get('source','crew'))
                elif case_callback:
                    result=callback.reply(path.split('/')[3],request)
                elif path.startswith('/api/missions/') and path.endswith('/feedback') and len(path.split('/'))==5:
                    result=service.feedback(path.split('/')[3],request,feedback)
                    shelters.ingest_feedback(request.get('text'),request.get('actor'),request.get('received_at'),request.get('case_id'),path.split('/')[3],request.get('source','crew'))
                elif path=='/api/missions':
                    result=service.approve(request)
                elif path.startswith('/api/missions/') and path.endswith('/cancel') and len(path.split('/'))==5:
                    result=service.cancel(path.split('/')[3],request)
                elif case_action and len(path.split('/'))==5:
                    cid=path.split('/')[3];action=request.get('action')
                    if action=='approve_mission': service.approve(request,cid);result=registry.read(cid)
                    elif action=='cancel_mission': service.cancel(request.get('mission_id'),request,cid);result=registry.read(cid)
                    else:
                        result=registry.action(cid,action,request.get('expected_version'),request.get('actor'),human=True,
                            asset=request.get('asset'),caution_acknowledged=request.get('caution_acknowledged',False),
                            target_case_id=request.get('target_case_id'),target_expected_version=request.get('target_expected_version'))
                else: raise KeyError(path)
                self.send_json(200,result)
            except Conflict as exc: self.send_json(409,{'error':str(exc)})
            except KeyError: self.send_json(404,{'error':'Caso ou missão não encontrado.'})
            except (ValueError,TypeError,UnicodeError) as exc:
                self.send_json(400,{'error':str(exc) if type(exc) is ValueError and not isinstance(exc,json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
            except Exception: self.send_json(500,{'error':'Falha interna no planejamento.'})
    server.RequestHandlerClass=Handler
    server.missions=service
    server.shelters=shelters
    server.landing=landing
    server.volunteers=volunteers
    server.feedback=feedback
    server.unit_status=unit_status
    server.telemetry=telemetry
    server.callback=callback
    server.supervisor=supervisor
    server.handover=handover
    server.redteam=redteam
    from app.replay.routes import ReplayController
    server.pipeline=pipeline
    server.intake=intake;server.ux=ux
    server.replay=ReplayController(server)
    return server


def main():
    load_env();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sample',action='store_true');p.add_argument('--host',default='127.0.0.1')
    p.add_argument('--port',type=int,default=int(setting('PORT','8080')))
    p.add_argument('--inventory',type=Path);p.add_argument('--radius-m',type=float,default=600)
    args=p.parse_args()
    inventory=json.loads(args.inventory.read_text(encoding='utf-8-sig')) if args.inventory else None
    from app.missions.planner import inventory_units
    inventory_units(inventory or [],'9999-12-31')
    server=create_server(args.host,args.port,args.sample or sample_mode(),inventory=inventory,radius_m=args.radius_m)
    print('Mission desk: http://localhost:'+str(server.server_port)+'/v2',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
