"""Landing planner (code only): case -> top-3 landing points (dry, nearest, not congested) -> shelters with room -> ambulance card for
medical cases. Nothing is dispatched; a human picks. Distance is pluggable (straight line until routing exists)."""
from app.landing import queue as lq
from app.shelters import router
from app.shelters.state import metres

SHORTLIST = 15
MAX_KM = 40
STRAIGHT = 'distância em linha reta — estimativa'
DRY_NOTE = 'Seco = camada retrospectiva (baixa confiança); desconhecido não é seco.'


def straight_line(a, b):
    return {'m': round(metres(a['lat'], a['lon'], b['lat'], b['lon'])), 'basis': 'straight_line', 'label_pt': STRAIGHT}


def _room(s):
    c = s['capacity']
    if c['known']: return 'vagas conhecidas: %s (%s)' % (c['remaining'], c['basis'])
    return 'capacidade desconhecida — não é vaga confirmada'


def ambulance_card(case, group, landing, shelter):
    if not group.get('medical'): return None
    med = [{'medical_need': m['medical_need'], 'label_pt': m.get('label_pt'), 'quote': m['quote']} for m in group['medical']]
    lo = min(m['hours_low'] for m in group['medical']);hi = min(m['hours_high'] for m in group['medical'])
    dest = shelter['label'] if shelter else 'destino a definir (nenhum abrigo elegível)'
    return {'kind': 'ambulancia_handoff', 'status': 'rascunho — aguarda aprovação humana; nada foi acionado',
            'who': {'case_id': case['case_id'], 'people': group.get('people'), 'people_note': None if group.get('people') else 'contagem desconhecida; confirmar no desembarque'},
            'what': {'medical': med, 'time_to_harm_hours': [lo, hi], 'basis_pt': 'janela estimada até dano (estimativa operacional, não diagnóstico)'},
            'where': {'pickup': landing['label'], 'pickup_lat': landing['lat'], 'pickup_lon': landing['lon'], 'destination': dest,
                      'destination_health_support': (shelter or {}).get('needs_match', {}).get('health_support')},
            'text_pt': 'Solicitar ambulância no ponto %s para %s pessoa(s) do caso %s; necessidade: %s; destino sugerido: %s.' % (
                landing['label'], group.get('people') if group.get('people') else 'número desconhecido', case['case_id'],
                '; '.join('«%s»' % m['quote'] for m in med), dest)}


def plan(case, now, points, shelter_states, events, access_fn=None, distance_fn=None, k=3):
    from app.missions.planner import point as case_point
    day = now[:10];distance_fn = distance_fn or straight_line
    group = router.group_of([case]);p = case_point(case)
    out = {'case_id': case['case_id'], 'now': now, 'options': [], 'human_choice_required': True, 'auto_dispatched': False, 'review_pt': [],
           'case_point': p, 'people': group['people'], 'medical': [{'medical_need': m['medical_need'], 'quote': m['quote']} for m in group['medical']],
           'labels_pt': {'distance': STRAIGHT, 'dry': DRY_NOTE, 'capacity': 'capacidade/hora = estimativa por tipo de local; vagas dos abrigos = relatos datados'}}
    if not p:
        out['review_pt'].append('REVISAR: caso sem ponto confirmado; não é possível ordenar pontos de desembarque.');return out
    by_shelter = {s['shelter_id']: s for s in shelter_states}
    near = sorted(((metres(p['lat'], p['lon'], q['lat'], q['lon']), q) for q in points), key=lambda t: (t[0], t[1]['landing_id']))
    near = [q for d, q in near if d <= MAX_KM * 1000][:SHORTLIST]
    rows = []
    for q in near:
        sid = q['landing_id'][1:] if q['source_kind'] == 'shelter_site' else None
        acc = router.access_for(by_shelter[sid], day, access_fn) if sid in by_shelter else (access_fn or router.layer_access)(q['lat'], q['lon'], day)
        if q.get('water_edge') and acc['state'] in ('flooded', 'conflict'):
            # A launch point sits ON the water's edge by construction (dry-side node of a wet road edge), so the flood layer at that spot
            # is expected to read wet. Keep it as an access-UNKNOWN candidate (never 'dry'): the crew confirms the ramp/parking on arrival.
            acc = {'state': 'unknown', 'source': 'roads_launch_points', 'layer': acc, 'reason_pt': 'ponto de lançamento na borda da água (lado seco derivado de HAND/OSM); estacionamento e acesso não verificados — confirmar no local'}
        if acc['state'] == 'flooded': continue
        d = distance_fn(p, q);qs = lq.state(events, q['landing_id'], q['capacity_per_hour'], now)
        rows.append(((qs['congested'], 0 if acc['state'] == 'dry' else 1, d['m'], q['landing_id']), q, acc, d, qs))
    if not rows:
        out['review_pt'].append('REVISAR: nenhum ponto de desembarque seco ou de acesso desconhecido num raio de %s km; decisão humana/coordenação.' % MAX_KM)
        return out
    rows.sort(key=lambda t: t[0])
    first_ok = next((r for r in rows if not r[4]['congested']), None)
    for i, (_, q, acc, d, qs) in enumerate(rows[:k]):
        warn = []
        if qs['congested']:
            warn.append('CONGESTIONADO: ' + qs['reason_pt'] + (' Alternativa: %s.' % first_ok[1]['label'] if first_ok else ' Sem alternativa livre na lista.'))
        if acc['state'] != 'dry': warn.append('Acesso %s: %s' % ('desconhecido (não significa seco)' if acc['state'] == 'unknown' else acc['state'], acc.get('reason_pt') or ''))
        if not qs['has_reports']: warn.append('Sem relatos de fila neste ponto: fila desconhecida, não vazia.')
        if qs['boats_without_count']: warn.append('%s barco(s) anunciado(s) sem contagem de pessoas.' % qs['boats_without_count'])
        g = {**group, 'point': {'lat': q['lat'], 'lon': q['lon']}}
        rec = router.recommend(g, shelter_states, day, access_fn, k)
        sh = rec['recommendations']
        for s in sh: s['room_pt'] = _room(s)
        if not sh: warn.append('Nenhum abrigo elegível (lotados ou sem dados) a partir deste ponto; acionar coordenação.')
        elif not any(s['capacity']['known'] for s in sh): warn.append('Nenhum abrigo com vagas confirmadas: capacidade desconhecida não é vaga.')
        out['options'].append({'rank': i + 1, 'landing_id': q['landing_id'], 'label': q['label'], 'lat': q['lat'], 'lon': q['lon'], 'municipality': q['municipality'],
                               'source_kind': q['source_kind'], 'source_label': q['source_label'], 'distance': d, 'access': acc,
                               'capacity_per_hour': {'value': q['capacity_per_hour'], 'basis': q['capacity_basis'], 'label_pt': 'estimativa'},
                               'queue': qs, 'congested': qs['congested'], 'warnings_pt': warn,
                               'shelters': sh, 'shelters_excluded': rec['excluded'], 'shelters_message_pt': rec['message_pt'],
                               'ambulance': ambulance_card(case, group, q, sh[0] if sh else None)})
    if all(o['congested'] for o in out['options']): out['review_pt'].append('REVISAR: todos os pontos listados estão congestionados; decisão humana.')
    if group['medical'] and not any(o['shelters'] for o in out['options']): out['review_pt'].append('REVISAR: caso médico sem abrigo elegível; ambulância precisa de destino definido por humano.')
    return out
