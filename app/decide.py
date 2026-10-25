"""All scores, count consistency checks and decisions are deterministic."""
from datetime import datetime


def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, OverflowError, AttributeError):
        # datetime's default error embeds the original input; keep identifiers out
        # of HTTP error responses as well as logs.
        raise ValueError('Horário inválido. Use ISO 8601 com fuso horário.') from None
    if dt.tzinfo is None:
        raise ValueError('Horário deve incluir fuso, por exemplo -03:00.')
    return dt


def decide(fields, location, replay_time, received_at, complete=True, cross_location=None, landmark_location=None,
           life_safety=False, people_signal=True):
    def v(key, default=None):
        return fields.get(key, {}).get('value', default)
    questions = []
    people = v('people', 0) or 0
    for key, label in (('people', 'total de pessoas'), ('street', 'rua'), ('number', 'número'), ('municipality', 'município')):
        if fields.get(key, {}).get('confirm'):
            questions.append('Pode confirmar a correção de '+label+'?')
    # A vulnerable-group count can only contradict a total that was actually given (no total -> ask the count, not a conflict).
    conflict = v('conflicting_counts', False) or (people >= 1 and any(v(k, 0) > people for k in ('children', 'elderly', 'disabled')))
    lm = landmark_location or {}
    resolved = lm.get('status') == 'resolved' and not lm.get('context_only')
    landmark_request = bool(v('landmark') or lm.get('requested'))
    context_only = bool(location['found'] and v('number') and lm.get('context_only'))
    area = bool(resolved and lm.get('precision') == 'area')
    approximate = bool(area or not v('number') and (resolved or life_safety and location['found']))
    if not v('municipality') and not resolved:
        questions.append('Em qual município está o pedido?')
    if lm.get('status') == 'conflict':
        questions.append('A referência contradiz o endereço; qual é o local correto?')
    elif landmark_request and not resolved and not context_only and not (approximate and location['found'] and lm.get('status') != 'ambiguous'):
        if lm.get('status') == 'ambiguous':
            names = [r['name'] + (' ('+r['neighbourhood']+')' if r.get('neighbourhood') else '') for r in lm['candidates']]
            questions.append('É '+ ' ou '.join(names) +'?')
        else:
            questions.append('Qual o nome do lugar/bairro?')
    elif not location['found'] and not resolved:
        questions.append('Qual é a rua e o município exatos?')
    exact_cross = bool(v('cross_street') and cross_location and cross_location['found'])
    if not v('number') and not exact_cross and not landmark_request and not resolved and not approximate:
        questions.append('Qual é o número da casa ou o cruzamento exato entre duas ruas?')
    if conflict:
        questions.append('Há contagens conflitantes. Qual é o total de pessoas e de pessoas vulneráveis?')
    if not complete:
        questions.append('A análise automática ficou incompleta. Pode confirmar os dados do pedido?')
    age = (timestamp(replay_time) - timestamp(received_at)).total_seconds() / 3600
    if age < 0:
        questions.append('O pedido é posterior ao horário de replay. Qual é o horário correto?')
    # Categories may overlap: use max, never sum to infer a distinct population.
    vulnerable = max(v('children', 0), v('elderly', 0), v('disabled', 0))
    priority = 5 * min(vulnerable, 10) + 8 * bool(v('risk_words'))
    priority += 4 * (location.get('in_water_by_date') is True) + min(24, max(0, int(age)))
    # SAFE2-B: an unknown count never blocks a usable location, but only when the text
    # shows people in danger; otherwise the desk still has to ask who needs rescue.
    count_open = people < 1
    if count_open and not (people_signal or life_safety or fields.get('count_unknown') or
                           any(v(k, 0) for k in ('children', 'elderly', 'disabled'))):
        questions.append('Quantas pessoas precisam de resgate?')
    decision = 'CALLBACK' if questions else 'SEND_CANDIDATE'
    if count_open and 'Quantas pessoas precisam de resgate?' not in questions:
        questions.append('Quantas pessoas precisam de resgate?')
    if approximate:
        questions.append('Qual é o ponto exato ou referência para a equipe localizar as pessoas?')
    if age < 0:
        priority = 0  # Future message facts cannot affect the replay queue.
    if v('already_rescued', False) and age >= 0:
        decision = 'REPORTED_RESCUED'
        questions.append('O resgate foi confirmado por uma equipe em campo?')
    reason = ('Resgate relatado no texto; aguarda confirmação em campo.' if decision == 'REPORTED_RESCUED' else
              'Risco à vida e local aproximado identificado; confirmar o ponto exato em paralelo.' if
                  decision == 'SEND_CANDIDATE' and approximate else
              'Dados pendentes: ' + ' '.join(questions) if questions else
              'Local por ponto de referência e contagem de pessoas informados; confirmar o local com a pessoa.' if resolved else
              'Rua e número ou cruzamento e contagem de pessoas informados; confirmar o local com a pessoa.')
    people_derived = bool(fields.get('people', {}).get('derived'))
    if count_open and decision == 'SEND_CANDIDATE':
        reason = 'contagem desconhecida, confirmar. ' + reason
    if people_derived and decision != 'REPORTED_RESCUED':
        grouped = fields['people'].get('source') == 'rule:grouped_people'
        reason = 'Contagem derivada — confirmar: '+('mínimo ' if fields['people'].get('minimum') else '')+str(people)+' ('+('grupos: ' if grouped else 'quem escreve + ')+', '.join(
            fields['people'].get('listed', []))+'). ' + reason
    return {'decision': decision, 'priority': priority, 'questions': questions,
            'decision_reason': reason, 'people_derived': people_derived,
            'location_approximate': approximate,
            'people': people if people >= 1 else None,
            'location_precision': 'area' if area else 'approximate' if approximate else 'exact' if v('number') else 'street',
            'age_hours': round(age, 2), 'conflicting_counts': conflict,
            'location_confidence': 'local por ponto de referência — confirmar com a pessoa' if resolved else
                ('rua no cadastro; confirmar com pessoa' if location['found'] else 'insuficiente')}
