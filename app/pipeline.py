"""Bounded per-message agents → deterministic tools → registry.

The only offline extraction is the explicit regex baseline. Ground truth and
saved example answers are never read by this module.
"""
import copy
import concurrent.futures
import contextvars
import hashlib
import json
import threading
import time
import uuid
import re
import math
import os
from pathlib import Path
from app.agents import baseline, intake, critic, hazard_critic, arbiter, location as location_agent
from app.fleet import screen
from app.agents.spans import validate
from app.config import ROOT, safe_error
from app.data.source import LocalSource, ZetarisSource
from app.decide import decide, timestamp
from app.derive_count import CORRECTION, canonical_municipality, count_values, derive_people, written_total
from app.geo.hazards import attach, get_data
from app.geo.streets import lookup
from app.geo.landmarks import match as match_landmark
from app.geo.incident import IncidentIndex
from app.rescue_state import guard_fields, state
from app.llm.nightshift import Nightshift, TRACE_LOCK, diagnostic_message
from app.redact import redact, redact_data
from app.routing import apply_route, finish_route, animal_rescue


class LatencyHistory:
    """Last 20 measured calls per role, shared by messages and persisted locally."""
    lock = threading.RLock()

    def __init__(self, path=None):
        self.path = Path(path) if path else ROOT/'runtime'/'agent_latency.json'

    def read(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return {k: [float(v) for v in values if type(v) in (int, float) and math.isfinite(v) and v >= 0][-20:]
                    for k, values in data.items() if isinstance(values, list)}
        except (OSError, ValueError, AttributeError, TypeError):
            return {}

    def observe(self, role, seconds):
        with self.lock:
            data = self.read()
            data[role] = (data.get(role, [])+[round(seconds, 4)])[-20:]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                pending = self.path.with_suffix('.tmp')
                pending.write_text(json.dumps(data), encoding='utf-8')
                os.replace(pending, self.path)
            except OSError:
                pass  # Telemetry storage cannot interrupt a rescue decision.

    def thresholds(self):
        medians, ceilings = dict(StageBudget.MEDIANS), dict(StageBudget.CEILINGS)
        with self.lock:
            for role, values in self.read().items():
                if role not in medians or not values:
                    continue
                values = sorted(values)
                n = len(values)
                p50 = (values[(n-1)//2]+values[n//2])/2
                medians[role] = max(medians[role], p50)
                if role != 'intake':  # The approved hard intake ceiling stays 48 s.
                    ceilings[role] = max(ceilings[role], values[math.ceil(n*.9)-1])
        return medians, ceilings


def case_counters(case, budget):
    """Public, receipt-based counters; retries count, boundary diagnostics do not."""
    calls = list(budget.receipts)
    real = [r for r in calls if r.get('source') != 'stage_boundary' and r.get('status') != 'skipped']
    for row in calls:
        if row.get('source') == 'stage_boundary' and row.get('invoked') and not any(
                r.get('role') == row['role'] and r.get('source') != 'stage_boundary' for r in calls):
            real.append(row)
    seconds = round(sum(max(0, r.get('seconds', 0) or 0) for r in real), 3)
    skipped = [dict(stage=r['stage'], reason=r.get('reason', 'unavailable')) for r in budget.records
               if r['status'] in ('skipped', 'code_fallback')]
    case['calls'] = calls
    case['nemotron'] = dict(calls=len(real), seconds=seconds, skipped_stages=skipped,
                            label_pt=f'{len(real)} chamadas Nemotron · {seconds:g} s')
    case['agent_evidence'] = dict(calls=len(real), seconds=seconds,
        skipped=[dict(role=r['stage'], reason=r['reason']) for r in skipped])
    case['result'].setdefault('warnings', [])
    for warning in case.get('agent_warnings', []):
        if warning not in case['result']['warnings']:
            case['result']['warnings'].append(warning)


class StageBudget:
    """Remaining message time, with per-call ceilings and deterministic reserve.

    Orbit, 26 Oct 2026: BRIEF_LIVEFIX.md, live2 (78438ef) / holdout_cases.
    Seconds per successful call: role       live2 median/p90  holdout median/p90
                                intake       5.9/17.0          7.4/29.0
                                critic       7.9/22.5         17.0/24.3
                                revision     8.2/12.8          3.9/28.1
                                location     5.1/18.6          8.1/32.0
                                hazard       5.1/13.5          3.7/4.6
    Use the larger median / p90. Unmeasured ID reviewers borrow critic's
    conservative thresholds (a proxy, not measured latency). Location's ceiling
    applies per tool turn; other agent retries share their first call's ceiling.
    Every call also shares the hard message deadline; skipped stages donate time.
    Streaming, thinking, tokens, and rejection of late responses remain unchanged.
    """
    remaining_budget_allocator = True
    RESERVE_SECONDS = 2.
    LONG_INTAKE_SECONDS = 20.
    HAZARD_BUDGET_FRACTION = .6
    # LIVEFIX6: the three retained LF5 location calls have p50=15.25s
    # (4.521 / 15.250 / 25.522). Protect that allowance before optional work.
    MEDIANS = dict(intake=7.4, critic=17., revision=8.2, verifier=17., location=15.25,
                   location_critic=17., hazard=5.1, credibility=17., arbiter=17.,
                   duplicate_reviewer=17.)
    # Orbit 26/10 16:08 live A/B (30-sample, RAM ok): 60 s/intake 29 s 17/30; 90 s/29 s 17/30; 90 s/intake 48 s 22/30,
    # 0 unsafe, mean 33.7 s, p95 61 s. Intake is required and its live tail exceeds its p90, so it gets a wider ceiling.
    CEILINGS = dict(intake=48., critic=24.3, revision=28.1, verifier=28.1, location=32.,
                    location_critic=24.3, hazard=13.5, credibility=24.3, arbiter=24.3,
                    duplicate_reviewer=24.3)

    def __init__(self, client, deadline, seconds, emit=None, *, trace=None, message_id=None, history=None):
        self.client, self.deadline, self.seconds, self.emit = client, deadline, seconds, emit
        self.deadline = min(deadline, time.monotonic()+seconds)
        self.reserve = min(self.RESERVE_SECONDS, seconds*.25)
        self.trace, self.message_id, self.receipts = trace, message_id, []
        self.ends, self.records, self.eligibility = {}, [], {}
        self.attempts = {}
        self.surge = False  # intake backlog policy: advisory stages are skipped (visible 'modo surto')
        self.pressured = False
        self.pressure_kind = None
        self.failure_kinds = []
        self.location_complete = False
        self.intake_seconds = 0.
        self.journal_lock = threading.RLock()
        # Custom trace roots (tests/replays) keep observations in that sandbox.
        history_path = None
        if isinstance(client, Nightshift) and isinstance(getattr(client, 'trace_path', None), Path) and isinstance(ROOT, Path):
            history_path = (ROOT/'runtime'/'agent_latency.json' if client.trace_path.parent == ROOT/'logs' else
                            client.trace_path.parent/'runtime'/'agent_latency.json')
        self.history = history or (LatencyHistory(history_path) if history_path else None)
        if self.history and self.history.read():
            self.MEDIANS, self.CEILINGS = self.history.thresholds()

    def __getattr__(self, key):
        return getattr(self.client, key)

    def record(self, stage, status, **data):
        role = dict(location='location_agent', location_critic='critic', hazard='hazard_critic',
                    credibility='credibility_reviewer').get(stage, stage)
        row = dict(stage=stage, status=status, role=role, seconds=0., queue_seconds=0.,
                   error_class=None, message=data.get('reason', 'Stage '+status))
        row.update(data)
        self.records.append(row)
        if self.emit:
            self.emit('stage_budget', **{k:v for k,v in row.items() if k != 'stage'}, budget_stage=stage)
        if self.trace:
            self.trace.parent.mkdir(exist_ok=True)
            with TRACE_LOCK:
                with self.trace.open('a', encoding='utf-8') as out:
                    out.write(json.dumps(redact_data(dict(kind='stage_budget', message_id=self.message_id, **row)), ensure_ascii=False)+'\n')

    def unavailable(self, stage, role, reason, remaining):
        self.record(stage, 'skipped', role=role, reason=reason, availability='stage_unavailable',
                    failure_kind=self.pressure_kind if reason == 'provider_pressure' else None,
                    note_pt='etapa pulada: modo surto (fila grande; prioridade ao atendimento)' if reason == 'surge_mode' else
                            'etapa pulada: provedor sob pressão' if reason == 'provider_pressure' else
                            'etapa pulada: orçamento protegido para localização' if reason == 'long_intake' else
                            'etapa pulada: orçamento restante insuficiente',
                    remaining_seconds=round(max(0, remaining), 4))

    def location_available(self, deadline):
        remaining = min(deadline, self.deadline-self.reserve)-time.monotonic()
        reason = 'provider_pressure' if self.pressured else 'insufficient_budget' if remaining < self.MEDIANS['location'] else None
        if reason:
            self.unavailable('location', 'location_agent', reason, remaining)
        return reason is None

    def agent_error(self, role, exc):
        """Errors in conversion/validation happen after a successful transport call."""
        if not isinstance(exc, TimeoutError):
            self.failure_kinds.append('agent_failure')
        stage = dict(credibility_reviewer='credibility', hazard_critic='hazard',
                     location_agent='location').get(role, role)
        self.record(stage, 'skipped' if isinstance(exc, TimeoutError) else 'error', role=role,
                    error_class=type(exc).__name__, message=diagnostic_message(exc),
                    **(dict(availability='stage_unavailable') if isinstance(exc, TimeoutError) else
                       dict(failure_kind='agent_failure')))

    def call(self, role, system, payload, deadline):
        stage = ('location' if role.startswith('location') else 'credibility' if role == 'credibility_reviewer'
                 else 'hazard' if role == 'hazard_critic' else role)
        if role == 'critic' and 'location' in self.ends:
            stage = 'location_critic'
        now = time.monotonic()
        remaining = min(deadline, self.deadline-self.reserve)-now
        protected = self.MEDIANS['location'] if not self.location_complete and stage not in ('intake', 'location', 'location_critic') else 0.
        remaining -= protected
        if stage != 'location' and stage in self.ends:
            remaining = min(remaining, self.ends[stage]-now)
        optional = stage not in ('intake', 'location') or self.attempts.get(stage, 0) > 0
        if self.surge and stage not in ('intake', 'location'):
            self.unavailable(stage, role, 'surge_mode', remaining)
            raise TimeoutError('stage_unavailable: surge_mode: '+stage)
        if self.pressured and (stage != 'intake' or self.attempts.get(stage, 0) > 0):
            self.unavailable(stage, role, 'provider_pressure', remaining)
            raise TimeoutError('stage_unavailable: provider_pressure: '+stage)
        if stage in ('critic', 'revision', 'verifier') and self.intake_seconds >= self.LONG_INTAKE_SECONDS:
            self.unavailable(stage, role, 'long_intake', remaining)
            raise TimeoutError('stage_unavailable: long_intake: '+stage)
        if optional and remaining < self.MEDIANS.get(stage, self.MEDIANS['critic']):
            self.unavailable(stage, role, 'insufficient_budget', remaining)
            raise TimeoutError('stage_unavailable: '+stage)
        ceiling = self.CEILINGS.get(stage, self.CEILINGS['critic'])
        if stage == 'location' or stage not in self.ends:
            self.ends[stage] = now+ceiling
        end = min(self.ends[stage], deadline, self.deadline-self.reserve-protected)
        self.attempts[stage] = self.attempts.get(stage, 0)+1
        queue = {'seconds': 0., 'invoked': False}
        journal = []
        closed = False
        def receive(receipt):
            # Publish each retry immediately, independently of future.result().
            with self.journal_lock:
                if not closed:
                    journal.append(receipt)
                    self.receipts.append(receipt)
        def observe(stage_status, **data):
            with self.journal_lock:
                if not closed:
                    self.record(stage, stage_status, role=role, **data)
        pool = None
        from app.llm.nightshift import CancelToken, SLOT_CLASS, REQUIRED_ROLES
        token = CancelToken()  # set in finally: abandoned provider work must stop and free its slot
        try:
            if now >= end:
                raise TimeoutError('Stage budget exhausted: '+stage)
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            def invoke():
                SLOT_CLASS.set('required' if role in REQUIRED_ROLES else 'advisory')
                # Nightshift receipts are thread-local. Carry each call's journal
                # back to the message worker, including unsuccessful attempts.
                try:
                    if isinstance(self.client, Nightshift):
                        self.client.start_message(self.message_id or 'stage')
                        self.client.local.minimum_seconds = self.MEDIANS.get(stage, self.MEDIANS['critic'])
                        self.client.local.receipt_observer = receive
                        self.client.local.cancel = token
                        def queued(seconds, admitted):
                            queue['seconds'] = seconds
                            observe('provider_queue', queue_seconds=round(seconds, 4), admitted=admitted,
                                    **({} if admitted else dict(availability='stage_unavailable')))
                        self.client.local.queue_observer = queued
                        def pressure(kind, status):
                            with self.journal_lock:
                                if not closed:
                                    self.pressured = True
                                    self.pressure_kind = kind
                                    observe('provider_error', failure_kind=kind, http_status=status,
                                            message='Provider call failed')
                        self.client.local.pressure_observer = pressure
                    queue['invoked'] = True
                    value, error = self.client.call(role, system, payload, end), None
                except Exception as exc:
                    value, error = None, exc
                return value, error
            future = pool.submit(contextvars.copy_context().run, invoke)
            value, error = future.result(timeout=max(0, end-time.monotonic()))
            backoff = sum(r.get('backoff_seconds', 0) for r in journal)
            if backoff:
                self.record(stage, 'provider_backoff', backoff_seconds=round(backoff, 4),
                            queue_seconds=round(queue['seconds'], 4))
            if error:
                raise error
            output, meta = value
            if not isinstance(meta, dict):
                raise ValueError('Provider metadata schema invalid')
            if time.monotonic() >= end:
                raise TimeoutError('Late stage response: '+stage)
            self.record(stage, 'ran', seconds=round(time.monotonic()-now, 4),
                        role=role,
                        queue_seconds=round(queue['seconds'], 4),
                        backoff_seconds=round(backoff, 4),
                        allowance_seconds=round(max(0, end-now), 4))
            if not journal:
                receive(dict(meta, role=role, status='ok', seconds=round(time.monotonic()-now, 4),
                             queue_seconds=round(queue['seconds'], 4), error_class=None,
                             message='Stage call completed'))
            return output, meta
        except Exception as exc:
            kind = getattr(exc, 'failure_kind', 'TIMEOUT' if isinstance(exc, TimeoutError) else 'agent_failure')
            if isinstance(exc, TimeoutError) and self.pressure_kind == 'provider_refused':
                kind = 'provider_refused'
            self.failure_kinds.append(kind)
            self.pressured = self.pressured or kind in ('provider_refused', 'provider_timeout', 'TIMEOUT',
                                                        'connection_reset', 'provider_connection')
            if self.pressured:
                self.pressure_kind = kind
            self.record(stage, 'code_fallback', reason='stage_over_budget' if isinstance(exc, TimeoutError) else kind,
                        role=role, error_class=type(exc).__name__, message=diagnostic_message(exc),
                        failure_kind=kind, http_status=getattr(exc, 'http_status', None),
                        note_pt='etapa pulada: provedor sob pressão' if self.pressured else 'etapa indisponível',
                        availability='stage_unavailable',
                        queue_seconds=round(queue['seconds'], 4),
                        seconds=round(time.monotonic()-now, 4))
            # A worker may still be blocked before its first receipt, or between
            # retries. Persist the observed boundary failure without waiting.
            if not journal or isinstance(exc, TimeoutError) or not any(r.get('error_class') for r in journal):
                receive(dict(role=role, status='timeout' if isinstance(exc, TimeoutError) else 'failed',
                             seconds=round(time.monotonic()-now, 4), queue_seconds=round(queue['seconds'], 4),
                             error_class=type(exc).__name__, message=diagnostic_message(exc),
                             failure_kind=kind, source='stage_boundary', invoked=queue['invoked']))
            raise
        finally:
            with self.journal_lock:
                closed = True
            token.cancel()
            if stage == 'intake':
                self.intake_seconds += time.monotonic()-now
            if pool:
                pool.shutdown(wait=False, cancel_futures=True)
                if self.history:
                    self.history.observe(stage, time.monotonic()-now)

    def snapshot(self):
        return dict(message_seconds=self.seconds, allocator='remaining_budget',
                    provider_pressure=self.pressured,
                    reserve_seconds=self.reserve, stage_seconds=dict(self.CEILINGS),
                    median_seconds=dict(self.MEDIANS), latency_window=20,
                    protected_location_seconds=self.MEDIANS['location'],
                    eligibility=dict(self.eligibility), stages=list(self.records))


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError('Envie um objeto JSON.')
    messages = request.get('messages')
    if not isinstance(messages, list) or not 1 <= len(messages) <= 15:
        raise ValueError('Envie de 1 a 15 mensagens por execução.')
    replay = request.get('replay_time')
    if not isinstance(replay, str):
        raise ValueError('Informe replay_time com fuso horário.')
    timestamp(replay)
    clean, ids = [], set()
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get('text'), str) or len(message['text']) > 12000:
            raise ValueError('Cada mensagem deve ter texto de até 12000 caracteres.')
        text = redact(message['text'])
        mid = message.get('message_id')
        if mid is None:
            mid = 'synthetic-'+hashlib.sha256(text.encode()).hexdigest()[:20]
        if not isinstance(mid, str) or not mid.strip() or len(mid) > 200:
            raise ValueError('message_id inválido.')
        from app.redact import external_id
        mid = external_id(mid)
        if mid in ids:
            raise ValueError('message_id repetido na mesma execução.')
        ids.add(mid)
        received = message.get('received_at', replay)
        if not isinstance(received, str):
            raise ValueError('received_at inválido.')
        timestamp(received)
        proposed=message.get('proposed_asset')
        if proposed is not None:
            from app.fleet import document
            if not isinstance(proposed,str) or proposed not in document()['assets']:
                raise ValueError('proposed_asset inválido.')
        clean.append({'message_id': mid, 'text': text, 'received_at': received, 'synthetic': True,
                      **({'proposed_asset':proposed} if proposed else {})})
    return replay, clean


class Pipeline:
    def __init__(self, registry, sample=False, source=None, client=None, budget_seconds=90, max_workers=2):
        self.registry, self.sample = registry, sample
        self.source = source or (LocalSource() if sample else ZetarisSource())
        self.client = client
        self.budget_seconds = min(480, budget_seconds)
        self.max_workers = max(1, min(2, max_workers))
        self.run_lock = threading.Lock()
        get_data()  # Build the shared local grid once, before per-case timing.

    def run(self, request, ablation='full', *, event_sink=None, case_sink=None):
        replay, messages = validate_request(request)
        # Provider slots default to two globally (NIGHTSHIFT_MAX_CONCURRENCY).
        if not self.run_lock.acquire(blocking=False):
            raise ValueError('Já existe uma execução ativa nesta mesa. Aguarde sua conclusão.')
        try:
            return self._run(replay, messages, ablation, event_sink=event_sink, case_sink=case_sink)
        finally:
            self.run_lock.release()

    def reply(self, case_id, request):
        if not isinstance(request, dict):
            raise ValueError('Envie um objeto JSON.')
        previous = self.registry.read(case_id)
        if previous is None:
            raise KeyError(case_id)
        received = request.get('received_at')
        timestamp(received)
        if timestamp(received) < timestamp(previous['received_at']):
            raise ValueError('Resposta anterior à última mensagem.')
        replay, clean = validate_request({'replay_time':received, 'messages':[
            {**request, 'message_id':previous['message_id']+':reply:'+str(previous['version'])}]})
        if not self.run_lock.acquire(blocking=False):
            raise ValueError('Já existe uma execução ativa nesta mesa.')
        try:
            return self._run(replay, clean, 'full', previous)['cases'][0]
        finally:
            self.run_lock.release()

    def _run(self, replay, messages, ablation, previous=None, event_sink=None, run_id=None, case_sink=None, surge=False):
        started = time.monotonic()
        deadline = started+self.budget_seconds
        run_id = run_id or uuid.uuid4().hex
        trace = ROOT/'logs'/('run_'+run_id+'.jsonl')
        client = self.client or Nightshift(trace)
        if event_sink:
            for message in messages:
                event_sink('received',case_id=hashlib.sha256(message['message_id'].encode()).hexdigest()[:24])
        source_error = None
        landmark_rows, landmark_error = [], None
        source_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            source_future = source_pool.submit(self.source.streets, timeout=max(.01, deadline-time.monotonic()))
            rows = source_future.result(timeout=max(0, deadline-time.monotonic()))
            if hasattr(self.source, 'landmarks'):
                landmark_future = source_pool.submit(self.source.landmarks, timeout=max(.01, deadline-time.monotonic()))
                try:
                    landmark_rows = landmark_future.result(timeout=max(0, deadline-time.monotonic()))
                except Exception as exc:
                    landmark_error = safe_error(exc)
        except Exception as exc:
            rows, source_error = [], safe_error(exc)
        finally:
            source_pool.shutdown(wait=False, cancel_futures=True)
        from app.geo.incident import prepared_index
        incident_index = prepared_index(rows, landmark_rows)
        credibility_history = []
        history = [fact for stored in self.registry.read() for fact in stored.get('facts', [])]
        history_seen = set()
        for fact in history:
            try:
                if timestamp(fact['replay_time']) > timestamp(replay):
                    continue
                for prior_message in fact.get('messages') or [fact]:
                    if timestamp(prior_message['received_at']) <= timestamp(replay):
                        entry = dict(id=prior_message['message_id'], text=prior_message['text'],
                                     time=prior_message['received_at'])
                        key = (entry['id'], entry['text'], entry['time'])
                        if key not in history_seen:
                            history_seen.add(key)
                            credibility_history.append(entry)
            except (KeyError, ValueError, TypeError):
                continue
        message_deadlines = {}
        message_budgets = {}
        deadline_lock = threading.Lock()
        def process(message):
            from app.runs import EventClient
            cid = previous['case_id'] if previous else hashlib.sha256(message['message_id'].encode()).hexdigest()[:24]
            def emit(stage, **data):
                if event_sink:
                    event_sink(stage, case_id=cid, **data)
            message_started = time.monotonic()
            deadline = message_started + self.budget_seconds
            budget = StageBudget(client, deadline, self.budget_seconds, emit, trace=trace, message_id=message['message_id'])
            budget.surge = bool(surge)
            agent_client = EventClient(budget, emit)
            with deadline_lock:
                message_deadlines[message['message_id']] = (deadline, message_started)
                message_budgets[message['message_id']] = budget
            emit('message_started', budget_seconds=self.budget_seconds)
            fields, unsupported, calls, errors = {}, [], [], []
            review_degraded = False
            intake_degraded = False
            agent_warnings = []
            initial_fields = {}
            stages = {'intake': None, 'critic': None, 'revision': None, 'location': None}
            complete = source_error is None
            if source_error:
                errors.append('data_source_failed:'+source_error)
            if self.sample or ablation == 'baseline':
                emit('intake_started',role='intake')
                context_city = previous['fields'].get('municipality', {}).get('value') if previous else None
                output = baseline.extract(message['text'], rows, context_city) if previous else baseline.extract(message['text'], rows)
                fields, unsupported = validate(output, message['text'])
                initial_fields = copy.deepcopy(fields)
                stages = {role: 'unavailable (offline)' for role in stages}
                reasons = critic.uncertainty(message['text'], fields, unsupported, output)
                budget.eligibility['critic'] = bool(reasons)
                budget.record('critic', 'skipped', reason='offline' if reasons else 'certain_intake', uncertainty=reasons)
                emit('intake_done',role='intake')
            else:
                extraction_role = 'intake'
                try:
                    output, meta, intake_degraded = intake.hedged_run(
                        agent_client, message['text'], deadline,
                        lambda: baseline.extract(message['text'], rows))
                    if meta is not None:
                        calls.append(meta)
                    if intake_degraded:
                        agent_warnings.append('leitura inicial degradada; extração determinística preservada.')
                        if previous is not None and not output.get('fields'):
                            raise TimeoutError('Intake reply unavailable; preserve previous evidence')
                    stages['intake'] = output
                    fields, rejected = validate(output, message['text'])
                    unsupported.extend(rejected)
                    initial_fields = dict(fields)
                    if not isinstance(output, dict) or not isinstance(output.get('fields'), dict):
                        raise ValueError('Intake schema invalid')
                    reasons = critic.uncertainty(message['text'], fields, rejected, output)
                    budget.eligibility['critic'] = bool(reasons)
                    if not reasons or ablation == 'intake' or previous is not None:
                        budget.record('critic', 'skipped', reason='certain_intake' if not reasons else 'ablation_or_dialogue', uncertainty=reasons)
                    use_verifier = bool(reasons) and ablation == 'full' and previous is None and critic.verifier_enabled()
                    if use_verifier:
                        # Verifier flag (RTD_VERIFIER=1): ONE call checks and corrects; code derives values from quotes.
                        try:
                            verdict, meta = critic.verify(agent_client, message['text'], fields, deadline)
                            calls.append(meta)
                            stages['verifier'] = dict(diffs=verdict['diffs'], rejected=verdict['rejected'])
                            if verdict['diffs']:
                                fields = verdict['fields']
                                agent_warnings.append('Verificador corrigiu: '+', '.join(d['field'] for d in verdict['diffs']))
                            unsupported.extend(verdict['rejected'])
                        except Exception as exc:
                            budget.agent_error('verifier', exc)
                            stages['verifier'] = 'failed'
                            agent_warnings.append('verificador indisponível; leitura inicial validada preservada.')
                    if reasons and ablation != 'intake' and previous is None and not use_verifier:
                        try:
                            review, meta = critic.run(agent_client, message['text'], fields, deadline)
                        except Exception as exc:
                            budget.agent_error('critic', exc)
                            stages['critic'] = 'failed'
                            agent_warnings.append('crítico indisponível; leitura inicial validada preservada.')
                            review, meta = {'objections': []}, None
                        if meta is not None:
                            calls.append(meta)
                            stages['critic'] = review
                        objections = review['objections']
                        if objections and not review_degraded:
                            try:
                                revised, meta = intake.run(agent_client, message['text'], deadline, objections)
                                if not isinstance(revised, dict) or not isinstance(revised.get('fields'), dict):
                                    raise ValueError('Revision schema invalid')
                                revised_fields, rejected = validate(revised, message['text'])
                                calls.append(meta)
                                stages['revision'] = revised
                                fields = revised_fields
                                unsupported.extend(rejected)
                            except Exception as exc:
                                budget.agent_error('revision', exc)
                                stages['revision'] = 'failed'
                                agent_warnings.append('revisão indisponível; leitura inicial validada preservada.')
                except Exception as exc:
                    budget.agent_error(extraction_role, exc)
                    stages[extraction_role] = 'failed'
                    complete = False
                    # Failed required extraction must finish deterministically;
                    # more advisory calls cannot repair its missing evidence.
                    budget.pressured = True
                    errors.append('agent_step_failed:'+safe_error(exc))
                    # Code extraction remains reviewable when an agent's stage expires.
                    if not fields:
                        fields, rejected = validate(baseline.extract(message['text'], rows), message['text'])
                        unsupported.extend(rejected)
                    budget.record('intake_or_revision', 'code_fallback', reason=type(exc).__name__)
            if time.monotonic() >= deadline:
                complete = False
                errors.append('message_deadline')
            dialogue_data = {}
            if previous is not None:
                from app.dialogue import merge
                reply_fields = copy.deepcopy(fields)
                fields, history, conflicts, changes, review, metas = merge(
                    previous, fields, message, agent_client, deadline, True)
                reply_reasons = critic.uncertainty('\n'.join(m['text'] for m in history), fields, unsupported)
                if not reply_fields:
                    reply_reasons.append('empty_reply_extraction')
                if conflicts:
                    reply_reasons.append('dialogue_contradiction')
                budget.eligibility['critic'] = bool(reply_reasons)
                if not self.sample and reply_reasons:
                    try:
                        # Reuse the original reply extraction; the prepass only
                        # merges supported history and computes contradictions.
                        fields, history, conflicts, changes, review, metas = merge(
                            previous, reply_fields, message, agent_client, deadline, False)
                    except Exception as exc:
                        review = 'failed'
                        agent_warnings.append('crítico indisponível; histórico determinístico preservado: '+type(exc).__name__)
                else:
                    budget.record('critic', 'skipped', reason='offline' if self.sample else 'certain_dialogue', uncertainty=reply_reasons)
                calls.extend(metas)
                stages['critic'] = review
                dialogue_data = {'messages':history, 'contradictions':conflicts, 'changes':changes,
                    'change_summary_pt':'; '.join(f"{c['field']}: {c['from']} → {c['to']} (mensagem {c['message_index']})" for c in changes)
                        or 'Nenhum campo alterado; confirmar pendências.', 'parent_version':previous['version']}
                # Extraction sees only the reply; downstream rules see the contact history.
                message = {**message, 'text':'\n'.join(m['text'] for m in history)}
                if not history[-1]['text'].strip():
                    complete = False
                    errors.append('empty_reply')
            get = lambda key: fields.get(key, {}).get('value', '')
            # This textual contradiction check does not depend on model compliance.
            counts = set(re.findall(r'\b(\d+)\s+(?:pessoas|pesssoas)\b', message['text'], re.I)) | {
                str(n) for n in count_values(message['text'])}
            # Spatial group counts are computed by code even if extraction
            # copied one local subtotal. Keep the source phrases for review.
            from app.derive_count import derive_grouped
            grouped = derive_grouped(message['text'])
            if grouped:
                fields['people'] = grouped
                fields.pop('conflicting_counts', None)
                counts = set()
            if previous is None and len(counts) > 1 and not CORRECTION.search(message['text']):
                fields['conflicting_counts'] = {'value': True, 'quote': message['text']}
            if get('municipality'):
                fields['municipality'] = {**fields['municipality'],
                                          'value': canonical_municipality(get('municipality')),
                                          'derived': True, 'source': 'rule:canonical_municipality'}
            outside_text = incident_index.resolve(fields, message['text'])
            rescue_state = guard_fields(fields, message['text'])
            if animal_rescue(message['text']):
                rescue_state['not_a_rescue'] = False
            # Yussef 24/10: counting is code. A single written total wins; else sender + listed people (flagged).
            if not get('people'):
                derived = written_total(message['text']) or derive_people(message['text'])
                if derived:
                    fields['people'] = derived
            emit('location_started', role='location')
            if rescue_state['not_a_rescue']:
                location, cross, landmark = lookup([], '', '', replay), None, None
                location_stage, location_calls = dict(location_path='not_required', precision='area',
                    steps=[], tool_steps=0, reason='Sem necessidade de resgate no texto.'), []
            else:
                location, cross, landmark, location_stage, location_calls = location_agent.locate(
                    rows, landmark_rows, fields, message['text'], replay,
                    None, deadline,
                    memory=__import__('app.memory.service', fromlist=['PlaceMemory']).PlaceMemory(self.registry, landmark_rows),
                    index=incident_index, trace=trace, emit=emit)
                code_found = location['found'] or bool(landmark and landmark.get('status') == 'resolved')
                budget.eligibility['location'] = not code_found
                budget.eligibility['location_newly_skipped'] = bool(code_found and location_stage.get('location_path') == 'agent')
                if not code_found and not self.sample and ablation == 'full' and budget.location_available(deadline):
                    location, cross, landmark, location_stage, location_calls = location_agent.locate(
                        rows, landmark_rows, fields, message['text'], replay, agent_client, deadline,
                        memory=__import__('app.memory.service', fromlist=['PlaceMemory']).PlaceMemory(self.registry, landmark_rows),
                        index=incident_index, trace=trace, emit=emit)
                elif code_found or self.sample or ablation != 'full':
                    budget.record('location', 'skipped', reason='code_lookup_resolved' if code_found else 'offline_or_ablation')
                    if code_found and location_stage.get('location_path') == 'agent':
                        location_stage.update(location_path='deterministic_lookup', offline=self.sample,
                                              agent_skipped=True)
                else:
                    location_stage.update(location_path='deterministic_fallback', offline=False,
                                          agent_skipped=True, fallback=True,
                                          fallback_reason='Location model unavailable; deterministic evidence checks retained.')
            if rescue_state['not_a_rescue']:
                budget.eligibility['location'] = False
                budget.record('location', 'skipped', reason='not_a_rescue')
            stages['location'] = location_stage
            budget.location_complete = True
            calls.extend(location_calls)
            if landmark and landmark.get('status') == 'resolved' and not get('municipality'):
                fields['municipality'] = {'value': landmark['matched']['municipality'],
                    'quote': get('landmark') or landmark['matched']['name'],
                    'derived': True, 'source': 'rule:landmark_catalogue'}
            if landmark and landmark_error:
                landmark['source_error'] = landmark_error
            if time.monotonic() >= deadline:
                complete = False
            emit('location_done', role='location')
            result = decide(fields, location, replay, message['received_at'], complete=complete,
                            cross_location=cross, landmark_location=landmark,
                            life_safety=rescue_state['life_safety'], people_signal=rescue_state['people_signal'])
            if previous is not None and dialogue_data.get('contradictions'):
                result['questions'].append('Confirmar contradições entre mensagens: '+', '.join(sorted({c['field'] for c in dialogue_data['contradictions']}))+'.')
                if not result['conflicting_counts']:
                    result.update(decision='REVIEW_REQUIRED', decision_reason='Local ou fatos contraditórios entre mensagens; confirmar com o contato.')
                dialogue_data['change_summary_pt'] += '; Contradições em aberto: '+', '.join(
                    f"{c['field']}: {c.get('previous', {}).get('value', '?')} → {c.get('reply', {}).get('value', c.get('quote', '?'))} (mensagem {c['message_index']})" for c in dialogue_data['contradictions'])
            if intake_degraded and result['decision'] == 'SEND_CANDIDATE' and not (
                    rescue_state['life_safety'] and (location['found'] or
                    landmark and landmark.get('status') == 'resolved' and not landmark.get('context_only'))):
                result.update(decision='CALLBACK',
                              decision_reason='Leitura inicial degradada; confirmar risco à vida e local validado.',
                              questions=result['questions']+['Pode confirmar o risco à vida e o local do resgate?'])
            if isinstance(client, Nightshift):
                calls = list(budget.receipts)
            proposed = sum(len(stage.get('fields', {})) for key, stage in stages.items()
                           if key != 'critic' and isinstance(stage, dict) and isinstance(stage.get('fields'), dict))
            if self.sample or ablation == 'baseline':
                proposed = len(fields)+len(unsupported)
            case = {**message, 'replay_time': replay, 'run_id': run_id, 'mode': 'sample_offline' if self.sample else ablation,
                    'fields': fields, 'unsupported': unsupported, 'agents': stages, 'calls': calls,
                    'checks': location, 'cross_street_check': cross, 'landmark_check': landmark,
                    'location_path': location_stage['location_path'], 'location_precision': location_stage['precision'],
                    'result': result, 'errors': errors, 'review_degraded': review_degraded,
                    'agent_warnings': agent_warnings,
                    'intake_degraded': intake_degraded,
                    'initial_fields': initial_fields, 'seconds': round(time.monotonic()-message_started, 4),
                    'complete': complete, 'proposed_field_count': proposed,
                    'call_count_complete': 'message_deadline' not in errors,
                    'extraction_method': 'regex_baseline' if self.sample or ablation == 'baseline' else
                                         'regex_baseline_degraded' if intake_degraded else 'nightshift'}
            case['incident_outside_text'] = outside_text
            case.update(dialogue_data)
            apply_route(case, rows)
            from app.credibility import assess as assess_credibility
            from app.geo.hydro import hydro_conflict
            from app.geo.hazards import case_position
            pos = case_position(case)
            conflict = hydro_conflict(
                message['text'], pos['lat'] if pos else None, pos['lon'] if pos else None, replay[:10],
                street=get('street'), municipality=get('municipality'), precision=case['location_precision'])
            # Use only messages visible by this message's time; detect() independently validates the 24h window.
            prior = [entry for entry in credibility_history if entry['id'] != message['message_id']]
            prior.extend(dict(id=m['message_id'], text=m['text'], time=m['received_at'])
                         for m in messages if m['message_id'] != message['message_id'])
            credibility = assess_credibility(message['text'], time=message['received_at'], history=prior,
                hydro_conflict=conflict, client=agent_client if not self.sample and ablation == 'full' else None,
                deadline=deadline)
            case['credibility'] = credibility
            if not credibility.get('signals') and not self.sample and ablation == 'full':
                budget.record('credibility', 'skipped', reason='no_signal')  # reviewer fires only on a credibility signal
            if credibility.get('fallback_reason'):
                agent_warnings.append('revisor de credibilidade indisponível; regras determinísticas preservadas.')
            case['hydro_conflict'] = conflict
            if conflict:
                case.setdefault('open_items', []).append(dict(reason='hydro_conflict',
                    question='Confirmar relato e local: camada retrospectiva diverge do risco informado.',
                    evidence=conflict))
            stages['credibility_reviewer'] = credibility
            if credibility['verdict'] == 'likely_fake':
                result.update(decision='REVIEW_REQUIRED', decision_reason=credibility['reason_pt'])
                case['route']['reason_pt'] = credibility['reason_pt']
            elif credibility['verdict'] == 'doubtful':
                result.setdefault('warnings', []).append(credibility['warning_pt'])
            attach(case)
            screen(case)
            emit('checks_done')
            case['hazard_review']='indisponível'
            case['hazard_critic']='indisponível'
            case['hazard_unsupported']=0
            case['hazard_check']='deterministic_only'
            hazard_eligible = bool(conflict) and not rescue_state['not_a_rescue'] and not self.sample and ablation == 'full'
            budget.eligibility['hazard'] = hazard_eligible
            hazard_late = time.monotonic()-message_started > self.budget_seconds*budget.HAZARD_BUDGET_FRACTION
            if hazard_eligible and not hazard_late:
                hazard_critic.attach(case,agent_client,deadline)
            else:
                budget.record('hazard', 'skipped', reason='message_budget_60_percent' if hazard_late else
                              'offline_or_ablation' if self.sample or ablation != 'full' else 'no_hydro_conflict')
            if not self.sample and ablation == 'full' and not isinstance(case['hazard_review'], dict):
                agent_warnings.append('perigo não revisado; verificações determinísticas preservadas.')
            if isinstance(client,Nightshift):
                case['calls']=list(budget.receipts)
            if previous is not None and 'hazard_critic' in case['agents'] and not isinstance(case['hazard_review'], dict):
                case['agent_warnings'].append('stage_unavailable: hazard; verificações determinísticas preservadas.')
            arbiter.attach(case, agent_client if not self.sample and ablation == 'full' else None,
                           deadline, trace=trace, emit=emit)
            case['latency_budget'] = budget.snapshot()
            case['stage_unavailable'] = sorted({r['stage'] for r in budget.records
                                                if r.get('availability') == 'stage_unavailable'})
            case['minimal_path'] = budget.pressured or bool(case['stage_unavailable'])
            unavailable_kinds = budget.failure_kinds + [budget.pressure_kind] + [r.get('failure_kind') for r in budget.records
                if r.get('availability') == 'stage_unavailable']
            case['failure_kind'] = ('provider_refused' if 'provider_refused' in unavailable_kinds else
                'TIMEOUT' if any(k in ('TIMEOUT', 'provider_timeout') for k in budget.failure_kinds) else
                'agent_failure' if budget.failure_kinds or errors else None)
            for row in budget.records:
                if row.get('availability') == 'stage_unavailable':
                    warning = row['stage']+': '+row.get('note_pt', 'etapa pulada: orçamento restante insuficiente')
                    if warning not in agent_warnings:
                        agent_warnings.append(warning)
            case['calls'] = list(budget.receipts)
            case['deterministic_fallback_decision'] = bool(not complete and 'message_deadline' in errors and
                                                          case['result']['decision'] == 'REVIEW_REQUIRED')
            case_counters(case, budget)
            if any(r['status'] == 'code_fallback' and r.get('reason') == 'stage_over_budget' for r in budget.records):
                case['call_count_complete'] = False
            emit('decision', decision=case['result']['decision'], seconds=round(time.monotonic()-message_started,4))
            if case['errors']: emit('error')
            finish_route(case)
            case['seconds'] = round(time.monotonic()-message_started, 4)
            return redact_data(case)
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        futures = {pool.submit(contextvars.copy_context().run, process, m): m for m in messages}
        results = []
        try:
            pending = set(futures)
            while pending:
                done, pending = concurrent.futures.wait(pending, timeout=.02,
                                                       return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        if event_sink: event_sink('error',case_id=hashlib.sha256(futures[future]['message_id'].encode()).hexdigest()[:24])
                        failure = self.failed_case(futures[future], replay, run_id, safe_error(exc), rows)
                        budget = message_budgets.get(futures[future]['message_id'])
                        if budget:
                            budget.agent_error('message_worker', exc)
                            failure['latency_budget'] = budget.snapshot()
                            failure['calls'] = list(budget.receipts)
                        results.append(failure)
                    if case_sink:
                        case_sink(copy.deepcopy(results[-1]))
                # Queued messages have no deadline until a worker starts them.
                with deadline_lock:
                    expired = [(f, message_deadlines.get(futures[f]['message_id'])) for f in pending]
                for future, timing in expired:
                    if timing and time.monotonic() >= timing[0]:
                        pending.remove(future)
                        future.cancel()
                        if event_sink: event_sink('error',case_id=hashlib.sha256(futures[future]['message_id'].encode()).hexdigest()[:24])
                        failure = self.failed_case(futures[future], replay, run_id, 'message_deadline', rows)
                        budget = message_budgets.get(futures[future]['message_id'])
                        if budget:
                            failure['latency_budget'] = budget.snapshot()
                            failure['calls'] = list(budget.receipts)
                        failure['seconds'] = round(time.monotonic()-timing[1], 4)
                        results.append(failure)
                        if case_sink:
                            case_sink(copy.deepcopy(failure))
        finally:
            # Workers have bounded network timeouts and may not mutate the registry.
            pool.shutdown(wait=False, cancel_futures=True)
        if previous is None:
            from app.duplicates import candidates
            from app.agents import duplicate_reviewer
            existing = self.registry.analysis_context(False)[0] if hasattr(self.registry, 'analysis_context') else self.registry.read()
            peers = existing + [{**c,'case_id':hashlib.sha256(c['message_id'].encode()).hexdigest()[:24]} for c in results]
            reviewed = {}
            for case in results:
                deadline = message_deadlines.get(case['message_id'], (0, 0))[0]
                cid = hashlib.sha256(case['message_id'].encode()).hexdigest()[:24]
                suggestions = candidates({**case,'case_id':cid},peers)
                case['duplicates'] = []
                if not suggestions and not self.sample and ablation == 'full' and case['message_id'] in message_budgets:
                    message_budgets[case['message_id']].record('duplicate_reviewer', 'skipped', reason='no_candidate')
                for suggestion in suggestions[:3]:
                    other = next(c for c in peers if c['case_id']==suggestion['case_id'])
                    pair = tuple(sorted((cid,other['case_id'])))
                    entry = {**suggestion,'message_hashes':[hashlib.sha256(c['text'].encode()).hexdigest() for c in (case,other)],'review':'indisponível'}
                    if not self.sample and ablation == 'full' and time.monotonic()<deadline:
                        if pair not in reviewed:
                            from app.runs import EventClient
                            def review_emit(stage, **data):
                                if event_sink: event_sink(stage,case_id=cid,**data)
                            try:
                                review,meta = duplicate_reviewer.run(EventClient(message_budgets[case['message_id']],review_emit),case,other,deadline)
                                reviewed[pair] = (cid,review)
                                if not isinstance(client,Nightshift): case['calls'].append(meta)
                            except ValueError as exc:
                                message_budgets[case['message_id']].agent_error('duplicate_reviewer', exc)
                                case['duplicate_unsupported'] = case.get('duplicate_unsupported',0)+1
                                reviewed[pair] = (cid,'indisponível')
                            except Exception as exc:
                                message_budgets[case['message_id']].agent_error('duplicate_reviewer', exc)
                                reviewed[pair] = (cid,'indisponível')
                            budget = message_budgets[case['message_id']]
                            case['latency_budget'] = budget.snapshot()
                            if any(r['status'] == 'code_fallback' for r in budget.records):
                                case['call_count_complete'] = False
                            case['calls'] = list(budget.receipts)
                        first,review=reviewed[pair]
                        entry['review']=copy.deepcopy(review)
                        if first!=cid and isinstance(entry['review'],dict):
                            for evidence in entry['review']['evidence']:
                                evidence['case']='B' if evidence['case']=='A' else 'A'
                    case['duplicates'].append(entry)
        for case in results:
            if surge:
                case['surge_mode'] = True
                note = 'modo surto: etapas consultivas puladas para atender a fila; revisão humana segue obrigatória.'
                if note not in case.setdefault('agent_warnings', []):
                    case['agent_warnings'].append(note)
            budget = message_budgets.get(case['message_id'])
            if budget:
                case['latency_budget'] = budget.snapshot()
                if any(d.get('review') == 'indisponível' for d in case.get('duplicates', [])):
                    case.setdefault('agent_warnings', []).append('revisor de duplicidade indisponível; sugestão determinística preservada.')
                case_counters(case, budget)
                if not self.sample and ablation == 'full' and (isinstance(client, Nightshift) or os.environ.get('RTD_CONTRIBUTION_PATH')):  # real runs only
                    from app.agents import contribution
                    contribution.observe(case)
        try:  # N2A3: advisory cross-source check AFTER every decision; deterministic here, model phrasing on a background thread
            from app.contradictions.hook import after_decision
            after_decision(self, results, previous, None if self.sample or ablation != 'full' else client)
        except Exception: pass
        if previous is not None:
            from app.dialogue import messages as reply_messages
            case = results[0]
            if not case['complete'] or case.get('review_degraded') or any('failed' in e for e in case.get('errors', [])):
                failure = copy.deepcopy(previous)
                for key in ('facts','actions'):
                    failure.pop(key, None)
                failure.update(messages=reply_messages(previous, messages[0]), received_at=messages[0]['received_at'],
                    replay_time=replay, parent_version=previous['version'], complete=False,
                    failure_kind=case.get('failure_kind'), minimal_path=case.get('minimal_path'),
                    calls=case.get('calls', []), nemotron=case.get('nemotron'),
                    agent_evidence=case.get('agent_evidence'), intake_degraded=case.get('intake_degraded', False),
                    agent_warnings=case.get('agent_warnings', []),
                    latency_budget=case.get('latency_budget'), stage_unavailable=case.get('stage_unavailable', []),
                    errors=case['errors'], changes=[], route=case['route'],
                    reply_attempt={k:case.get(k) for k in ('agents','calls','errors','run_id','complete','latency_budget','arbitration')},
                    change_summary_pt='Falha na resposta; análise anterior preservada para revisão.')
                failure['result'].update(decision='REVIEW_REQUIRED', decision_reason='Falha na resposta; revisão humana obrigatória.')
                case = failure
            cases = [self.registry.append_reply(previous['case_id'], previous['version'], case)]
        else:
            cases = [self.registry.ingest(case) for case in results]
        if self.sample:  # Offline harnesses remove scratch registries immediately on return.
            from app.contradictions.service import wait_all
            wait_all()
        summary = {'run_id': run_id, 'mode': 'sample_offline' if self.sample else ablation,
                   'synthetic': True, 'seconds': round(time.monotonic()-started, 3),
                   'partial': any(not c['complete'] for c in results), 'cases': cases}
        event = {'kind': 'run_summary', 'run_id': run_id, 'mode': summary['mode'],
                 'messages': len(messages), 'partial': summary['partial'], 'seconds': summary['seconds'],
                 'unsupported': [{'message_id': c['message_id'], 'fields': c['unsupported']} for c in results]}
        trace.parent.mkdir(exist_ok=True)
        with TRACE_LOCK:
            with trace.open('a', encoding='utf-8') as out:
                out.write(json.dumps(event, ensure_ascii=False)+'\n')
            print(json.dumps(event, ensure_ascii=False), flush=True)
        return summary

    def failed_case(self, message, replay, run_id, error, rows=None):
        # An outer deadline still returns reviewable, validated code evidence.
        try:
            fields, unsupported = validate(baseline.extract(message['text'], rows or []), message['text'])
        except Exception:
            fields, unsupported = {}, []  # Last-resort review must itself be total.
        location = lookup(rows or [], fields.get('street', {}).get('value', ''),
                          fields.get('municipality', {}).get('value', ''), replay)
        case = screen({**message, 'replay_time': replay, 'run_id': run_id, 'mode': 'sample_offline' if self.sample else 'full',
                'fields': fields, 'unsupported': unsupported, 'agents': {r: 'unavailable (failed)' for r in ('intake', 'critic', 'revision')},
                'calls': [], 'checks': location, 'cross_street_check': None,
                'position': None, 'hazards': None, 'hazards_reason': 'Location unavailable after failed analysis.',
                'hazard_review': 'indisponível', 'hazard_critic': 'indisponível', 'hazard_unsupported': 0,
                'result': decide(fields, location, replay, message['received_at'], complete=False),
                'intake_degraded': True,
                'deterministic_fallback_decision': error == 'message_deadline',
                'agent_warnings': ['leitura inicial indisponível; extração determinística para revisão humana.'],
                'errors': [error], 'complete': False, 'proposed_field_count': 0,
                'call_count_complete': False, 'extraction_method': 'unavailable'})

        apply_route(case, [])
        finish_route(case)
        return case
