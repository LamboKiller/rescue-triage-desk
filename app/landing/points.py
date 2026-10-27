"""Landing points = dry places where a boat can unload. Sources, in order: data/roads launch points (F2-DATA) when present;
otherwise a derived list from OSM landmarks (public places with open ground) and shelter sites. Every row carries its source kind;
capacity_per_hour is always an ESTIMATE by place type unless the roads file gives a figure. Dryness is checked at plan time, never assumed."""
import csv
import json
from functools import lru_cache
from app.config import ROOT

ROADS_DIR = ROOT / 'data' / 'roads'
LANDMARKS = ROOT / 'data' / 'landmarks.csv'
# People per hour a crew can realistically unload at a place of that type: author estimate, not measured.
EST_PER_HOUR = {'amenity:school': 40, 'amenity:community_centre': 40, 'leisure:stadium': 80, 'amenity:fire_station': 30, 'amenity:bus_station': 60,
                'amenity:marketplace': 40, 'amenity:police': 30, 'amenity:hospital': 40, 'amenity:townhall': 30, 'amenity:university': 60,
                'aeroway:aerodrome': 80, 'shop:mall': 60, 'shelter_site': 30, 'launch_point': 30}
CAPACITY_LABEL = 'capacidade por hora = estimativa por tipo de local (não medida); trocar por dado da equipe quando houver'
SOURCE_LABELS = {'roads_launch_points': 'Ponto de lançamento (data/roads)', 'osm_landmark': 'Referência OSM derivada (retrospectiva, não é rampa verificada)',
                 'shelter_site': 'Local de abrigo (lista pré-existente)'}


def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def _graph_launch_points(date):
    """Launch points from the F2-DATA graph (app/geo/roads.py). The DRY-side node is where trucks park / boats unload, so it is the landing
    location; synthetic derived ids carry no node, so the point itself is used. Parking stays 'unverified' and the layer decides dryness."""
    try:
        from app.geo import roads
        net = roads.load()
        return _network_points(net, date)
    except Exception: return []


@lru_cache(maxsize=4)
def _network_points(net, date):
    # RoadNetwork is an immutable loaded snapshot; replacement networks get a
    # distinct key. load_points returns detached dictionaries below.
    pts = net.launch_points(date)
    out = []
    for i, r in enumerate(pts):
        node = net.nodes.get(str(r.get('dry_side_node_id') or ''))
        lat, lon = (node['lat'], node['lon']) if node else (r.get('lat'), r.get('lon'))
        lat, lon = _num(lat), _num(lon)
        if lat is None or lon is None: continue
        name = r.get('nearest_street_name')
        out.append({'landing_id': 'RG%s-%d' % (date, i), 'label': 'Ponto de lançamento%s' % (' · ' + name if name and name != '(sem nome)' else ' (%s)' % (r.get('municipality') or 'sem rua')),
                    'lat': lat, 'lon': lon, 'source_kind': 'roads_launch_points', 'municipality': r.get('municipality') or '', 'water_edge': True,
                    'capacity_per_hour': EST_PER_HOUR['launch_point'], 'capacity_basis': 'estimate'})
    return out


def _roads():
    out = []
    if not ROADS_DIR.is_dir(): return out
    for p in sorted(ROADS_DIR.glob('launch_points*')):
        try:
            if p.suffix == '.csv':
                with p.open(encoding='utf-8-sig', newline='') as f: rows = list(csv.DictReader(f))
            elif p.suffix in ('.json', '.geojson'):
                d = json.loads(p.read_text(encoding='utf-8-sig'))
                rows = [{**(x.get('properties') or {}), 'lon': x['geometry']['coordinates'][0], 'lat': x['geometry']['coordinates'][1]} if 'geometry' in x else x
                        for x in (d.get('features') if isinstance(d, dict) else d) or []]
            else: continue
        except (OSError, ValueError, KeyError, TypeError, IndexError): continue
        for i, r in enumerate(rows):
            lat, lon = _num(r.get('lat')), _num(r.get('lon'))
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180): continue
            cap = _num(r.get('capacity_per_hour'))
            out.append({'landing_id': 'R%s' % (r.get('id') or '%s%d' % (p.stem, i)), 'label': r.get('name') or 'Ponto de lançamento %s' % (r.get('id') or i),
                        'lat': lat, 'lon': lon, 'source_kind': 'roads_launch_points', 'municipality': r.get('municipality') or '',
                        'capacity_per_hour': int(cap) if cap and cap > 0 else EST_PER_HOUR['launch_point'], 'capacity_basis': 'roads_file' if cap and cap > 0 else 'estimate'})
    return out


@lru_cache(maxsize=1)
def _derived():
    out = []
    if not LANDMARKS.is_file(): return out
    with LANDMARKS.open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            cat = r.get('category')
            lat, lon = _num(r.get('lat')), _num(r.get('lon'))
            if cat not in EST_PER_HOUR or lat is None or lon is None or not r.get('name'): continue
            out.append({'landing_id': 'L%s' % r['osm_id'], 'label': r['name'], 'lat': lat, 'lon': lon, 'source_kind': 'osm_landmark', 'category': cat,
                        'municipality': r.get('municipality') or '', 'capacity_per_hour': EST_PER_HOUR[cat], 'capacity_basis': 'estimate'})
    return out


def load_points(shelter_states=None, day=None):
    """Roads launch points (graph file for `day`, or launch_points* files) else derived OSM landmarks. Shelter sites are added as extra candidates."""
    base = (_graph_launch_points(day) if day else []) + _roads() or _derived()
    extra = [{'landing_id': 'S' + s['shelter_id'], 'label': s['label'], 'lat': s['lat'], 'lon': s['lon'], 'source_kind': 'shelter_site',
              'municipality': s['municipality'], 'capacity_per_hour': EST_PER_HOUR['shelter_site'], 'capacity_basis': 'estimate'} for s in (shelter_states or [])]
    return [{**p, 'source_label': SOURCE_LABELS[p['source_kind']]} for p in base + extra]
