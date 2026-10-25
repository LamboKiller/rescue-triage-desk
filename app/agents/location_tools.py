"""Read-only location tools over source rows. Coordinates always come from data.

Each instance is scoped to one message; result IDs cannot cross cases. Street
geometry is a centroid/bbox, never a house or a verified street intersection.
"""
import hashlib
import json
import math
import re
from difflib import SequenceMatcher
from app.derive_count import _plain
from app.geo.incident import IncidentIndex, incident_text, key
from app.geo.landmarks import CATEGORIES, distance, distinct_places, normalize as place_normalize
from app.geo.streets import normalize

CATEGORY = {**CATEGORIES, 'church': {'amenity:place_of_worship'}, 'school': {'amenity:school'},
            'market': {'shop:supermarket', 'amenity:marketplace'}, 'hospital': {'amenity:hospital'}}
GENERIC = {'igreja', 'escola', 'colegio', 'mercado', 'supermercado', 'hospital', 'bairro', 'rua', 'avenida'}


def identity(kind, city, name):
    return kind+':'+hashlib.sha256((normalize(city)+'|'+normalize(name)).encode()).hexdigest()[:16]


def similarity(query, name, normalizer=normalize):
    q, n = normalizer(query), normalizer(name)
    if not q or not n:
        return 0
    if q == n:
        return 1.0
    if set(q.split()) <= set(n.split()) and set(q.split()) - GENERIC:
        return .92
    return SequenceMatcher(None, q, n, autojunk=False).ratio()


def supported_name(name, quote):
    """Allow spelling recovery, but never use an unrelated quote as authority."""
    words = quote.split()
    return any(similarity(name, ' '.join(words[i:i+n])) >= .8
               for n in range(1, min(len(words), len(name.split())+3)+1)
               for i in range(len(words)-n+1))


