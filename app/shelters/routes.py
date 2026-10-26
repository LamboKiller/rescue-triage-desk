"""HTTP glue for /api/shelters*. Always responds; returns True. Writes need same-origin JSON like the other desk routes."""
import json
import re
from urllib.parse import parse_qs, urlsplit
from app.engines.world_model.registry import Conflict


def _when(query):
    v = query.get('now', query.get('date', []))
    if len(v) != 1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T[0-9:.+\-Zz]+)?', v[0]): raise ValueError('Informe date=YYYY-MM-DD (ou now=ISO).')
    return v[0]


def handle(handler, service, method):
    parts = urlsplit(handler.path);path = parts.path
    try:
        if method == 'GET':
            query = parse_qs(parts.query, keep_blank_values=True)
            if path == '/api/shelters': handler.send_json(200, service.listing(_when(query)));return True
            if path == '/api/shelters/recommend':
                ids = [i for i in (query.get('case_ids', [''])[0]).split(',') if i]
                if not ids: raise ValueError('Informe case_ids.')
                people = query.get('people', [None])[0]
                handler.send_json(200, service.recommend(_when(query), ids, int(people) if people else None));return True
            raise KeyError(path)
        if path != '/api/shelters/reports': raise KeyError(path)
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
        request = json.loads(raw.decode('utf-8'))
        if not isinstance(request, dict): raise ValueError('Envie um objeto JSON.')
        handler.send_json(200, service.report(request))
    except Conflict as exc: handler.send_json(409, {'error': str(exc)})
    except KeyError: handler.send_json(404, {'error': 'Recurso de abrigos ou caso não encontrado.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception: handler.send_json(500, {'error': 'Falha interna em abrigos.'})
    return True
