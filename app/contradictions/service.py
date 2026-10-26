"""Contradiction items: attach (after the decision), journal events, human decisions. Advisory only.

Journal events (kind='contradiction', skipped by the World Model projection, read by the Fluxo tab):
  detected {case_id, items:[{id,kind,strength}]}      phrased {case_id, item_id, question_pt, phrased_by, fallback_reason, calls}
  decision {case_id, item_id, decision, actor, execution}
No code path here changes result.decision, priority, status or an asset; 'confirm' on a suggestion calls the
human-only World Model action `report_rescued` (status becomes reported_rescued_unconfirmed; the crew still confirms).
"""
import copy
import hashlib
import json
import threading
import time
from app.contradictions import phrase as phrasing
from app.contradictions.detectors import detect, STRENGTHS
from app.decide import timestamp
from app.redact import redact

DECISIONS = ('acknowledge', 'dismiss', 'confirm')
PENDING = []  # background workers (tests join them)
PHRASE_LOCK = threading.Lock()
QUESTION_FROM = ('medium', 'strong')


def case_key(message_id):
    return hashlib.sha256(message_id.encode()).hexdigest()[:24]


def attach(case, *, key, peers=(), shelters=None, now=None):
    """Mutate `case` with items; return them. Never touches decision/priority/status."""
    started = time.perf_counter()
    items = detect(case, case_key=key, peers=peers, shelters=shelters, now=now)
    case['cross_source'] = items
    open_items = [i for i in case.get('open_items') or [] if i.get('reason') != 'contradiction']
    questions = list((case.get('result') or {}).get('questions') or [])
    for it in items:
        open_items.append({'field': 'contradiction', 'reason': 'contradiction', 'contradiction_id': it['id'], 'kind': it['kind'],
                           'strength': it['strength'], 'question': it['question_pt'] if it['strength'] in QUESTION_FROM else None,
                           'sources': [{k: s[k] for k in ('role', 'source', 'ref', 'quote')} for s in it['sources']]})
        if it['strength'] in QUESTION_FROM and it['question_pt'] not in questions:
            questions.append(it['question_pt'])
    case['open_items'] = open_items
    if items and isinstance(case.get('result'), dict):
        case['result']['questions'] = questions
    case['contradiction_check'] = {'items': len(items), 'by_strength': {s: sum(i['strength'] == s for i in items) for s in STRENGTHS},
                                   'seconds': round(time.perf_counter() - started, 4), 'model_in_triage_path': False}
    return items


