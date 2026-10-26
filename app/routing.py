"""Deterministic, auditable routing; untrusted instructions never authorize SEND."""
import re
from app.derive_count import INJECTION, _plain, completed_rescue_quote, REMAINING
from app.geo.incident import incident_text, rs_municipalities, municipality_mentions
from app.rescue_state import ANIMALS, state
from app.volunteers.detect import is_offer as volunteer_offer

COVERED = {'porto alegre', 'canoas', 'sao leopoldo', 'eldorado do sul', 'guaiba', 'novo hamburgo'}
OUTSIDE = re.compile(r'\b(?:'+'|'.join(map(re.escape, sorted(set(rs_municipalities()) - COVERED, key=len, reverse=True)))+
    r'|recife|curitiba|sao paulo|rio de janeiro|belo horizonte|florianopolis|pernambuco|parana|santa catarina|bahia|ceara|maranhao|piaui|estado do para|amazonas|acre|amapa|roraima|rondonia|tocantins|goias|mato grosso(?: do sul)?|espirito santo|sergipe|alagoas|paraiba|rio grande do norte|distrito federal)\b|(?:/|\bestado (?:de|do) )\s*(?:sp|pr|pe|sc|rj|mg|ba|ce|ma|pi|pa|am|ac|ap|rr|ro|to|go|mt|ms|es|se|al|pb|rn|df)\b')
REQUEST = re.compile(r'precisamos|preciso|socorro|nos resgat|nos ajudar|estamos (?:presos|ilhados)|agua (?:entrou|subindo)|need (?:rescue|help)|necesitamos|evacuar|resgat(?:e|ar) (?:meu|nosso|a gente)')
LABELS = {'street':'Rua identificada', 'landmark':'Ponto de referência', 'ambiguous_place':'Local ambíguo',
          'not_a_rescue':'Sem pessoas para resgatar — revisão humana',
          'volunteer_offer':'Voluntários — oferta de ajuda',
          'already_rescued':'Resgate relatado', 'not_a_request_or_injection':'Sem pedido verificável ou instrução suspeita',
          'out_of_area':'Fora da área atendida', 'agent_failure':'Falha na análise', 'incomplete':'Dados incompletos'}


def animal_rescue(text):
    """Animal danger still needs rescue review even when no people remain."""
    status = state(text)
    normalized = _plain(text)
    danger = status['life_safety'] or re.search(r'\b(?:na agua|alag\w*|inund\w*|enchente)\b', normalized)
    return bool(status['not_a_rescue'] and danger and ANIMALS.search(normalized))


