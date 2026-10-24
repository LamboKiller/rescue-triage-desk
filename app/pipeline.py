"""Bounded per-message agents → deterministic tools → registry.

The only offline extraction is the explicit regex baseline. Ground truth and
saved example answers are never read by this module.
"""
import concurrent.futures
import hashlib
import json
import threading
import time
import uuid
import re
from app.agents import baseline, intake, critic
from app.agents.spans import validate
from app.config import ROOT, safe_error
from app.data.source import LocalSource, ZetarisSource
from app.decide import decide, timestamp
from app.geo.streets import lookup
from app.llm.nightshift import Nightshift, TRACE_LOCK
from app.redact import redact


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
        if not isinstance(message, dict) or not isinstance(message.get('text'), str) or not 1 <= len(message['text'].strip()) <= 12000:
            raise ValueError('Cada mensagem deve ter texto de 1 a 12000 caracteres.')
        text = redact(message['text'])
        mid = message.get('message_id')
        if mid is None:
            mid = 'synthetic-'+hashlib.sha256(text.encode()).hexdigest()[:20]
        if not isinstance(mid, str) or not mid.strip() or len(mid) > 200:
            raise ValueError('message_id inválido.')
        mid = redact(mid)
        if mid in ids:
            raise ValueError('message_id repetido na mesma execução.')
        ids.add(mid)
        received = message.get('received_at', replay)
        if not isinstance(received, str):
            raise ValueError('received_at inválido.')
        timestamp(received)
        clean.append({'message_id': mid, 'text': text, 'received_at': received, 'synthetic': True})
    return replay, clean


class Pipeline:
    def __init__(self, registry, sample=False, source=None, client=None, budget_seconds=480):
        self.registry, self.sample = registry, sample
        self.source = source or (LocalSource() if sample else ZetarisSource())
        self.client = client
        self.budget_seconds = min(480, budget_seconds)
        self.run_lock = threading.Lock()

    def run(self, request, ablation='full'):
        replay, messages = validate_request(request)
        # One active run per desk bounds provider concurrency globally to three.
        if not self.run_lock.acquire(blocking=False):
            raise ValueError('Já existe uma execução ativa nesta mesa. Aguarde sua conclusão.')
        try:
            return self._run(replay, messages, ablation)
        finally:
            self.run_lock.release()

    def _run(self, replay, messages, ablation):
        started = time.monotonic()
        deadline = started+self.budget_seconds
        run_id = uuid.uuid4().hex
        trace = ROOT/'logs'/('run_'+run_id+'.jsonl')
        client = self.client or Nightshift(trace)
        source_error = None
        source_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            source_future = source_pool.submit(self.source.streets, timeout=max(.01, deadline-time.monotonic()))
            rows = source_future.result(timeout=max(0, deadline-time.monotonic()))
        except Exception as exc:
            rows, source_error = [], safe_error(exc)
        finally:
            source_pool.shutdown(wait=False, cancel_futures=True)
        def process(message):
            fields, unsupported, calls, errors = {}, [], [], []
            if isinstance(client, Nightshift):
                client.start_message(message['message_id'])
            stages = {'intake': None, 'critic': None, 'revision': None}
            complete = source_error is None
            if source_error:
                errors.append('data_source_failed:'+source_error)
            if self.sample or ablation == 'baseline':
                fields, unsupported = validate(baseline.extract(message['text'], rows), message['text'])
                stages = {role: 'unavailable (offline)' for role in stages}
            else:
                try:
                    output, meta = intake.run(client, message['text'], deadline)
                    calls.append(meta)
                    stages['intake'] = output
                    fields, rejected = validate(output, message['text'])
                    unsupported.extend(rejected)
                    if not isinstance(output, dict) or not isinstance(output.get('fields'), dict):
                        raise ValueError('Intake schema invalid')
                    if ablation != 'intake':
                        review, meta = critic.run(client, message['text'], fields, deadline)
                        calls.append(meta)
                        stages['critic'] = review
                        objections = review['objections'] + [{'field': r['field'], 'reason': r['reason']} for r in rejected]
                        if objections:
                            revised, meta = intake.run(client, message['text'], deadline, objections)
                            calls.append(meta)
                            stages['revision'] = revised
                            fields, rejected = validate(revised, message['text'])
                            unsupported.extend(rejected)
                            if not isinstance(revised, dict) or not isinstance(revised.get('fields'), dict):
                                raise ValueError('Revision schema invalid')
                except Exception as exc:
                    complete = False
                    errors.append('agent_step_failed:'+safe_error(exc))
            if time.monotonic() >= deadline:
                complete = False
                errors.append('global_deadline')
            get = lambda key: fields.get(key, {}).get('value', '')
            # This textual contradiction check does not depend on model compliance.
            counts = re.findall(r'\b(\d+)\s+(?:pessoas|pesssoas)\b', message['text'], re.I)
            if len(set(counts)) > 1:
                fields['conflicting_counts'] = {'value': True, 'quote': message['text']}
            location = lookup(rows, get('street'), get('municipality'), replay)
            cross = lookup(rows, get('cross_street'), get('municipality'), replay) if get('cross_street') else None
            result = decide(fields, location, replay, message['received_at'], complete=complete, cross_location=cross)
            if isinstance(client, Nightshift):
                calls = client.message_calls()
            proposed = sum(len(stage.get('fields', {})) for key, stage in stages.items()
                           if key != 'critic' and isinstance(stage, dict) and isinstance(stage.get('fields'), dict))
            if self.sample or ablation == 'baseline':
                proposed = len(fields)+len(unsupported)
            case = {**message, 'replay_time': replay, 'run_id': run_id, 'mode': 'sample_offline' if self.sample else ablation,
                    'fields': fields, 'unsupported': unsupported, 'agents': stages, 'calls': calls,
                    'checks': location, 'cross_street_check': cross, 'result': result, 'errors': errors,
                    'complete': complete, 'proposed_field_count': proposed,
                    'call_count_complete': 'global_deadline' not in errors,
                    'extraction_method': 'regex_baseline' if self.sample or ablation == 'baseline' else 'nightshift'}
            # Redact the entire model argument as well as input: models can emit PII.
            return json.loads(redact(json.dumps(case, ensure_ascii=False)))
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        futures = {pool.submit(process, m): m for m in messages}
        results = []
        try:
            pending = set(futures)
            while pending and time.monotonic() < deadline:
                done, pending = concurrent.futures.wait(pending, timeout=max(0, deadline-time.monotonic()),
                                                       return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        results.append(self.failed_case(futures[future], replay, run_id, safe_error(exc)))
            for future in pending:
                future.cancel()
                results.append(self.failed_case(futures[future], replay, run_id, 'global_deadline'))
        finally:
            # Workers have bounded network timeouts and may not mutate the registry.
            pool.shutdown(wait=False, cancel_futures=True)
        cases = [self.registry.ingest(case) for case in results]
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

    def failed_case(self, message, replay, run_id, error):
        location = lookup([], '', '', replay)
        return {**message, 'replay_time': replay, 'run_id': run_id, 'mode': 'sample_offline' if self.sample else 'full',
                'fields': {}, 'unsupported': [], 'agents': {r: 'unavailable (failed)' for r in ('intake', 'critic', 'revision')},
                'calls': [], 'checks': location, 'cross_street_check': None,
                'result': decide({}, location, replay, message['received_at'], complete=False),
                'errors': [error], 'complete': False, 'proposed_field_count': 0,
                'call_count_complete': False, 'extraction_method': 'unavailable'}
