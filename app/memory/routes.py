"""Same-origin human memory controls; no model receives this capability."""
import json
from urllib.parse import urlsplit, parse_qs
from app.engines.world_model.registry import Conflict
from app.memory.service import PlaceMemory, place_id


def handle(handler, registry, method):
    try:
        memory = PlaceMemory(registry)
        if method == 'GET':
            query = parse_qs(urlsplit(handler.path).query, keep_blank_values=True)
            at = query.get('at', [None])
            if len(at) != 1:
                raise ValueError('Informe um horário de replay.')
            handler.send_json(200, {'entries': memory.entries(at[0]),
                'places': [dict(id=place_id(r), name=r['name'], city=r['municipality']) for r in memory.rows]})
            return
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'}); return
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'}); return
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 16000:
            raise ValueError('JSON ausente ou muito grande.')
        body = json.loads(handler.rfile.read(length).decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('Envie um objeto JSON.')
        if body.get('action') == 'propose':
            case = registry.read(body['case_id'])
            if not case:
                raise KeyError(body['case_id'])
            result = memory.propose(case, body.get('phrase'), body.get('place_id'))
        else:
            result = memory.decide(body.get('id'), body.get('action'), body.get('actor'), human=True)
        handler.send_json(200, {'entry': result})
    except Conflict as exc:
        handler.send_json(409, {'error': str(exc)})
    except KeyError:
        handler.send_json(404, {'error': 'Memória ou caso não encontrado.'})
    except (ValueError, TypeError, UnicodeError):
        handler.send_json(400, {'error': 'Parâmetros inválidos; copie a referência exata e confirme o caso.'})
