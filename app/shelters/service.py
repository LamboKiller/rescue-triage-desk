"""Shelter service: list/state, structured + free-text reports, destination recommendation for cases/missions."""
import copy
from datetime import datetime
from app.shelters import reports, router
from app.shelters.state import Shelters, Store, fold, naive, SOURCES
from app.redact import redact


class ShelterService:
    def __init__(self, registry=None, path=None, shelters=None, access_fn=None):
        self.registry = registry
        self.shelters = shelters or Shelters(store=Store(path))
        self.access_fn = access_fn

    def listing(self, now):
        states = self.shelters.state(now)
        known = [s for s in states if s['capacity_known']]
        return {'now': now, 'shelters': states, 'summary': {
                    'total': len(states), 'capacity_known': len(known), 'capacity_unknown': len(states) - len(known),
                    'full': sum(1 for s in states if s['full']), 'delivered_total': sum(s['delivered_total'] for s in states),
                    'with_event_reports': sum(1 for s in states if s['last_event_report_at'])},
                'labels_pt': {'list': 'Lista de abrigos = pré-existente (OSM/UFRGS D1, retrospectiva).',
                              'capacity': 'Capacidade/vagas = retrato datado ou relato durante o evento (fonte e hora em cada linha); desconhecido continua desconhecido.'}}

    def report(self, request):
        """Structured event(s) or free text (+optional shelter_id). Returns recorded events and what could not be resolved."""
        if not isinstance(request, dict): raise ValueError('Envie um objeto JSON.')
        at = request.get('at') or request.get('received_at')
        naive(at)
        base = {'actor': request.get('actor'), 'source': request.get('source', 'operator'), 'at': at}
        for k in ('case_id', 'mission_id'):
            if request.get(k): base[k] = request[k]
        if request.get('kind'):
            ev = self.shelters.record({**base, **{k: request.get(k) for k in ('kind', 'shelter_id', 'value', 'attr', 'name', 'lat', 'lon', 'municipality', 'quote') if k in request}})
            return {'recorded': [ev], 'unresolved': None}
        text = request.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > 2000: raise ValueError('Informe texto de até 2000 caracteres ou um relato estruturado.')
        text = redact(text)
        parsed = reports.parse(text, self.shelters.aliases(at), request.get('shelter_id'))
        if parsed.get('unresolved_pt'):
            return {'recorded': [], 'unresolved': parsed['unresolved_pt'], 'parsed': parsed['events']}
        out = [self.shelters.record({**base, **e, 'shelter_id': parsed['shelter_id'], 'quote': e.get('quote')}) for e in parsed['events']]
        return {'recorded': out, 'unresolved': None if out else 'Nenhum dado de abrigo reconhecido no texto.', 'shelter_id': parsed['shelter_id']}

    def ingest_feedback(self, text, actor, received_at, case_id=None, mission_id=None, source='crew'):
        """Crew feedback hook: only records when a shelter is NAMED/resolved; never raises into the feedback path."""
        try:
            if not isinstance(text, str) or source not in SOURCES: return None
            result = self.report({'text': text, 'actor': actor, 'at': received_at, 'source': source, 'case_id': case_id, 'mission_id': mission_id})
            return result if result['recorded'] else None
        except (ValueError, TypeError, KeyError): return None

    def recommend(self, day_or_now, case_ids=None, people=None, cases=None, k=3):
        now = day_or_now;day = now[:10]
        pool = cases if cases is not None else (self.registry.read() if self.registry else [])
        byid = {c['case_id']: c for c in pool}
        chosen = [byid[i] for i in (case_ids or []) if i in byid]
        if case_ids and len(chosen) != len(case_ids): raise KeyError('case')
        group = router.group_of(chosen)
        if type(people) is int and people > 0: group['people'] = people
        return router.recommend(group, self.shelters.state(now), day, self.access_fn, k)
