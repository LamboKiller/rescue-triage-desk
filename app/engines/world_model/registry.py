"""Own World Model behavioral implementation, adapted from R3's prototype.

Append-only JSONL is the source of truth. A process lock and an OS advisory lock
serialize read/check/append across threads and server processes. No model has
access to the action capability. This is not upstream conformance certification.
"""
import contextlib
import copy
import hashlib
import json
import os
import threading
from pathlib import Path
from app.decide import timestamp
from app.redact import redact

_locks = {}
_guard = threading.Lock()


class Conflict(ValueError):
    pass


class Registry:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _guard:
            self.lock = _locks.setdefault(str(self.path.resolve()), threading.RLock())

    @contextlib.contextmanager
    def locked(self):
        with self.lock, self.path.with_suffix('.lock').open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self):
        cases, seen = {}, set()
        if self.path.exists():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                event = json.loads(line)  # Fail closed on damaged log; never silently skip.
                cid = event['case_id']
                if event['kind'] in ('ingest', 'analysis'):
                    seen.add(event['provenance'])
                    case = cases.setdefault(cid, {'case_id': cid, 'version': 0, 'status': 'proposed',
                                                  'location_confirmed': False, 'facts': [], 'actions': []})
                    case['facts'].append(event['case'])
                    # Retain stale observations without rolling the current projection back.
                    if 'received_at' not in case or timestamp(event['case']['received_at']) >= timestamp(case['received_at']):
                        case.update(event['case'])
                    case['version'] = event['version']
                else:
                    case = cases[cid]
                    case['version'] = event['version']
                    case['actions'].append(event)
                    action = event['action']
                    if action == 'confirm_location':
                        case['location_confirmed'] = True
                    elif action == 'approve_dispatch':
                        case['status'] = 'human_approved'
                        case['approved_asset'] = event.get('asset')
                        case['caution_acknowledgement'] = event.get('caution_acknowledgement')
                    elif action == 'dispatch':
                        case['status'] = 'dispatched'
                    elif action == 'field_confirm':
                        case['status'] = 'field_confirmed'
                    elif action == 'request_callback':
                        case['status'] = 'callback_requested'
                    elif action == 'report_rescued':
                        case['status'] = 'reported_rescued_unconfirmed'
        return cases, seen

    def _append(self, event):
        with self.path.open('a', encoding='utf-8', newline='\n') as out:
            out.write(json.dumps(event, ensure_ascii=False, separators=(',', ':'))+'\n')
            out.flush()
            os.fsync(out.fileno())

    def ingest(self, case):
        case = json.loads(redact(json.dumps(case, ensure_ascii=False)))
        mid = case['message_id']
        text_hash = hashlib.sha256(case['text'].encode()).hexdigest()
        provenance = mid + ':' + text_hash
        cid = hashlib.sha256(mid.encode()).hexdigest()[:24]
        with self.locked():
            cases, seen = self._read()
            previous = cases.get(cid)
            # A delivery is ingested once. A changed replay/analysis is a separate
            # versioned event, so an earlier-time replay never returns later evidence.
            comparable = ('replay_time', 'mode', 'fields', 'errors', 'fleet', 'hazard_review')
            reanalysis = provenance in seen and previous is not None and any(
                previous.get(k) != case.get(k) for k in comparable)
            if provenance not in seen or reanalysis:
                current = cases.get(cid)
                if current:
                    # New text must be reviewed again; prior approval cannot carry over.
                    case['status'] = 'proposed'
                    case['location_confirmed'] = False
                    case['approved_asset'] = None
                    case['caution_acknowledgement'] = None
                self._append({'schema_version': 1, 'kind': 'analysis' if reanalysis else 'ingest', 'case_id': cid,
                              'provenance': provenance, 'version': cases.get(cid, {}).get('version', 0)+1,
                              'case': case})
            return copy.deepcopy(self._read()[0][cid])

    def read(self, case_id=None):
        with self.locked():
            cases, _ = self._read()
            return copy.deepcopy(cases.get(case_id) if case_id else sorted(cases.values(), key=lambda c: -c['result']['priority']))

    def action(self, case_id, action, expected_version, actor, *, human=False, asset=None, caution_acknowledged=False):
        if not human:
            raise PermissionError('Ação exclusiva de operador humano.')
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError('Identifique o operador com um apelido de demonstração.')
        if type(expected_version) is not int:
            raise ValueError('expected_version deve ser inteiro.')
        with self.locked():
            cases, _ = self._read()
            if case_id not in cases:
                raise KeyError(case_id)
            case = cases[case_id]
            if case['version'] != expected_version:
                raise Conflict('Versão alterada. Recarregue e revise o caso.')
            status = case['status']
            allowed = {'confirm_location', 'approve_dispatch', 'dispatch', 'field_confirm', 'request_callback', 'report_rescued'}
            if action not in allowed:
                raise ValueError('Ação desconhecida.')
            if status == 'field_confirmed':
                raise ValueError('Caso confirmado em campo; nova observação exige nova revisão.')
            if action == 'approve_dispatch' and (not case['location_confirmed'] or status != 'proposed'
                                                  or case['result']['decision'] != 'SEND_CANDIDATE'):
                raise ValueError('Confirme a localização de um candidato proposto antes de aprovar.')
            acknowledgement = None
            if action == 'approve_dispatch':
                if not isinstance(asset,str) or not asset:
                    raise ValueError('Selecione o recurso para aprovar o despacho.')
                selected = next((r for r in case.get('fleet',[]) if r['asset']==asset),None)
                if selected is None:
                    raise Conflict('Recurso sem avaliação de frota; reanalise o caso.')
                if selected['verdict']=='unsafe':
                    raise Conflict('Recurso inseguro: '+' '.join(selected['reasons_pt']))
                if selected['verdict']=='caution':
                    if caution_acknowledged is not True:
                        raise Conflict('Reconheça explicitamente as cautelas do recurso.')
                    acknowledgement = {'asset':asset,'reasons_pt':selected['reasons_pt'],
                                       'rule_ids':selected['rule_ids'],'source_ids':selected['source_ids'],
                                       'acknowledged':True,'actor':redact(actor.strip())}
            if action == 'dispatch' and status != 'human_approved':
                raise ValueError('Aprovação humana necessária antes do despacho.')
            if action == 'field_confirm' and status != 'dispatched':
                raise ValueError('Confirmação de campo exige despacho anterior.')
            if action == 'confirm_location' and status != 'proposed':
                raise ValueError('Localização só pode ser confirmada durante a proposta.')
            self._append({'schema_version': 1, 'kind': 'action', 'case_id': case_id,
                          'version': case['version']+1, 'action': action, 'actor': redact(actor.strip()),
                          **({'asset':asset,'caution_acknowledgement':acknowledgement} if action=='approve_dispatch' else {})})
            return copy.deepcopy(self._read()[0][case_id])
