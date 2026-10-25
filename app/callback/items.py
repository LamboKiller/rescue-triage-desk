"""Open items per case. Pure code: which facts still block (or refine) a dispatch, with the evidence for each.

Item ids are stable per kind so a before/after diff after a reply is a set difference.
Blocking mirrors app/decide.py + app/routing.py; nothing here authorizes anything.
"""

# Order = what unblocks dispatch first (place before people before status).
RANK = ['area.out_of_area', 'loc.municipality', 'loc.place', 'loc.number', 'dialogue.conflict', 'people.count',
        'people.conflict', 'stale.contact', 'rescue.unconfirmed', 'loc.approximate', 'people.derived',
        'vuln.unknown', 'people.remaining_conflict', 'source.original', 'dup.suspected', 'review.injection',
        'review.not_rescue', 'review.incomplete']
# Safety items outrank pure count refinements when nothing blocks (default one-question pick, see planner.primary_item).
SAFETY = ('stale.contact', 'rescue.unconfirmed', 'vuln.unknown', 'source.original')
GROUP = {'area.out_of_area': 'location', 'loc.municipality': 'location', 'loc.place': 'location', 'loc.number': 'location',
         'loc.approximate': 'location', 'dialogue.conflict': 'location', 'people.count': 'people',
         'people.conflict': 'people', 'people.derived': 'people', 'vuln.unknown': 'people',
         'people.remaining_conflict': 'people', 'source.original': 'status',
         'stale.contact': 'status', 'rescue.unconfirmed': 'status', 'dup.suspected': 'status'}
COUNT_FIELDS = ('people', 'children', 'elderly', 'disabled', 'pets', 'conflicting_counts')
WHY = {
    'area.out_of_area': 'Município ou estado possivelmente fora da área atendida; sem confirmação não há despacho.',
    'loc.municipality': 'Sem município confirmado, a equipe não sabe onde procurar.',
    'loc.place': 'A rua ou o ponto de referência não foi identificado com segurança.',
    'loc.number': 'Falta número da casa ou cruzamento exato.',
    'loc.approximate': 'Local aproximado: despacho possível, mas o ponto exato deve ser confirmado.',
    'dialogue.conflict': 'As mensagens indicam locais diferentes; é preciso saber qual vale.',
    'people.count': 'Sem número de pessoas não há como dimensionar o meio.',
    'people.conflict': 'Contagens conflitantes de pessoas.',
    'people.derived': 'Total de pessoas derivado por código (quem escreve + citados); confirmar.',
    'vuln.unknown': 'Crianças, idosos e acamados não informados; muda prioridade e equipamento.',
    'people.remaining_conflict': 'Pessoas resgatadas e restantes não fecham com o total inicial; confirmar com a equipe ou o contato.',
    'source.original': 'Mensagem repassada: falta a pessoa que fez o pedido original (só ela confirma local e pessoas).',
    'stale.contact': 'Sem atualização há muito tempo; confirmar se ainda estão no local.',
    'rescue.unconfirmed': 'Resgate apenas relatado no texto; falta confirmação.',
    'dup.suspected': 'Possível pedido duplicado de outro caso; revisão humana decide a união.',
    'review.injection': 'Texto com instrução suspeita; revisão humana, nenhuma pergunta automática.',
    'review.not_rescue': 'Mensagem sem pedido de resgate; revisão humana.',
    'review.incomplete': 'Análise automática incompleta; revisão humana.',
}


def _val(case, key):
    return (case.get('fields') or {}).get(key, {}).get('value')


def _quote(case, key):
    f = (case.get('fields') or {}).get(key) or {}
    return {'source': 'field', 'field': key, 'quote': f.get('quote'), 'value': f.get('value')} if f else None


def _fact(path, value):
    return {'source': 'fact', 'path': path, 'value': value}


