"""Hydro-aware geocoding helpers (deterministic, no model calls).

Street signs and landmarks go under water, so people describe what is still visible or how far the water is.
Everything here uses the dated flood layers (no-hindsight: a layer counts for replay day D when its observation
date <= D). All layers are RETROSPECTIVE (EMSN194 HAND, created after the event): results carry that label and a
low-confidence note. A missing value is "unknown", never "dry"; "dry" needs positive evidence (inside the layer
coverage with an explicit zero-depth observation, outside the observed extent).
"""
import csv
import json
import math
import re
import unicodedata
from functools import lru_cache
from app.config import ROOT
from app.geo import depth as depthmod
from app.geo.hazards import replay_day, get_data
from app.geo.streets import normalize as street_norm

AREA_LABEL = 'ponto aproximado: parte alagada do bairro'
RETRO_NOTE = 'retrospectivo (EMSN194/HAND, criado após o evento); confiança baixa; sem dado não significa seco'
BAIRRO_RADIUS_M = 2500.0     # no bairro polygons in the data: a bairro = cells nearest to its OSM place node, <= this radius
PERIMETER_M = 60.0           # depth.lookup search radius

LIFE_SAFETY = re.compile(
    r'\b(telhado|forro|sotao|laje|cobertura|(?:segundo|2o|2º|terceiro|3o|3º)\s+andar|andar\s+de\s+cima|em\s+cima\s+d[oae]|'
    r'agua\s+(?:subindo|chegando|ate\s+(?:o|a)\s+\w+|n[oa]\s+(?:pescoco|peito|cintura|joelho)|pelo\s+(?:pescoco|peito|joelho)|cobrindo)|'
    r'nivel\s+da\s+agua|agua\s+(?:subiu|ta\s+subindo|esta\s+subindo|so\s+sobe|nao\s+para\s+de\s+subir))\b')


def fold1(text):
    """Accent-stripped lowercase, 1:1 character mapping so spans map back to the original text."""
    out = []
    for ch in str(text):
        d = unicodedata.normalize('NFD', ch)
        out.append((d[0] if d else ch).lower() if len(d) else ch)
    return ''.join(out)


def key(text):
    t = re.sub(r'[^a-z0-9]+', ' ', fold1(text))
    return ' '.join(w for w in t.split() if w not in ('do', 'da', 'dos', 'das', 'de'))


def life_safety_quote(text):
    """Exact message quote of a life-safety cue (roof/ceiling/upper floor/water rising) or None."""
    text = text or ''
    m = LIFE_SAFETY.search(fold1(text))
    return text[m.start():m.end()] if m else None


def observed_date(day):
    replay_day(day)
    return max((d for d in depthmod.DATES if d <= day), default=None)


def _metres(lat1, lon1, lat2, lon2):
    k = 111320.0
    return math.hypot((lat2 - lat1) * 110574.0, (lon2 - lon1) * k * math.cos(math.radians((lat1 + lat2) / 2)))


@lru_cache(maxsize=4)
def _extent(date):
    h = depthmod.grid(date).h
    pts = [depthmod.utm22s_to_lonlat(h['origin_x'] + dx * h['width'] * h['pixel_m'], h['origin_y'] - dy * h['height'] * h['pixel_m'])
           for dx in (0, 1) for dy in (0, 1)]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def classify_point(lat, lon, day):
    """wet | dry | unknown for a point on replay day `day`, with depth band + source."""
    dates = [d for d in depthmod.DATES if d <= replay_day(day)]
    base = {'state': 'unknown', 'depth_m': None, 'depth_band': 'unknown', 'observed_date': max(dates, default=None),
            'source': depthmod.ATTRIBUTION, 'retrospective': True, 'confidence': depthmod.CONFIDENCE}
    if lat is None or lon is None or not dates:
        base['reason_pt'] = 'sem camada de alagamento observada até esta data; desconhecido, não seco'
        return base
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        base['reason_pt'] = 'coordenadas inválidas; desconhecido, não seco'
        return base
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        base['reason_pt'] = 'coordenadas inválidas; desconhecido, não seco'
        return base
    latest = max(dates)
    looked = depthmod.lookup(lon, lat, day)
    depth = looked['depth_by_date'].get(latest, {}).get('depth_m')
    index = get_data().indices
    in_water = latest in index and index[latest].contains(lat, lon)
    # Use only the latest eligible observation, never the union of past floods.
    if (depth is not None and depth > 0) or in_water:
        band = depthmod.band(depth) if depth is not None else 'unknown'
        txt = ('profundidade estimada %.1f m (%s)' % (depth, band)) if depth is not None else 'extensão observada, sem profundidade'
        base.update(state='wet', depth_m=depth, depth_band=band,
                    reason_pt='área alagada observada em %s: %s; %s' % (latest, txt, RETRO_NOTE))
    elif depth == 0:
        # Grid envelope and absence from flood polygons do NOT prove dryness.
        base.update(state='dry', depth_m=0, depth_band=depthmod.band(0),
                    reason_pt='profundidade zero observada em %s; %s' % (latest, RETRO_NOTE))
    else:
        base['reason_pt'] = 'sem medida de profundidade neste ponto em %s; desconhecido, não seco' % latest
    return base


