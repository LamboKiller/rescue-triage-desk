"""Mission-enabled desk entrypoint, retaining all existing server routes.

python -m app.web.server --sample --port 8080 [--inventory path.json]
"""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from app.config import ROOT, load_env, sample_mode, setting
from app.engines.world_model.registry import Registry, Conflict
from app.missions.service import MissionService
from app.pipeline import Pipeline


def create_server(host='0.0.0.0',port=8080,sample=None,registry_path=None,pipeline=None,inventory=None,radius_m=600):
    from run import create_server as original_server
    offline=sample_mode() if sample is None else sample
    registry=pipeline.registry if pipeline else Registry(registry_path or ROOT/'runtime/events.jsonl')
    pipeline=pipeline or Pipeline(registry,sample=offline)
    from app.missions.client import MissionClient
    service=MissionService(registry,inventory,None if offline else pipeline.client or MissionClient(ROOT/'runtime/mission_trace.jsonl'),radius_m)
    from app.feedback import FeedbackService
    feedback=FeedbackService(registry,None if offline else __import__('app.missions.client',fromlist=['MissionClient']).MissionClient(ROOT/'runtime/feedback_trace.jsonl'))
    from app.supervisor.service import SupervisorService
    from app.supervisor import routes as supervisor_routes
    from app.resources import inventory as resource_inventory
    supervisor=SupervisorService(registry,lambda:resource_inventory(registry,inventory),service.proposals,
        None if offline else __import__('app.missions.client',fromlist=['MissionClient']).MissionClient(ROOT/'runtime/supervisor_trace.jsonl'))
    from app.redteam.service import RedTeamService, handle as redteam_handle
    redteam=RedTeamService(offline=offline)
    from app.callback.service import CallbackService
    callback_client=None
    if not offline:
        from app.llm.nightshift import Nightshift
        callback_client=pipeline.client or Nightshift(ROOT/'runtime/callback_trace.jsonl')
    callback=CallbackService(registry,pipeline,callback_client,ROOT/'runtime/callback_log.jsonl')
    server=original_server(host,port,sample=offline,pipeline=pipeline)
    from app.replay import routes as replay_routes
    BaseHandler=server.RequestHandlerClass

    class Handler(BaseHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            if path == '/api/memory':
                from app.memory.routes import handle
                return handle(self,registry,'GET')
            if path.startswith('/api/cases/') and path.endswith('/callback') and len(path.split('/'))==5:
                try:
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    self.send_json(200,callback.view(path.split('/')[3],refresh='refresh' in query,expand='expand' in query));return
                except KeyError: self.send_json(404,{'error':'Caso não encontrado.'});return
                except Exception: self.send_json(500,{'error':'Falha ao montar o retorno.'});return
            if path.startswith('/api/supervisor'): return supervisor_routes.handle(self,supervisor,'GET')
            if path.startswith('/api/redteam'): return redteam_handle(self,redteam,'GET')
            if path.startswith('/api/replay'): return replay_routes.handle(self,server.replay,'GET')
            if path not in ('/api/resources','/api/cases') and not path.startswith('/api/missions'): return super().do_GET()
            try:
                if path=='/api/resources':
                    from app.resources import read
                    from app.fleet import document
                    self.send_json(200,{'resources':read(registry),'types':{k:v.get('label_pt',k) for k,v in document()['assets'].items()},
                        'verification_fields':document()['verification_fields']});return
                if path=='/api/cases':
                    from app.priority import queue
                    from app.decide import timestamp
                    query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                    clock=None
                    if 'replay_time' in query:
                        if len(query['replay_time'])!=1: raise ValueError('Informe um horario.')
                        clock=query['replay_time'][0];timestamp(clock)
                    registry.detect_stale(clock)
                    self.send_json(200,{'cases':queue(registry.read(),clock)});return
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
            if path == '/api/memory':
                from app.memory.routes import handle
                return handle(self,registry,'POST')
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
                elif case_callback:
                    result=callback.reply(path.split('/')[3],request)
                elif path.startswith('/api/missions/') and path.endswith('/feedback') and len(path.split('/'))==5:
                    result=service.feedback(path.split('/')[3],request,feedback)
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
    server.feedback=feedback
    server.callback=callback
    server.supervisor=supervisor
    server.redteam=redteam
    from app.replay.routes import ReplayController
    server.pipeline=pipeline
    server.replay=ReplayController(server)
    return server


def main():
    load_env();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sample',action='store_true');p.add_argument('--host',default='0.0.0.0')
    p.add_argument('--port',type=int,default=int(setting('PORT','8080')))
    p.add_argument('--inventory',type=Path);p.add_argument('--radius-m',type=float,default=600)
    args=p.parse_args()
    inventory=json.loads(args.inventory.read_text(encoding='utf-8-sig')) if args.inventory else []
    from app.missions.planner import inventory_units
    inventory_units(inventory,'9999-12-31')
    server=create_server(args.host,args.port,args.sample or sample_mode(),inventory=inventory,radius_m=args.radius_m)
    print('Mission desk: http://localhost:'+str(server.server_port)+'/v2',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
