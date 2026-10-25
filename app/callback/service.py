"""Callback service: items + plan for a case, and the reply loop (A3 reply merge via Pipeline.reply, then code re-evaluation)."""
import json
import threading
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
        with self.lock:
            self.cache[key] = out
        return out

    def view(self, case_id, refresh=False):
        case = self._case(case_id)
        items = compute_items(case)
        plan = self._plan(case, items, refresh)
        records = simulator.load_records() if self.records is None else self.records
        return {'case_id': case['case_id'], 'version': case['version'], 'decision': case['result']['decision'],
                'decision_reason': case['result'].get('decision_reason'), 'items': items, 'plan': plan,
                'simulator_available': simulator.available(case, records),
                'mode': 'offline' if self.pipeline.sample else 'live'}

    def reply(self, case_id, request):
        if not isinstance(request, dict):
            raise ValueError('Envie um objeto JSON.')
        previous = self._case(case_id)
        if request.get('expected_version') not in (None, previous['version']):
            raise Conflict('Versão alterada. Recarregue e revise o caso.')
        items_before = compute_items(previous)
        with self.lock:
            cached = self.cache.get((case_id, previous['version']))
        asked_ids = {i for q in cached['questions'] for i in q['item_ids']} if cached else None
        simulated = request.get('simulated') is True
        if simulated:
            plan = self._plan(previous, items_before)
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
        sent = (simulator.PREFIX if simulated else '')+text.strip()
        new = self.pipeline.reply(case_id, {'text': sent, 'received_at': received})
        items_after = compute_items(new)
        diff = {'decision': {'before': previous['result']['decision'], 'after': new['result']['decision'],
                             'changed': previous['result']['decision'] != new['result']['decision'],
                             'reason_after': new['result'].get('decision_reason')},
                'version': {'before': previous['version'], 'after': new['version']},
                'fields_changed': new.get('changes') or [], 'items': diff_items(items_before, items_after, asked_ids)}
        out = {'case_id': case_id, 'simulated': simulated, 'reply_text': sent, 'diff': diff, 'items': items_after,
               'items_before': items_before, 'case': new}
        self._log({'case_id': case_id, 'simulated': simulated, 'version_before': previous['version'],
                   'version_after': new['version'], 'decision_before': diff['decision']['before'],
                   'decision_after': diff['decision']['after'], 'resolved': diff['items']['resolved'],
                   'remaining': diff['items']['remaining']})
        return out

    def _log(self, row):
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open('a', encoding='utf-8') as out:
                out.write(redact(json.dumps(row, ensure_ascii=False))+'\n')
