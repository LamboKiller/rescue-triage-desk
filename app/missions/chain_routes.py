"""Bounded same-origin HTTP interface for chain and reroute proposals."""
import json
from urllib.parse import urlsplit, parse_qs
from app.engines.world_model.registry import Conflict
from . import reroutes


def handle(handler,service,method):
    try:
        url=urlsplit(handler.path);parts=url.path.split('/');q=parse_qs(url.query)
        if method=='GET':
            if url.path=='/api/reroutes':
                if len(q.get('date',[]))!=1: raise ValueError('Informe uma data ISO.')
                result=reroutes.reroutes(service,q['date'][0])
            elif len(parts)==5 and parts[4]=='chain':
                result=reroutes.chain(service,parts[3],float(q.get('radius_km',['1'])[0]))
            else: raise KeyError(url.path)
        else:
            n=int(handler.headers.get('Content-Length','0'))
            if not 0<n<=256000: raise ValueError('JSON ausente ou maior que 256 KB.')
            handler.connection.settimeout(10);raw=handler.rfile.read(n)
            origin=handler.headers.get('Origin')
            if origin and urlsplit(origin).netloc!=handler.headers.get('Host'):
                return handler.send_json(403,{'error':'Origem não permitida.'})
            if not handler.headers.get('Content-Type','').startswith('application/json'):
                return handler.send_json(415,{'error':'Use application/json.'})
            request=json.loads(raw.decode('utf-8'))
            if not isinstance(request,dict): raise ValueError('Envie objeto JSON.')
            if len(parts)!=5 or parts[4] not in ('approve','decline','undo'): raise KeyError(url.path)
            result=reroutes.decide(service,parts[3],parts[4],request)
        return handler.send_json(200,result)
    except Conflict as exc: return handler.send_json(409,{'error':str(exc)})
    except KeyError: return handler.send_json(404,{'error':'Proposta ou missão ausente.'})
    except (ValueError,TypeError,UnicodeError) as exc: return handler.send_json(400,{'error':str(exc)})