# ---------------------------------------------------------------- 1. ranking
def rank_candidates(candidates, text, day, municipality=None):
    """Annotate candidates with hydro state; for life-safety messages put wet candidates before unknown before dry.

    Stable otherwise (the original textual ranking is kept inside each group). A candidate from a different
    municipality than the stated one is never promoted above matching ones.
    """
    quote = life_safety_quote(text)
    want = key(municipality) if municipality else None
    annotated = []
    for i, c in enumerate(candidates):
        h = classify_point(c.get('lat'), c.get('lon'), day) if c.get('lat') not in (None, '') else classify_point(None, None, day)
        annotated.append({**c, 'hydro': h, '_i': i})
    rank = {'wet': 0, 'unknown': 1, 'dry': 2}

    def sort_key(c):
        wrong = bool(want and key(c.get('municipality') or c.get('city') or '') != want)
        return (wrong, rank[c['hydro']['state']] if quote else 0, c['_i'])
    ordered = sorted(annotated, key=sort_key)
    for c in ordered:
        c['hydro_original_index'] = c.pop('_i')
    return {'life_safety': bool(quote), 'life_safety_quote': quote,
            'reordered': [c['hydro_original_index'] for c in ordered] != list(range(len(candidates))), 'ranked': ordered,
            'note': RETRO_NOTE}


