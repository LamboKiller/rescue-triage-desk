"""Read-only event-time projection for handovers; replay through the real registry."""
import contextlib
import json
import threading
from app.decide import timestamp
from app.engines.world_model.registry import Registry


def snapshot(registry, now):
    limit = timestamp(now)
    with registry.locked():
        lines = registry.path.read_text(encoding='utf-8').splitlines() if registry.path.exists() else []
    kept, clocks = [], {}
    for line in lines:
        e = json.loads(line)
        c = e.get('case') or {}
        projections = e.get('projections') or []
        times = [e.get('at'), e.get('replay_time'), c.get('replay_time') or c.get('received_at')]
        for p in projections:
            if e.get('kind') == 'field_feedback' and p.get('feedback'):
                times.append(p['feedback'][-1].get('received_at'))
            elif p.get('actions'):
                a = p['actions'][-1]
                times.append(a.get('received_at') or a.get('replay_time') or a.get('at'))
            times.append(p.get('replay_time') or p.get('received_at'))
        dated = [timestamp(t) for t in times if t]
        # Legacy human actions have no independent clock: the journal uses their
        # case's last replay clock. Never substitute the machine's wall clock.
        at = max(dated) if dated else clocks.get(e.get('case_id'))
        if e.get('case_id') and at is not None:
            clocks[e['case_id']] = at
        if at is not None and at <= limit:
            kept.append(line)

    class Journal:
        def exists(self): return True
        def read_text(self, **kwargs): return '\n'.join(kept)

    class ReadOnly(Registry):
        def __init__(self):
            self.path, self.lock = Journal(), threading.RLock()

        @contextlib.contextmanager
        def locked(self):
            with self.lock:
                yield

    return ReadOnly()
