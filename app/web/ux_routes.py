"""UX2: one-click "Despachar" with undo, built only on the existing mission/registry/unit-status APIs.

POST /api/ux/dispatch  {case_id, unit_id, date, actor, checks:[{key,text_pt,codes:[..],done}], caution_acknowledged, override_reason}
POST /api/ux/undo      {dispatch_id, actor}               (only within UNDO_SECONDS of the dispatch)
GET  /api/ux/dispatches[?case_id=..]                      (records incl. the saved checks and undo window)

Rules: a human actor is required; every checklist code the allocation lists must be covered by a ticked check;
nothing here invents state - the mission is created by MissionService.approve and cancelled by MissionService.cancel.
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from app.engines.world_model.registry import Conflict

UNDO_SECONDS = 10


class UxDesk:
    def __init__(self, registry, service, unit_status=None, path=None, clock=time.time, undo_seconds=UNDO_SECONDS):
        self.registry, self.service, self.unit_status = registry, service, unit_status
        self.path, self.clock, self.undo_seconds = path, clock, undo_seconds
        self.lock = threading.RLock()
        self.records = {}
        if path is not None and path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                self.records[row['dispatch_id']] = row  # last row of an id wins

    def _save(self, rec):
        self.records[rec['dispatch_id']] = rec
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False, separators=(',', ':')) + '\n')

    def _view(self, rec):
        out = dict(rec)
        left = max(0.0, rec['undo_until'] - self.clock())
        out['undo_left_s'] = round(left, 1) if rec['state'] == 'dispatched' else 0
        return out

    def list(self, case_id=None):
        with self.lock:
            rows = [self._view(r) for r in self.records.values() if case_id in (None, r['case_id'])]
        return {'dispatches': sorted(rows, key=lambda r: r['at'], reverse=True), 'undo_seconds': self.undo_seconds}

    @staticmethod
    def _text(value, name, limit=500):
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'{name} inválido.')
        return value.strip()

    def dispatch(self, req):
        if not isinstance(req, dict):
            raise ValueError('Envie um objeto JSON.')
        cid, unit_id, day = req.get('case_id'), req.get('unit_id'), req.get('date')
        actor = req.get('actor')
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError('Identifique o operador.')
        if not all(isinstance(x, str) and x for x in (cid, unit_id, day)):
            raise ValueError('Informe caso, unidade e data.')
        checks = req.get('checks')
        if not isinstance(checks, list) or not checks or len(checks) > 12:
            raise ValueError('Marque as checagens antes de despachar.')
        for c in checks:
            if not isinstance(c, dict) or not isinstance(c.get('key'), str) or not isinstance(c.get('codes'), list):
                raise ValueError('Checagem inválida.')
        pending = [c['key'] for c in checks if c.get('done') is not True]
        if pending:
            raise ValueError('Faltam checagens: ' + ', '.join(pending))
        with self.lock:
            case = self.registry.read(cid)
            if case is None:
                raise KeyError(cid)
            if str(case['status']).startswith('ASSIGNED:'):
                raise Conflict('Caso já está em missão; desfaça ou cancele antes.')
            if case['result']['decision'] != 'SEND_CANDIDATE':
                raise Conflict('Somente candidatos a envio podem ser despachados; resolva a pendência do caso.')
            expected = req.get('expected_version')
            if expected is not None and expected != case['version']:
                raise Conflict('Versão alterada. Recarregue e revise o caso.')
            located = case.get('location_confirmed') is True
            if not located:
                # refuse BEFORE the irreversible confirm_location when something else still blocks the mission
                first = self.service.assets(cid, day)
                row0 = next((r for r in first['top3'] if r['id'] == unit_id), None)
                if row0 is None:
                    raise Conflict('Unidade fora das três opções atuais; escolha outra.')
                other = [b for b in row0.get('approval_blockers') or [] if not b.startswith('Confirmar localização')]
                if other:
                    raise Conflict(' '.join(other))
                # the operator's ticked "local confirmado" check is the human confirmation
                self.registry.action(cid, 'confirm_location', case['version'], actor, human=True)
            data = self.service.assets(cid, day)
            row = next((r for r in data['top3'] if r['id'] == unit_id), None)
            if row is None:
                raise Conflict('Unidade fora das três opções atuais; escolha outra.')
            if row.get('approval_blockers'):
                raise Conflict(' '.join(row['approval_blockers']))
            ticked = {code for c in checks for code in c['codes']}
            missing = [x['code'] for x in row['confirmation_checklist'] if x['code'] not in ticked]
            if missing:
                raise ValueError('Checagens não cobrem: ' + ', '.join(missing))
            reason = self._text(req.get('override_reason'), 'Motivo')
            if row['rank'] > 1 and not reason:
                reason = 'Escolhido pelo operador no painel Meios (Trocar).'
            mission = self.service.approve(dict(
                proposal_id=row['proposal_id'], expected_versions=row['expected_versions'], actor=actor,
                caution_acknowledged=req.get('caution_acknowledged') is True, override_reason=reason,
                checklist_confirmations={x['code']: True for x in row['confirmation_checklist']}))
            mid = mission.get('mission_id') or row['proposal_id']
            now = self.clock()
            unit_state = self._unit_en_route(unit_id, mid, actor)
            rec = dict(dispatch_id=uuid.uuid4().hex[:16], state='dispatched', case_id=cid, unit_id=unit_id, mission_id=mid,
                       at=now, undo_until=now + self.undo_seconds, actor=actor, date=day, asset=row['asset'],
                       label_pt=row['label_pt'], rank=row['rank'], synthetic=bool(row.get('synthetic')),
                       checks=[dict(key=c['key'], text_pt=str(c.get('text_pt', ''))[:300], codes=c['codes'], done=True) for c in checks],
                       unit_status=unit_state, expected_versions=row['expected_versions'])
            self._save(rec)
            return self._view(rec)

    def _unit_en_route(self, unit_id, mid, actor, status='en_route', text='Despachada pelo operador.'):
        if self.unit_status is None:
            return 'indisponível'
        try:
            self.unit_status.report(unit_id, dict(received_at=datetime.now(timezone.utc).isoformat(), actor=actor, source='operator',
                                                  status=status, text=text if status == 'en_route' else '', mission_id=mid))
            return status
        except Exception as exc:  # status is a convenience; the mission itself is the record
            return 'erro: ' + str(exc)[:80]

    def undo(self, req):
        if not isinstance(req, dict):
            raise ValueError('Envie um objeto JSON.')
        rid, actor = req.get('dispatch_id'), req.get('actor')
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('Identifique o operador.')
        with self.lock:
            rec = self.records.get(rid)
            if rec is None:
                raise KeyError(rid)
            if rec['state'] != 'dispatched':
                raise Conflict('Despacho já desfeito.')
            if self.clock() > rec['undo_until']:
                raise Conflict(f'Prazo de {self.undo_seconds} s para desfazer terminou; cancele a missão em Missões.')
            case = self.registry.read(rec['case_id'])
            versions = dict(rec['expected_versions'])
            versions[rec['case_id']] = case['version']
            self.service.cancel(rec['mission_id'], dict(actor=actor, expected_versions=versions))
            self._unit_en_route(rec['unit_id'], rec['mission_id'], actor, status='available')
            rec = dict(rec, state='undone', undone_at=self.clock(), undone_by=actor)
            self._save(rec)
            return self._view(rec)


def handle(handler, ux, method):
    path = urlsplit(handler.path).path
    try:
        if method == 'GET':
            if path != '/api/ux/dispatches':
                raise KeyError(path)
            q = parse_qs(urlsplit(handler.path).query)
            return handler.send_json(200, ux.list((q.get('case_id') or [None])[0]))
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 64000:
            raise ValueError('JSON ausente ou grande demais.')
        raw = handler.rfile.read(length)
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            return handler.send_json(403, {'error': 'Origem não permitida.'})
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            return handler.send_json(415, {'error': 'Use application/json.'})
        request = json.loads(raw.decode('utf-8'))
        if path == '/api/ux/dispatch':
            return handler.send_json(200, ux.dispatch(request))
        if path == '/api/ux/undo':
            return handler.send_json(200, ux.undo(request))
        raise KeyError(path)
    except Conflict as exc:
        handler.send_json(409, {'error': str(exc)})
    except KeyError:
        handler.send_json(404, {'error': 'Caso, missão ou despacho não encontrado.'})
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError and not isinstance(exc, json.JSONDecodeError) else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha interna ao despachar; confira o caso e tente de novo.'})
