"""Explicit deterministic regex baseline, also used for offline recomputation.

This is deliberately limited; it is never presented as an available LLM agent.
"""
import re
from app.geo.streets import normalize


def extract(text, rows):
    fields = {}
    def match(key, pattern, value=None):
        m = re.search(pattern, text, re.I)
        if m:
            fields[key] = {'value': value(m) if callable(value) else value,
                           'quote': m.group(0)}
    match('people', r'\b(\d+)\s+(?:pessoas|pesssoas)\b', lambda m: int(m[1]))
    for key, noun in [('children', 'crianças?'), ('elderly', 'idos[oa]s?'),
                      ('disabled', 'acamad[oa]s?'), ('pets', 'cachorros?|gatos?|pets?')]:
        match(key, rf'\b(\d+)\s+(?:{noun})\b', lambda m: int(m[1]))
    match('number', r'(?:n[úu]mero|n[ºo.]|nro)\s*[:=]?\s*(\d+)\b', lambda m: m[1])
    match('landmark', r'(?:perto|próximo|ao lado) d[aeo]\s+[^.;\n]+', lambda m: m[0])
    match('risk_words', r'telhado|[áa]gua subindo|[áa]gua entrou', lambda m: m[0])
    match('already_rescued', r'j[áa] (?:fomos resgatados|resgatad[oa]s?|tiraram todo mundo)', True)
    counts = re.findall(r'\b(\d+)\s+(?:pessoas|pesssoas)\b', text, re.I)
    if len(set(counts)) > 1:
        fields['conflicting_counts'] = {'value': True, 'quote': text}
    # Match actual substrings, preserving quotes even with case and accents.
    cities = sorted({r['municipality'] for r in rows}, key=len, reverse=True)
    for city in cities + ['Curitiba', 'São Paulo']:
        m = re.search(re.escape(city), text, re.I)
        if m:
            fields['municipality'] = {'value': city, 'quote': m[0]}
            break
    city = fields.get('municipality', {}).get('value')
    for row in sorted((r for r in rows if r['municipality'] == city),
                      key=lambda r: len(r['display_name']), reverse=True):
        m = re.search(re.escape(row['display_name']), text, re.I)
        if m:
            fields['street'] = {'value': row['display_name'], 'quote': m[0]}
            break
    return {'fields': fields}
