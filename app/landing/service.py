"""Landing service: plan for a case, operator/crew queue reports, reversible human choice (all append-only events)."""
import threading
import copy
import hashlib
import json
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
        event=lq.validate(landing_id, kind, request, known)
        if request.get('unit_id'):
            uid=request['unit_id'];mid=request.get('mission_id')
            if not hasattr(self,'unit_status'): raise ValueError('Vínculo de unidade indisponível.')
            rows=self.unit_status.view(request['at'])['units']
            row=next((r for r in rows if r['unit_id']==uid),None)
            if not row or not mid or row['mission_id']!=mid: raise ValueError('Unidade não pertence à missão informada.')
            event.update(unit_id=uid,mission_id=mid)
        return self.store.add(event)

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
        pending = False
        access_fn = self.access_fn
        if getattr(self, 'road_routing', False):
            from app.geo.routing import landing_distance, landing_transfers
            warmup = getattr(self, 'warmup', None)
            pending = warmup is not None and not warmup.task_ready('routing')
            if pending:
                distance_fn = distance_fn or (lambda a, b: dict(planner.straight_line(a, b), pending=True,
                    review_pt=['REVISAR: malha viaria e grade aquatica preparando em segundo plano; distancia em linha reta, rota nao comprovada.']))
                access_fn = access_fn or (lambda lat, lon, day: {'state': 'unknown', 'source': 'preparing', 'reason_pt': 'Camadas preparando; acesso desconhecido.'})
            else:
                distance_fn = distance_fn or landing_distance(now[:10], budget_seconds=.5)
        points = self.points if self.points is not None else lp.load_points(states, None if pending else now[:10])
        out = planner.plan(case, now, points, states, self.store.events, access_fn, distance_fn)
        out['routing_pending'] = pending or any(o['distance'].get('pending') for o in out['options'])
        if getattr(self, 'road_routing', False) and not pending:
            landing_transfers(out['options'], now[:10], background=True)
            out['routing_pending'] = out['routing_pending'] or any(
                s.get('land_route', {}).get('pending') for o in out['options'] for s in o.get('shelters', []))
        ch = self.choice_of(case_id, now)
        out['choice'] = ch
        pick = next((o for o in out['options'] if ch and o['landing_id'] == ch['landing_id']), None)
        target = pick or (out['options'][0] if out['options'] else None)
        if target:
            target = copy.deepcopy(target)
            sid = ch.get('shelter_id') if ch else None
            if sid:
                selected = next((s for s in target['shelters'] if s['shelter_id'] == sid), None)
                target['shelters'] = [selected] if selected else []
                if not selected: target['warnings_pt'].append('Abrigo escolhido indisponível; confirmar novo destino com a coordenação.')
            key = hashlib.sha256(json.dumps({'facts': note.facts_of(out, target), 'choice': ch},
                                           ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            with self.lock:
                if key not in self.cache:
                    self.cache[key] = note.write(out, target)
                    if len(self.cache) > 128: self.cache.pop(next(iter(self.cache)))
                out['handoff'] = {**copy.deepcopy(self.cache[key]), 'landing_id': target['landing_id'], 'for_choice': bool(ch)}
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
