"""Resolve incident addresses from source data, retaining evidence for derivations.

Bairros come from OSM place:suburb/place:neighbourhood names and address
neighbourhood columns. Only names belonging to exactly one city imply a city.
"""
import csv
from functools import lru_cache
from pathlib import Path
import re
from app.derive_count import _plain, canonical_municipality, MUNICIPALITY_ALIASES, CORRECTION
from app.geo.streets import normalize as street_normalize

COVERED = {'porto alegre', 'canoas', 'sao leopoldo', 'eldorado do sul', 'guaiba', 'novo hamburgo'}
PREFIX = dict.fromkeys(('av', 'avenida', 'r', 'rua', 'tv', 'travessa', 'est', 'estrada'), 'via')
STOP = {'de', 'da', 'do', 'das', 'dos'}
CALLER = re.compile(r'\b(?:(?:estou|to|tou)\s+)?(?:ligando|telefonando|falando|escrevendo|ligo|moro|sou)\s+(?:aqui\s+)?(?:perto\s+(?:de|do|da)|ao\s+lado\s+(?:de|do|da)|de|do|da|em|no|na)\s+[^.;!\n]+', re.I)
INCIDENT = re.compile(r'\b(?:mas|porem|enquanto|o pedido|o resgate|ela mora|ele mora|eles estao|elas estao|minha irma|meu irmao)\b')


@lru_cache(maxsize=1)
def rs_municipalities():
    """Official IBGE snapshot; loading never performs network requests."""
    with (Path(__file__).resolve().parents[2]/'data/rs_municipios.csv').open(encoding='utf-8', newline='') as source:
        return {_plain(r['name']): r['name'] for r in csv.DictReader(source)}


@lru_cache(maxsize=1)
def municipality_pattern():
    return re.compile(r'\b(?:'+'|'.join(map(re.escape, sorted(rs_municipalities(), key=len, reverse=True)))+r')\b')


def municipality_mentions(scoped, name_spans=()):
    """Municipality assertions exclude caller clauses and catalogue place names."""
    masked = scoped.replace('rio grande do sul', ' '*len('rio grande do sul'))
    result = []
    for match in municipality_pattern().finditer(masked):
        if any(a <= match.start() and b >= match.end() and (a < match.start() or b > match.end())
               for a, b, _ in name_spans):
            continue
        # Avoid interpreting an unmapped street named after a municipality as
        # the municipality itself (e.g. Rua Rio Grande, em Canoas).
        before = masked[max(0, match.start()-90):match.start()]
        if re.search(r'\b(?:rua|avenida|travessa|estrada|bairro)\s+(?:(?:de|do|da)\s+)?$', before):
            continue
        cue = re.search(r'\b(?:em|no|na|cidade|municipio|municipality|city)(?:\s+(?:de|do|da))?\s*$|,\s*$', before)
        named_bairro = any(a == match.start() and b == match.end() for a, b, _ in name_spans)
        city_claim = re.search(r'\b(?:em|cidade|municipio|municipality|city)(?:\s+(?:de|do|da))?\s*$', before)
        if named_bairro and not city_claim:
            continue
        heading = not before.strip() and re.match(r'\s*[,;:]', masked[match.end():])
        if match[0] in COVERED or cue or heading or re.match(r'\s*[,/\-]?\s*rs\b', masked[match.end():]):
            result.append((match.start(), match.end(), rs_municipalities()[match[0]]))
    return result