def compute_items(case):
    """Return ordered open items: {id, kind, group, blocking, ask, resolvable_by_reply, why_pt, evidence}."""
    result = case.get('result') or {}
    flags = case.get('routing_flags') or {}
    route = (case.get('route') or {}).get('id')
    lm = case.get('landmark_check') or {}
    found = bool((case.get('checks') or {}).get('found'))
    items = []

    def add(item_id, blocking, evidence, ask=True, resolvable=True):
        items.append({'id': item_id, 'kind': item_id, 'group': GROUP.get(item_id), 'blocking': blocking, 'ask': ask,
                      'resolvable_by_reply': resolvable, 'why_pt': WHY[item_id],
                      'evidence': [e for e in evidence if e]})

    if flags.get('injection'):
        add('review.injection', True, [_fact('routing_flags.injection', True)], ask=False, resolvable=False)
    elif route == 'not_a_rescue':
        add('review.not_rescue', True, [_fact('route.id', route)], ask=False, resolvable=False)
    elif route == 'agent_failure' or (case.get('complete') is False and case.get('review_degraded')):
        add('review.incomplete', True, [_fact('route.id', route)], ask=False, resolvable=False)
    if items:
        return items  # never turn untrusted/failed analysis into questions
    if flags.get('out_of_area'):
        add('area.out_of_area', True, [_quote(case, 'municipality'), _fact('routing_flags.out_of_area', True)])
    else:
        if not _val(case, 'municipality'):
            add('loc.municipality', True, [_fact('fields.municipality', None), _fact('result.location_confidence', result.get('location_confidence'))])
        landmark_requested = bool(_val(case, 'landmark') or lm.get('requested'))
        resolved = lm.get('status') == 'resolved'
        approximate = bool(result.get('location_approximate'))
        place_open = ((landmark_requested and not resolved and not (approximate and found and lm.get('status') != 'ambiguous'))
                      or (not landmark_requested and not found and not resolved))
        if place_open:
            ev = [_quote(case, 'landmark'), _quote(case, 'street'), _fact('result.location_confidence', result.get('location_confidence'))]
            if lm.get('status') == 'ambiguous':
                for cand in lm.get('candidates') or []:
                    ev.append({'source': 'candidate', 'name': cand.get('name'), 'neighbourhood': cand.get('neighbourhood')})
            add('loc.place', True, ev)
        cross = bool(_val(case, 'cross_street') and (case.get('cross_street_check') or {}).get('found'))
        if not _val(case, 'number') and not cross and not landmark_requested and not resolved and not approximate:
            add('loc.number', True, [_quote(case, 'street'), _fact('fields.number', None)])
        if approximate:
            add('loc.approximate', False, [_fact('result.location_approximate', True), _quote(case, 'landmark'), _quote(case, 'street')])
    conflicts = case.get('contradictions') or []
    place_conflicts = [c for c in conflicts if c.get('field') not in COUNT_FIELDS]
    count_conflicts = [c for c in conflicts if c.get('field') in COUNT_FIELDS]
    if place_conflicts:
        ev = []
        for c in place_conflicts:
            ev.append({'source': 'conflict', 'field': c['field'], 'previous': (c.get('previous') or {}).get('value'),
                       'reply': (c.get('reply') or {}).get('value'), 'quote': c.get('quote') or (c.get('reply') or {}).get('quote')})
        add('dialogue.conflict', True, ev)
    people = _val(case, 'people') or 0
    if not isinstance(people, int) or people < 1:
        add('people.count', result.get('decision') != 'SEND_CANDIDATE', [_fact('fields.people', None)])
        people = 0
    if result.get('conflicting_counts') or count_conflicts:
        ev = [{'source': 'conflict', 'field': c['field'], 'previous': (c.get('previous') or {}).get('value'),
               'reply': (c.get('reply') or {}).get('value'), 'quote': c.get('quote') or (c.get('reply') or {}).get('quote')}
              for c in count_conflicts]
        ev.append(_quote(case, 'conflicting_counts'))
        add('people.conflict', True, ev)
    if case.get('stale') or any(i.get('reason') == 'stale' for i in case.get('open_items') or []):
        add('stale.contact', True, [_fact('stale', True)])
    if result.get('decision') == 'REPORTED_RESCUED':
        # Only a field team can confirm a rescue (decide.py): a citizen reply never closes this item.
        add('rescue.unconfirmed', True, [_quote(case, 'already_rescued'), _fact('result.decision', 'REPORTED_RESCUED')],
            resolvable=False)
    if result.get('people_derived'):
        f = (case.get('fields') or {}).get('people') or {}
        add('people.derived', False, [_quote(case, 'people'), _fact('fields.people.listed', f.get('listed'))])
    if people >= 1 and not any(k in (case.get('fields') or {}) for k in ('children', 'elderly', 'disabled')):
        add('vuln.unknown', False, [_fact('fields.children/elderly/disabled', None)])
    state = case.get('incident_state') or {}
    for conflict in state.get('open_items') or []:
        add(conflict['id'], False, [{'source': 'incident_state', 'reasons': conflict.get('reasons_pt')}]+list(conflict.get('evidence') or []))
    if (state.get('sender_role') or {}).get('value') == 'volunteer_repost':
        add('source.original', False, [{'source': 'sender_role', 'quote': (state['sender_role'].get('provenance') or {}).get('quote'),
                                         'value': 'volunteer_repost'}])
    dups = case.get('duplicates') or []
    if dups:
        add('dup.suspected', False, [{'source': 'duplicate', 'case_id': d.get('case_id'), 'score': d.get('score'),
                                      'reasons': d.get('reasons')} for d in dups], resolvable=False)
    items.sort(key=lambda i: RANK.index(i['id']))
    return items


def diff_items(before, after, asked=None):
    """Code-computed set difference. Items not resolvable by a reply (and, if given, not asked) are excluded from the ratio."""
    b, a = {i['id'] for i in before}, {i['id'] for i in after}
    resolvable = [i['id'] for i in before if i['resolvable_by_reply'] and (asked is None or i['id'] in asked)]
    resolved = [i for i in resolvable if i not in a]
    return {'resolved': sorted(resolved, key=RANK.index), 'remaining': [i for i in RANK if i in b & a],
            'new': [i for i in RANK if i in a - b], 'resolvable_before': len(resolvable),
            'resolved_ratio': round(len(resolved)/len(resolvable), 3) if resolvable else None}
