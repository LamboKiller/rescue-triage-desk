"""Deterministic destination-shelter recommendation. Code decides and computes; a human picks (top-3 with reasons).

Order: (1) hard exclusions - shelter reported/recorded FULL is never offered; shelters with FLOODED access are dropped whenever a
non-flooded alternative exists; (2) needs match (medical -> health support; pets -> animals accepted); (3) access evidence
(dry measured > unknown); (4) capacity (fits > unknown > too small); (5) straight-line distance. Unknown is never treated as dry/open.
"""
from functools import lru_cache
from app.shelters.state import metres

MAX_KM = 40
EVAL_NEAREST = 60
CAPACITY_UNKNOWN_PT = 'Capacidade desconhecida; confirmar com o abrigo.'


@lru_cache(maxsize=4096)
def _layer_access(lat, lon, day):
    from app.geo.hydro import classify_point
    c = classify_point(lat, lon, day)
    return {'state': {'wet': 'flooded', 'dry': 'dry'}.get(c['state'], 'unknown'), 'source': 'layer', 'observed_date': c.get('observed_date'),
            'depth_m': c.get('depth_m'), 'retrospective': True, 'confidence': c.get('confidence'), 'reason_pt': c.get('reason_pt')}


def layer_access(lat, lon, day):
    return dict(_layer_access(round(lat, 5), round(lon, 5), day))


def access_for(shelter, day, access_fn=None):
    """Layer (retrospective, low confidence) combined with a timestamped crew/operator access report. Disagreement -> conflict."""
    layer = (access_fn or layer_access)(shelter['lat'], shelter['lon'], day)
    rep = shelter.get('reported_access')
    if not rep: return layer
    reported = 'dry' if rep['value'] == 'dry' else 'flooded'
    if layer['state'] in ('unknown', reported):
        return {'state': reported, 'source': rep['source'], 'reported_at': rep['at'], 'reason_pt': 'acesso %s relatado (%s, %s)' % (
            'seco' if reported == 'dry' else 'alagado', rep['source'], rep['at']), 'layer': layer}
    return {'state': 'conflict', 'source': 'conflict', 'reported_at': rep['at'], 'layer': layer,
            'reason_pt': 'relato (%s) diverge da camada retrospectiva (%s); confirmar o acesso antes de enviar' % (reported, layer['state'])}


def group_of(cases):
    """Reference point, people, medical needs and pets of a mission/rescued group, from stored cases (code only)."""
    from app.missions.planner import point
    from app.priority import medical_needs
    from app.agents.needs import fallback, texts
    pts = [p for p in (point(c) for c in cases) if p]
    counts = [c.get('remaining_n', c.get('fields', {}).get('people', {}).get('value')) for c in cases]
    med = [];animals = False
    for c in cases:
        med.extend({**m, 'case_id': c['case_id']} for m in medical_needs(c))
        tags = {n['tag'] for n in fallback(texts(c))['needs']} | {n['tag'] for n in c.get('operational_needs', {}).get('needs', [])}
        animals = animals or 'animals' in tags
    return {'point': {'lat': sum(p['lat'] for p in pts) / len(pts), 'lon': sum(p['lon'] for p in pts) / len(pts)} if pts else None,
            'people': sum(counts) if counts and all(type(n) is int and n > 0 for n in counts) else None,
            'medical': sorted(med, key=lambda m: (m['hours_low'], m['medical_need'])), 'animals': animals, 'case_ids': [c['case_id'] for c in cases]}


