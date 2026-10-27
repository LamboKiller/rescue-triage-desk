"""HandoverService: skeleton on every GET (not stored); POST builds + (on demand) summarizes and stores one event."""
import hashlib
import json
import threading
from app.decide import timestamp
from app.redact import redact_json
from app.handover import agent, skeleton as S


class HandoverService:
    def __init__(self, registry, path, client=None, **sources):
        self.registry, self.path, self.client, self.sources = registry, path, client, sources
        self.lock = threading.Lock()

    def view(self, day=None, now=None):
        if now is None:
            now = S.default_now(self.registry.read(), day)
        return S.build(self.registry, now, **self.sources)

    def create(self, request):
        """Build, optionally summarize (request['summary'] true; never on the triage path), store as an event."""
        now = request.get('replay_time') or S.default_now(self.registry.read(), request['date'])
        timestamp(now)
        actor = str(request.get('actor') or 'operador')[:80]
        sk = self.view(now=now)
        summary = agent.summarize(sk, self.client) if request.get('summary') else {
            'status': 'not_requested', 'sentences': [], 'label_pt': 'Resumo do modelo não solicitado; esqueleto determinístico.'}
        event = {'kind': 'handover', 'handover_id': 'ho-' + hashlib.sha1((now + json.dumps(sk['counts'], sort_keys=True)).encode()).hexdigest()[:10],
                 'actor': actor, 'replay_time': now, 'skeleton': sk, 'summary': summary}
        line = redact_json(json.dumps(event, ensure_ascii=False, separators=(',', ':')))
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8', newline='\n') as out:
                out.write(line + '\n')
        return json.loads(line)

    def history(self):
        if not self.path.is_file():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding='utf-8').splitlines() if l.strip()]
