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
    server=original_server(host,port,sample=offline,pipeline=pipeline)
    BaseHandler=server.RequestHandlerClass

    class Handler(BaseHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            if not path.startswith('/api/missions'): return super().do_GET()
            try:
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
            case_action=path.startswith('/api/cases/') and path.endswith('/actions')
            if not path.startswith('/api/missions') and not case_action: return super().do_POST()
            try:
                origin=self.headers.get('Origin')
                if origin and urlsplit(origin).netloc!=self.headers.get('Host'):
                    self.send_json(403,{'error':'Origem não permitida.'});return
                if not self.headers.get('Content-Type','').startswith('application/json'):
                    self.send_json(415,{'error':'Use application/json.'});return
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256000: raise ValueError('JSON ausente ou maior que 256 KB.')
                self.connection.settimeout(10)
                request=json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(request,dict): raise ValueError('Envie um objeto JSON.')
                if path=='/api/missions':
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