def apply_route(case, rows):
    fields = case['fields']; result = case['result']; text = _plain(case['text'])
    city = _plain(fields.get('municipality', {}).get('value', ''))
    lm = case.get('landmark_check') or {}
    injection = bool(INJECTION.search(case['text']))
    outside_text = case.get('incident_outside_text', incident_text(case['text']))
    outside_match = OUTSIDE.search(outside_text)
    # Outside text must assert an incident location, not just mention a city.
    outside_cue = bool(outside_match and re.search(
        r'\b(?:em|no|na|municipio|cidade|estado|pedido|resgate|socorro)\b[^.;!\n]{0,70}$|/\s*$',
        outside_text[:outside_match.start()]))
    outside = bool((city and city not in COVERED) or outside_cue or
                   any(_plain(h[2]) not in COVERED for h in municipality_mentions(outside_text)))
    # A direct assertion about the incident's state contradicts a city match;
    # a street catalogue hit alone cannot reconcile that conflicting address.
    if outside_match and re.search(r'\b(?:endereco|local|pedido|resgate)\b[^.;!\n]{0,30}\bestado\b',
                                   outside_text[:outside_match.start()]):
        outside = True
    rescue = state(case['text'])
    rescue_quote = completed_rescue_quote(case['text'])
    remaining = rescue['partial'] or bool(REMAINING.search(text))
    if rescue_quote and not remaining and result.get('age_hours', 0) >= 0:
        fields['already_rescued'] = dict(value=True, quote=rescue_quote, source='rule:completed_rescue')
        result.update(decision='REPORTED_RESCUED', decision_reason='Resgate relatado no texto; aguarda confirmação em campo.',
                      questions=['O resgate foi confirmado por uma equipe em campo?'])
    elif remaining:
        fields.pop('already_rescued', None)
        if result['decision'] == 'REPORTED_RESCUED':
            result.update(decision='CALLBACK', decision_reason='Há pessoas ainda no local; confirmar quem precisa de resgate.',
                          questions=['Quem ainda precisa de resgate e em qual local?'])
    for key in ('street', 'number', 'municipality'):
        field = fields.get(key, {})
        if field.get('confirm'):
            conflicts = case.setdefault('contradictions', [])
            for old in field.get('previous', []):
                conflicts.append(dict(field=key, previous=old, reply=field, quote=field['quote']))
    failure = not case.get('complete', False) or case.get('review_degraded') or any(
        e.startswith(('agent_step_failed', 'location_failed', 'global_deadline', 'message_deadline')) for e in case.get('errors', []))
    route = 'street'
    if injection:
        route = 'not_a_request_or_injection'
        result.update(decision='REVIEW_REQUIRED',
                      decision_reason='Instrução suspeita no texto; revisão humana obrigatória.')
    elif volunteer_offer(case['text']):  # F6: boat offer, never a rescue case
        route = 'volunteer_offer'
        result.update(decision='REVIEW_REQUIRED', questions=[], decision_reason='oferta de ajuda — verificar voluntário')
    elif rescue['not_a_rescue'] and not animal_rescue(case['text']) and case.get('complete') and not case.get('errors'):
        route = 'not_a_rescue'
        note = ' critic indisponível; revisão humana necessária.' if case.get('review_degraded') else ''
        result.update(decision='REVIEW_REQUIRED', questions=[],
                      decision_reason='Sem pessoas precisando de resgate; encaminhar para revisão humana.'+note)
    elif failure:
        route = 'agent_failure'
        result.update(decision='REVIEW_REQUIRED', decision_reason='Falha na análise automática; revisão humana obrigatória.')
    elif animal_rescue(case['text']):
        route = 'incomplete'
        result.update(decision='REVIEW_REQUIRED',
                      decision_reason='Animais precisando de resgate; revisão humana obrigatória.')
    elif rescue['not_a_rescue']:
        route = 'not_a_rescue'
        result.update(decision='REVIEW_REQUIRED',
                      decision_reason='Sem pessoas precisando de resgate; encaminhar para revisão humana.')
    elif outside:
        route = 'out_of_area'
        result.update(decision='CALLBACK', decision_reason='Município ou estado fora dos seis municípios atendidos; confirmar encaminhamento.')
    elif result['decision'] == 'REPORTED_RESCUED':
        route = 'already_rescued'
    elif fields.get('ambiguous_place', {}).get('value'):
        route = 'ambiguous_place'
        result.update(decision='CALLBACK', decision_reason='Rua presente em mais de um município; confirmar o local.',
                      questions=['Qual é o município, bairro ou referência da rua?'])
    elif ((len(re.findall(r'\b(?:rua|avenida|travessa|estrada)\b', text)) > 1 or
           sum(bool(re.search(r'\b'+re.escape(c)+r'\b', text)) for c in COVERED) > 1)
          and (re.search(r'\bou\b|pedido (?:um|dois)|nao sei qual|(?:dois|ambos (?:os )?)\s*(?:lugares|locais|enderecos)|duas casas', text))):
        route = 'ambiguous_place'
        result.update(decision='CALLBACK', decision_reason='Há mais de um local ou pedido; confirmar cada local separadamente.',
                      questions=['Qual local corresponde a cada grupo de pessoas?'])
    elif lm.get('status') == 'ambiguous':
        route = 'ambiguous_place'
        result.update(decision='CALLBACK')
    elif result['decision'] == 'CALLBACK':
        route = 'incomplete' if fields else 'not_a_request_or_injection'
    elif lm.get('status') == 'resolved' and not lm.get('context_only'):
        route = 'landmark'
    if route in ('out_of_area', 'not_a_request_or_injection'):
        result['questions'] = ['Pode confirmar o pedido e o município para encaminhamento humano?']
    case['route'] = {'id':route, 'label_pt':LABELS[route], 'reason_pt':result['decision_reason'], 'steps':[]}
    case.pop('incident_outside_text', None)
    case['routing_flags'] = {'injection':injection, 'out_of_area':outside,
                            'location_approximate':bool(result.get('location_approximate')),
                            'source':'rule:routing_v2'}


def finish_route(case):
    steps = case['route']['steps']
    offline = case.get('extraction_method') == 'regex_baseline'
    if offline:
        steps.append({'stage':'regex_baseline', 'status':'ran', 'reason_pt':'Modo offline explícito.'})
    for role in ('intake', 'critic', 'revision', 'location'):
        stage = case.get('agents', {}).get(role)
        ran = isinstance(stage, dict)
        failed = isinstance(stage, str) and 'fail' in stage
        steps.append({'stage':role, 'status':'ran' if ran else 'failed' if failed else 'skipped',
                      'reason_pt':'Resultado registrado.' if ran else 'Falha registrada.' if failed else
                      'Modo offline.' if offline else 'Não necessário nesta análise.'})
    for stage in ('street_lookup', 'landmark_lookup', 'hazards', 'fleet', 'decision'):
        ran = (case.get('extraction_method') != 'unavailable' and
               (stage != 'landmark_lookup' or case.get('landmark_check') is not None))
        if stage in ('decision', 'fleet'):
            ran = True
        steps.append({'stage':stage, 'status':'ran' if ran else 'skipped',
                      'reason_pt':'Regra determinística.' if ran else 'Etapa dispensada ou análise indisponível.'})
    ran = isinstance(case.get('hazard_review'), dict)
    failed = 'hazard_critic' in case.get('agents', {}) and not ran
    steps.append({'stage':'hazard_critic', 'status':'ran' if ran else 'failed' if failed else 'skipped',
                  'reason_pt':'Revisão registrada.' if ran else 'Crítica indisponível.' if failed else
                  'Modo offline.' if offline else 'Decisão: '+case['result']['decision']})
    for row in case.get('latency_budget', {}).get('stages', []):
        if row['status'] in ('skipped', 'code_fallback'):
            steps.append({'stage':row['stage'], 'status':row['status'],
                          'reason_pt':row.get('reason', 'Orçamento por etapa.'), 'source':'stage_budget'})
    for event in case.get('arbitration', []):
        steps.append({'stage':'arbitration', 'status':'escalated' if event['verdict']=='ESCALATE' else 'resolved',
                      'reason_pt':event.get('rule') or event['method'], 'conflict_id':event['id'],
                      'claims':event['claims'], 'verdict':event['verdict'], 'receipt':event.get('receipt')})
