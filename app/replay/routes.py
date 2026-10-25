"""HTTP glue for /api/replay/* (start, pause, speed, state). Called from the mission-enabled server handler."""
import json
import re
import threading
from urllib.parse import parse_qs, urlsplit
from app.engines.world_model.registry import Conflict
from app.replay import scenario as scenarios
from app.replay.runner import Desk, ReplayRunner, SPEEDS


class ReplayController:
    def __init__(self, server, scenario_path=None, sleep=None):
        self.server, self.path, self.sleep = server, scenario_path or scenarios.DEFAULT, sleep
        self.runner, self.lock = None, threading.Lock()

    def start(self, speed=10, tick_every=None):
        if speed not in SPEEDS:
            raise ValueError('Velocidade deve ser 1, 10 ou 60.')
        with self.lock:
            if self.runner and self.runner.status in ('running', 'paused'):
                raise Conflict('O replay já está em andamento.')
            scenario = scenarios.load(self.path)
            desk = Desk.from_server(self.server)
            existing = {c.get('message_id') for c in desk.registry.read()}
            if existing & set(scenario['message_ids']):
                raise Conflict('Este cenário já foi executado neste registro. Reinicie com um registro limpo: python -m app.replay')
            kwargs = {'sleep': self.sleep} if self.sleep else {}
            runner = ReplayRunner(desk, scenario, speed=speed, tick_every=tick_every, **kwargs)
            runner.foreign_cases = len(existing)
            self.runner = runner
            runner.start_thread()
            return self.state()

    def state(self, since=0):
        if self.runner is None:
            meta = scenarios.load(self.path)['meta']
            return {'status': 'idle', 'speed': 10, 'speeds': list(SPEEDS), 'events': [], 'event_count': 0, 'lanes': [],
                    'clock': {'day': meta['replay_day'], 'start': meta['start'], 'end_min': meta['end_min'], 't_min': 0,
                              'replay_time': meta['replay_day']+'T'+meta['start']+':00-03:00'},
                    'scenario': {'name': meta.get('name'), 'synthetic': True, 'tick_every_min': meta.get('tick_every_min', 30),
                                 'note': meta.get('note')}}
        out = self.runner.state(since)
        out['speeds'] = list(SPEEDS)
        if getattr(self.runner, 'foreign_cases', 0):
            out['warning'] = f'O registro tinha {self.runner.foreign_cases} casos fora do cenário; use python -m app.replay para um registro limpo.'
        return out


def handle(handler, controller, method):
    """Serve one replay request. Always responds; returns True."""
    parts = urlsplit(handler.path)
    path = parts.path
    try:
        if method == 'GET':
            if path != '/api/replay/state':
                raise KeyError(path)
            query = parse_qs(parts.query, keep_blank_values=True)
            since = query.get('since', ['0'])[0]
            if not re.fullmatch(r'\d{1,9}', since):
                raise ValueError('since deve ser inteiro.')
            handler.send_json(200, controller.state(int(since)))
            return True
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 4000:
            raise ValueError('JSON ausente ou maior que 4 KB.')
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
        if path == '/api/replay/start':
            speed = request.get('speed', 10)
            handler.send_json(200, controller.start(speed if type(speed) is int else -1))
            return True
        runner = controller.runner
        if path == '/api/replay/pause':
            if runner is None:
                raise Conflict('Nenhum replay em andamento.')
            paused = request.get('paused', True)
            if type(paused) is not bool:
                raise ValueError('paused deve ser booleano.')
            runner.pause(paused)
            handler.send_json(200, controller.state())
            return True
        if path == '/api/replay/speed':
            if runner is None:
                raise Conflict('Nenhum replay em andamento.')
            speed = request.get('speed')
            runner.set_speed(speed if type(speed) is int else -1)
            handler.send_json(200, controller.state())
            return True
        raise KeyError(path)
    except Conflict as exc:
        handler.send_json(409, {'error': str(exc)})
    except KeyError:
        handler.send_json(404, {'error': 'Rota do replay não encontrada.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha interna no replay.'})
    return True
