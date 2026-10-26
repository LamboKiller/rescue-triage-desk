"""HTTP glue for /api/contradictions (read case items; record a human decision). Always responds; returns True."""
import json
from urllib.parse import parse_qs, urlsplit
from app.engines.world_model.registry import Conflict


def handle(handler, service, method):
    parts = urlsplit(handler.path)
    try:
        if method == 'GET':
            if parts.path != '/api/contradictions':
                raise KeyError(parts.path)
            ids = parse_qs(parts.query, keep_blank_values=True).get('case_id', [])
            if len(ids) != 1:
                raise ValueError('Informe exatamente um case_id.')
            handler.send_json(200, service.view(ids[0]))
            return True
        if parts.path != '/api/contradictions/decision':
            raise KeyError(parts.path)
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 16000:
            raise ValueError('JSON ausente ou maior que 16 KB.')
        handler.connection.settimeout(10)
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError('JSON incompleto.')
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'})
            return True
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'})
            return True
        body = json.loads(raw.decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('Envie um objeto JSON.')
        handler.send_json(200, service.decide(body.get('case_id'), body.get('item_id'), body.get('decision'), body.get('actor'),
                                              body.get('expected_version')))
    except Conflict as exc:
        handler.send_json(409, {'error': str(exc)})
    except KeyError:
        handler.send_json(404, {'error': 'Caso ou item não encontrado.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha interna na checagem de contradições.'})
    return True