def recommend(group, states, day, access_fn=None, k=3):
    p = group.get('point')
    if not p: return {'recommendations': [], 'excluded': [], 'human_choice_required': True,
                      'message_pt': 'Sem ponto confirmado para o grupo; não é possível ordenar abrigos por distância.'}
    people = group.get('people');need_med = bool(group.get('medical'));need_pet = bool(group.get('animals'))
    scored = [];excluded = []
    near = sorted(((metres(p['lat'], p['lon'], s['lat'], s['lon']), s) for s in states), key=lambda t: (t[0], t[1]['shelter_id']))
    near = [t for t in near if t[0] <= MAX_KM * 1000][:EVAL_NEAREST]
    for dist, s in near:
        if s['full']:
            excluded.append({'shelter_id': s['shelter_id'], 'label': s['label'], 'distance_m': round(dist), 'reason_pt': 'Lotado (%s)' % s['capacity_note_pt']});continue
        acc = access_for(s, day, access_fn)
        scored.append((dist, s, acc))
    nonflooded = [t for t in scored if t[2]['state'] != 'flooded']
    if nonflooded:
        for dist, s, acc in scored:
            if acc['state'] == 'flooded': excluded.append({'shelter_id': s['shelter_id'], 'label': s['label'], 'distance_m': round(dist),
                                                            'reason_pt': 'Acesso alagado (%s) e há alternativa sem alagamento registrado' % acc.get('reason_pt')})
        scored = nonflooded
    rows = []
    for dist, s, acc in scored:
        reasons = [];confirm = [];warn = []
        attrs = s['attributes']
        hs = attrs['health_support']['value'];an = attrs['animals_ok']['value']
        needs_rank = 0
        if need_med:
            if hs is True: reasons.append('Apoio de saúde relatado (%s).' % attrs['health_support']['source'])
            elif hs is False: needs_rank += 2;warn.append('Abrigo relatado SEM apoio de saúde; há necessidade médica no grupo.')
            else: needs_rank += 1;confirm.append('Confirmar com o abrigo: apoio de saúde (atributo desconhecido) - há necessidade médica no grupo.')
        if need_pet:
            if an is True: reasons.append('Aceita animais (%s).' % attrs['animals_ok']['source'])
            elif an is False: needs_rank += 2;warn.append('Abrigo relatado SEM aceitar animais; grupo tem animais.')
            else: needs_rank += 1;confirm.append('Confirmar com o abrigo: se aceita animais (atributo desconhecido).')
        a_rank = {'dry': 0, 'unknown': 1, 'conflict': 1, 'flooded': 3}[acc['state']]
        if acc['state'] == 'dry': reasons.append('Acesso seco: %s' % acc['reason_pt'])
        elif acc['state'] == 'flooded': warn.append('TODOS os candidatos têm acesso alagado: %s' % acc['reason_pt'])
        elif acc['state'] == 'conflict': warn.append(acc['reason_pt'])
        else: confirm.append('Acesso desconhecido (não significa seco): confirmar por rádio/equipe. %s' % (acc.get('reason_pt') or ''))
        rem = s['remaining'];c_rank = 1
        if rem is not None and people is not None and rem >= people: c_rank = 0;reasons.append('Vagas conhecidas: %s para %s pessoas (%s).' % (rem, people, s['capacity_basis']))
        elif rem is not None and people is not None: c_rank = 2;warn.append('Só %s vagas para %s pessoas: dividir o grupo ou escolher outro.' % (rem, people))
        elif rem is not None: c_rank = 0;reasons.append('Vagas conhecidas: %s (%s); contagem do grupo desconhecida.' % (rem, s['capacity_basis']))
        else: confirm.append(CAPACITY_UNKNOWN_PT + (' ' + s['capacity_note_pt'] if s['remaining_max'] is not None else ''))
        if s['last_report_age_h'] is not None and s['last_report_age_h'] > 12: warn.append('Último dado há %s h; pode estar desatualizado.' % s['last_report_age_h'])
        reasons.append('Distância em linha reta %.1f km (rota não verificada).' % (dist / 1000))
        rows.append(((needs_rank, a_rank, c_rank, round(dist), s['shelter_id']), {
            'shelter_id': s['shelter_id'], 'label': s['label'], 'municipality': s['municipality'], 'lat': s['lat'], 'lon': s['lon'], 'distance_m': round(dist),
            'access': acc, 'capacity': {'remaining': rem, 'known': s['capacity_known'], 'total': s['capacity_total'], 'basis': s['capacity_basis'], 'note_pt': s['capacity_note_pt'],
                                        'last_report_at': s['last_report_at'], 'last_report_age_h': s['last_report_age_h']},
            'needs_match': {'health_support': hs, 'animals_ok': an}, 'origin_label': s['origin_label'],
            'reasons_pt': reasons, 'confirm_pt': confirm, 'warnings_pt': warn, 'rank_key': [needs_rank, a_rank, c_rank]}))
    rows.sort(key=lambda t: t[0])
    top = []
    for i, (_, row) in enumerate(rows[:k]): top.append({'rank': i + 1, **row})
    only_flooded = bool(top) and all(r['access']['state'] == 'flooded' for r in top)
    return {'recommendations': top, 'excluded': excluded[:8], 'excluded_total': len(excluded), 'candidates_evaluated': len(near), 'human_choice_required': True,
            'group': {'people': people, 'medical': [{'medical_need': m['medical_need'], 'quote': m['quote']} for m in group.get('medical', [])],
                      'animals': need_pet, 'case_ids': group.get('case_ids', []), 'reference_point': p,
                      'reference_basis': 'centro dos pontos de resgate (destino de desembarque não definido)'},
            'ranking_pt': 'Ordem: necessidades x atributos, evidência de acesso, vagas, distância. Lotados nunca são oferecidos; alagados só sem alternativa.',
            'only_flooded_access': only_flooded,
            'message_pt': ('Nenhum abrigo elegível no raio de %s km (lotados/inexistentes); acionar coordenação.' % MAX_KM) if not top else
                          ('Todos os abrigos candidatos têm acesso alagado; escolha exige decisão humana.' if only_flooded else None)}
