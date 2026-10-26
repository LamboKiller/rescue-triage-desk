"""HTTP glue: GET /api/volunteers, POST /api/volunteers (paste an offer), POST /api/volunteers/<id>/(verify|reject|merge|unmerge)."""
import json
import time
from urllib.parse import urlsplit
from app.engines.world_model.registry import Conflict


def handle(handler, service, method, cases=None):
    path = urlsplit(handler.path).path.split('/')
    try:
        if method == 'GET':
            if len(path) != 3:
                raise KeyError(handler.path)
            if cases is not None:
                service.sync_cases(cases())
            handler.send_json(200, service.list());return True
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 64000:
            raise ValueError('JSON ausente ou maior que 64 KB.')
        handler.connection.settimeout(10)
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError('JSON incompleto.')
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'});return True
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'});return True
        req = json.loads(raw.decode('utf-8'))
        if not isinstance(req, dict):
            raise ValueError('Envie um objeto JSON.')
        if len(path) == 3:
            result = service.submit(req.get('text'), synthetic=req.get('synthetic') is True, deadline=time.monotonic() + 45,
                                    actor=str(req.get('actor') or 'operador')[:120])
        elif len(path) == 5 and path[4] in ('verify', 'reject', 'merge', 'unmerge'):
            result = getattr(service, path[4])(path[3], req)
        else:
            raise KeyError(handler.path)
        handler.send_json(200, result);return True
    except Conflict as exc: handler.send_json(409, {'error': str(exc)})
    except KeyError: handler.send_json(404, {'error': 'Oferta de voluntário não encontrada.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha interna em voluntários.'})
    return True
