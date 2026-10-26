"""HTTP glue: GET /api/cases/<id>/landing, POST /api/landing/<id>/(arrival|unloaded|full), POST /api/cases/<id>/landing/choice."""
import json
import re
from urllib.parse import parse_qs, urlsplit
from app.shelters.routes import _when


def handle(handler, service, method):
    parts = urlsplit(handler.path);path = parts.path.split('/')
    try:
        if method == 'GET':
            q = parse_qs(parts.query, keep_blank_values=True)
            if len(path) == 5 and path[1:3] == ['api', 'cases'] and path[4] == 'landing':
                handler.send_json(200, service.view(path[3], _when(q), 'expand' in q));return True
            raise KeyError(parts.path)
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 64000: raise ValueError('JSON ausente ou maior que 64 KB.')
        handler.connection.settimeout(10)
        raw = handler.rfile.read(length)
        if len(raw) != length: raise ValueError('JSON incompleto.')
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'});return True
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'});return True
        req = json.loads(raw.decode('utf-8'))
        if not isinstance(req, dict): raise ValueError('Envie um objeto JSON.')
        if len(path) == 5 and path[1:3] == ['api', 'landing'] and path[4] in ('arrival', 'unloaded', 'full'):
            handler.send_json(200, service.report(path[3], path[4], req));return True
        if len(path) == 6 and path[1:3] == ['api', 'cases'] and path[4:] == ['landing', 'choice']:
            handler.send_json(200, service.choose(path[3], req));return True
        raise KeyError(parts.path)
    except KeyError: handler.send_json(404, {'error': 'Caso ou ponto de desembarque não encontrado.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception: handler.send_json(500, {'error': 'Falha interna em desembarque.'})
    return True
