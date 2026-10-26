"""Bounded, same-origin unit report API."""
import json
import re
from urllib.parse import urlsplit, parse_qs, unquote


def handle(handler, service, method):
    path = urlsplit(handler.path).path
    try:
        if method=='GET' and path=='/api/units/status':
            q=parse_qs(urlsplit(handler.path).query,keep_blank_values=True)
            if set(q)-{'replay_time'} or any(len(v)!=1 for v in q.values()): raise ValueError('Relógio inválido.')
            return handler.send_json(200,service.view(q.get('replay_time',[None])[0]))
        match=re.fullmatch(r'/api/units/([^/]+)/report',path)
        if method!='POST' or not match: raise KeyError(path)
        size=int(handler.headers.get('Content-Length','0'))
        if not 0<size<=64000: raise ValueError('JSON ausente ou maior que 64 KB.')
        handler.connection.settimeout(10)
        raw=handler.rfile.read(size)
        if len(raw)!=size: raise ValueError('JSON incompleto.')
        origin=handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc!=handler.headers.get('Host'):
            return handler.send_json(403,{'error':'Origem não permitida.'})
        if not handler.headers.get('Content-Type','').startswith('application/json'):
            return handler.send_json(415,{'error':'Use application/json.'})
        result=service.report(unquote(match[1]),json.loads(raw.decode('utf-8')))
        return handler.send_json(200,result)
    except KeyError: return handler.send_json(404,{'error':'Unidade não encontrada.'})
    except (ValueError,TypeError,UnicodeError): return handler.send_json(400,{'error':'Relato inválido; confira unidade, fonte, missão e horário.'})
