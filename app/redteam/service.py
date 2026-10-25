"""HTTP service + routes for /api/redteam/*. Runs use a throwaway registry; the desk's cases are never touched."""
import json
import re
import threading
from urllib.parse import urlsplit
from app.config import ROOT
from app.engines.world_model.registry import Conflict
from app.redteam import harness
from app.redteam.attacker import Attacker

MAX_N = 48


class RedTeamService:
    def __init__(self, store=None, offline=True, attacker_client=None):
        self.store = store or harness.Store()
        self.offline = offline
        self.attacker_client = attacker_client
        self.lock = threading.Lock()

    def _client(self):
        if self.offline:
            return None
        if self.attacker_client is None:
            from app.missions.client import MissionClient
            self.attacker_client = MissionClient(ROOT/'runtime/redteam/attacker_trace.jsonl')
        return self.attacker_client

    def state(self):
        return {**harness.state(self.store), 'mode': 'offline' if self.offline else 'live'}

    def run(self, n, seed=None):
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_N:
            raise ValueError(f'Informe n entre 1 e {MAX_N}.')
        if not self.lock.acquire(blocking=False):
            raise ValueError('Já existe uma rodada de red team em andamento.')
        try:
            seed = seed if isinstance(seed, int) else len(self.store.read('results')) + 1
            out = harness.run_batch(n, self.store, Attacker(self._client()), harness.make_runner(self.offline), seed=seed)
            return {**self.state(), 'new_run': out['run_id']}
        finally:
            self.lock.release()

    def decide(self, proposal_id, decision, actor):
        harness.decide_proposal(self.store, proposal_id, decision, actor)
        return self.state()

    def rerun(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError('Já existe uma rodada de red team em andamento.')
        try:
            return {**self.state(), 'replay': harness.replay_regression(self.store, harness.make_runner(self.offline))}
        finally:
            self.lock.release()


def handle(handler, service, method):
    """Serve one /api/redteam request. Always responds; returns True."""
    path = urlsplit(handler.path).path
    try:
        if method == 'GET':
            if path != '/api/redteam':
                raise KeyError(path)
            handler.send_json(200, service.state())
            return True
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 16000:
            raise ValueError('JSON ausente ou maior que 16 KB.')
        handler.connection.settimeout(10)
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError('JSON incompleto.')
        from urllib.parse import urlsplit as _u
        origin = handler.headers.get('Origin')
        if origin and _u(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'})
            return True
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'})
            return True
        request = json.loads(raw.decode('utf-8'))
        if not isinstance(request, dict):
            raise ValueError('Envie um objeto JSON.')
        if path == '/api/redteam/run':
            handler.send_json(200, service.run(request.get('n'), request.get('seed')))
            return True
        if path == '/api/redteam/rerun':
            handler.send_json(200, service.rerun())
            return True
        match = re.fullmatch(r'/api/redteam/proposals/(pr-[0-9a-f]{10})', path)
        if match:
            handler.send_json(200, service.decide(match[1], request.get('decision'), request.get('actor')))
            return True
        raise KeyError(path)
    except Conflict as exc:
        handler.send_json(409, {'error': str(exc)})
    except KeyError:
        handler.send_json(404, {'error': 'Recurso do red team não encontrado.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha interna no red team.'})
    return True
