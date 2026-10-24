"""Nightshift contract verified by the builder's Gate 0, not by this sandbox."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from app.config import setting
from app.redact import redact

TRACE_LOCK = threading.Lock()
CALL_SLOTS = threading.BoundedSemaphore(3)


def first_json(content):
    decoder = json.JSONDecoder()
    for i, char in enumerate(content):
        if char in '{[':
            try:
                return decoder.raw_decode(content[i:])[0]
            except ValueError:
                continue
    raise ValueError('No JSON object or array')


class Nightshift:
    def __init__(self, trace_path):
        self.trace_path = trace_path
        self.local = threading.local()

    def start_message(self, message_id):
        self.local.message_id = message_id
        self.local.events = []

    def message_calls(self):
        return list(getattr(self.local, 'events', []))

    def call(self, role, system, payload, deadline):
        if not CALL_SLOTS.acquire(timeout=max(0, deadline-time.monotonic())):
            raise TimeoutError('Global deadline waiting for provider slot')
        try:
            return self._call(role, system, payload, deadline)
        finally:
            CALL_SLOTS.release()

    def _call(self, role, system, payload, deadline):
        key = setting('NIGHTSHIFT_API_KEY')
        if not key:
            raise RuntimeError('Nightshift key missing')
        # A single message per call; thinking remains ON (no template overrides).
        body = {'model': setting('NIGHTSHIFT_MODEL', 'nvidia/nemotron-3.5-lightning-30b-a3b'),
                'max_tokens': 2000, 'messages': [{'role': 'system', 'content': system},
                {'role': 'user', 'content': redact(json.dumps(payload, ensure_ascii=False))}]}
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Global deadline')
            start = time.monotonic()
            event = {'role': role, 'message_id': getattr(self.local, 'message_id', None),
                     'attempt': attempt+1, 'requested_model': body['model'],
                     'model': None, 'receipt': None, 'route_kind': None}
            retry = False
            try:
                req = urllib.request.Request(setting('NIGHTSHIFT_BASE_URL', 'http://127.0.0.1:8088/v1').rstrip('/')+'/chat/completions',
                    data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                    'Authorization': 'Bearer '+key, 'meterless-app': 'rescue-triage-desk', 'meterless-scope': 'user'})
                with urllib.request.urlopen(req, timeout=min(180, remaining)) as response:
                    data = json.load(response)
                meterless = data.get('meterless', {})
                event.update(model=meterless.get('routed_model'), receipt=meterless.get('receipt_id'),
                             route_kind=meterless.get('winning_route', {}).get('kind'))
                result = first_json(data['choices'][0]['message']['content'])
                event['status'] = 'ok'
                if time.monotonic() >= deadline:
                    raise TimeoutError('Global deadline')
                return result, event
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                retry = (isinstance(exc, urllib.error.HTTPError) and exc.code == 502) or isinstance(exc, (TimeoutError, socket.timeout))
                if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, (TimeoutError, socket.timeout)):
                    retry = True
                event.update(status='failed', error=type(exc).__name__)
                if not retry or attempt == 2 or time.monotonic() >= deadline:
                    raise RuntimeError('Nightshift step failed') from None
            except Exception as exc:
                event.update(status='failed', error=type(exc).__name__)
                raise RuntimeError('Nightshift response invalid') from None
            finally:
                event['seconds'] = round(time.monotonic()-start, 3)
                if hasattr(self.local, 'events'):
                    self.local.events.append(dict(event))
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                line = redact(json.dumps(event, ensure_ascii=False))
                # Never log input, provider bodies, credentials, or hidden reasoning.
                with TRACE_LOCK:
                    with self.trace_path.open('a', encoding='utf-8') as out:
                        out.write(line+'\n')
                    print(line, flush=True)
            if retry:
                time.sleep(min(2**attempt, max(0, deadline-time.monotonic())))
