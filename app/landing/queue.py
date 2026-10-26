"""Landing-point queue from timestamped crew/operator reports (append-only). Reports after the replay clock are invisible."""
from app.shelters.state import naive, clock

KINDS = ('arrival', 'unloaded', 'full', 'choice', 'choice_revoked')
SOURCES = ('operator', 'crew')
ARRIVAL_WINDOW_H = 6   # older arrivals without an unloaded report are not counted as still waiting
FULL_TTL_H = 2         # a "saturated" report expires; re-report to extend


def validate(landing_id, kind, raw, known):
    if kind not in ('arrival', 'unloaded', 'full'): raise ValueError('Tipo de relato inválido.')
    if landing_id not in known: raise KeyError(landing_id)
    if not isinstance(raw, dict): raise ValueError('Envie um objeto JSON.')
    if raw.get('source', 'operator') not in SOURCES: raise ValueError('Fonte deve ser operator ou crew.')
    actor = raw.get('actor')
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 120: raise ValueError('Identifique quem relatou.')
    naive(raw.get('at'))
    ev = {'kind': kind, 'landing_id': landing_id, 'at': raw['at'], 'source': raw.get('source', 'operator'), 'actor': actor.strip()}
    n = raw.get('people')
    if kind == 'unloaded' and (type(n) is not int or not 1 <= n <= 5000): raise ValueError('Informe quantas pessoas desembarcaram (inteiro).')
    if kind == 'arrival' and n is not None and (type(n) is not int or not 1 <= n <= 5000): raise ValueError('Pessoas a bordo deve ser inteiro ou ausente.')
    if n is not None and kind != 'full': ev['people'] = n
    if isinstance(raw.get('quote'), str) and raw['quote'].strip(): ev['quote'] = raw['quote'].strip()[:300]
    return ev


def state(events, landing_id, capacity_per_hour, now):
    limit = clock(now);mine = [e for e in events if e.get('landing_id') == landing_id and e['kind'] in ('arrival', 'unloaded', 'full') and naive(e['at']) <= limit]
    hrs = lambda e: (limit - naive(e['at'])).total_seconds() / 3600
    arr = [e for e in mine if e['kind'] == 'arrival' and hrs(e) <= ARRIVAL_WINDOW_H]
    unl = [e for e in mine if e['kind'] == 'unloaded' and hrs(e) <= ARRIVAL_WINDOW_H]
    arrived = sum(e.get('people') or 0 for e in arr);unloaded = sum(e['people'] for e in unl)
    unknown_boats = sum(1 for e in arr if not e.get('people'))
    waiting = max(0, arrived - unloaded)
    fulls = [e for e in mine if e['kind'] == 'full' and hrs(e) <= FULL_TTL_H]
    over = waiting > capacity_per_hour
    return {'boats_reported': len(arr), 'boats_without_count': unknown_boats, 'people_arrived': arrived, 'people_unloaded': unloaded, 'people_waiting': waiting,
            'wait_hours_estimate': round(waiting / capacity_per_hour, 1) if capacity_per_hour else None,
            'reported_full': bool(fulls), 'reported_full_at': fulls[-1]['at'] if fulls else None, 'congested': over or bool(fulls),
            'reason_pt': ('Ponto saturado (relato %s, vale %s h).' % (fulls[-1]['at'], FULL_TTL_H)) if fulls else
                         ('Fila de %s pessoas > %s/h (estimativa): ~%s h de espera.' % (waiting, capacity_per_hour, round(waiting / capacity_per_hour, 1))) if over else None,
            'has_reports': bool(mine), 'basis_pt': 'relatos de operador/equipe até o relógio do replay; sem relato = fila desconhecida, não vazia' if not mine else
                                                    'relatos de operador/equipe (janela de %s h)' % ARRIVAL_WINDOW_H}