def incident_text(text):
    plain = _plain(text)
    # A worried family in another city is a remote contact, not a second
    # incident address. Require the emotional-state predicate so a family
    # actually trapped in that city remains incident evidence.
    plain = re.sub(r'\b(?:(?:a|minha|nossa|sua)\s+)?(?:familia|parentes)\s+(?:toda\s+|todos\s+)?'
                   r'em\s+[^.;!?\n]{1,70}?\s+(?:(?:esta|ta|estao|tao)\s+)?(?:desesperad[oa]s?|preocupad[oa]s?)\b',
                   lambda m: m[0] if re.search(r'\b(?:ilhad|pres|agua|resgate|socorro)', m[0]) else ' '*len(m[0]), plain)
    # A remote reporter can state their own city after the incident clause too.
    # Mask only the city assertion, retaining offsets and the victim's address.
    remote = re.search(r'\b(?:a rua (?:da|do)|(?:minha|meu)\s+(?:ti[oa]|prim[oa]|irmao?|mae|pai|familia))\b', plain)
    if remote:
        caller_city = re.compile(r'\b(?:eu\s+)?(?:estou|to|tou)\s+(?:aqui\s+)?em\s+(?:'
            + '|'.join(map(re.escape, sorted(set(rs_municipalities()) | {'curitiba', 'recife', 'sao paulo', 'rio de janeiro', 'florianopolis'}, key=len, reverse=True))) + r')\b')
        plain = caller_city.sub(lambda m: m[0] if re.match(r'\s+com\b', plain[m.end():]) else ' '*len(m[0]), plain)
    def remove(m):
        tail = INCIDENT.search(m[0])
        return ' ' * (tail.start() if tail else len(m[0])) + (m[0][tail.start():] if tail else '')
    plain = CALLER.sub(remove, plain)
    # "Estou em X, mas o pedido é em Y" makes the first location caller-only.
    plain = re.sub(r'\b(?:estou|to|tou)\s+(?:(?:aqui|trabalhando)\s+)?(?:em|no|na)\s+[^.;!\n]+?(?=\b(?:mas|porem|o pedido|o resgate)\b)',
                   lambda m: ' '*len(m[0]), plain)
    def remote_relative(m):
        return m[0] if re.search(r'\bcom\b', m[0]) else ' '*len(m[0])
    plain = re.sub(r'\b(?:estou|to|tou)\s+(?:(?:aqui|trabalhando)\s+)?(?:em|no|na)\s+[^.;!\n]+?'
                   r'(?:,\s*|\s+e\s+)(?=(?:(?:a rua|o endereco|a casa) (?:da|do) |minha (?:mae|irma|avo|vo)|meu (?:pai|irmao|avo))\b)', remote_relative, plain)
    # Keep offsets into the original text; superseded streets cannot compete
    # with the explicitly corrected address.
    for correction in reversed(list(CORRECTION.finditer(plain))):
        if re.match(r'\s*[:,-]?\s*(?:e\s+)?(?:na\s+)?(?:rua|avenida|travessa|estrada)\b', plain[correction.end():]):
            plain = ' '*correction.end()+plain[correction.end():]
            break
    return plain


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
        for alias, city in MUNICIPALITY_ALIASES.items():
            if _plain(city) in self.cities:
                self.cities[alias] = city

    def hits(self, text, index, max_words=None):
        ts = tokens(text)
        result = []
        limit = max_words or max(map(len, index), default=0)
        for i in range(len(ts)):
            for size in range(1, min(limit, len(ts)-i)+1):
                found = index.get(tuple(t[0] for t in ts[i:i+size]))
                if found and index is self.streets:
                    # Some source records contain the municipality name as a
                    # street label. A city mention alone is not a street claim.
                    found = [r for r in found if key(r['display_name']) != key(r['municipality']) or
                             re.search(r'\b(?:rua|avenida|travessa|estrada)\s*$',
                                       _plain(text[max(0, ts[i][1]-20):ts[i][1]]))]
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
        all_street_hits = self.hits(_plain(text), self.streets, self.max_words) if CORRECTION.search(text) else street_hits
        if not street_hits and CORRECTION.search(text):
            # A correction still owns its exact phrase when the new street is
            # absent from the catalogue; unresolved does not restore old data.
            corrected = re.search(r'\b(?:rua|avenida|travessa|estrada)\s+[^,.;!\n\d]+?'
                                  r'(?=\s+\d|\s+em\s+|[,.;!\n]|$)', scoped)
            if corrected:
                a, b = corrected.span()
                previous = [dict(value=r['display_name'], quote=text[x:y])
                            for x, y, rs in all_street_hits for r in rs if y < a]
                if not previous and fields.get('street'):
                    previous = [fields['street']]
                fields['street'] = dict(value=text[a:b], quote=text[a:b], previous=previous,
                                        confirm=True, source='rule:corrected_street')
                old = fields.pop('number', None)
                number = re.match(r'\s*[,\-]?\s*(?:(?:numero|nro|n[º°o.]?)\s*[:=]?\s*)?(\d+[a-z]?)\b', scoped[b:])
                if number:
                    fields['number'] = dict(value=number[1], quote=text[b+number.start(1):b+number.end(1)],
                                            previous=[old] if old else [], confirm=True, source='rule:corrected_address_number')
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
        official = municipality_mentions(scoped, street_hits + bairro_hits)
        outside = [h for h in official if _plain(h[2]) not in COVERED]
        if outside:
            a, b, city = outside[-1]
            fields['municipality'] = dict(value=city, quote=text[a:b], source='rule:ibge_incident_municipality')
            # Do not let an identically named street in a covered city win.
            return scoped
        if len(cities) == 1:
            city = next(iter(cities))
        elif not cities and not bairro_cities:
            # An extracted city inferred from a street is not independent
            # evidence for choosing between same-named streets.
            city = ''
        if not city:
            implied = set().union(*(cs for _, _, cs in bairro_hits)) if bairro_hits else set()
            if len(implied) == 1:
                city = next(iter(implied))
            elif implied and street_hits:
                compatible = implied & {r['municipality'] for _, _, rs in street_hits for r in rs}
                if len(compatible) == 1:
                    city = next(iter(compatible))
        landmark_hits = self.hits(scoped, self.landmarks) if not city else []
        if not city and landmark_hits:
            implied = set().union(*(cs for _, _, cs in landmark_hits))
            if len(implied) == 1:
                city = next(iter(implied))
        candidates = [(a, b, r) for a, b, rs in street_hits for r in rs
                      if not city or _plain(r['municipality']) == _plain(city)]
        identities = {(key(r['display_name']), r['municipality']) for _, _, r in candidates}
        if not city and len({r['municipality'] for _, _, r in candidates}) > 1:
            fields['ambiguous_place'] = dict(value=True, quote=text, source='rule:multi_city_street')
        else:
            fields.pop('ambiguous_place', None)
        if len(identities) == 1:
            a, b, row = candidates[0]
            city = row['municipality']
            old_street = fields.get('street', {})
            name = (old_street['value'] if street_normalize(old_street.get('value', '')) ==
                    street_normalize(row['display_name']) else row['display_name'])
            if old_street.get('value') != name or old_street.get('quote') != text[a:b]:
                fields['street'] = {**old_street, 'value': name, 'quote': text[a:b],
                                    'derived': True, 'source': 'rule:street_catalogue'}
            superseded = [dict(value=r['display_name'], quote=text[x:y]) for x, y, r in
                          ((x, y, r) for x, y, rs in all_street_hits for r in rs)
                          if x < a and _plain(text[x:y]) not in scoped and key(r['display_name']) != key(name)]
            if superseded and CORRECTION.search(text):
                fields['street'].update(previous=superseded, confirm=True)
                old_number = fields.pop('number', None)
            else:
                old_number = None
            number = re.match(r'\s*[,\-]?\s*(?:(?:numero|nro|n[º°o.]?)\s*[:=]?\s*)?(\d+[a-z]?)\b', scoped[b:])
            if number:
                fields['number'] = {'value': number[1], 'quote': text[b+number.start(1):b+number.end(1)],
                                    'source': 'rule:address_number'}
                if old_number:
                    fields['number'].update(previous=[old_number], confirm=True)
            # Numeric corrections are explicitly tied to the old address
            # number; they must not consume corrections to a people total.
            number_fix = list(re.finditer(r'\bnao (?:e|era)\s+(\d+[a-z]?)\s*[,;]?\s*(?:e|era)\s+(\d+[a-z]?)\b', scoped))
            for fix in number_fix:
                old = fields.get('number', {})
                if str(old.get('value', '')) == fix[1]:
                    fields['number'] = dict(value=fix[2], quote=text[fix.start(2):fix.end(2)],
                        source='rule:corrected_address_number', previous=[old], confirm=True)
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
