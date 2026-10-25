"""Resolve incident addresses from source data, retaining evidence for derivations.

Bairros come from OSM place:suburb/place:neighbourhood names and address
neighbourhood columns. Only names belonging to exactly one city imply a city.
"""
import re
from app.derive_count import _plain, canonical_municipality
from app.geo.streets import normalize as street_normalize

COVERED = {'porto alegre', 'canoas', 'sao leopoldo', 'eldorado do sul', 'guaiba', 'novo hamburgo'}
PREFIX = dict.fromkeys(('av', 'avenida', 'r', 'rua', 'tv', 'travessa', 'est', 'estrada'), 'via')
STOP = {'de', 'da', 'do', 'das', 'dos'}
CALLER = re.compile(r'\b(?:(?:estou|to|tou)\s+)?(?:ligando|telefonando|falando|escrevendo|ligo|moro|sou)\s+(?:aqui\s+)?(?:de|em|no|na)\s+[^.;!\n]+', re.I)
INCIDENT = re.compile(r'\b(?:mas|porem|enquanto|o pedido|o resgate|ela mora|ele mora|eles estao|elas estao|minha irma|meu irmao)\b')


def incident_text(text):
    plain = _plain(text)
    def remove(m):
        tail = INCIDENT.search(m[0])
        return ' ' * (tail.start() if tail else len(m[0])) + (m[0][tail.start():] if tail else '')
    return CALLER.sub(remove, plain)


def tokens(text):
    return [(PREFIX.get(m[0], m[0]), m.start(), m.end())
            for m in re.finditer(r'\w+', _plain(text)) if m[0] not in STOP]


def key(text):
    return tuple(t[0] for t in tokens(text))


class IncidentIndex:
    def __init__(self, streets, landmarks):
        self.streets = {}
        self.bairros = {}
        self.landmarks = {}
        self.cities = {}
        for row in streets:
            self.cities[_plain(row['municipality'])] = row['municipality']
            self.streets.setdefault(key(row['display_name']), []).append(row)
        for row in landmarks:
            city = row['municipality']
            if _plain(city) not in COVERED:
                continue
            self.cities[_plain(city)] = city
            for name in [row['name']] + re.split(r'[|;]', row.get('alt_names', '')):
                if len(key(name)) >= 2:
                    self.landmarks.setdefault(key(name), set()).add(city)
            names = [row.get('neighbourhood', '')]
            if row.get('category') in ('place:suburb', 'place:neighbourhood'):
                names += [row['name']] + re.split(r'[|;]', row.get('alt_names', ''))
            for name in names:
                if name.strip():
                    self.bairros.setdefault(key(name), set()).add(city)
        self.max_words = max(map(len, self.streets), default=0)

    def hits(self, text, index, max_words=None):
        ts = tokens(text)
        result = []
        limit = max_words or max(map(len, index), default=0)
        for i in range(len(ts)):
            for size in range(1, min(limit, len(ts)-i)+1):
                found = index.get(tuple(t[0] for t in ts[i:i+size]))
                if found:
                    result.append((ts[i][1], ts[i+size-1][2], found))
        # Suppress names contained in a more specific street/bairro name.
        return [h for h in result if not any(a <= h[0] and b >= h[1] and b-a > h[1]-h[0]
                                             for a, b, _ in result)]

    def resolve(self, fields, text):
        value = lambda k: fields.get(k, {}).get('value', '')
        scoped = incident_text(text)
        street_hits = self.hits(scoped, self.streets, self.max_words)
        bairro_hits = self.hits(scoped, self.bairros)
        city_quote = fields.get('municipality', {}).get('quote', '')
        if city_quote and _plain(city_quote) in _plain(text) and _plain(city_quote) not in scoped:
            fields.pop('municipality', None)  # The evidence belongs only to the caller.
        raw_city = canonical_municipality(value('municipality'))
        city = self.cities.get(_plain(raw_city), '')
        bairro_cities = self.bairros.get(key(raw_city), set())
        if not city and len(bairro_cities) == 1:
            city = next(iter(bairro_cities))
        # Names embedded in street names do not assert a municipality.
        explicit = [(name, m) for name, display in self.cities.items()
                    for m in re.finditer(r'\b'+re.escape(name)+r'\b', scoped)
                    if not any(a <= m.start() and b >= m.end() for a, b, _ in street_hits)]
        cities = {self.cities[name] for name, _ in explicit}
        if len(cities) == 1:
            city = next(iter(cities))
        if not city:
            implied = set().union(*(cs for _, _, cs in bairro_hits)) if bairro_hits else set()
            if len(implied) == 1:
                city = next(iter(implied))
        landmark_hits = self.hits(scoped, self.landmarks) if not city else []
        if not city and landmark_hits:
            implied = set().union(*(cs for _, _, cs in landmark_hits))
            if len(implied) == 1:
                city = next(iter(implied))
        candidates = [(a, b, r) for a, b, rs in street_hits for r in rs
                      if not city or _plain(r['municipality']) == _plain(city)]
        identities = {(key(r['display_name']), r['municipality']) for _, _, r in candidates}
        if len(identities) == 1:
            a, b, row = candidates[0]
            city = row['municipality']
            old_street = fields.get('street', {})
            if street_normalize(old_street.get('value', '')) != street_normalize(row['display_name']):
                fields['street'] = {**old_street, 'value': row['display_name'], 'quote': text[a:b],
                                    'derived': True, 'source': 'rule:street_catalogue'}
            if not value('number'):
                number = re.match(r'\s*[,\-]?\s*(?:(?:n[uú]mero|n[ºo.]|nro)\s*[:=]?\s*)?(\d+[a-z]?)\b', scoped[b:])
                if number:
                    fields['number'] = {'value': number[1], 'quote': text[b+number.start(1):b+number.end(1)],
                                        'source': 'rule:address_number'}
        if city and (city != value('municipality')):
            quote = fields.get('municipality', {}).get('quote') or (
                text[explicit[0][1].start():explicit[0][1].end()] if explicit else
                text[bairro_hits[0][0]:bairro_hits[0][1]] if bairro_hits else
                text[landmark_hits[0][0]:landmark_hits[0][1]] if landmark_hits else
                fields.get('street', {}).get('quote', ''))
            fields['municipality'] = {**fields.get('municipality', {}), 'value': city, 'quote': quote, 'derived': True,
                                      'source': 'rule:incident_catalogue'}
        # Mask whole verified names before outside-city detection.
        masked = list(scoped)
        for a, b, _ in street_hits + bairro_hits:
            masked[a:b] = ' ' * (b-a)
        return ''.join(masked).replace('rio grande do sul', ' ' * len('rio grande do sul'))
