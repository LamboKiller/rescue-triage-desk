"""Bounded per-message agents → deterministic tools → registry.

The only offline extraction is the explicit regex baseline. Ground truth and
saved example answers are never read by this module.
"""
import copy
import concurrent.futures
import hashlib
import json
import threading
import time
import uuid
import re
from app.agents import baseline, intake, critic, hazard_critic, location as location_agent
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
from app.rescue_state import guard_fields
from app.llm.nightshift import Nightshift, TRACE_LOCK
from app.redact import redact
from app.routing import apply_route, finish_route


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
        mid = redact(mid)
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
    def __init__(self, registry, sample=False, source=None, client=None, budget_seconds=480, max_workers=4):
        self.registry, self.sample = registry, sample
        self.source = source or (LocalSource() if sample else ZetarisSource())
        self.client = client
        self.budget_seconds = min(480, budget_seconds)
        self.max_workers = max(1, min(4, max_workers))
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

    def _run(self, replay, messages, ablation, previous=None, event_sink=None, run_id=None, case_sink=None):
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
        incident_index = IncidentIndex(rows, landmark_rows)
        message_deadlines = {}
        deadline_lock = threading.Lock()
        def process(message):
            from app.runs import EventClient
            cid = previous['case_id'] if previous else hashlib.sha256(message['message_id'].encode()).hexdigest()[:24]
            def emit(stage, **data):
                if event_sink:
                    event_sink(stage, case_id=cid, **data)
            agent_client = EventClient(client, emit)
            message_started = time.monotonic()
            deadline = message_started + self.budget_seconds
            with deadline_lock:
                message_deadlines[message['message_id']] = (deadline, message_started)
            emit('message_started', budget_seconds=self.budget_seconds)
            fields, unsupported, calls, errors = {}, [], [], []
            review_degraded = False
            initial_fields = {}
            if isinstance(client, Nightshift):
                client.start_message(message['message_id'])
            stages = {'intake': None, 'critic': None, 'revision': None, 'location': None}
            complete = source_error is None
            if source_error:
                errors.append('data_source_failed:'+source_error)
            if self.sample or ablation == 'baseline':
                emit('intake_started',role='intake')
                context_city = previous['fields'].get('municipality', {}).get('value') if previous else None
                output = baseline.extract(message['text'], rows, context_city) if previous else baseline.extract(message['text'], rows)
                fields, unsupported = validate(output, message['text'])
                stages = {role: 'unavailable (offline)' for role in stages}
                emit('intake_done',role='intake')
            else:
                try:
                    output, meta = intake.run(agent_client, message['text'], deadline)
                    calls.append(meta)
                    stages['intake'] = output
                    fields, rejected = validate(output, message['text'])
                    unsupported.extend(rejected)
                    initial_fields = dict(fields)
                    if not isinstance(output, dict) or not isinstance(output.get('fields'), dict):
                        raise ValueError('Intake schema invalid')
                    if ablation != 'intake' and previous is None:
                        try:
                            review, meta = critic.run(agent_client, message['text'], fields, deadline)
                        except Exception as exc:
                            stages['critic'] = 'failed'
                            review_degraded = True
                            errors.append('critic_failed:'+safe_error(exc))
                            review, meta = {'objections': []}, None
                        if meta is not None:
                            calls.append(meta)
                            stages['critic'] = review
                        objections = review['objections']
                        if objections and not review_degraded:
                            revised, meta = intake.run(agent_client, message['text'], deadline, objections)
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
                errors.append('message_deadline')
            dialogue_data = {}
            if previous is not None:
                from app.dialogue import merge
                fields, history, conflicts, changes, review, metas = merge(
                    previous, fields, message, agent_client, deadline, self.sample)
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
            # Yussef 24/10: counting is code. A single written total wins; else sender + listed people (flagged).
            if not get('people'):
                derived = written_total(message['text']) or derive_people(message['text'])
                if derived:
                    fields['people'] = derived
            emit('location_started', role='location')
            location, cross, landmark, location_stage, location_calls = location_agent.locate(
                rows, landmark_rows, fields, message['text'], replay,
                agent_client if not self.sample and ablation == 'full' else None, deadline,
                memory=__import__('app.memory.service', fromlist=['PlaceMemory']).PlaceMemory(self.registry, landmark_rows),
                index=incident_index, trace=trace, emit=emit)
            stages['location'] = location_stage
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
                            life_safety=rescue_state['life_safety'])
            if previous is not None and dialogue_data.get('contradictions'):
                result['questions'].append('Confirmar contradições entre mensagens: '+', '.join(sorted({c['field'] for c in dialogue_data['contradictions']}))+'.')
                if not result['conflicting_counts']:
                    result.update(decision='REVIEW_REQUIRED', decision_reason='Local ou fatos contraditórios entre mensagens; confirmar com o contato.')
                dialogue_data['change_summary_pt'] += '; Contradições em aberto: '+', '.join(
                    f"{c['field']}: {c.get('previous', {}).get('value', '?')} → {c.get('reply', {}).get('value', c.get('quote', '?'))} (mensagem {c['message_index']})" for c in dialogue_data['contradictions'])
            if review_degraded:
                result.update(decision='REVIEW_REQUIRED', questions=[],
                              decision_reason='A crítica falhou; leitura inicial preservada para revisão humana.')
            if isinstance(client, Nightshift):
                calls = client.message_calls()
            proposed = sum(len(stage.get('fields', {})) for key, stage in stages.items()
                           if key != 'critic' and isinstance(stage, dict) and isinstance(stage.get('fields'), dict))
            if self.sample or ablation == 'baseline':
                proposed = len(fields)+len(unsupported)
            case = {**message, 'replay_time': replay, 'run_id': run_id, 'mode': 'sample_offline' if self.sample else ablation,
                    'fields': fields, 'unsupported': unsupported, 'agents': stages, 'calls': calls,
                    'checks': location, 'cross_street_check': cross, 'landmark_check': landmark,
                    'location_path': location_stage['location_path'], 'location_precision': location_stage['precision'],
                    'result': result, 'errors': errors, 'review_degraded': review_degraded,
                    'initial_fields': initial_fields, 'seconds': round(time.monotonic()-message_started, 4),
                    'complete': complete, 'proposed_field_count': proposed,
                    'call_count_complete': 'message_deadline' not in errors,
                    'extraction_method': 'regex_baseline' if self.sample or ablation == 'baseline' else 'nightshift'}
            case['incident_outside_text'] = outside_text
            case.update(dialogue_data)
            apply_route(case, rows)
            attach(case)
            screen(case)
            emit('checks_done')
            case['hazard_review']='indisponível'
            case['hazard_critic']='indisponível'
            case['hazard_unsupported']=0
            if not self.sample and ablation == 'full' and (previous is not None or result['decision'] in ('SEND_CANDIDATE','REVIEW_REQUIRED')):
                hazard_critic.attach(case,agent_client,deadline)
            if isinstance(client,Nightshift):
                case['calls']=client.message_calls()
            if previous is not None and 'hazard_critic' in case['agents'] and not isinstance(case['hazard_review'], dict):
                case['complete'] = False
                case['errors'].append('hazard_critic_failed')
            emit('decision', decision=case['result']['decision'], seconds=round(time.monotonic()-message_started,4))
            if case['errors']: emit('error')
            finish_route(case)
            case['seconds'] = round(time.monotonic()-message_started, 4)
            # Redact the entire model argument as well as input: models can emit PII.
            return json.loads(redact(json.dumps(case, ensure_ascii=False)))
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        futures = {pool.submit(process, m): m for m in messages}
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
                        results.append(self.failed_case(futures[future], replay, run_id, safe_error(exc)))
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
                        failure = self.failed_case(futures[future], replay, run_id, 'message_deadline')
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
            existing = self.registry.read()
            peers = existing + [{**c,'case_id':hashlib.sha256(c['message_id'].encode()).hexdigest()[:24]} for c in results]
            reviewed = {}
            for case in results:
                deadline = message_deadlines.get(case['message_id'], (0, 0))[0]
                cid = hashlib.sha256(case['message_id'].encode()).hexdigest()[:24]
                suggestions = candidates({**case,'case_id':cid},peers)
                case['duplicates'] = []
                for suggestion in suggestions[:3]:
                    other = next(c for c in peers if c['case_id']==suggestion['case_id'])
                    pair = tuple(sorted((cid,other['case_id'])))
                    entry = {**suggestion,'message_hashes':[hashlib.sha256(c['text'].encode()).hexdigest() for c in (case,other)],'review':'indisponível'}
                    if not self.sample and ablation == 'full' and time.monotonic()<deadline:
                        if pair not in reviewed:
                            from app.runs import EventClient
                            def review_emit(stage, **data):
                                if event_sink: event_sink(stage,case_id=cid,**data)
                            if isinstance(client,Nightshift): client.start_message(case['message_id'])
                            try:
                                review,meta = duplicate_reviewer.run(EventClient(client,review_emit),case,other,deadline)
                                reviewed[pair] = (cid,review)
                                if not isinstance(client,Nightshift): case['calls'].append(meta)
                            except ValueError:
                                case['duplicate_unsupported'] = case.get('duplicate_unsupported',0)+1
                                reviewed[pair] = (cid,'indisponível')
                            except Exception:
                                reviewed[pair] = (cid,'indisponível')
                            if isinstance(client,Nightshift): case['calls'].extend(client.message_calls())
                        first,review=reviewed[pair]
                        entry['review']=copy.deepcopy(review)
                        if first!=cid and isinstance(entry['review'],dict):
                            for evidence in entry['review']['evidence']:
                                evidence['case']='B' if evidence['case']=='A' else 'A'
                    case['duplicates'].append(entry)
        if previous is not None:
            from app.dialogue import messages as reply_messages
            case = results[0]
            if not case['complete'] or case.get('review_degraded') or any('failed' in e for e in case.get('errors', [])):
                failure = copy.deepcopy(previous)
                for key in ('facts','actions'):
                    failure.pop(key, None)
                failure.update(messages=reply_messages(previous, messages[0]), received_at=messages[0]['received_at'],
                    replay_time=replay, parent_version=previous['version'], complete=False,
                    errors=case['errors'], changes=[], route=case['route'],
                    reply_attempt={k:case.get(k) for k in ('agents','calls','errors','run_id','complete')},
                    change_summary_pt='Falha na resposta; análise anterior preservada para revisão.')
                failure['result'].update(decision='REVIEW_REQUIRED', decision_reason='Falha na resposta; revisão humana obrigatória.')
                case = failure
            cases = [self.registry.append_reply(previous['case_id'], previous['version'], case)]
        else:
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
        case = screen({**message, 'replay_time': replay, 'run_id': run_id, 'mode': 'sample_offline' if self.sample else 'full',
                'fields': {}, 'unsupported': [], 'agents': {r: 'unavailable (failed)' for r in ('intake', 'critic', 'revision')},
                'calls': [], 'checks': location, 'cross_street_check': None,
                'position': None, 'hazards': None, 'hazards_reason': 'Location unavailable after failed analysis.',
                'hazard_review': 'indisponível', 'hazard_critic': 'indisponível', 'hazard_unsupported': 0,
                'result': decide({}, location, replay, message['received_at'], complete=False),
                'errors': [error], 'complete': False, 'proposed_field_count': 0,
                'call_count_complete': False, 'extraction_method': 'unavailable'})

        apply_route(case, [])
        finish_route(case)
        return case