class LocationTools:
    def __init__(self, streets, landmarks, text, replay, points=(), index=None):
        self.streets, self.landmarks = streets, landmarks
        self.text, self.replay = text, replay
        self.scoped = incident_text(text)
        self.index = index or IncidentIndex(streets, landmarks)
        self.points = {(normalize(r['display_name']), normalize(r['municipality'])): r for r in points}
        self.candidates, self.results = {}, {}
        self._landmark_rows = None
        self.aliases = {}
        for row in landmarks:
            self.aliases[row['osm_type'], str(row['osm_id'])] = [a['alias'] for a in row.get('curated_aliases', [])]

    def check_text(self, quote):
        exists = isinstance(quote, str) and bool(quote.strip()) and quote in self.text
        return {'exists': exists, 'incident': bool(exists and _plain(quote) in self.scoped)}

    def _water(self, row, prefix):
        days = [d for d in ('2024-05-06', '2024-05-08') if d <= self.replay[:10]]
        day = days[-1] if days else None
        raw = row.get(prefix+day) if day else None
        overlap = True if raw in ('1', 'true', True) else False if raw in ('0', 'false', False) else None
        return dict(observed_date=day, retrospective_water_overlap=overlap, in_water_by_date=None,
                    retrospective=True, confidence='low', publication_available=False,
                    warning='Retrospective source; unknown is not dry/safe. House number is not geocoded.')

    def _remember(self, candidate):
        self.candidates[candidate['candidate_id']] = candidate
        return candidate

    def _street(self, row, score):
        p = self.points.get((normalize(row['display_name']), normalize(row['municipality'])), {})
        c = dict(candidate_id=identity('street', row['municipality'], row['display_name']),
                 kind='street', name=row['display_name'], city=row['municipality'], municipality=row['municipality'],
                 precision='street', score=round(score, 4), segments=row.get('segments'),
                 geometry_kind='street_centroid', source='streets_flood', **self._water(row, 'any_in_water_'))
        if p:
            try:
                c.update(lat=float(p['lat']), lon=float(p['lon']), bounds=json.loads(p['bbox']))
            except (ValueError, KeyError, TypeError):
                pass
        return self._remember(c)

    def search_street(self, name, city=None):
        if not normalize(name):
            return []
        scored = [(similarity(name, r['display_name']), r) for r in self.streets
                  if not city or normalize(city) == normalize(r['municipality'])]
        scored = [(s, r) for s, r in scored if s >= .82]
        best = max((s for s, _ in scored), default=0)
        return [self._street(r, s) for s, r in sorted(scored, key=lambda x: (-x[0], x[1]['municipality'], x[1]['display_name']))
                if s >= best-.06][:12]

    def _place(self, row, score=1):
        area = row['category'] in ('place:suburb', 'place:neighbourhood')
        return self._remember(dict(candidate_id='osm:'+row['osm_type']+':'+str(row['osm_id']), kind='bairro' if area else 'landmark',
            name=row['name'], city=row['municipality'], municipality=row['municipality'], category=row['category'],
            precision='area' if area else 'approximate', geometry_kind='catalogue_centroid', source='landmarks', score=round(score, 4),
            lat=float(row['lat']), lon=float(row['lon']), osm_type=row['osm_type'], osm_id=row['osm_id'],
            neighbourhood=row.get('neighbourhood', ''), street=row.get('street', ''),
            osm_members=row.get('osm_members', []), **self._water(row, 'in_water_')))

    def _places(self):
        if self._landmark_rows is None:
            self._landmark_rows = distinct_places(self.landmarks)
        return self._landmark_rows

    def search_landmark(self, name, city=None, category=None):
        allowed = CATEGORY.get(_plain(category or ''), {category} if category else set())
        if not normalize(name) or set(normalize(name).split()) <= GENERIC:
            return []
        hits = []
        for row in self._places():
            if city and normalize(city) != normalize(row['municipality']) or allowed and row['category'] not in allowed:
                continue
            names = [row['name']] + re.split(r'[|;]', row.get('alt_names', ''))
            # Clustering preserves the primary member's aliases. Also include
            # aliases on other OSM representations of the same place.
            members = {(m['osm_type'], str(m['osm_id'])) for m in row.get('osm_members', [row])}
            names += [alias for member in members for alias in self.aliases.get(member, [])]
            score = max((similarity(name, n, place_normalize) for n in names), default=0)
            if score >= .82:
                hits.append((score, row))
        if not hits and allowed and _plain(category or '') not in CATEGORY:
            # Unknown category = model guess (e.g. 'bus_station' vs OSM tags): retry by name/city only. Known ones stay strict.
            return self.search_landmark(name, city, None)
        best = max((s for s, _ in hits), default=0)
        return [self._place(r, s) for s, r in sorted(hits, key=lambda x: (-x[0], x[1]['municipality'], x[1]['name']))
                if s >= best-.06][:12]

    def search_bairro(self, name):
        keys = [(k, cs) for k, cs in self.index.bairros.items() if similarity(name, ' '.join(k)) >= .88]
        hits = []
        for k, cities in keys:
            for city in sorted(cities):
                rows = [r for r in self.landmarks if r['municipality'] == city and (
                    key(r.get('neighbourhood', '')) == k or r['category'] in ('place:suburb', 'place:neighbourhood')
                    and k in [key(r['name'])]+[key(a) for a in re.split(r'[|;]', r.get('alt_names', ''))])]
                if not rows:
                    continue
                named = [r for r in rows if r['category'] in ('place:suburb', 'place:neighbourhood') and key(r['name']) == k]
                anchors = named or rows
                lat = sum(float(r['lat']) for r in anchors)/len(anchors)
                lon = sum(float(r['lon']) for r in anchors)/len(anchors)
                hits.append(self._remember(dict(candidate_id=identity('bairro', city, ' '.join(k)), kind='bairro',
                    name=named[0]['name'] if named else ' '.join(k), city=city, municipality=city, precision='area',
                    score=round(similarity(name, ' '.join(k)), 4), lat=lat, lon=lon,
                    bounds=None, geometry_kind='catalogue_centroid' if named else 'member_centroid',
                    source='incident_bairro_catalogue', **self._water({}, 'in_water_'))))
        return sorted(hits, key=lambda c: (-c['score'], c['city'], c['name']))[:12]

    def near(self, anchor_id, radius_m, category=None, other_anchor_id=None):
        if isinstance(radius_m, bool) or not isinstance(radius_m, (int, float)) or not math.isfinite(radius_m) or not 0 < radius_m <= 2000:
            raise ValueError('Radius must be between 0 and 2000 metres')
        anchor = self.candidates.get(anchor_id)
        if not anchor:
            raise ValueError('Unknown anchor')
        if category == 'intersection' or other_anchor_id:
            other = self.candidates.get(other_anchor_id)
            if not other or other['city'] != anchor['city'] or other['candidate_id'] == anchor_id:
                return []
            if anchor['kind'] != 'street' or other['kind'] != 'street':
                return []
            a, b = anchor.get('bounds'), other.get('bounds')
            if not a or not b:
                return []
            box = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
            if box[0] > box[2] or box[1] > box[3]:
                return []
            return [self._remember(dict(candidate_id=identity('corner', anchor['city'], '|'.join(sorted((anchor_id, other_anchor_id)))),
                name=anchor['name']+' / '+other['name'], city=anchor['city'], municipality=anchor['city'], kind='corner',
                precision='approximate', score=1, source='street_bbox_overlap', geometry_kind='bbox_overlap_proxy',
                bounds=box, lat=(box[1]+box[3])/2, lon=(box[0]+box[2])/2, anchors=[anchor_id, other_anchor_id],
                **self._water({}, 'in_water_')))]
        if 'lat' not in anchor:
            return []
        allowed = CATEGORY.get(_plain(category or ''), {category} if category else set())
        hits = []
        for row in self._places():
            if row['municipality'] != anchor['city'] or allowed and row['category'] not in allowed:
                continue
            metres = distance(anchor, row)
            if metres <= radius_m:
                candidate = self._place(row)
                if candidate['candidate_id'] != anchor_id:
                    hits.append({**candidate, 'distance_m': round(metres, 1), 'anchor_id': anchor_id,
                                 'distance_kind': 'straight_line_to_centroid'})
        return sorted(hits, key=lambda c: (c['distance_m'], c['candidate_id']))[:12]

    def execute(self, tool, args, why_quote):
        check = self.check_text(why_quote)
        if not check['incident']:
            raise ValueError('Quote is absent or belongs only to caller')
        if not isinstance(args, dict) or tool not in ('search_street', 'search_landmark', 'search_bairro', 'near', 'check_text'):
            raise ValueError('Unknown tool or arguments')
        if tool.startswith('search_') and (not isinstance(args.get('name'), str) or not supported_name(args['name'], why_quote)):
            raise ValueError('Search name unsupported by quote')
        if tool in ('search_street', 'search_landmark') and normalize(args['name']) in {
                normalize(c) for c in self.index.cities.values()}:
            designators = r'\b(?:rua|avenida|av|travessa|estrada|estacao|hospital|igreja|escola|colegio|mercado|rodoviaria)\b'
            if not re.search(designators, _plain(why_quote)):
                raise ValueError('A municipality name alone does not identify a street or landmark')
        if args.get('city'):
            streets = self.index.hits(self.scoped, self.index.streets, self.index.max_words)
            explicit = any(not any(a <= m.start() and b >= m.end() for a, b, _ in streets)
                           for m in re.finditer(r'\b'+re.escape(_plain(args['city']))+r'\b', self.scoped))
            bairros = self.index.hits(self.scoped, self.index.bairros)
            cities = set().union(*(cs for _, _, cs in bairros)) if bairros else set()
            if not explicit and not (len(cities) == 1 and normalize(args['city']) == normalize(next(iter(cities)))):
                raise ValueError('Search city unsupported by incident')
        if tool == 'near':
            returned = {c['candidate_id'] for r in self.results.values() for c in r['candidates']}
            if any(args.get(k) not in returned for k in ('anchor_id', 'other_anchor_id') if k in args):
                raise ValueError('Anchor was not returned in this conversation')
        try:
            output = getattr(self, tool)(**args)
        except TypeError:
            raise ValueError('Invalid tool arguments') from None
        if isinstance(output, list) and output:
            from app.geo.hydro import rank_candidates
            ranked = rank_candidates(output, self.scoped, self.replay[:10], args.get('city'))
            output = ranked['ranked']
            for candidate in output:
                self.candidates[candidate['candidate_id']] = candidate
        rid = 't'+str(len(self.results)+1)
        result = dict(result_id=rid, tool=tool, args=args, why_quote=why_quote,
                      candidates=output if isinstance(output, list) else [],
                      **({'check': output} if isinstance(output, dict) else {}))
        self.results[rid] = result
        return result
