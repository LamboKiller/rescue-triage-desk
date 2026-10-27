"""HTTP glue for /api/supervisor/*; called from the mission-enabled server handler."""
import json
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit
from app.decide import timestamp
from app.engines.world_model.registry import Conflict


def handle(handler, service, method):
    """Serve one supervisor request. Always responds; returns True."""
    parts = urlsplit(handler.path)
    path = parts.path
    try:
        if method == 'GET':
            if path not in ('/api/supervisor', '/api/supervisor/ticks'):
                raise KeyError(path)
            query = parse_qs(parts.query, keep_blank_values=True)
            day = query.get('date', [])
            if not day and path == '/api/supervisor':
                ticks = service.state()['ticks']
                day = [ticks[-1]['replay_time'][:10] if ticks else date.today().isoformat()]
            if len(day) != 1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day[0]):
                raise ValueError('Informe exatamente uma data ISO.')
            handler.send_json(200, service.ticks(day[0]))
            return True
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 64000:
            raise ValueError('JSON ausente ou maior que 64 KB.')
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
        request = json.loads(raw.decode('utf-8'))
        if not isinstance(request, dict):
            raise ValueError('Envie um objeto JSON.')
        if path == '/api/supervisor/tick':
            now = request.get('replay_time')
            timestamp(now)
            ticks = service.run(now, request.get('until')) if request.get('until') else [service.tick(now)]
            handler.send_json(200, {**service.ticks(now[:10]), 'new_ticks': ticks})
            return True
        match = re.fullmatch(r'/api/supervisor/alerts/(al-[0-9a-f]{10})', path)
        if match:
            alert = service.decide(match[1], request.get('decision'), request.get('actor'), request.get('replay_time'))
            handler.send_json(200, alert)
            return True
        raise KeyError(path)
    except Conflict as exc:
        handler.send_json(409, {'error': str(exc)})
    except KeyError:
        handler.send_json(404, {'error': 'Recurso do supervisor não encontrado.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha interna no supervisor.'})
    return True
