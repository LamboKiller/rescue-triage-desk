"""Deterministic OSM name matching. Model guesses never become coordinates."""
import re
import unicodedata
import math
from app.geo.streets import normalize as street_normalize

STOP = {'a', 'o', 'as', 'os', 'de', 'da', 'do', 'das', 'dos', 'em', 'no', 'na', 'estacao', 'hospital'}


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', str(text).casefold()) if unicodedata.category(c) != 'Mn')
    return ' '.join(w for w in re.findall(r'[a-z0-9]+', text) if w not in STOP)


CONTEXT_STOP = {'dentro', 'perto', 'proximo', 'lado', 'ao', 'estamos', 'estou', 'aqui', 'junto'}
CATEGORIES = {'hospital': {'amenity:hospital'}, 'escola': {'amenity:school'},
              'igreja': {'amenity:place_of_worship'}, 'mercado': {'amenity:marketplace', 'shop:supermarket'},
              'aeroporto': {'aeroway:aerodrome', 'aeroway:terminal'}, 'estadio': {'leisure:stadium'},
              'shopping': {'shop:mall'}, 'rodoviaria': {'amenity:bus_station'}}
GENERIC = {'mercado', 'hospital', 'escola', 'igreja', 'shopping', 'aeroporto', 'estadio', 'zaffari'}
MARGIN = 7.0


def distance(a, b):
    try:
        lat1, lon1, lat2, lon2 = map(math.radians, (float(a['lat']), float(a['lon']), float(b['lat']), float(b['lon'])))
        h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        return 6371000*2*math.asin(min(1, math.sqrt(h)))
    except (KeyError, ValueError, TypeError):
        return float('inf')


def distinct_places(rows):
    """Cluster equal primary names within 400 m; prefer relation, then way.

    Retain member IDs for evaluation against either representation of a place.
    Missing coordinates are never evidence of duplication.
    """
    groups = {}
    for row in sorted(rows, key=lambda r: (r.get('osm_type', ''), r.get('osm_id', ''))):
        key = (normalize(row['municipality']), normalize(row['name']))
        clusters = groups.setdefault(key, [])
        group = next((g for g in clusters if any(distance(row, old) <= 400 for old in g)), None)
        if group is None:
            clusters.append([row])
        else:
            group.append(row)
    result = []
    for clusters in groups.values():
        for group in clusters:
            ordered = sorted(group, key=lambda r: (-{'relation': 2, 'way': 1}.get(r.get('osm_type'), 0), r['osm_id']))
            row = dict(ordered[0])
            for key in ('street', 'neighbourhood', 'housenumber'):
                row[key] = next((r.get(key) for r in ordered if r.get(key)), '')
            row['alt_names'] = '|'.join(sorted({n for r in group for n in re.split(r'[|;]', r.get('alt_names', '')) if n}))
            row['osm_members'] = [{'osm_type': r['osm_type'], 'osm_id': r['osm_id']} for r in ordered]
            result.append(row)
    return result


