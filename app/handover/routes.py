"""GET /api/handover?date=YYYY-MM-DD (skeleton, read-only; ?history lists stored ones); POST /api/handover {date|replay_time, summary?, actor?} stores an event."""
import json
import re
from urllib.parse import parse_qs, urlsplit

DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


def handle(handler, service, method):
    try:
        if method == 'GET':
            q = parse_qs(urlsplit(handler.path).query, keep_blank_values=True)
            if 'history' in q:
                handler.send_json(200, {'handovers': [{**{k: h[k] for k in ('handover_id', 'actor', 'replay_time')},
                                                       'summary_status': h['summary']['status']} for h in service.history()]})
                return True
            day = q.get('date', [])
            if len(day) != 1 or not DAY.fullmatch(day[0]):
                raise ValueError('Informe exatamente uma data ISO.')
            handler.send_json(200, service.view(day[0]))
            return True
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 8000:
            raise ValueError('JSON ausente ou maior que 8 KB.')
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'})
            return True
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'})
            return True
        req = json.loads(handler.rfile.read(length).decode('utf-8'))
        if not isinstance(req, dict) or not (DAY.fullmatch(str(req.get('date', ''))) or req.get('replay_time')):
            raise ValueError('Informe date (YYYY-MM-DD) ou replay_time.')
        req.setdefault('date', str(req.get('replay_time'))[:10])
        handler.send_json(200, service.create(req))
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha ao montar a passagem de turno.'})
    return True
