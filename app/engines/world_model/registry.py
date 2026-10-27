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
from app.redact import redact, redact_data

_locks = {}
_guard = threading.Lock()


class Conflict(ValueError):
    pass


_INDEX = {}  # path -> incremental projection (offset, signature, cases, seen)


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

    def _read(self, shared=False):
        """Incremental projection: replay only the journal tail appended since the last read of this file.

        The authoritative journal is unchanged and a damaged row still fails closed. The index is rebuilt from scratch
        when the file shrank or the bytes just before our offset changed (rewritten/reset journal). `shared=True`
        returns the live index for read-only callers; the default returns detached copies (callers may mutate).
        """
        if not isinstance(self.path, Path):  # virtual read-only journals (as-of replay) are parsed whole and never cached
            cases, seen, touched = {}, set(), set()
            for line in (self.path.read_text(encoding='utf-8').splitlines() if self.path.exists() else []):
                self._apply(cases, seen, json.loads(line), touched)
            self._project_incident_state(cases)
            return cases, seen
        key = self.__dict__.get('_resolved') or self.__dict__.setdefault('_resolved', str(self.path.resolve()))  # resolve() costs 0.3-1.3 s per call on this host
        with _guard:
            idx = _INDEX.setdefault(key, {'offset': 0, 'sig': b'', 'cases': {}, 'seen': set(), 'replayed': 0})
        if self.path.exists():
            size = self.path.stat().st_size
            with self.path.open('rb') as handle:
                if idx['offset'] and (size < idx['offset'] or not self._signature_matches(handle, idx)):
                    idx.update(offset=0, sig=b'', cases={}, seen=set(), replayed=0)
                handle.seek(idx['offset'])
                chunk = handle.read()
            if chunk:
                events = [json.loads(line) for line in chunk.decode('utf-8').splitlines() if line.strip()]  # Fail closed on damaged log; never silently skip.
                touched = set()
                for event in events:
                    touched.update(p['case_id'] for p in event['projections']) if 'projections' in event else touched.add(event.get('case_id'))
                    self._apply(idx['cases'], idx['seen'], event, touched)
                idx['offset'] += len(chunk)
                idx['sig'] = chunk[-32:] if len(chunk) >= 32 else (idx['sig'] + chunk)[-32:]
                idx['replayed'] += len(events)
                self._project_incident_state({c: idx['cases'][c] for c in touched if c in idx['cases']})
        else:
            idx.update(offset=0, sig=b'', cases={}, seen=set(), replayed=0)
        if shared:
            return idx['cases'], idx['seen']
        return copy.deepcopy(idx['cases']), set(idx['seen'])

    @staticmethod
    def _signature_matches(handle, idx):
        handle.seek(max(0, idx['offset']-len(idx['sig'])))
        return handle.read(len(idx['sig'])) == idx['sig']

    def _read_case(self, case_id):
        """Detached copy of ONE case from the incremental index (cost scales with the case, not the journal)."""
        cases, _ = self._read(shared=True)
        return copy.deepcopy(cases[case_id])

    @staticmethod
    def _apply(cases, seen, event, touched):
        if event['kind'] in ('place_memory', 'unit_status'):
            return
        if event['kind'] in ('resource', 'supervisor', 'contradiction'):  # supervisor ticks/decisions are journal-only, never case state
            return
        if event['kind'] in ('field_feedback', 'stale_callback', 'merge', 'unmerge', 'approve_mission', 'cancel_mission',
                             'repost_link', 'repost_unlink', 'mission_update'):
            for projection in event['projections']:
                earlier = cases.get(projection['case_id'])
                cases[projection['case_id']] = projection
                if earlier and 'people_initial_n' in earlier:  # logs written before P1S carry no initial count
                    projection.setdefault('people_initial_n', earlier['people_initial_n'])
            if event.get('provenance'):  # an unlinked repost is ingested exactly once
                seen.add(event['provenance'])
            return
        cid = event['case_id']
        if event['kind'] in ('ingest', 'analysis'):
            seen.add(event['provenance'])
            case = cases.setdefault(cid, {'case_id': cid, 'version': 0, 'status': 'proposed',
                                          'location_confirmed': False, 'facts': [], 'actions': []})
            case['facts'].append(event['case'])
            if 'people_initial_n' not in case:  # first observation, frozen: facts alias live fields after later edits
                first = (event['case'].get('fields') or {}).get('people')
                case['people_initial_n'] = {'value': first.get('value'), 'quote': first.get('quote'), 'source': first.get('source'),
                                            'message_id': event['case'].get('message_id')} if isinstance(first, dict) else None
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

    @staticmethod
    def _project_incident_state(cases):
        """P1S: canonical incident fields re-derived from events on every read; never stored, never silently absent."""
        from app import incident_state
        for case in cases.values():
            try:
                case['incident_state'] = incident_state.compute(case)
            except Exception as exc:
                case['incident_state'] = {'error': type(exc).__name__+': '+str(exc)[:120]}

    @staticmethod
    def _stored(case):
        """Copy of a projection without derived fields (also inside merge_state.before) so the log holds facts, not views."""
        out = {k: v for k, v in case.items() if k != 'incident_state'}
        state = out.get('merge_state')
        if isinstance(state, dict) and state.get('before'):
            out['merge_state'] = {**state, 'before': [Registry._stored(c) for c in state['before']]}
        return out

    def _append(self, event):
        if 'projections' in event:
            event = {**event, 'projections': [self._stored(p) for p in event['projections']]}
        if isinstance(event.get('case'), dict):
            event = {**event, 'case': self._stored(event['case'])}
        with self.path.open('a', encoding='utf-8', newline='\n') as out:
            out.write(json.dumps(event, ensure_ascii=False, separators=(',', ':'))+'\n')
            out.flush()
            os.fsync(out.fileno())

    def ingest(self, case):
        case = redact_data(case)
        case.pop('case_id', None)
        mid = case['message_id']
        text_hash = hashlib.sha256(case['text'].encode()).hexdigest()
        provenance = mid + ':' + text_hash
        cid = hashlib.sha256(mid.encode()).hexdigest()[:24]
        with self.locked():
            cases, seen = self._read(shared=True)
            previous = cases.get(cid)
            linked = self._linked_primary(cases, provenance)
            if linked is not None:  # this delivery is already attached to a case as a repost
                return copy.deepcopy(linked)
            if previous is None and provenance not in seen:
                hit = self._try_repost(cases, cid, case, provenance)
                if hit is not None:
                    return hit
            if previous and previous.get('status','').startswith('ASSIGNED:'):
                raise Conflict('Cancele a missão antes de reanalisar o caso atribuído.')
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
            return self._read_case(cid)

    @staticmethod
    def _linked_primary(cases, provenance):
        for c in cases.values():
            if any(l.get('provenance') == provenance and not l.get('unlinked') for l in c.get('linked_reports') or []):
                return c
        return None

    def _try_repost(self, cases, cid, case, provenance):
        """P1S: identical text + same place within 24 h attaches to the earlier case (no new case). Unlink is one human action."""
        from app.duplicates import find_repost
        from app.agents.needs import scan_context
        from app.derive_count import INJECTION
        hit = find_repost({**case, 'case_id': cid}, list(cases.values()))
        if hit is None:
            return None
        primary, match = hit
        sender = scan_context([case['text']])['sender']
        updated = copy.deepcopy(primary)
        updated.setdefault('linked_reports', []).append({
            'message_id': case['message_id'], 'provenance': provenance, 'received_at': case['received_at'],
            'text': case['text'], 'sender_role': sender['role'] if sender else 'unknown',
            'prompt_injection_detected': bool(INJECTION.search(case['text'])),
            'overlap': match['overlap'], 'hours': match['hours'], 'reason': match['reason'], 'unlinked': False,
            'payload': self._stored(case)})
        self._append({'schema_version': 1, 'kind': 'repost_link', 'case_id': primary['case_id'], 'actor': 'system',
                      'projections': [updated]})
        return self._read_case(primary['case_id'])

    def _unlink(self, cases, case, actor, message_id):
        """Human undo of an automatic repost link: the stored analysis becomes its own proposed case."""
        if case.get('merge_state') or case['status'].startswith('MERGED_INTO:'):
            raise Conflict('Desfaça a união antes de desvincular relatos.')
        link = next((l for l in case.get('linked_reports') or [] if l['message_id'] == message_id and not l.get('unlinked')), None)
        if link is None:
            raise ValueError('Relato vinculado não encontrado.')
        cid = hashlib.sha256(message_id.encode()).hexdigest()[:24]
        if cid in cases:
            raise Conflict('Relato já existe como caso próprio.')
        updated = copy.deepcopy(case)
        for l in updated['linked_reports']:
            if l['message_id'] == message_id:
                l.update(unlinked=True, unlinked_by=redact(actor.strip()))
        payload = copy.deepcopy(link['payload'])
        payload.pop('case_id', None)
        first = (payload.get('fields') or {}).get('people')
        fresh = {'people_initial_n': {'value': first.get('value'), 'quote': first.get('quote'), 'source': first.get('source'),
                                      'message_id': message_id} if isinstance(first, dict) else None,
                 'case_id': cid, 'version': 1, 'status': 'proposed', 'location_confirmed': False, 'facts': [payload],
                 'actions': [], **payload, 'unlinked_from': case['case_id']}
        self._append({'schema_version': 1, 'kind': 'repost_unlink', 'case_id': case['case_id'], 'actor': redact(actor.strip()),
                      'provenance': link['provenance'], 'projections': [updated, fresh]})
        return self._read_case(case['case_id'])

    def append_reply(self, case_id, expected_version, case):
        case = redact_data(case)
        with self.locked():
            cases, _ = self._read()
            if case_id not in cases:
                raise KeyError(case_id)
            if cases[case_id].get('status','').startswith('ASSIGNED:'):
                raise Conflict('Cancele a missão antes de responder ao caso atribuído.')
            if cases[case_id].get('merge_state') or cases[case_id].get('status','').startswith('MERGED_INTO:'):
                raise Conflict('Desfaça a união antes de responder.')
            if cases[case_id]['version'] != expected_version:
                raise Conflict('Versão alterada. Recarregue e revise o caso.')
            case.update(last_update_at=case['received_at'], stale=False,
                        open_items=[i for i in case.get('open_items',[]) if i.get('reason')!='stale'],
                        status='proposed', location_confirmed=False, approved_asset=None,
                        caution_acknowledgement=None, parent_version=expected_version)
            self._append({'schema_version':1, 'kind':'analysis', 'case_id':case_id,
                'provenance':case['message_id']+':reply:'+str(expected_version),
                'version':expected_version+1, 'case':case})
            return self._read_case(case_id)

    def read(self, case_id=None):
        with self.locked():
            cases, _ = self._read(shared=True)
            return copy.deepcopy(cases.get(case_id) if case_id else sorted(cases.values(), key=lambda c: -c['result']['priority']))

    def queue_view(self):
        """Copy only queue/scoring fields, never complete fact or agent histories."""
        from app.case_summary import project
        with self.locked():
            cases, _ = self._read(shared=True)
            return [project(c, scoring=True) for c in sorted(cases.values(), key=lambda c: -c['result']['priority'])]

    def action(self, case_id, action, expected_version, actor, *, human=False, asset=None, caution_acknowledged=False, target_case_id=None, target_expected_version=None, mission=None, mission_inventory=None, mission_id=None, expected_versions=None, event_at=None):
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
            if action in ('approve_mission', 'cancel_mission'):
                from app.missions.actions import apply
                return apply(self, cases, case, action, actor, mission, mission_inventory,
                             mission_id, expected_versions, caution_acknowledged, event_at)
            if case['status'].startswith('ASSIGNED:'):
                raise Conflict('Caso em missão; cancele a missão antes de outra ação.')
            if action == 'unlink_report':  # target_case_id carries the repost's message_id
                return self._unlink(cases, case, actor, target_case_id)
            if action in ('merge', 'unmerge'):
                return self._merge(cases, case, action, actor, target_case_id, target_expected_version)
            status = case['status']
            if status.startswith('MERGED_INTO:'):
                raise Conflict('Caso unido; use o caso principal.')
            allowed = {'confirm_location', 'approve_dispatch', 'dispatch', 'field_confirm', 'request_callback', 'report_rescued', 'approve_mission', 'cancel_mission'}
            if action not in allowed:
                raise ValueError('Ação desconhecida.')
            if status == 'field_confirmed':
                raise ValueError('Caso confirmado em campo; nova observação exige nova revisão.')
            if action == 'approve_dispatch' and (not case['location_confirmed'] or status not in ('proposed','PARTIAL')
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
            if action == 'confirm_location' and status not in ('proposed','PARTIAL'):
                raise ValueError('Localização só pode ser confirmada durante a proposta.')
            self._append({'schema_version': 1, 'kind': 'action', 'case_id': case_id,
                          'version': case['version']+1, 'action': action, 'actor': redact(actor.strip()),
                          **({'asset':asset,'caution_acknowledgement':acknowledgement} if action=='approve_dispatch' else {})})
            if action == 'confirm_location':
                from app.memory.service import PlaceMemory
                PlaceMemory(self).confirmed(self._read_case(case_id))
            return self._read_case(case_id)

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
                if c['status'].startswith('ASSIGNED:'):
                    raise Conflict('Caso em missão; cancele a missão antes de unir.')
                if c.get('merge_state') or c['status'].startswith('MERGED_INTO:') or c['status'] in ('human_approved','dispatched','field_confirmed'):
                    raise Conflict('Caso unido ou despacho ativo; união indisponível.')
            a,b = copy.deepcopy(case),copy.deepcopy(other)
            before = [copy.deepcopy(case),copy.deepcopy(other)]
            for c in (a,b):
                c['version'] += 1
                c['actions'].append({'action':'merge','actor':redact(actor.strip()),'version':c['version'],'target_case_id':target_id})
            a['linked_reports'] = copy.deepcopy(a.get('linked_reports', [])) + copy.deepcopy(b.get('linked_reports', []))
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
        return self._read_case(case['case_id'])

    def record_feedback(self, case_id, expected_version, report, actor, received_at, source, mission_id=None):
        from app.feedback import apply
        with self.locked():
            cases, _ = self._read()
            if case_id not in cases: raise KeyError(case_id)
            case = cases[case_id]
            if case['version'] != expected_version: raise Conflict('Versao alterada; revise o retorno.')
            if case.get('merge_state') or case.get('status','').startswith('MERGED_INTO:'):
                raise Conflict('Desfaca a uniao antes do retorno de campo.')
            if case.get('status') in ('RESCUED','field_confirmed'):
                raise Conflict('Caso encerrado; nova observacao exige revisao humana.')
            if mission_id and (case.get('mission_id') != mission_id or case.get('mission_stop_done')):
                raise Conflict('Parada nao pertence a esta missao ativa.')
            projection = apply(case, report, actor, received_at, source)
            self._append({'schema_version':1,'kind':'field_feedback','case_id':case_id,
                          'projections':[projection]})
            return copy.deepcopy(projection)

    def detect_stale(self, now=None, hours=None):
        from app.priority import stale_info
        with self.locked():
            cases, _ = self._read(shared=True); changed=[]
            for case in cases.values():
                clock=now or case['replay_time']
                info=stale_info(case,clock,hours)
                if not info['stale'] or any(i.get('reason')=='stale' for i in case.get('open_items',[])): continue
                c=copy.deepcopy(case)
                c.setdefault('open_items',[]).append({'field':'contact','reason':'stale',
                    'question':'Ainda estao no local?', 'created_at':clock,
                    'last_update_at':c.get('last_update_at',c['received_at'])})
                c['stale']=True;c['version']+=1
                c.setdefault('actions',[]).append({'action':'stale_callback','version':c['version'],'received_at':clock})
                changed.append(c)
            if changed: self._append({'schema_version':1,'kind':'stale_callback','projections':changed})
            return len(changed)
