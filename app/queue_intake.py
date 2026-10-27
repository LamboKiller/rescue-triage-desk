"""Accept-and-queue intake: a request is NEVER bounced or hidden.

POST /run {async:true} and POST /api/intake persist every raw message at once (idempotent by
message id; exact/near reposts are linked before any model call), answer 202 with a queue
position, and a bounded worker pool (NIGHTSHIFT_MAX_CONCURRENCY) drains the queue by
provisional priority then age, with a starvation guard. Waiting messages are shown as
"em fila" cards computed by app.queue_pretriage (deterministic, never dispatches); the agent
pipeline result replaces the card. Backpressure is queue length only; above the backlog
threshold "modo surto" skips advisory stages (visible in every affected case).
"""
import copy
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.config import setting
from app.queue_pretriage import pretriage, text_hash, fold

HEAVY = ('facts', 'fleet', 'hazard_facts', 'hazards', 'fleet_summary', 'incident_state')
STATES = ('queued', 'running', 'final', 'failed')


def _int(name, default):
    try:
        return max(1, int(float(setting(name, str(default)))))
    except (TypeError, ValueError):
        return default


def near_key(text):
    """Order-insensitive token multiset signature + digit tokens (addresses must match exactly)."""
    tokens = re.findall(r'[a-z0-9]+', fold(text))
    return frozenset(tokens), tuple(sorted(t for t in tokens if any(c.isdigit() for c in t)))


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds')


def lean(case):
    """Run-result view: identity + decision fields only (the registry keeps the full record)."""
    out = {k: v for k, v in case.items() if k not in HEAVY}
    out['facts'] = [{'message_id': f.get('message_id')} for f in case.get('facts') or [] if isinstance(f, dict)]
    out['summary'] = True
    return out


