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
                if event['kind'] in ('merge', 'unmerge'):
                    for projection in event['projections']:
                        cases[projection['case_id']] = projection
                    continue
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
        case.pop('case_id', None)
        mid = case['message_id']
        text_hash = hashlib.sha256(case['text'].encode()).hexdigest()
        provenance = mid + ':' + text_hash
        cid = hashlib.sha256(mid.encode()).hexdigest()[:24]
        with self.locked():
            cases, seen = self._read()
            previous = cases.get(cid)
            if previous and (previous.get('merge_state') or previous.get('status','').startswith('MERGED_INTO:')):
                raise Conflict('Desfaça a união antes de reanalisar o caso.')
            # A delivery is ingested once. A changed replay/analysis is a separate
            # versioned event, so an earlier-time replay never returns later evidence.
            comparable = ('replay_time', 'mode', 'fields', 'errors', 'fleet', 'hazard_review', 'route', 'result')
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

    def append_reply(self, case_id, expected_version, case):
        case = json.loads(redact(json.dumps(case, ensure_ascii=False)))
        with self.locked():
            cases, _ = self._read()
            if case_id not in cases:
                raise KeyError(case_id)
            if cases[case_id].get('merge_state') or cases[case_id].get('status','').startswith('MERGED_INTO:'):
                raise Conflict('Desfaça a união antes de responder.')
            if cases[case_id]['version'] != expected_version:
                raise Conflict('Versão alterada. Recarregue e revise o caso.')
            case.update(status='proposed', location_confirmed=False, approved_asset=None,
                        caution_acknowledgement=None, parent_version=expected_version)
            self._append({'schema_version':1, 'kind':'analysis', 'case_id':case_id,
                'provenance':case['message_id']+':reply:'+str(expected_version),
                'version':expected_version+1, 'case':case})
            return copy.deepcopy(self._read()[0][case_id])

    def read(self, case_id=None):
        with self.locked():
            cases, _ = self._read()
            return copy.deepcopy(cases.get(case_id) if case_id else sorted(cases.values(), key=lambda c: -c['result']['priority']))

    def action(self, case_id, action, expected_version, actor, *, human=False, asset=None, caution_acknowledged=False, target_case_id=None, target_expected_version=None):
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
            if action in ('merge', 'unmerge'):
                return self._merge(cases, case, action, actor, target_case_id, target_expected_version)
            status = case['status']
            if status.startswith('MERGED_INTO:'):
                raise Conflict('Caso unido; use o caso principal.')
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

    def _merge(self, cases, case, action, actor, target_id, target_version):
        """Called under the registry's process/OS lock; one append changes both."""
        if action == 'unmerge':
            if case['status'] in ('human_approved','dispatched','field_confirmed'):
                raise Conflict('Despacho ativo; não desfaça a união.')
            state = case.get('merge_state')
            if not state:
                raise ValueError('Caso sem união ativa.')
            other = cases[state['other_id']]
            if other['version'] != state['other_version']:
                raise Conflict('Caso secundário alterado.')
            restored = copy.deepcopy(state['before'])
            for old in restored:
                current = cases[old['case_id']]
                old['version'] = current['version']+1
                old['actions'] = current['actions'] + [{'action':'unmerge','actor':redact(actor.strip()),'version':old['version']}]
            projections = restored
        else:
            if not isinstance(target_id,str) or target_id == case['case_id']:
                raise ValueError('Informe outro target_case_id.')
            if target_id not in cases:
                raise KeyError(target_id)
            other = cases[target_id]
            if type(target_version) is not int:
                raise ValueError('target_expected_version deve ser inteiro.')
            if other['version'] != target_version:
                raise Conflict('Versão do caso secundário alterada.')
            for c in (case,other):
                if c.get('merge_state') or c['status'].startswith('MERGED_INTO:') or c['status'] in ('human_approved','dispatched','field_confirmed'):
                    raise Conflict('Caso unido ou despacho ativo; união indisponível.')
            a,b = copy.deepcopy(case),copy.deepcopy(other)
            before = [copy.deepcopy(case),copy.deepcopy(other)]
            for c in (a,b):
                c['version'] += 1
                c['actions'].append({'action':'merge','actor':redact(actor.strip()),'version':c['version'],'target_case_id':target_id})
            a['messages'] = []
            a['evidence_union'] = []
            for c in before:
                for m in c.get('messages') or [{k:c[k] for k in ('message_id','text','received_at')}]:
                    if m not in a['messages']: a['messages'].append(m)
                for fact in c.get('facts',[]):
                    if fact not in a['evidence_union']: a['evidence_union'].append(fact)
            a['facts'] = copy.deepcopy(a['evidence_union'])
            a['text'] = '\n'.join(m['text'] for m in a['messages'])
            for key in ('hazard_facts','unsupported'):
                a[key] = list(a.get(key,[]))
                for fact in b.get(key,[]):
                    if fact not in a[key]: a[key].append(fact)
            a['open_items'] = list(a.get('open_items',[]))
            for key in ('people','children','elderly','disabled','pets'):
                av,bv = a.get('fields',{}).get(key),b.get('fields',{}).get(key)
                if av and bv and av.get('value') != bv.get('value'):
                    a['open_items'].append({'field':key,'reason':'conflicting_counts','values':[av,bv]})
                    a['fields'].pop(key,None)
                elif not av and bv:
                    a.setdefault('fields',{})[key] = copy.deepcopy(bv)
            if a['open_items']:
                a['result'].update(conflicting_counts=True,people_derived=False,decision='REVIEW_REQUIRED',
                                   decision_reason='Contagens conflitantes nos pedidos unidos; confirmar com uma pessoa.')
                a['result'].setdefault('questions',[]).append('Confirmar contagens conflitantes dos pedidos unidos.')
            a.update(status='proposed',location_confirmed=False,approved_asset=None,caution_acknowledgement=None)
            # Demographics from either history can constrain the resource package.
            from app.fleet import screen
            prior_evidence = copy.deepcopy(a['hazard_facts'])
            screen(a)
            a['hazard_review'] = a['hazard_critic'] = 'indisponível'
            a.setdefault('agents',{})['hazard_critic'] = 'indisponível'
            for fact in prior_evidence:
                if fact not in a['hazard_facts']: a['hazard_facts'].append(fact)
            b['status'] = 'MERGED_INTO:'+a['case_id']
            a['merge_state'] = {'other_id':target_id,'other_version':b['version'],'before':before}
            projections = [a,b]
        self._append({'schema_version':1,'kind':action,'case_id':case['case_id'],
                      'actor':redact(actor.strip()),'projections':projections})
        return copy.deepcopy(self._read()[0][case['case_id']])
