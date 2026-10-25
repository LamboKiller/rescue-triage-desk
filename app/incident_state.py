"""Canonical incident state, computed by code from the case projection (which the World Model builds from its event log).

Nothing here is stored: the append-only JSONL already is the immutable mutation log, and this view is re-derived on every
read, so it can never drift from the events. Every value carries provenance (message id + exact quote). Agents only supply
quote-validated evidence (app/agents/needs.py); numbers and levels are chosen by code.
"""
from app.agents import needs as needs_agent
from app.decide import timestamp

PRECISIONS = ('EXACT', 'STREET', 'LANDMARK', 'AREA', 'AMBIGUOUS')
VULNERABILITY_TAGS = ('infant', 'pregnant', 'wheelchair', 'stretcher_or_bedridden', 'medical_urgent')
PLACE_FIELDS = ('municipality', 'street', 'number', 'landmark', 'cross_street')


def _field(case, key):
    return (case.get('fields') or {}).get(key) or {}


def _messages(case):
    """[(message_id, text, received_at, kind)] for the case's own contact history (reposts are separate)."""
    rows = case.get('messages')
    if not rows:
        return [(case.get('message_id'), case.get('text', ''), case.get('received_at'), 'original')]
    out = []
    for i, m in enumerate(rows):
        mid = m.get('message_id')
        out.append((mid, m.get('text', ''), m.get('received_at'),
                    'reply' if ':reply:' in str(mid) else 'original' if i == 0 else 'merged_case'))
    return out


def _prov(message_id, quote, source):
    return {'message_id': message_id, 'quote': quote, 'source': source}


def _quote_message(case, quote):
    return next((mid for mid, text, _, _ in reversed(_messages(case)) if quote and quote in text),
                case.get('message_id'))


def location_precision(case):
    lm = case.get('landmark_check') or {}
    quote = _field(case, 'landmark').get('quote') or _field(case, 'street').get('quote')
    mid = case.get('message_id')
    place_conflicts = [c for c in case.get('contradictions') or [] if c.get('field') in PLACE_FIELDS]
    if lm.get('status') == 'ambiguous' or place_conflicts:
        why = 'landmark_ambiguous' if lm.get('status') == 'ambiguous' else 'dialogue_location_conflict'
        return {'value': 'AMBIGUOUS', 'provenance': _prov(mid, quote, why)}
    raw = case.get('location_precision')
    position = (case.get('position') or {}).get('position_kind')
    if raw == 'exact':
        value = 'EXACT'
        quote = _field(case, 'number').get('quote') or quote
    elif lm.get('status') == 'resolved' or position == 'landmark' or (raw == 'approximate' and _field(case, 'landmark')):
        value = 'LANDMARK'
    elif raw in ('street', 'approximate') or (case.get('checks') or {}).get('found'):
        value = 'STREET'
    else:
        value, quote = 'AREA', _field(case, 'municipality').get('quote')
    return {'value': value, 'provenance': _prov(_quote_message(case, quote), quote, 'location_stage:'+str(raw))}


def context(case):
    """Needs-agent evidence for vertical level / sender / vulnerability: model-reviewed when the case carries it, else keyword."""
    messages = [t for _, t, _, _ in _messages(case)]
    ctx = needs_agent.fallback(messages)
    op = case.get('operational_needs') or {}
    rows = ctx['vertical']+list(op.get('vertical') or [])
    sender = op.get('sender') or ctx['sender']
    tags = list(ctx['needs'])+[n for n in op.get('needs') or [] if n not in ctx['needs']]
    return {'vertical': rows, 'sender': sender, 'needs': tags,
            'source': op.get('needs_check') or 'deterministic_only'}


def vulnerability(case, ctx):
    mids = [m for m, _, _, _ in _messages(case)]
    out, seen = [], set()
    for n in ctx['needs']:
        if n['tag'] in VULNERABILITY_TAGS and n['tag'] not in seen:
            seen.add(n['tag'])
            out.append({'flag': n['tag'], 'quote': n['quote'], 'message_id': mids[min(n['message_index'], len(mids)-1)],
                        'source': 'needs_agent' if ctx['source'] == 'model_reviewed' else 'keyword_fallback'})
    for key in ('children', 'elderly', 'disabled'):
        f = _field(case, key)
        if type(f.get('value')) is int and f['value'] > 0 and key not in seen:
            out.append({'flag': key, 'quote': f.get('quote'), 'message_id': case.get('message_id'), 'source': 'field'})
    return out


