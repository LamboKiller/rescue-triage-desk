"""Explicit deterministic regex baseline, also used for offline recomputation.

This is deliberately limited; it is never presented as an available LLM agent.
"""
import re
from functools import lru_cache
import unicodedata
from app.geo.streets import normalize


def _fold(text):
    """Lower-case, accent-free copy of identical length (ACC1: 'cristovao' must find 'Cristóvão')."""
    out = ''.join((unicodedata.normalize('NFD', c.lower()) or c)[0] for c in text)
    return out if len(out) == len(text) else text.lower()


@lru_cache(maxsize=16)
def _street_patterns(names):
    patterns = []
    for display in names:
        name = re.escape(_fold(display))
        name = re.sub(r'^rua\\ ', r'ru+a+\\ ', name)
        name = re.sub(r'^avenida\\ ', r'av(?:enida)?\\.?\\s*', name)
        pattern = r'\b' + name.replace(r'\ ', r'\s+(?:(?:de|da|das|do|dos)\s+)?') + r'\b'
        patterns.append(re.compile(pattern))
    return patterns


def extract(text, rows, municipality=None):
    fields = {}
    def match(key, pattern, value=None):
        m = re.search(pattern, text, re.I)
        if m:
            fields[key] = {'value': value(m) if callable(value) else value,
                           'quote': m.group(0)}
    match('people', r'\b(\d+)\s+(?:pessoas|pesssoas|people|personas|pacientes)\b', lambda m: int(m[1]))
    for key, noun in [('children', 'crianças?'), ('elderly', 'idos[oa]s?'),
                      ('disabled', 'acamad[oa]s?'), ('pets', 'cachorros?|gatos?|pets?')]:
        match(key, rf'\b(\d+)\s+(?:{noun})\b', lambda m: int(m[1]))
    match('number', r'(?:n[úu]mero|n[ºo.]|nro|number)\s*[:=]?\s*(\d+)\b', lambda m: m[1])
    match('landmark', r'(?:perto|próximo|ao lado) d[aeo]\s+[^.;\n]+', lambda m: m[0])
    match('risk_words', r'telhado|[áa]gua subindo|[áa]gua entrou', lambda m: m[0])
    match('already_rescued', r'j[áa] (?:fomos resgatados|resgatad[oa]s?|tiraram todo mundo)', True)
    counts = re.findall(r'\b(\d+)\s+(?:pessoas|pesssoas|people|personas|pacientes)\b', text, re.I)
    if len(set(counts)) > 1:
        fields['conflicting_counts'] = {'value': True, 'quote': text}
    # Match actual substrings, preserving quotes even with case and accents.
    folded = _fold(text)
    cities = sorted({r['municipality'] for r in rows}, key=len, reverse=True)
    for city in cities + ['Curitiba', 'São Paulo']:
        m = re.search(re.escape(_fold(city)), folded)
        if m:
            fields['municipality'] = {'value': city, 'quote': text[m.start():m.end()]}
            break
    city = fields.get('municipality', {}).get('value') or municipality
    names = tuple(r['display_name'] for r in sorted((r for r in rows if r['municipality'] == city),
                                                   key=lambda r: len(r['display_name']), reverse=True))
    for pattern in _street_patterns(names):
        m = pattern.search(folded)
        if m:
            quote = text[m.start():m.end()]
            fields['street'] = {'value': quote, 'quote': quote}
            break
    return {'fields': fields}
