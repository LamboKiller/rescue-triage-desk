"""Row constructor for dev2 items (labels are written by hand; this only fixes the schema)."""

DECISIONS = ('SEND', 'SEND_APPROX', 'CALLBACK', 'REVIEW', 'RESCUED')
BASES = ('stated', 'derived', 'unknown', 'none')
ROUTES = ('street', 'landmark', 'ambiguous_place', 'already_rescued', 'not_a_request_or_injection',
          'not_a_rescue', 'volunteer_offer', 'out_of_area', 'incomplete', None)
BUCKET = {}  # class -> bucket, filled by build.py


def R(cls, text, decision, people=None, basis='none', route=None, municipality=None, street=None,
      bairro=None, lm=None, amb=False, why='', date='2024-05-06', in_area=True, street_ok=True,
      approx=False, bucket=None):
    if approx and decision == 'SEND':
        decision = 'SEND_APPROX'
    return {'class': cls, 'text': text, 'replay_date': date,
            'expected_decision': decision, 'expected_people': people, 'count_basis': basis,
            'expected_route': route, 'expected_precision': (
                'approximate' if decision == 'SEND_APPROX' else 'exact' if decision == 'SEND' else None),
            'key_fields': {k: v for k, v in (('municipality', municipality), ('street', street),
                                              ('bairro', bairro), ('landmark', lm)) if v},
            'in_area': in_area, 'ambiguous': bool(amb), 'rationale': why, 'bucket': bucket}
