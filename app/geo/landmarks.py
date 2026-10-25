"""Deterministic OSM name matching. Model guesses never become coordinates."""
import re
import unicodedata
import math
from app.geo.streets import normalize as street_normalize

STOP = {'a', 'o', 'as', 'os', 'de', 'da', 'do', 'das', 'dos', 'em', 'no', 'na', 'estacao', 'hospital',
        'igreja', 'capela', 'paroquia'}


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', str(text).casefold()) if unicodedata.category(c) != 'Mn')
    return ' '.join(w for w in re.findall(r'[a-z0-9]+', text) if w not in STOP)


CONTEXT_STOP = {'dentro', 'perto', 'proximo', 'lado', 'ao', 'estamos', 'estou', 'aqui', 'junto'}
CATEGORIES = {'hospital': {'amenity:hospital'}, 'escola': {'amenity:school'},
              'colegio': {'amenity:school'},
              'capela': {'amenity:place_of_worship'}, 'paroquia': {'amenity:place_of_worship'},
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
        tokens = [('escola' if t == 'colegio' else t) for t in normalize(q).split() if t not in CONTEXT_STOP]
        # Municipality is a scope, not a distinguishing landmark token.
        local = [t for t in tokens if t not in city]
        if local:
            queries.append(' '.join(local))
    context = normalize(' '.join((message, landmark_quote, place_name, neighbourhood)))
    raw_context = ' '.join(re.findall(r'[a-z0-9]+', unicodedata.normalize('NFD',
                                  ' '.join((message, landmark_quote, place_name))).encode('ascii', 'ignore').decode().lower()))
    words = set(raw_context.split())
    school = bool(words & {'escola', 'colegio'})
    station = 'trensurb' in words or 'estacao aeroporto' in raw_context
    brique = 'brique' in words
    hints = {category for word, categories in CATEGORIES.items() if word in raw_context.split() for category in categories}
    if 'banco sangue' in context or 'laboratorio' in context.split():
        hints = {'amenity:clinic'}
    if station:
        hints = {'public_transport:station'}
    if brique:
        hints = {'amenity:marketplace'}
    # Established short names provide category evidence, never invented coordinates.
    if not hints:
        if 'salgado filho' in context:
            hints = CATEGORIES['aeroporto']
        elif 'beira rio' in context or 'arena gremio' in context:
            hints = CATEGORIES['estadio']
        elif 'clinicas' in context.split():
            hints = CATEGORIES['hospital']
    alias_hits = {}
    for row in rows:
        for alias in row.get('curated_aliases', []):
            if municipality and normalize(alias['municipality']) != normalize(municipality):
                continue
            name = normalize(alias['alias'])
            if name == 'conceicao' and 'hospital conceicao' not in raw_context:
                continue
            if not name or (' '+name+' ') not in (' '+context+' '):
                continue
            if (row['category'] == 'aeroway:aerodrome' and (school or station)
                    or normalize(alias['alias']) in ('redencao', 'parque redencao') and brique
                    or row['category'] == 'amenity:hospital' and hints == {'amenity:clinic'}):
                continue
            alias_hits.setdefault((row['osm_type'], row['osm_id']), []).append(name)
    # A longer matching phrase suppresses shorter contained aliases, across targets.
    names = {name for hits in alias_hits.values() for name in hits}
    alias_hits = {key: max((name for name in hits if not any(
        name != other and (' '+name+' ') in (' '+other+' ') for other in names)),
        key=lambda name: (len(name.split()), len(name)), default='') for key, hits in alias_hits.items()}
    scoped = [r for r in rows if (municipality and normalize(r['municipality']) == normalize(municipality))
              or (not municipality and (r['osm_type'], r['osm_id']) in alias_hits)]
    # Island context must constrain the incident, even if a mainland facility
    # has the same dedication. Derive island names and anchors from OSM names.
    island_anchors = []
    for row in scoped:
        name = normalize(row['name']).split()
        if 'ilha' in name:
            locality = name[name.index('ilha'):]
            if len(locality) >= 2 and (' '+' '.join(locality)+' ') in (' '+context+' '):
                island_anchors.append(row)
    suburbs = {normalize(r['name']) for r in scoped if r['category'] in ('place:suburb', 'place:neighbourhood')
               and (' '+normalize(r['name'])+' ') in (' '+context+' ')}
    if neighbourhood:
        suburbs.add(normalize(neighbourhood))
    street_cues = {street_normalize(r['display_name']) for r in streets
                   if normalize(r['municipality']) == normalize(municipality)
                   and street_normalize(r['display_name'])
                   and (' '+street_normalize(r['display_name'])+' ') in (' '+street_normalize(context)+' ')}
    street_cues.update(street_normalize(r.get('street', '')) for r in scoped
                       if street_normalize(r.get('street', '')) and
                       (' '+street_normalize(r['street'])+' ') in (' '+street_normalize(context)+' '))
    street_cues = {s for s in street_cues if len(s.split()) >= 2 and
                   not any(set(s.split()) == set(q.split()) for q in queries) and
                   not set(s.split()) <= city and
                   # A neighbourhood can share its name with a street. Only
                   # an explicit road designator makes it a street constraint.
                   (s not in suburbs or re.search(
                       r'\b(?:rua|r|avenida|av|travessa|tv|estrada|rodovia|alameda) '+re.escape(s)+r'\b', context))}
    candidates = []
    message_normalized = normalize(message)
    for row in distinct_places(scoped):
        if island_anchors and not any(distance(row, anchor) <= 2000 for anchor in island_anchors):
            continue
        alias = next((alias_hits.get((m['osm_type'], m['osm_id']), '') for m in row['osm_members']
                      if alias_hits.get((m['osm_type'], m['osm_id']))), '')
        if hints and row['category'] not in hints and not alias:
            continue
        score = 120 if alias else 0
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
                               'reason': 'alias:'+alias if alias else 'name',
                               'street_preferred': street_match, 'neighbourhood_preferred': preference})
    if street_cues:
        candidates = [c for c in candidates if c['street_preferred']]
    # Airport dispatch uses the aerodrome; retain the specifically named terminal.
    airports = [r for r in rows if r['category'] == 'aeroway:aerodrome']
    collapsed = {}
    for candidate in candidates:
        if candidate['category'] == 'aeroway:terminal':
            nearby = sorted((a for a in airports if distance(a, candidate) <= 3000),
                            key=lambda a: (distance(a, candidate), a['osm_type'], a['osm_id']))
            if nearby:
                terminal = candidate
                candidate = {**candidate, **nearby[0]}
                candidate.pop('sub_place', None)
                # Keep the terminal as a detail only when the message actually mentions one.
                if 'terminal' in words:
                    candidate['sub_place'] = {
                        'name': terminal['name'], 'osm_type': terminal['osm_type'], 'osm_id': terminal['osm_id'],
                        'osm_url': 'https://www.openstreetmap.org/'+terminal['osm_type']+'/'+terminal['osm_id']}
                candidate['osm_members'] = [{'osm_type': candidate['osm_type'], 'osm_id': candidate['osm_id']}]
        key = (candidate['osm_type'], candidate['osm_id'])
        old = collapsed.get(key)
        if old is None or candidate['score'] > old['score']:
            if old and old.get('sub_place'):
                candidate.setdefault('sub_place', old['sub_place'])
            collapsed[key] = candidate
        elif candidate.get('sub_place'):
            old.setdefault('sub_place', candidate['sub_place'])
    candidates = list(collapsed.values())
    if 'terminal' in words:
        for candidate in candidates:
            if candidate['category'] == 'aeroway:aerodrome' and not candidate.get('sub_place'):
                terminals = [r for r in rows if r['category'] == 'aeroway:terminal' and distance(r, candidate) <= 3000
                             and normalize(r['name']) == 'terminal 1']
                if terminals and not (words & {'2', 'antigo'}):
                    terminal = terminals[0]
                    candidate['sub_place'] = {'name': terminal['name'], 'osm_type': terminal['osm_type'],
                                              'osm_id': terminal['osm_id'], 'osm_url':
                                              'https://www.openstreetmap.org/'+terminal['osm_type']+'/'+terminal['osm_id']}
    candidates.sort(key=lambda r: (-r['score'], -r['neighbourhood_preferred'], r['name'], r['osm_id']))
    generic = bool(queries) and all(set(q.split()) <= GENERIC for q in queries) and not street_cues and not suburbs and not any(alias_hits.values()) and not station
    bare_ambiguous = bool(queries) and all(q in ('pronto socorro', 'conceicao') for q in queries) and not street_cues and not suburbs and not any(alias_hits.values())
    clear = bool(candidates) and not generic and not bare_ambiguous and candidates[0]['score'] >= 82 and (
        len(candidates) == 1 or candidates[0]['score']-candidates[1]['score'] >= MARGIN)
    dates = [d for d in ('2024-05-06', '2024-05-08') if d <= replay[:10]]
    observed = dates[-1] if dates else None
    return {'status': 'resolved' if clear else ('ambiguous' if candidates else 'unresolved'),
            'matched': candidates[0] if clear else None, 'candidates': candidates[:3], 'observed_date': observed,
            'sub_place': candidates[0].get('sub_place') if clear else None,
            'reason': (candidates[0]['reason'] if clear and candidates[0]['reason'].startswith('alias:') else
                       'Nome e contexto identificam um local com margem de pelo menos 7 pontos.' if clear else
                       'Há locais distintos sem margem suficiente; confirme o nome, rua ou bairro.' if candidates else
                       'Nenhum local compatível com nome, município e contexto no cadastro.'),
            'retrospective_water_overlap': candidates[0].get('in_water_'+observed) in ('1', True) if clear and observed else None,
            'in_water_by_date': None, 'publication_available': False}
