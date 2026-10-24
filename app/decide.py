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


def decide(fields, location, replay_time, received_at, complete=True, cross_location=None):
    def v(key, default=None):
        return fields.get(key, {}).get('value', default)
    questions = []
    people = v('people', 0)
    conflict = v('conflicting_counts', False) or any(v(k, 0) > people for k in ('children', 'elderly', 'disabled'))
    if not v('municipality'):
        questions.append('Em qual município está o pedido?')
    if not location['found']:
        questions.append('Qual é a rua e o município exatos? Só o ponto de referência não basta.')
    exact_cross = bool(v('cross_street') and cross_location and cross_location['found'])
    if not v('number') and not exact_cross:
        questions.append('Qual é o número da casa ou o cruzamento exato entre duas ruas?')
    if people < 1:
        questions.append('Quantas pessoas precisam de resgate?')
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
    decision = 'CALLBACK' if questions else 'SEND_CANDIDATE'
    if age < 0:
        priority = 0  # Future message facts cannot affect the replay queue.
    if v('already_rescued', False) and age >= 0:
        decision = 'REPORTED_RESCUED'
        questions.append('O resgate foi confirmado por uma equipe em campo?')
    return {'decision': decision, 'priority': priority, 'questions': questions,
            'age_hours': round(age, 2), 'conflicting_counts': conflict,
            'location_confidence': 'rua no cadastro; confirmar com pessoa' if location['found'] else 'insuficiente'}
