"""Landing service: plan for a case, operator/crew queue reports, reversible human choice (all append-only events)."""
import threading
from app.landing import planner, queue as lq, points as lp, note
from app.shelters.state import Store, naive


class LandingService:
    def __init__(self, registry, shelter_service, path=None, client=None, access_fn=None, distance_fn=None, points=None):
        self.registry, self.shelters, self.store = registry, shelter_service, Store(path)
        self.client, self.access_fn, self.distance_fn, self.points = client, access_fn, distance_fn, points
        self.cache, self.lock = {}, threading.Lock()

    def _points(self, states, day=None):
        return self.points if self.points is not None else lp.load_points(states, day)

    def _case(self, case_id):
        c = self.registry.read(case_id)
        if c is None: raise KeyError(case_id)
        return c

    def report(self, landing_id, kind, request):
        states = self.shelters.shelters.state(request.get('at') or '2100-01-01')
        known = {p['landing_id'] for p in self._points(states, (request.get('at') or '')[:10] or None)}
        return self.store.add(lq.validate(landing_id, kind, request, known))

    def choice_of(self, case_id, now):
        from app.shelters.state import clock
        limit = clock(now);cur = None
        for e in self.store.events:
            if e.get('case_id') != case_id or naive(e['at']) > limit: continue
            if e['kind'] == 'choice': cur = e
            elif e['kind'] == 'choice_revoked': cur = None
        return cur

    def view(self, case_id, now, expand=False):
        case = self._case(case_id)
        states = self.shelters.shelters.state(now)
        distance_fn = self.distance_fn
        if getattr(self, 'road_routing', False):
            from app.geo.routing import landing_distance, landing_transfers
            distance_fn = distance_fn or landing_distance(now[:10])
        out = planner.plan(case, now, self._points(states, now[:10]), states, self.store.events, self.access_fn, distance_fn)
        if getattr(self, 'road_routing', False): landing_transfers(out['options'], now[:10])
        ch = self.choice_of(case_id, now)
        out['choice'] = ch
        pick = next((o for o in out['options'] if ch and o['landing_id'] == ch['landing_id']), None)
        target = pick or (out['options'][0] if out['options'] else None)
        if target:
            key = (case_id, case['version'], target['landing_id'], bool(ch), now, bool(expand and self.client))
            with self.lock:
                if key not in self.cache:
                    # Model only writes the note for a human-chosen landing (or on explicit expand); otherwise the template previews it.
                    self.cache[key] = note.write(out, target, self.client if (ch or expand) else None)
                out['handoff'] = {**self.cache[key], 'landing_id': target['landing_id'], 'for_choice': bool(ch)}
        return out

    def choose(self, case_id, request):
        case = self._case(case_id)
        at = request.get('at');naive(at)
        actor = request.get('actor')
        if not isinstance(actor, str) or not actor.strip(): raise ValueError('Identifique quem decidiu.')
        base = {'case_id': case_id, 'at': at, 'actor': actor.strip(), 'source': 'operator'}
        if request.get('revoke'):
            return self.store.add({**base, 'kind': 'choice_revoked'})
        v = self.view(case_id, at)
        lid, sid = request.get('landing_id'), request.get('shelter_id')
        top = v['options'][0] if v['options'] else None
        opt = next((o for o in v['options'] if o['landing_id'] == lid), None)
        known = {p['landing_id'] for p in self._points(self.shelters.shelters.state(at), at[:10])}
        if lid not in known: raise ValueError('Ponto de desembarque desconhecido.')
        shelter_ids = {s['shelter_id'] for s in (opt or {}).get('shelters', [])}
        override = not opt or opt['rank'] != 1 or (sid is not None and opt['shelters'] and sid != opt['shelters'][0]['shelter_id']) or (sid and sid not in shelter_ids)
        reason = request.get('override_reason')
        if override and (not isinstance(reason, str) or not reason.strip()): raise ValueError('Escolha diferente da sugestão: informe o motivo (override_reason).')
        ev = {**base, 'kind': 'choice', 'landing_id': lid, 'shelter_id': sid, 'override': bool(override),
              'suggested_landing_id': top['landing_id'] if top else None, 'case_version': case['version']}
        if override: ev['override_reason'] = reason.strip()[:300]
        return self.store.add(ev)
