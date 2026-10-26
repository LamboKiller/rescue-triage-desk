"""Same-origin routes for the Reencontro tab. GET builds candidates on demand; POST is a human decision."""
import json
from urllib.parse import urlsplit, parse_qs


def handle(handler, service, method):
    try:
        parts = urlsplit(handler.path)
        if method == 'GET':
            query = parse_qs(parts.query, keep_blank_values=True)
            if parts.path == '/api/reunite/notes':
                handler.send_json(200, {'notes': service.notes((query.get('case_id') or [''])[0])}); return True
            handler.send_json(200, service.view((query.get('at') or [None])[0] or None)); return True
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'}); return True
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'}); return True
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 4000:
            raise ValueError('JSON ausente ou muito grande.')
        body = json.loads(handler.rfile.read(length).decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('Envie um objeto JSON.')
        handler.send_json(200, {'decision': service.decide(body.get('pair_id'), body.get('action'), body.get('actor'), human=True, asof=body.get('at'))}); return True
    except PermissionError as exc:
        handler.send_json(403, {'error': str(exc)})
    except KeyError:
        handler.send_json(404, {'error': 'Candidato não encontrado ou já decidido.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) or 'Parâmetros inválidos.'})
    return True