def match(rows, place_name='', landmark_quote='', municipality='', neighbourhood='', replay='2024-05-06',
          message='', streets=()):
    city = set(normalize(municipality).split())
    queries = []
    for q in (place_name, landmark_quote):
        tokens = [t for t in normalize(q).split() if t not in CONTEXT_STOP]
        # Municipality is a scope, not a distinguishing landmark token.
        local = [t for t in tokens if t not in city]
        if local:
            queries.append(' '.join(local))
    context = normalize(' '.join((message, landmark_quote, place_name, neighbourhood)))
    raw_context = ' '.join(re.findall(r'[a-z0-9]+', unicodedata.normalize('NFD',
                                  ' '.join((message, landmark_quote, place_name))).encode('ascii', 'ignore').decode().lower()))
    hints = {category for word, categories in CATEGORIES.items() if word in raw_context.split() for category in categories}
    if 'banco sangue' in context or 'laboratorio' in context.split():
        hints = {'amenity:clinic'}
    # Established short names provide category evidence, never invented coordinates.
    if not hints:
        if 'salgado filho' in context:
            hints = CATEGORIES['aeroporto']
        elif 'beira rio' in context or 'arena gremio' in context:
            hints = CATEGORIES['estadio']
        elif 'clinicas' in context.split():
            hints = CATEGORIES['hospital']
    scoped = [r for r in rows if municipality and normalize(r['municipality']) == normalize(municipality)]
    street_cues = {street_normalize(r['display_name']) for r in streets
                   if normalize(r['municipality']) == normalize(municipality)
                   and street_normalize(r['display_name'])
                   and (' '+street_normalize(r['display_name'])+' ') in (' '+street_normalize(context)+' ')}
    street_cues.update(street_normalize(r.get('street', '')) for r in scoped
                       if street_normalize(r.get('street', '')) and
                       (' '+street_normalize(r['street'])+' ') in (' '+street_normalize(context)+' '))
    street_cues = {s for s in street_cues if len(s.split()) >= 2 and
                   not any(set(s.split()) == set(q.split()) for q in queries) and
                   not set(s.split()) <= city}
    suburbs = {normalize(r['name']) for r in scoped if r['category'] in ('place:suburb', 'place:neighbourhood')
               and (' '+normalize(r['name'])+' ') in (' '+context+' ')}
    if neighbourhood:
        suburbs.add(normalize(neighbourhood))
    candidates = []
    message_normalized = normalize(message)
    for row in distinct_places(scoped):
        if hints and row['category'] not in hints:
            continue
        score = 0
        for name in [row['name']] + re.split(r'[|;]', row.get('alt_names', '')):
            n = normalize(name)
            if not n:
                continue
            if (message and len(n.split()) >= 2 and not set(n.split()) <= city
                    and (' '+n+' ') in (' '+message_normalized+' ')):
                score = max(score, 90)
            for q in queries:
                # A street qualifier is matched separately against address context.
                qtokens = set(q.split())
                for street in street_cues:
                    qtokens -= set(street.split())
                ntokens = set(n.split()) - city
                if not qtokens or not ntokens:
                    continue
                overlap = len(qtokens & ntokens) / len(qtokens | ntokens)
                qn = ' '.join(t for t in q.split() if t in qtokens)
                if q == n:
                    value = 100
                elif qtokens == ntokens:
                    value = 100
                elif qtokens <= ntokens:
                    value = 90
                elif overlap >= .8:
                    value = 82 + overlap
                elif (min(len(qn), len(n)) >= 5 and (qn in n or n in qn)
                      and not ntokens <= GENERIC and len(qtokens & ntokens)/len(qtokens) >= .5):
                    value = 55
                else:
                    value = 0
                if value:
                    score = max(score, value)
        if score:
            preference = bool(normalize(row.get('neighbourhood', '')) in suburbs)
            street_match = bool(street_normalize(row.get('street', '')) in street_cues)
            # Sub-facilities must be explicitly requested, even when their parent name matches.
            if any(w in normalize(row['name']) and w not in context for w in ('banco sangue', 'laboratorio', 'anexo')):
                score -= 15
            candidates.append({**row, 'score': round(score + 10*preference, 3),
                               'street_preferred': street_match, 'neighbourhood_preferred': preference})
    if street_cues:
        candidates = [c for c in candidates if c['street_preferred']]
    candidates.sort(key=lambda r: (-r['score'], -r['neighbourhood_preferred'], r['name'], r['osm_id']))
    generic = bool(queries) and all(set(q.split()) <= GENERIC for q in queries) and not street_cues and not suburbs
    clear = bool(candidates) and not generic and candidates[0]['score'] >= 82 and (
        len(candidates) == 1 or candidates[0]['score']-candidates[1]['score'] >= MARGIN)
    dates = [d for d in ('2024-05-06', '2024-05-08') if d <= replay[:10]]
    observed = dates[-1] if dates else None
    return {'status': 'resolved' if clear else ('ambiguous' if candidates else 'unresolved'),
            'matched': candidates[0] if clear else None, 'candidates': candidates[:3], 'observed_date': observed,
            'reason': ('Nome e contexto identificam um local com margem de pelo menos 7 pontos.' if clear else
                       'Há locais distintos sem margem suficiente; confirme o nome, rua ou bairro.' if candidates else
                       'Nenhum local compatível com nome, município e contexto no cadastro.'),
            'retrospective_water_overlap': candidates[0].get('in_water_'+observed) in ('1', True) if clear and observed else None,
            'in_water_by_date': None, 'publication_available': False}