class ContradictionService:
    def __init__(self, registry, client=None):
        self.registry = registry
        self.client = client

    # ---- journal ------------------------------------------------------------------------------
    def append(self, event):
        event = json.loads(redact(json.dumps({'schema_version': 1, 'kind': 'contradiction', **event}, ensure_ascii=False)))
        with self.registry.locked():
            self.registry._append(event)
        return event

    def events(self):
        out = []
        with self.registry.locked():
            if self.registry.path.exists():
                for line in self.registry.path.read_text(encoding='utf-8').splitlines():
                    if '"kind":"contradiction"' in line:
                        e = json.loads(line)
                        if e.get('kind') == 'contradiction':
                            out.append(e)
        return out

    def overlay(self, case_id, items):
        """Items + what happened to them since: phrasing (model or visible fallback) and the human decision."""
        events = [e for e in self.events() if e.get('case_id') == case_id]
        out = []
        for it in items:
            it = copy.deepcopy(it)
            for e in events:
                if e.get('item_id') != it['id']:
                    continue
                if e['type'] == 'phrased':
                    it['phrasing'] = {k: e.get(k) for k in ('phrased_by', 'fallback_reason', 'seconds')}
                    if e.get('question_pt'):
                        it['question_pt'] = e['question_pt']
                        it['phrased_by'] = 'model'
                    else:
                        it['phrased_by'] = 'template'
                elif e['type'] == 'decision':
                    it['state'] = {'acknowledge': 'acknowledged', 'dismiss': 'dismissed', 'confirm': 'confirmed'}[e['decision']]
                    it['decision'] = {k: e.get(k) for k in ('decision', 'actor', 'at', 'execution')}
            out.append(it)
        return out

    def view(self, case_id):
        case = self.registry.read(case_id)
        if case is None:
            raise KeyError(case_id)
        return {'case_id': case_id, 'version': case['version'], 'status': case.get('status'),
                'items': self.overlay(case_id, case.get('cross_source') or []),
                'check': case.get('contradiction_check')}

    # ---- human decision -----------------------------------------------------------------------
    def decide(self, case_id, item_id, decision, actor, expected_version):
        if decision not in DECISIONS:
            raise ValueError('Decisão desconhecida.')
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 120:
            raise ValueError('Identifique o operador.')
        if type(expected_version) is not int:
            raise ValueError('Informe expected_version inteiro.')
        view = self.view(case_id)
        item = next((i for i in view['items'] if i['id'] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if item['state'] != 'open':
            raise ValueError('Item já tratado.')
        execution = None
        if decision == 'confirm':
            sug = item.get('suggestion')
            if not sug:
                raise ValueError('Este item não tem sugestão a confirmar.')
            case = self.registry.action(case_id, sug['action'], expected_version, actor.strip(), human=True)
            execution = {'action': sug['action'], 'status': case['status'], 'version': case['version']}
        self.append({'type': 'decision', 'case_id': case_id, 'item_id': item_id, 'decision': decision, 'actor': redact(actor.strip()),
                     'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'replay_time': (self.registry.read(case_id) or {}).get('replay_time'),
                     'kind_of_item': item['kind'], 'strength': item['strength'], 'execution': execution})
        return self.view(case_id)

    # ---- background: journal + model phrasing, strictly after the decision --------------------
    def finish(self, case_id, items, replay_time, client=None, wait=60):
        """Wait until the case is in the World Model, then journal `detected` and phrase STRONG items. Never raises."""
        try:
            end = time.monotonic() + wait
            while self.registry.read(case_id) is None:
                if time.monotonic() > end:
                    return
                time.sleep(.2)
            self.append({'type': 'detected', 'case_id': case_id, 'replay_time': replay_time,
                         'items': [{'id': i['id'], 'kind': i['kind'], 'strength': i['strength'], 'suggestion': bool(i.get('suggestion'))} for i in items]})
            for it in items:
                if it['strength'] != 'strong':
                    continue
                with PHRASE_LOCK:
                    question, meta = phrasing.phrase(it, client)
                self.append({'type': 'phrased', 'case_id': case_id, 'item_id': it['id'], 'replay_time': replay_time, 'question_pt': question,
                             'phrased_by': meta['phrased_by'], 'fallback_reason': meta['fallback_reason'], 'seconds': meta.get('seconds'),
                             'calls': meta['calls']})
        except Exception:
            pass

    def schedule(self, jobs, client=None):
        """jobs = [(case_id, items, replay_time)]; returns the daemon thread (also kept in PENDING)."""
        jobs = [j for j in jobs if j[1]]
        if not jobs:
            return None
        if client is None:
            # Offline / no provider: nothing to phrase (the template question is already on the case), so journal now and start
            # no thread. A polling thread outliving short-lived registries (evals, tests) kept events.jsonl open on Windows.
            for case_id, items, when in jobs:
                try:
                    self.append({'type': 'detected', 'case_id': case_id, 'replay_time': when,
                                 'items': [{'id': i['id'], 'kind': i['kind'], 'strength': i['strength'],
                                            'suggestion': bool(i.get('suggestion'))} for i in items]})
                except Exception:
                    pass
            return None

        def work():
            for case_id, items, when in jobs:
                self.finish(case_id, items, when, client)

        t = threading.Thread(target=work, name='contradiction-phrase', daemon=True)
        PENDING[:] = [x for x in PENDING if x.is_alive()] + [t]
        t.start()
        return t


def wait_all(timeout=30):
    for t in list(PENDING):
        t.join(timeout)