def people(case):
    """(initial, remaining, open_items). Never below 0; impossible combinations become an open item, not a silent pick."""
    frozen = case.get('people_initial_n')  # set by the registry at first ingest; facts[] can alias later edits
    if frozen is not None:
        first, first_mid = frozen, frozen.get('message_id') or case.get('message_id')
    else:
        first = ((case.get('facts') or [{}])[0].get('fields') or {}).get('people') or _field(case, 'people')
        first_mid = ((case.get('facts') or [{}])[0]).get('message_id') or case.get('message_id')
    initial_v = first.get('value') if type(first.get('value')) is int else None
    initial = {'value': None if initial_v is None else max(0, initial_v),
               'provenance': _prov(first_mid, first.get('quote'), first.get('source') or 'field')}
    feedback = [f for f in case.get('feedback') or [] if not f.get('conflicts')]
    quote = ' | '.join(o.get('quote', '') for f in feedback for o in f.get('outcomes', []) if str(o.get('kind', '')).endswith('_n'))
    current = _field(case, 'people')
    rem_n = case.get('remaining_n')
    items, remaining_v, src = [], None, None
    if type(rem_n) is int:
        remaining_v, src = rem_n, ('feedback', quote)
    elif type(current.get('value')) is int:
        remaining_v, src = current['value'], ('field', current.get('quote'))
    observed = [(i, f) for i, f in enumerate(case.get('feedback') or []) if not f.get('conflicts')
                and any(o.get('kind') in ('remaining_n', 'rescued_n', 'left_by_other_means') for o in f.get('outcomes', []))]
    if type(current.get('value')) is int and observed:
        field_mid = _quote_message(case, current.get('quote'))
        field_time = next((at for mid, _, at, kind in _messages(case) if mid == field_mid and kind == 'reply'), None)
        feedback_time = observed[-1][1].get('received_at')
        if field_time and feedback_time and timestamp(field_time) > timestamp(feedback_time):
            remaining_v, src = current['value'], ('field', current.get('quote'))
    latest_feedback = (case.get('feedback') or [None])[-1]
    problems = list(latest_feedback.get('conflicts') or []) if latest_feedback else []
    if problems:
        quote = ' | '.join(o.get('quote', '') for o in latest_feedback.get('outcomes', []))
    if initial_v is not None and initial_v < 0:
        problems.append('Total inicial negativo no registro.')
    if remaining_v is not None and remaining_v < 0:
        problems.append('Pessoas restantes negativas no registro.')
    rescued = case.get('rescued_n_total')
    if initial_v is not None:
        if type(rem_n) is int and rem_n > initial_v:
            problems.append('Restantes (%d) excedem o total inicial (%d).' % (rem_n, initial_v))
        if type(rescued) is int and rescued > initial_v:
            problems.append('Resgatados (%d) excedem o total inicial (%d).' % (rescued, initial_v))
        elif type(rescued) is int and type(rem_n) is int and rescued+rem_n != initial_v:
            problems.append('Resgatados (%d) + restantes (%d) diferem do total inicial (%d).' % (rescued, rem_n, initial_v))
    if problems:
        items.append({'id': 'people.remaining_conflict', 'reasons_pt': problems,
                      'evidence': [{'source': 'feedback', 'quote': quote or None, 'initial': initial_v,
                                    'rescued': rescued, 'remaining': rem_n}]})
    remaining = {'value': None if remaining_v is None else max(0, remaining_v),
                 'provenance': _prov(_quote_message(case, src[1] if src else None), src[1] if src else None, src[0] if src else None)}
    if type(rem_n) is int and src and src[0] == 'feedback':
        if observed:
            index, event = observed[-1]
            outcomes = [o for o in event.get('outcomes', []) if o.get('kind') in ('remaining_n', 'rescued_n', 'left_by_other_means')]
            remaining['provenance'] = {**_prov(None, outcomes[-1].get('quote'), 'field_feedback'),
                                       'case_id': case.get('case_id'), 'feedback_index': index,
                                       'received_at': event.get('received_at')}
    return initial, remaining, items


def raw_reports(case, ctx):
    texts = _messages(case)
    injected_case = bool((case.get('routing_flags') or {}).get('injection'))
    from app.derive_count import INJECTION
    out = []
    for i, (mid, text, at, kind) in enumerate(texts):
        s = needs_agent.scan_context([text])['sender']
        op_sender = (case.get('operational_needs') or {}).get('sender')
        if op_sender and op_sender.get('message_index') == i:
            s = op_sender
        out.append({'message_id': mid, 'received_at': at, 'kind': kind, 'sender_role': s['role'] if s else 'unknown',
                    'prompt_injection_detected': bool(INJECTION.search(text or '')) or (injected_case and i == 0)})
    for link in case.get('linked_reports') or []:
        if link.get('unlinked'):
            continue
        out.append({'message_id': link['message_id'], 'received_at': link['received_at'], 'kind': 'repost',
                    'sender_role': link.get('sender_role') or 'unknown',
                    'prompt_injection_detected': bool(link.get('prompt_injection_detected')),
                    'overlap': link.get('overlap')})
    return out


def compute(case):
    """Return the canonical state dict for one case projection."""
    from app.priority import score, dated_depth
    ctx = context(case)
    vertical = needs_agent.pick_vertical(ctx)
    mids = [m for m, _, _, _ in _messages(case)]
    sender = ctx['sender']
    initial, remaining, items = people(case)
    reports = raw_reports(case, ctx)
    clock = case.get('replay_time') or case.get('received_at')
    try:
        urgency = score(case, clock, dated_depth(case, clock))
    except Exception as exc:  # visible, never a silent zero
        urgency = {'score': None, 'reasons': [{'reason_pt': 'Urgência indisponível: '+type(exc).__name__, 'points': 0}]}
    return {
        'location_precision': location_precision(case),
        'people_initial': initial,
        'people_remaining': remaining,
        'vertical_level': {'value': vertical['level'],
                           'provenance': _prov(mids[min(vertical['message_index'], len(mids)-1)] if vertical['message_index'] is not None else None,
                                               vertical['quote'], ctx['source'])},
        'sender_role': {'value': sender['role'] if sender else 'unknown',
                        'provenance': _prov(mids[min(sender['message_index'], len(mids)-1)] if sender else None,
                                            sender['quote'] if sender else None, ctx['source'])},
        'vulnerability_flags': vulnerability(case, ctx),
        'report_count': sum(1 for r in reports if r['kind'] != 'reply'),
        'raw_reports': reports,
        'urgency_score': urgency['score'],
        'urgency_reasons': urgency['reasons'],
        'open_items': items,
        # Reposts are shown, never scored: more copies of one text are not more people.
        'viral_count_raises_priority': False,
    }