# ---------------------------------------------------------------- 2. flooded part of a bairro
@lru_cache(maxsize=1)
def _places():
    rows = []
    with (ROOT / 'data/landmarks.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['category'] in ('place:suburb', 'place:neighbourhood') and r['lat'] and r['lon'] and r['name']:
                rows.append({'name': r['name'], 'key': key(r['name']), 'mun': key(r['municipality']), 'municipality': r['municipality'],
                             'lat': float(r['lat']), 'lon': float(r['lon']), 'osm_id': r['osm_id']})
    return rows


def find_bairro(name, municipality):
    k, m = key(name or ''), key(municipality or '')
    return [p for p in _places() if p['key'] == k and p['mun'] == m] if k and m else []


def area_point(bairro, municipality, day):
    """Approximate point for an area-only message: centroid of the FLOODED part of the bairro on `day`.

    Bairro extent has no polygon in the data: the bairro = depth cells whose nearest OSM place node (same city)
    is one of the bairro's nodes, within BAIRRO_RADIUS_M. Falls back to the plain centroid, labelled.
    """
    nodes = find_bairro(bairro, municipality)
    obs = observed_date(day)
    out = {'found': bool(nodes), 'bairro': bairro, 'municipality': municipality, 'precision': 'AREA', 'observed_date': obs,
           'retrospective': True, 'confidence': depthmod.CONFIDENCE, 'source': depthmod.ATTRIBUTION, 'boundary_estimated': True,
           'boundary_source': 'OSM place-node nearest-neighbour proxy, not an official bairro polygon'}
    if not nodes:
        out.update(label='bairro não encontrado no catálogo desta cidade; sem ponto', point=None)
        return out
    others = [p for p in _places() if p['mun'] == nodes[0]['mun']]
    mine = {id(n) for n in nodes}
    cx = sum(n['lat'] for n in nodes) / len(nodes)
    cy = sum(n['lon'] for n in nodes) / len(nodes)
    out['bairro_centroid'] = {'lat': round(cx, 6), 'lon': round(cy, 6)}

    def member(lat, lon):
        best = min(others, key=lambda p: _metres(lat, lon, p['lat'], p['lon']))
        return id(best) in mine and _metres(lat, lon, best['lat'], best['lon']) <= BAIRRO_RADIUS_M

    cells = []
    if obs:
        span = 0.03
        for lon, lat, bnd, d in depthmod.aggregated(obs):
            if (d > 0 and abs(lat - cx) <= span and abs(lon - cy) <= span and member(lat, lon)
                    and classify_point(lat, lon, day)['state'] == 'wet'):
                cells.append((lat, lon, d))
    if not cells:
        why = ('sem camada observada até %s' % day) if not obs else 'nenhuma célula alagada do bairro na camada de %s (não significa seco)' % obs
        out.update(point={'lat': round(cx, 6), 'lon': round(cy, 6)}, flooded=False, n_cells=0,
                   label='ponto aproximado: centro do bairro (%s)' % why)
        return out
    lat = sum(c[0] for c in cells) / len(cells)
    lon = sum(c[1] for c in cells) / len(cells)
    medoid = False
    if not member(lat, lon) or classify_point(lat, lon, day)['state'] != 'wet':   # concave region: snap to the member cell nearest to the mean
        lat, lon, _ = min(cells, key=lambda c: _metres(lat, lon, c[0], c[1]))
        medoid = True
    half_lat, half_lon = 50 / 110574.0, 50 / (111320.0 * math.cos(math.radians(lat)))
    out.update(point={'lat': round(lat, 6), 'lon': round(lon, 6)}, flooded=True, n_cells=len(cells), snapped_to_cell=medoid,
               bbox=[round(min(c[1] for c in cells) - half_lon, 6), round(min(c[0] for c in cells) - half_lat, 6),
                     round(max(c[1] for c in cells) + half_lon, 6), round(max(c[0] for c in cells) + half_lat, 6)],
               max_depth_m=max(c[2] for c in cells), max_depth_band=depthmod.band(max(c[2] for c in cells)),
               extent_rule='células mais próximas deste bairro (nó OSM), raio %d m; sem polígono de bairro' % BAIRRO_RADIUS_M,
               label=AREA_LABEL)
    return out


# ---------------------------------------------------------------- 3. relative descriptors
@lru_cache(maxsize=1)
def _streets():
    rows, by_key = [], {}
    with (ROOT / 'data/hazards/street_points.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            r['bbox_v'] = json.loads(r['bbox'])
            r['lat_v'], r['lon_v'] = float(r['lat']), float(r['lon'])
            rows.append(r)
            by_key.setdefault((street_norm(r['display_name']), key(r['municipality'])), r)
    return rows, by_key


@lru_cache(maxsize=1)
def _poi():
    with (ROOT / 'data/landmarks.csv').open(encoding='utf-8-sig', newline='') as f:
        return [r for r in csv.DictReader(f) if r['lat'] and r['lon']]


def _street_in(fragment, municipality):
    """Longest word-prefix of `fragment` that is a catalogue street of `municipality`."""
    words = re.findall(r"[^\W_][\w'’-]*", fragment)
    _, by_key = _streets()
    m = key(municipality)
    for n in range(min(6, len(words)), 0, -1):
        row = by_key.get((street_norm(' '.join(words[:n])), m))
        if row and (n > 1 or len(words[0]) >= 4):
            return row
    return None


def _hydro(lat, lon, day):
    h = classify_point(lat, lon, day)
    return {k: h[k] for k in ('state', 'depth_m', 'depth_band', 'observed_date', 'source', 'retrospective', 'reason_pt')}


def _point_cand(cid, name, lat, lon, precision, evidence, day, **extra):
    return {'id': cid, 'name': name, 'lat': round(lat, 6), 'lon': round(lon, 6), 'precision': precision,
            'evidence': evidence, 'hydro': _hydro(lat, lon, day), **extra}


def _descriptor_name(raw):
    """Stop a relative reference at ordinary rescue prose, retaining name tokens."""
    words = []
    for word in (raw or '').split():
        if fold1(word) in {'estamos', 'estou', 'to', 'ta', 'tem', 'preciso', 'precisamos',
                           'com', 'sem', 'e', 'em', 'no', 'na', 'aqui', 'agua', 'socorro',
                           'meu', 'minha', 'meus', 'minhas', 'nosso', 'nossa', 'pessoal',
                           'alguem', 'ajuda', 'mandem', 'manda', 'urgente', 'por', 'pfv', 'pfvr'}:
            break
        words.append(word)
    return ' '.join(words)


def _intersection(a, b):
    (w1, s1, e1, n1), (w2, s2, e2, n2) = a['bbox_v'], b['bbox_v']
    w, s, e, n = max(w1, w2), max(s1, s2), min(e1, e2), min(n1, n2)
    if w <= e and s <= n:
        return (s + n) / 2, (w + e) / 2, _metres(s, w, n, e) / 2, 'bboxes das duas ruas se sobrepõem'
    cs, cw = min(max((s1 + n1) / 2, s2), n2), min(max((w1 + e1) / 2, w2), e2)       # nearest points of the two boxes
    ns, nw = min(max(cs, s1), n1), min(max(cw, w1), e1)
    gap = _metres(ns, nw, cs, cw)
    if gap <= 150:
        return (ns + cs) / 2, (nw + cw) / 2, gap / 2 + 50, 'bboxes a %d m uma da outra' % round(gap)
    return None


CORNER = re.compile(r"(?:esquina|cruzamento|encruzilhada)\s+(?:entre\s+|d[aeo]s?\s+)?(?P<a>[^,.;:\n]{2,45}?)\s+(?:com|e|x|c/)\s+(?:a\s+|o\s+)?(?P<b>[^,.;:\n]{2,45})", re.I)
BRIDGE = re.compile(r"(?:depois|antes|perto|proximo|logo\s+apos|ao\s+lado|embaixo|debaixo|sob|apos|passando)\s+(?:d[aeo]s?\s+|a\s+)?(?P<kind>ponte|viaduto|passarela)(?P<name>(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ú][\wÀ-ú'-]*){0,3})?", re.I)
LOWLAND = re.compile(r"\b(?:na|numa|pra|para a)\s+(baixada|baixadao|parte\s+baixa|parte\s+mais\s+baixa)\b", re.I)
TALL = re.compile(r"(?:perto|proximo|ao\s+lado|em\s+frente|atras|na\s+frente|pertinho|junto)\s+(?:d[aeo]s?\s+|a\s+|da\s+|do\s+)?(?P<kind>caixa\s+d['’` ]?\s*agua|torre|igreja|capela|matriz|paroquia|campanario|silo)(?P<name>(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ú][\wÀ-ú'-]*){0,3})?", re.I)


def resolve_descriptors(text, municipality, day, bairro=None):
    """Relative descriptors -> candidates (precision LANDMARK/AREA) with evidence. Needs the city; never guesses one."""
    text = text or ''
    out = []
    if not municipality:
        return [{'kind': 'none', 'candidates': [], 'note': 'cidade ausente: descritores relativos não são resolvidos sem cidade'}]
    mk = key(municipality)
    folded = fold1(text)
    rows, _ = _streets()
    for m in CORNER.finditer(text):
        a, b = _street_in(m.group('a'), municipality), _street_in(m.group('b'), municipality)
        item = {'kind': 'corner', 'quote': m.group(0), 'candidates': []}
        if not (a and b and a is not b):
            item['note'] = 'uma das ruas não está no catálogo de %s' % municipality
        else:
            cross = _intersection(a, b)
            if not cross:
                item['note'] = 'as duas ruas existem mas não se tocam nos dados; sem ponto'
            else:
                lat, lon, unc, how = cross
                item['candidates'].append(_point_cand(
                    'corner:%s|%s' % (a['normalized_name'], b['normalized_name']), '%s × %s' % (a['display_name'], b['display_name']),
                    lat, lon, 'LANDMARK', {'streets': [a['display_name'], b['display_name']], 'rule': how, 'uncertainty_m': round(unc),
                                           'source': 'data/hazards/street_points.csv (bbox, esquina aproximada)'}, day, municipality=municipality))
        out.append(item)
    for m in BRIDGE.finditer(folded):
        kind = fold1(m.group('kind'))
        name = _descriptor_name(m.group('name'))
        cands = [r for r in rows if key(r['municipality']) == mk and fold1(r['display_name']).startswith(kind)]
        if name:
            toks = set(key(name).split())
            narrowed = [r for r in cands if toks <= set(key(r['display_name']).split())]
            cands = narrowed
        node = (find_bairro(bairro, municipality) or [None])[0]
        if node:
            cands.sort(key=lambda r: _metres(node['lat'], node['lon'], r['lat_v'], r['lon_v']))
        item = {'kind': kind, 'quote': text[m.start():m.end()], 'ambiguous': len(cands) > 1, 'candidates': []}
        for r in cands[:5]:
            item['candidates'].append(_point_cand(
                'street:%s|%s' % (r['normalized_name'], r['normalized_municipality']), r['display_name'], r['lat_v'], r['lon_v'],
                'LANDMARK' if len(cands) == 1 else 'AREA',
                {'street': r['display_name'], 'rule': 'estrutura nomeada no catálogo de vias; "depois de" é só referência',
                 'source': 'data/hazards/street_points.csv'}, day, municipality=municipality))
        if not cands:
            item['note'] = '%s não encontrada no catálogo de %s' % (kind, municipality)
        out.append(item)
    for m in LOWLAND.finditer(folded):
        item = {'kind': 'baixada', 'quote': text[m.start():m.end()], 'candidates': []}
        if not bairro:
            item['note'] = 'baixada sem bairro: sem ponto (a cidade inteira não é um ponto)'
        else:
            ap = area_point(bairro, municipality, day)
            if ap.get('point'):
                item['candidates'].append(_point_cand('baixada:' + key(bairro), bairro, ap['point']['lat'], ap['point']['lon'], 'AREA',
                                                      {'rule': ap['label'], 'n_cells': ap.get('n_cells'), 'source': ap['source']}, day, municipality=municipality))
            else:
                item['note'] = ap['label']
        out.append(item)
    for m in TALL.finditer(folded):
        kind = fold1(m.group('kind'))
        name = _descriptor_name(m.group('name'))
        item = {'kind': 'tall:' + kind, 'quote': text[m.start():m.end()], 'candidates': []}
        if kind in ('igreja', 'capela', 'matriz', 'paroquia', 'campanario'):
            test = lambda r: r['category'] == 'amenity:place_of_worship'
        elif kind.startswith('caixa'):
            test = lambda r: r['category'] == 'man_made:water_tower' or 'caixa' in fold1(r['name'])
        elif kind == 'silo':
            test = lambda r: r['category'] == 'man_made:silo' or 'silo' in fold1(r['name'])
        else:
            test = lambda r: r['category'] in ('man_made:water_tower', 'man_made:tower', 'man_made:communications_tower') or 'torre' in fold1(r['name'])
        cands = [r for r in _poi() if key(r['municipality']) == mk and test(r)]
        if name:
            toks = set(key(name).split())
            cands = [r for r in cands if toks <= set(key(r['name']).split())] or ([] if toks else cands)
        node = (find_bairro(bairro, municipality) or [None])[0]
        if node:
            near = [r for r in cands if key(r['neighbourhood']) == key(bairro) or _metres(node['lat'], node['lon'], float(r['lat']), float(r['lon'])) <= BAIRRO_RADIUS_M]
            cands = sorted(near, key=lambda r: _metres(node['lat'], node['lon'], float(r['lat']), float(r['lon'])))
        item['ambiguous'] = len(cands) > 1
        for r in cands[:5]:
            item['candidates'].append(_point_cand(
                'osm:%s:%s' % (r['osm_type'], r['osm_id']), r['name'] or r['category'], float(r['lat']), float(r['lon']),
                'LANDMARK' if len(cands) == 1 else 'AREA',
                {'osm': '%s/%s' % (r['osm_type'], r['osm_id']), 'category': r['category'], 'source': 'data/landmarks.csv'}, day, municipality=municipality))
        if not cands:
            item['note'] = 'nenhum %s no catálogo OSM carregado para %s' % (kind, municipality)
        out.append(item)
    return out


# ---------------------------------------------------------------- 4. contradiction for the credibility filter
@lru_cache(maxsize=1)
def _street_water():
    with (ROOT / 'data/streets_flood.csv').open(encoding='utf-8-sig', newline='') as f:
        return {(street_norm(r['display_name']), key(r['municipality'])): r for r in csv.DictReader(f)}


def hydro_conflict(text, lat, lon, day, *, street=None, municipality=None, precision='street'):
    """Life-safety claim at a point that is confidently DRY on `day` -> conflict item, else None.

    Only street/exact/landmark points count (a bairro centroid says nothing about dryness). A street with any
    segment in the water on an observed date is never "dry". The item is retrospective: it can only make a message
    "doubtful", never "likely fake" by itself.
    """
    quote = life_safety_quote(text)
    if not quote or lat is None or lon is None or str(precision).lower() in ('area', 'bairro', 'city'):
        return None
    c = classify_point(lat, lon, day)
    if c['state'] != 'dry':
        return None
    if street and municipality:
        row = _street_water().get((street_norm(street), key(municipality)))
        if row and any(row.get('any_in_water_' + d) in ('1', 'true', 'True') for d in depthmod.DATES if d <= day):
            return None
    return {'id': 'hydro_conflict', 'kind': 'life_safety_at_dry_point', 'quote': quote, 'observed_date': c['observed_date'],
            'impact': 'doubtful_only', 'retrospective': True, 'confidence': depthmod.CONFIDENCE,
            'point': {'lat': float(lat), 'lon': float(lon)}, 'hydro': c,
            'message_pt': 'Relato de risco de vida em ponto fora da área alagada observada em %s; camada retrospectiva — '
                          'pode ser cobertura, não recessão. Apenas "duvidoso".' % c['observed_date'],
            'source': depthmod.ATTRIBUTION}