class IntakeQueue:
    def __init__(self, pipeline, path, *, workers=None, runner=None, clock=time.time, surge_backlog=None,
                 starve_seconds=None, autostart=True):
        self.pipeline = pipeline
        self.autostart = autostart
        self.path = Path(path)
        self.clock = clock
        self.workers = workers or _int('NIGHTSHIFT_MAX_CONCURRENCY', 2)
        self.surge_backlog = surge_backlog or _int('QUEUE_SURGE_BACKLOG', 30)
        self.starve_seconds = starve_seconds or _int('QUEUE_STARVATION_MIN', 10) * 60
        self.runner = runner or self._default_runner
        self.cond = threading.Condition(threading.RLock())
        self.items = OrderedDict()
        self.by_hash = {}
        self.near = []  # (frozenset, digits, mid) of recent accepted messages
        self.runs = OrderedDict()
        self.run_limit = 300
        self.surge = False
        self.surge_entered = 0
        self.stop = threading.Event()
        self.threads = []
        self.version = 0
        self.journal_lock = threading.Lock()
        self.stats_counter = dict(accepted=0, idempotent=0, linked_at_intake=0, linked_resolved=0,
                                  surge_jobs=0, failed=0, retried=0)
        self._load()
        if autostart and any(r['state'] in ('queued', 'running') for r in self.items.values()):
            self.start()

    # ---- persistence -------------------------------------------------------------------
    def _write(self, rows, sync=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_lock:
            with self.path.open('a', encoding='utf-8') as out:
                for row in rows:
                    out.write(json.dumps(row, ensure_ascii=False, separators=(',', ':'))+'\n')
                out.flush()
                if sync:
                    os.fsync(out.fileno())

    def _load(self):
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind = row.get('k')
            if kind == 'accept':
                self._register(row['message'], row['replay_time'], row['accepted_at'], row.get('duplicate_of'), row.get('run_id'), journal=False)
            elif kind == 'run':
                self.runs[row['run_id']] = dict(run_id=row['run_id'], mids=row['mids'], events=[], status='running', result=None,
                                                created=row.get('at', 0))
            elif kind == 'state' and row['mid'] in self.items:
                rec = self.items[row['mid']]
                rec.update({k: row[k] for k in ('state', 'decision', 'case_id', 'started_at', 'finished_at', 'attempts', 'error', 'surge', 'seconds') if k in row})
        for rec in self.items.values():
            if rec['state'] == 'running':  # interrupted by a restart: back to the queue, never lost
                rec['state'] = 'queued'
        with self.cond:
            for run in self.runs.values():
                self._maybe_complete(run, journal=False)

    # ---- accept ------------------------------------------------------------------------
    def _register(self, message, replay, accepted_at, duplicate_of, run_id, journal=True):
        mid = message['message_id']
        rec = dict(message_id=mid, case_id=hashlib.sha256(mid.encode()).hexdigest()[:24], message=message,
                   text=message['text'], received_at=message['received_at'], replay_time=replay,
                   accepted_at=accepted_at, text_hash=text_hash(message['text']), pre=pretriage(message['text']),
                   state='queued', duplicate_of=duplicate_of, run_ids=[run_id] if run_id else [], attempts=0,
                   started_at=None, finished_at=None, decision=None, error=None, surge=False, seconds=None)
        if message.get('_callback'):
            rec['case_id'] = message['_callback']['case_id']
        self.items[mid] = rec
        self.by_hash.setdefault(rec['text_hash'], mid)
        tokens, digits = near_key(message['text'])
        self.near.append((tokens, digits, mid))
        if len(self.near) > 400:
            del self.near[:100]
        return rec

    def _find_primary(self, message):
        digest = text_hash(message['text'])
        mid = self.by_hash.get(digest)
        if mid and mid != message['message_id']:
            return mid, 'texto idêntico'
        tokens, digits = near_key(message['text'])
        if len(tokens) < 8:
            return None, None
        for other, other_digits, other_mid in reversed(self.near):
            if other_mid != message['message_id'] and other_digits == digits and \
                    len(tokens & other)/max(1, len(tokens | other)) >= .92:
                return other_mid, 'texto quase idêntico'
        return None, None

    def accept(self, request, *, callback=None):
        from app.pipeline import validate_request
        if isinstance(request, dict) and isinstance(request.get('messages'), list) and len(request['messages']) > 15 \
                and request.get('_bulk'):
            chunks = [request['messages'][i:i+15] for i in range(0, len(request['messages']), 15)]
        else:
            chunks = [None]
        accepted, now, run_id = [], self.clock(), uuid.uuid4().hex
        rows, mids = [], []
        replay = None
        with self.cond:
            for chunk in chunks:
                replay, clean = validate_request(request if chunk is None else dict(request, messages=chunk))
                for message in clean:
                    if callback is not None:
                        message['_callback'] = callback
                    mid = message['message_id']
                    existing = self.items.get(mid)
                    mids.append(mid)
                    if existing is not None:
                        self.stats_counter['idempotent'] += 1
                        if run_id not in existing['run_ids']:
                            existing['run_ids'].append(run_id)
                        accepted.append((existing, True))
                        continue
                    primary, why = (None, None) if callback is not None else self._find_primary(message)
                    rec = self._register(message, replay, now, primary, run_id)
                    if primary:
                        rec['duplicate_why'] = why
                        self.stats_counter['linked_at_intake'] += 1
                    self.stats_counter['accepted'] += 1
                    rows.append(dict(k='accept', message=message, replay_time=replay, accepted_at=now, duplicate_of=primary, run_id=run_id))
                    accepted.append((rec, False))
            self.runs[run_id] = dict(run_id=run_id, mids=mids, events=[], status='running', result=None, created=now)
            while len(self.runs) > self.run_limit:
                self.runs.popitem(last=False)
            rows.append(dict(k='run', run_id=run_id, mids=mids, at=now))
            self._write(rows, sync=True)  # persisted before the 202
            run = self.runs[run_id]
            positions = self._positions()
            for rec, _ in accepted:
                self._emit(run, 'received', case_id=rec['case_id'])
                self._emit(run, 'queued', case_id=rec['case_id'], state=rec['state'], position=positions.get(rec['message_id']))
            self.version += 1
            self._maybe_complete(run)
            out = dict(run_id=run_id, status=run['status'] if run['status'] != 'complete' else 'complete', accepted=len(accepted),
                       queue=self.summary(limit=0),
                       messages=[self._ack(rec, positions, dup) for rec, dup in accepted])
            self.cond.notify_all()
        if self.autostart:
            self.start()
        return out

    def _ack(self, rec, positions, already):
        return dict(message_id=rec['message_id'], case_id=rec['case_id'], state=rec['state'], position=positions.get(rec['message_id']),
                    priority=dict(level=rec['pre']['level'], score=rec['pre']['score'], provisional=True),
                    duplicate_of=rec['duplicate_of'], already_known=already)

    # ---- scheduling --------------------------------------------------------------------
    def _key(self, rec, now):
        age = now-rec['accepted_at']
        penalty = 100 if rec['duplicate_of'] else 0
        if age >= self.starve_seconds:
            return (0, rec['accepted_at'], rec['message_id'])  # starvation guard: oldest first, ahead of everything
        return (1, -(rec['pre']['score']-penalty), rec['accepted_at'], rec['message_id'])

    def _pending(self):
        return [r for r in self.items.values() if r['state'] in ('queued', 'running') and r['state'] == 'queued']

    def _positions(self):
        now = self.clock()
        ordered = sorted(self._pending(), key=lambda r: self._key(r, now))
        return {r['message_id']: i+1 for i, r in enumerate(ordered)}

    def _pick(self):
        now = self.clock()
        best, best_key = None, None
        for rec in self.items.values():
            if rec['state'] != 'queued':
                continue
            primary = self.items.get(rec['duplicate_of']) if rec['duplicate_of'] else None
            if primary is not None and primary['state'] in ('queued', 'running'):
                continue  # wait for the primary; the link then costs no model call
            key = self._key(rec, now)
            if best is None or key < best_key:
                best, best_key = rec, key
        return best

    def _update_surge(self, backlog):
        if not self.surge and backlog > self.surge_backlog:
            self.surge, self.surge_entered = True, self.clock()
        elif self.surge and backlog <= max(1, self.surge_backlog//2):
            self.surge = False
        return self.surge

    def start(self):
        with self.cond:
            self.threads = [t for t in self.threads if t.is_alive()]
            if self.workers:
                sys.setswitchinterval(min(sys.getswitchinterval(), .002))  # keep HTTP threads responsive next to CPU-bound analysis
            while len(self.threads) < self.workers:
                thread = threading.Thread(target=self._loop, daemon=True, name=f'rtd-intake-{len(self.threads)}')
                self.threads.append(thread)
                thread.start()

    def close(self):
        self.stop.set()
        with self.cond:
            self.cond.notify_all()

    def _loop(self):
        while not self.stop.is_set():
            with self.cond:
                rec = self._pick()
                if rec is None:
                    self.cond.wait(1.0)
                    continue
                backlog = sum(1 for r in self.items.values() if r['state'] == 'queued')
                surge = self._update_surge(backlog)
                rec.update(state='running', started_at=self.clock(), surge=surge, attempts=rec['attempts']+1)
                self.stats_counter['surge_jobs'] += int(surge)
                self.version += 1
                self._write([self._state_row(rec)])
            try:
                case = self.runner(rec, surge)
                decision = ((case or {}).get('result') or {}).get('decision') or ('LINKED' if rec.get('linked') else None)
                finish = dict(state='final', decision=decision, error=None, finished_at=self.clock(),
                              seconds=round(self.clock()-rec['started_at'], 3))
                view = lean(case) if isinstance(case, dict) else None
            except Exception as exc:
                view = None
                retry = rec['attempts'] < 2
                self.stats_counter['retried' if retry else 'failed'] += 1
                finish = dict(state='queued' if retry else 'failed', error=type(exc).__name__, finished_at=None)
            with self.cond:
                rec.update(finish)
                rec['view'] = view
                self.version += 1
                self._write([self._state_row(rec)])
                if rec['state'] in ('final', 'failed'):
                    for run_id in rec['run_ids']:
                        run = self.runs.get(run_id)
                        if run:
                            if rec['state'] == 'final':
                                self._emit(run, 'decision' if rec['decision'] == 'LINKED' else 'finalized', case_id=rec['case_id'], decision=rec['decision'])
                            self._maybe_complete(run)
                self.cond.notify_all()

    def _state_row(self, rec):
        return dict(k='state', mid=rec['message_id'], **{k: rec[k] for k in ('state', 'decision', 'case_id', 'started_at', 'finished_at', 'attempts', 'error', 'surge', 'seconds')})

    # ---- default runner ----------------------------------------------------------------
    def _default_runner(self, rec, surge):
        from app.llm.nightshift import MESSAGE_PRIORITY
        pipeline = self.pipeline
        if rec['message'].get('_callback'):
            service = getattr(self, 'callback_service', None)
            if service is None:
                from app.callback.service import CallbackService
                service = CallbackService(pipeline.registry, pipeline, records={})
            MESSAGE_PRIORITY.set(int(rec['pre']['score']))
            return service.run_queued(rec, surge)
        if rec['duplicate_of']:
            linked = self._try_link(rec)
            if linked is not None:
                rec['linked'] = True
                self.stats_counter['linked_resolved'] += 1
                return linked
        MESSAGE_PRIORITY.set(int(rec['pre']['score']))
        def sink(stage, **data):
            with self.cond:
                for run_id in rec['run_ids']:
                    run = self.runs.get(run_id)
                    if run:
                        self._emit(run, stage, **data)
        summary = pipeline._run(rec['_replay'] if '_replay' in rec else rec['replay_time'], [rec['message']], 'full',
                                event_sink=sink, run_id=rec['run_ids'][0] if rec['run_ids'] else None, surge=surge)
        return summary['cases'][0]

    def _try_link(self, rec):
        """Attach an exact/near repost to its finished primary WITHOUT model calls, only when the
        registry's own place-aware repost rule agrees; otherwise it is analysed normally."""
        from app.duplicates import find_repost
        registry = self.pipeline.registry
        try:
            case = self.pipeline.failed_case(rec['message'], rec['replay_time'], 'intake-link', 'duplicate_link', [])
            cid = rec['case_id']
            if find_repost({**case, 'case_id': cid}, registry.read()) is None:
                return None
            ingested = registry.ingest(case)
            if any(r.get('message_id') == rec['message_id'] for r in ingested.get('linked_reports', [])):
                return ingested
        except Exception:
            return None
        return None

    # ---- runs (SSE + polling compatible with RunStore) ---------------------------------
    def _emit(self, run, stage, **fields):
        run['events'].append({'stage': stage, 'run_id': run['run_id'], 'case_id': None, 'role': None, 'model': None,
                              'receipt': None, 'seconds': 0, **fields})
        self.cond.notify_all()

    def _maybe_complete(self, run, journal=True):
        if run['status'] != 'running':
            return
        recs = [self.items[m] for m in run['mids'] if m in self.items]
        if any(r['state'] in ('queued', 'running') for r in recs):
            return
        cases, seen = [], set()
        for rec in recs:
            view = rec.get('view')
            if view is None:
                try:
                    full = self.pipeline.registry.read(rec['case_id'])
                    view = lean(full) if full else None
                except Exception:
                    view = None
            if view is not None and view.get('case_id') not in seen:
                seen.add(view.get('case_id'))
                cases.append(view)
        failed = [r['message_id'] for r in recs if r['state'] == 'failed']
        run['result'] = dict(run_id=run['run_id'], mode='sample_offline' if getattr(self.pipeline, 'sample', False) else 'full',
                             synthetic=True, cases=cases, failed_messages=failed, queued_seconds=round(self.clock()-run['created'], 3),
                             partial=bool(failed))
        run['status'] = 'complete'
        self._emit(run, 'done', seconds=run['result']['queued_seconds'])

    def has_run(self, run_id):
        with self.cond:
            return run_id in self.runs

    def read_run(self, run_id):
        with self.cond:
            run = self.runs.get(run_id)
            if run is None:
                return None
            return copy.deepcopy({k: v for k, v in run.items() if k not in ('events', 'mids', 'created')})

    def events(self, run_id):
        index = 0
        while True:
            with self.cond:
                run = self.runs.get(run_id)
                if run is None:
                    return
                batch = copy.deepcopy(run['events'][index:])
                index += len(batch)
                done = run['status'] != 'running'
                # One shared condition wakes every stream on any event: wait until THIS run has news
                # (or 10 s passed) so idle streams do not spin out keep-alives and starve the UI.
                end = time.monotonic()+10
                while not batch and not done and time.monotonic() < end:
                    self.cond.wait(timeout=max(.05, end-time.monotonic()))
                    batch = copy.deepcopy(run['events'][index:])
                    index += len(batch)
                    done = run['status'] != 'running'
            for event in batch:
                yield 'event: '+event['stage']+'\ndata: '+json.dumps(event, ensure_ascii=False)+'\n\n'
            if done:
                return
            if not batch:
                yield ': keep-alive\n\n'

    # ---- views -------------------------------------------------------------------------
    def label(self, rec, now):
        minutes = max(0, int((now-rec['accepted_at'])//60))
        age = 'há menos de 1 min' if minutes < 1 else f'há {minutes} min'
        if rec['state'] == 'failed':
            return f'em fila · falha ao analisar; revisar manualmente · {age}'
        if rec['state'] == 'running':
            return f'em fila · agentes analisando agora · {age}'
        if rec['duplicate_of']:
            return f"em fila · repetição de outro relato; aguardando o original · {age}"
        return f'em fila · aguardando agentes · {age}'

    def card(self, rec, now, position=None, full=False):
        pre = rec['pre']
        label = self.label(rec, now)
        text = rec['text'] if full or len(rec['text']) <= 400 else rec['text'][:400]+'…'
        return {'case_id': rec['case_id'], 'message_id': rec['message_id'], 'text': text, 'received_at': rec['received_at'],
                'replay_time': rec['replay_time'], 'summary': True, 'queued': True, 'queue_state': rec['state'],
                'queue_position': position, 'age_seconds': int((now-rec['accepted_at'])//5*5), 'accepted_at': iso(rec['accepted_at']),
                'label_pt': label, 'status': 'EM_FILA', 'version': 0, 'complete': False, 'fields': {}, 'facts': [], 'fleet': [],
                'linked_reports': [], 'errors': [], 'calls': [], 'duplicate_of': rec['duplicate_of'],
                'live_priority': {'score': pre['score'], 'level': pre['level'], 'provisional': True, 'reasons': pre['reasons']},
                'pre_triage': {k: pre[k] for k in ('score', 'level', 'life_risk', 'injection', 'location_strength', 'provisional', 'dispatch')},
                'result': {'decision': 'QUEUED', 'decision_reason': label, 'priority': pre['score'], 'provisional': True,
                           'next_action_pt': 'Sem despacho: aguardando análise dos agentes e aprovação humana.'}}

    def card_items(self, full=False):
        """[(score, json)] for /api/cases. Per-record JSON is cached per state and 5 s age bucket
        so a 600-card poll does no per-card rebuild; queue_position is left to /api/queue."""
        with self.cond:
            now = self.clock()
            out = []
            for r in self.items.values():
                if r['state'] not in ('queued', 'running', 'failed'):
                    continue
                key = (r['state'], int((now-r['accepted_at'])//5), int((now-r['accepted_at'])//60), full)
                hit = r.get('_json')
                if hit is None or hit[0] != key:
                    card = self.card(r, now, None, full)
                    hit = r['_json'] = (key, json.dumps(card, ensure_ascii=False, separators=(',', ':')))
                out.append((r['pre']['score'], hit[1]))
        return out

    def cards(self, full=False):
        with self.cond:
            now = self.clock()
            positions = self._positions()
            out = [self.card(r, now, positions.get(r['message_id']), full) for r in self.items.values()
                   if r['state'] in ('queued', 'running', 'failed')]
        out.sort(key=lambda c: (-c['live_priority']['score'], c['received_at'], c['case_id']))
        return out

    def card_for(self, case_id):
        with self.cond:
            now = self.clock()
            for r in self.items.values():
                if r['case_id'] == case_id and r['state'] in ('queued', 'running', 'failed'):
                    return self.card(r, now, self._positions().get(r['message_id']), full=True)
        return None

    def summary(self, limit=50):
        with self.cond:
            now = self.clock()
            counts = {s: 0 for s in STATES}
            levels = {'P1': 0, 'P2': 0, 'P3': 0}
            for r in self.items.values():
                counts[r['state']] += 1
                if r['state'] in ('queued', 'running'):
                    levels[r['pre']['level']] += 1
            pending = [r for r in self.items.values() if r['state'] in ('queued', 'running')]
            out = dict(total_accepted=len(self.items), queued=counts['queued'], running=counts['running'], final=counts['final'],
                       failed=counts['failed'], backlog=counts['queued'], by_level_waiting=levels,
                       oldest_age_seconds=int(max([now-r['accepted_at'] for r in pending] or [0])),
                       surge=dict(active=self.surge, threshold=self.surge_backlog, label_pt='modo surto' if self.surge else None),
                       workers=self.workers, starvation_seconds=self.starve_seconds, counters=dict(self.stats_counter),
                       persisted=True)
            if limit:
                positions = self._positions()
                ordered = sorted((r for r in self.items.values() if r['state'] in ('queued', 'running', 'failed')),
                                 key=lambda r: (r['state'] != 'running', positions.get(r['message_id'], 0)))
                out['items'] = [dict(message_id=r['message_id'], state=r['state'], position=positions.get(r['message_id']),
                                     level=r['pre']['level'], score=r['pre']['score'], age_seconds=int(now-r['accepted_at']),
                                     duplicate_of=r['duplicate_of']) for r in ordered[:limit]]
        try:
            from app.llm.nightshift import CALL_SLOTS
            out['provider'] = CALL_SLOTS.stats()
        except Exception:
            pass
        return out

    def message_state(self, message_id):
        with self.cond:
            rec = self.items.get(message_id)
            if rec is None:
                for r in self.items.values():
                    if r['case_id'] == message_id:
                        rec = r
                        break
            if rec is None:
                return None
            pos = self._positions().get(rec['message_id'])
            return dict(message_id=rec['message_id'], case_id=rec['case_id'], state=rec['state'], position=pos,
                        decision=rec['decision'], duplicate_of=rec['duplicate_of'], attempts=rec['attempts'], surge_mode=rec['surge'],
                        accepted_at=iso(rec['accepted_at']), age_seconds=int(self.clock()-rec['accepted_at']),
                        priority=dict(level=rec['pre']['level'], score=rec['pre']['score'], provisional=True), error=rec['error'])

    def wait_idle(self, timeout=30):
        end = time.monotonic()+timeout
        with self.cond:
            while any(r['state'] in ('queued', 'running') for r in self.items.values()):
                left = end-time.monotonic()
                if left <= 0:
                    return False
                self.cond.wait(min(.2, left))
        return True


# ---- HTTP glue (used by app/web/server.py) --------------------------------------------------
def read_json_body(handler):
    length = int(handler.headers.get('Content-Length', '0'))
    if not 0 < length <= 256000:
        raise ValueError('JSON ausente ou maior que 256 KB.')
    handler.connection.settimeout(10)
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ValueError('JSON incompleto.')
    return raw


def handle_post(handler, intake, path):
    """True when handled. Non-async /run bodies are replayed to the legacy handler untouched."""
    if path not in ('/run', '/api/intake'):
        return False
    try:
        origin = handler.headers.get('Origin')
        if origin and urlsplit(origin).netloc != handler.headers.get('Host'):
            handler.send_json(403, {'error': 'Origem não permitida.'})
            return True
        if not handler.headers.get('Content-Type', '').startswith('application/json'):
            handler.send_json(415, {'error': 'Use application/json.'})
            return True
        raw = read_json_body(handler)
        request = json.loads(raw.decode('utf-8'))
        if path == '/run' and not (isinstance(request, dict) and request.get('async') is True):
            handler.rfile = io.BytesIO(raw)
            return False
        if not isinstance(request, dict):
            raise ValueError('Envie um objeto JSON.')
        handler.send_json(202, intake.accept(dict(request, _bulk=path == '/api/intake')))
    except (ValueError, TypeError, UnicodeError) as exc:
        handler.send_json(400, {'error': str(exc) if type(exc) is ValueError else 'JSON ou parâmetros inválidos.'})
    except Exception:
        handler.send_json(500, {'error': 'Falha interna ao registrar o pedido; reenvie (é idempotente).'})
    return True


def handle_get(handler, intake, path):
    if path == '/api/queue':
        handler.send_json(200, intake.summary())
        return True
    if path.startswith('/api/queue/') and len(path.split('/')) == 4:
        state = intake.message_state(path.split('/')[3])
        handler.send_json(200 if state else 404, state or {'error': 'Mensagem não encontrada na fila.'})
        return True
    if path.startswith('/api/runs/') and intake.has_run(path.split('/')[3]):
        run_id = path.split('/')[3]
        if path == '/api/runs/'+run_id+'/events':
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            handler.send_header('Cache-Control', 'no-cache')
            handler.send_header('Connection', 'keep-alive')
            handler.end_headers()
            try:
                for event in intake.events(run_id):
                    handler.wfile.write(event.encode('utf-8'))
                    handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            handler.close_connection = True
        elif path == '/api/runs/'+run_id:
            handler.send_json(200, intake.read_run(run_id))
        else:
            return False
        return True
    return False
