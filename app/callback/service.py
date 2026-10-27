"""Callback service: items + plan for a case, and the reply loop (A3 reply merge via Pipeline.reply, then code re-evaluation)."""
import json
import threading
import hashlib
from urllib.parse import quote
from datetime import timedelta
from app.callback import planner, simulator
from app.callback.items import compute_items, diff_items
from app.decide import timestamp
from app.engines.world_model.registry import Conflict
from app.redact import redact


class CallbackService:
    def __init__(self, registry, pipeline, client=None, log_path=None, records=None):
        self.registry, self.pipeline, self.client = registry, pipeline, client
        self.log_path, self.records = log_path, records
        self.cache, self.lock = {}, threading.Lock()
        self.queue = None

    def _event(self, case_id, kind, when, **data):
        row = {'kind': 'callback_loop', 'type': kind, 'case_id': case_id, 'replay_time': when, **data}
        with self.registry.locked():
            self.registry._append(json.loads(redact(json.dumps(row, ensure_ascii=False))))

    def _last_reply(self, case_id):
        with self.registry.locked():
            lines = self.registry.path.read_text(encoding='utf-8').splitlines() if self.registry.path.exists() else []
        for line in reversed(lines):
            if 'callback_loop' not in line:
                continue
            row = json.loads(line)
            if row.get('case_id') == case_id and row.get('type') == 'retriage':
                return {k: row[k] for k in ('decision', 'version', 'simulated')}
        return None

    def _case(self, case_id):
        case = self.registry.read(case_id)
        if case is None:
            raise KeyError(case_id)
        return case

    def _plan(self, case, items, refresh=False):
        key = (case['case_id'], case['version'])
        with self.lock:
            if key in self.cache and not refresh:
                return self.cache[key]
        out = planner.plan(items, self.client)  # client=None (offline desk) -> visible templates
        primary = planner.narrow(out, items, self._role(case))
        if primary['questions']:
            self._event(case['case_id'], 'ask', case.get('replay_time') or case['received_at'],
                        version=case['version'], item_ids=primary['questions'][0]['item_ids'],
                        text=redact(primary['questions'][0]['text_pt']))
        with self.lock:
            self.cache[key] = out
        return out

    @staticmethod
    def _role(case):
        return ((case.get('incident_state') or {}).get('sender_role') or {}).get('value')

    def view(self, case_id, refresh=False, expand=False):
        case = self._case(case_id)
        items = compute_items(case)
        raw_plan = self._plan(case, items, refresh)
        plan = planner.narrow(raw_plan, items, self._role(case), expand)
        records = simulator.load_records() if self.records is None else self.records
        primary = planner.narrow(raw_plan, items, self._role(case))
        text = redact(primary['questions'][0]['text_pt']) if primary['questions'] else ''
        return {'case_id': case['case_id'], 'version': case['version'], 'decision': case['result']['decision'],
                'decision_reason': case['result'].get('decision_reason'), 'items': items, 'plan': plan,
                'simulator_available': simulator.available(case, records),
                'mode': 'offline' if self.pipeline.sample else 'live',
                'outbound': {'text': text, 'whatsapp_url': 'https://wa.me/?text='+quote(text, safe='') if text else None},
                'last_reply': self._last_reply(case_id)}

    def reply(self, case_id, request):
        if not isinstance(request, dict):
            raise ValueError('Envie um objeto JSON.')
        previous = self._case(case_id)
        if request.get('expected_version') not in (None, previous['version']):
            raise Conflict('Versão alterada. Recarregue e revise o caso.')
        items_before = compute_items(previous)
        with self.lock:
            cached = self.cache.get((case_id, previous['version']))
        # scope 'primary' = only what the desk showed by default (one question); 'all' keeps the full <=3 plan.
        primary_only = self.queue is not None or request.get('scope') == 'primary'
        if primary_only and cached:
            cached = planner.narrow(cached, items_before, self._role(previous))
        asked_ids = {i for q in cached['questions'] for i in q['item_ids']} if cached else None
        simulated = request.get('simulated') is True
        if simulated:
            plan = self._plan(previous, items_before)
            if primary_only:
                plan = planner.narrow(plan, items_before, self._role(previous))
            asked = [i for q in plan['questions'] for i in q['item_ids']] or [i['id'] for i in items_before]
            asked_ids = set(asked)
            records = simulator.load_records() if self.records is None else self.records
            sim = simulator.reply_for(previous, asked, records)
            text = sim['text']
        else:
            text = request.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                raise ValueError('Informe o texto da resposta (até 4000 caracteres).')
        received = request.get('received_at')
        if received is None:
            last = previous['messages'][-1]['received_at'] if previous.get('messages') else previous['received_at']
            received = (timestamp(last)+timedelta(minutes=10)).isoformat()
        else:
            timestamp(received)
        if timestamp(received) < timestamp(previous['received_at']):
            raise ValueError('Resposta anterior à última mensagem.')
        sent = (simulator.PREFIX if simulated else '')+text.strip()
        if self.queue is not None:
            # Private metadata is supplied by this service, never copied from HTTP input.
            meta = {'case_id': case_id, 'expected_version': previous['version'], 'simulated': simulated,
                    'items_before': items_before, 'asked_ids': sorted(asked_ids) if asked_ids else None,
                    'decision_before': previous['result']['decision']}
            mid = 'callback-'+hashlib.sha256(f'{case_id}:{previous["version"]}:{received}:{sent}'.encode()).hexdigest()[:40]
            # Time defaults are stable for an HTTP retry of this version.
            out = self.queue.accept({'replay_time': received, 'messages': [
                {'message_id': mid, 'text': sent, 'received_at': received}]}, callback=meta)
            return {**out, 'status': 'queued', 'case_id': case_id, 'simulated': simulated}
        self._event(case_id, 'reply', received, version=previous['version'], simulated=simulated)
        new = self.pipeline.reply(case_id, {'text': sent, 'received_at': received})
        return self._finish(previous, new, items_before, asked_ids, simulated, sent)

    def run_queued(self, rec, surge=False):
        message, meta = rec['message'], rec['message']['_callback']
        case_id = meta['case_id']
        previous = self._case(case_id)
        expected = meta['expected_version']
        sent = message['text']
        if previous['version'] == expected+1 and (previous.get('messages') or [{}])[-1].get('text') == sent:
            # Recovered after an append but before queue finalization: never merge twice.
            last = self._last_reply(case_id)
            if not last or last['version'] != previous['version']:
                self._finish({'case_id': case_id, 'version': expected, 'result': {'decision': meta['decision_before']}},
                             previous, meta['items_before'], meta['asked_ids'], meta['simulated'], sent)
            return previous
        if previous['version'] != expected:
            raise Conflict('Versão alterada. Recarregue e revise o caso.')
        if timestamp(message['received_at']) < timestamp(previous['received_at']):
            raise ValueError('Resposta anterior à última mensagem.')
        self._event(case_id, 'reply', message['received_at'], version=expected, simulated=meta['simulated'])
        new = self.pipeline._run(rec['replay_time'], [message], 'full', previous=previous,
                                 run_id=rec['run_ids'][0] if rec['run_ids'] else None, surge=surge)['cases'][0]
        self._finish(previous, new, meta['items_before'], meta['asked_ids'], meta['simulated'], sent)
        return new

    def _finish(self, previous, new, items_before, asked_ids, simulated, sent):
        case_id = previous['case_id']
        items_after = compute_items(new)
        # A3 preserves prior validated evidence on failure. Diagnostics must describe
        # this reply attempt rather than the successful analysis it preserved.
        analysis = new.get('reply_attempt') or new
        diff = {'decision': {'before': previous['result']['decision'], 'after': new['result']['decision'],
                             'changed': previous['result']['decision'] != new['result']['decision'],
                             'reason_after': new['result'].get('decision_reason')},
                'version': {'before': previous['version'], 'after': new['version']},
                'fields_changed': new.get('changes') or [], 'items': diff_items(items_before, items_after, asked_ids),
                'analysis': {k: analysis.get(k) for k in ('complete', 'errors', 'latency_budget')}}
        out = {'case_id': case_id, 'simulated': simulated, 'reply_text': sent, 'diff': diff, 'items': items_after,
               'items_before': items_before, 'case': new}
        self._log({'case_id': case_id, 'simulated': simulated, 'version_before': previous['version'],
                   'version_after': new['version'], 'decision_before': diff['decision']['before'],
                   'decision_after': diff['decision']['after'], 'resolved': diff['items']['resolved'],
                   'remaining': diff['items']['remaining']})
        self._event(case_id, 'retriage', new['received_at'],
                    decision={'before': diff['decision']['before'], 'after': diff['decision']['after']},
                    version=new['version'], simulated=simulated, resolved=diff['items']['resolved'])
        return out

    def _log(self, row):
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open('a', encoding='utf-8') as out:
                out.write(redact(json.dumps(row, ensure_ascii=False))+'\n')
