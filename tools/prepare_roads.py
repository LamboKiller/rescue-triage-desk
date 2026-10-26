"""Build ODbL road graphs. Stdlib only; only Overpass is contacted.

Run: python tools/prepare_roads.py [--offline]
Raw per-city responses are cached under data/roads/source/ for reproducibility.
Polyline coordinates are [lon, lat]; connectivity uses OSM node ids, not proximity.
"""
import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.geo.depth import DepthGrid, DATES, CONFIDENCE

HIGHWAYS = ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary',
            'primary_link', 'secondary', 'secondary_link', 'tertiary',
            'tertiary_link', 'residential', 'service', 'unclassified', 'living_street', 'track')
ATTRS = ('highway', 'oneway', 'bridge', 'tunnel', 'maxheight', 'surface', 'name',
         'ref', 'access', 'vehicle', 'motor_vehicle', 'junction', 'layer')
LABEL = 'estimativa (derivado de HAND/OSM)'
CAP = 20_000_000


def normalized(value):
    value = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode().lower()
    return ' '.join(re.findall(r'[a-z0-9]+', value))


def distance(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    s = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(s)))


def samples(polyline, spacing=25):
    """Include all vertices and subdivide every leg into intervals <= spacing m."""
    if not polyline:
        return []
    result = [polyline[0]]
    for a, b in zip(polyline, polyline[1:]):
        n = max(1, math.ceil(distance(a, b)/spacing))
        result.extend([[a[0]+(b[0]-a[0])*i/n, a[1]+(b[1]-a[1])*i/n] for i in range(1, n+1)])
    return result


def sample_depth(polyline, grid, day):
    points = samples(polyline)
    # Half-pixel diagonal: use the existing reader without its default 60m gap fill.
    values = [grid.nearest(*p, radius=grid.h['pixel_m']/math.sqrt(2)+0.01)['depth_m'] for p in points]
    known = [v for v in values if v is not None]
    n = len(values)
    return {'observation_date': day, 'kind': 'retrospective',
            'max_depth_m': max(known, default=None),
            'wet_fraction': round(sum(v is not None and v > 0 for v in values)/n, 6) if n else 0,
            'unknown_fraction': round(sum(v is None for v in values)/n, 6) if n else 1}, points, values


def build_graph(payload, city):
    ways = []
    for way in payload.get('elements', []):
        tags = way.get('tags', {})
        if way.get('type') != 'way' or tags.get('highway') not in HIGHWAYS:
            continue
        # The most specific motor-vehicle rule overrides general access.
        permission = next((tags[k] for k in ('motor_vehicle', 'vehicle', 'access') if k in tags), '')
        if permission in ('no', 'private') or len(way.get('nodes', [])) < 2:
            continue
        if len(way['nodes']) != len(way.get('geometry', [])):
            raise ValueError('Missing OSM geometry')
        ways.append(way)
    uses = Counter(n for w in ways for n in w['nodes'])
    nodes, edges = {}, []
    for w in sorted(ways, key=lambda w: w['id']):
        ids = w['nodes']
        coords = [[round(p['lon'], 6), round(p['lat'], 6)] for p in w['geometry']]
        breaks = [i for i, n in enumerate(ids) if i == 0 or i == len(ids)-1 or uses[n] > 1]
        for start, end in zip(breaks, breaks[1:]):
            a, b = str(ids[start]), str(ids[end])
            polyline = coords[start:end+1]
            nodes[a], nodes[b] = coords[start], coords[end]
            attrs = {k: w.get('tags', {}).get(k) for k in ATTRS}
            if attrs['oneway'] is None and (attrs['junction'] == 'roundabout' or attrs['highway'] == 'motorway'):
                attrs['oneway'] = 'yes'
            edges.append(dict(id=f"{w['id']}:{start}:{end}", osm_way_id=w['id'], u=a, v=b,
                              municipality=city, length_m=round(sum(distance(x,y) for x,y in zip(polyline,polyline[1:])),2),
                              polyline=polyline, **attrs, depth={}, closed_dates=[], closure_matches=[]))
    return {'municipality': city, 'nodes': nodes, 'edges': edges}


def point_edge_distance(point, edge):
    lon, lat = point
    scale = math.cos(math.radians(lat))
    best = float('inf')
    for a, b in zip(edge['polyline'], edge['polyline'][1:]):
        ax, ay = (a[0]-lon)*scale*111195, (a[1]-lat)*111195
        bx, by = (b[0]-lon)*scale*111195, (b[1]-lat)*111195
        dx, dy = bx-ax, by-ay
        t = max(0, min(1, -(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx or dy else 0
        best = min(best, math.hypot(ax+t*dx, ay+t*dy))
    return best


def detect_launches(graph, day, sampled):
    candidates = []
    adjacent = Counter()
    for e in graph['edges']:
        if (e['depth'][day]['max_depth_m'] or 0) >= .5:
            adjacent.update(set((e['u'], e['v'])))
    for e in graph['edges']:
        points, values = sampled[e['id']]
        for reverse, node in ((False, e['u']), (True, e['v'])):
            pairs = list(zip(points, values))
            if reverse:
                pairs.reverse()
            if not pairs or pairs[0][1] is None or pairs[0][1] >= .3:
                continue
            last_shallow = None
            for point, value in pairs:
                if value is None:
                    break  # Never infer a usable dry-side connection through a gap.
                if value < .3:
                    last_shallow = point
                if value >= .5 and last_shallow is not None:
                    candidates.append(dict(lon=round(last_shallow[0],6), lat=round(last_shallow[1],6),
                        nearest_street_name=e.get('name') or e.get('ref') or '(sem nome)',
                        depth_beyond_m=value, municipality=graph['municipality'], dry_side_node_id=node,
                        edge_id=e['id'], adjacent_wet_edges=adjacent[node], label=LABEL,
                        synthetic_node_ids=graph.get('synthetic_node_ids',False),
                        routing_eligible=graph.get('routing_eligible',True),
                        observation_date=day, kind='retrospective', parking_status='unverified'))
                    break
    selected = cluster_launches(candidates)
    # Name an unnamed access by the nearest named street, not an invented label.
    buckets = defaultdict(list)
    for edge in graph['edges']:
        if not edge.get('name'):
            continue
        xs,ys = zip(*edge['polyline'])
        for x in range(math.floor(min(xs)/.005),math.floor(max(xs)/.005)+1):
            for y in range(math.floor(min(ys)/.005),math.floor(max(ys)/.005)+1):
                buckets[x,y].append(edge)
    for point in selected:
        x,y = math.floor(point['lon']/.005),math.floor(point['lat']/.005)
        nearby = {edge['id']:edge for dx in (-1,0,1) for dy in (-1,0,1)
                  for edge in buckets[(x+dx,y+dy)]}
        ranked = [(point_edge_distance((point['lon'],point['lat']),edge),edge['id'],edge)
                  for edge in nearby.values()]
        if ranked:
            dist,_,edge = min(ranked,key=lambda item:(item[0],item[1]))
            if dist <= 500:
                point['nearest_street_name'] = edge['name']
                point['street_name_distance_m'] = round(dist,2)
                point['street_name_edge_id'] = edge['id']
    return selected


def cluster_launches(candidates):
    """Greedy clusters; each member stays within 150m of its representative."""
    selected, buckets = [], defaultdict(list)
    for c in sorted(candidates, key=lambda c: (-c['adjacent_wet_edges'], c['edge_id'], c['dry_side_node_id'])):
        key = (math.floor(c['lon']/.002), math.floor(c['lat']/.002))
        nearby = [x for dx in (-1,0,1) for dy in (-1,0,1) for x in buckets[(key[0]+dx,key[1]+dy)]]
        if any(distance([c['lon'],c['lat']], [x['lon'],x['lat']]) <= 150 for x in nearby):
            continue
        selected.append(c)
        buckets[key].append(c)
    return selected


def join_closures(graphs, rows, dates=DATES):
    matched, unmatched = [], []
    cities = {g['municipality'] for g in graphs}
    edges = [e for g in graphs for e in g['edges']]
    for row in rows:
        rid = row.get('record_id', '')
        city = row.get('municipality', '')
        scoped = [city] if city in cities else [c for c in cities if normalized(c) in normalized(row.get('segment',''))]
        names = {normalized(x) for x in row.get('road','').split('|') if x}
        hits = []
        if row.get('transport_mode', 'road') == 'road':
            for e in edges:
                if scoped and e['municipality'] not in scoped:
                    continue
                edge_names = {normalized(e.get('name'))} | {
                    normalized(ref) for ref in (e.get('ref') or '').split(';')}
                by_name = bool(scoped and names & edge_names)
                try:
                    by_point = point_edge_distance((float(row['lon']),float(row['lat'])), e) <= 60
                except (KeyError, ValueError, TypeError):
                    by_point = False
                if by_name or by_point:
                    hits.append((e, 'nearest_60m' if by_point else 'corridor_candidate'))
        if not hits:
            unmatched.append(rid)
            continue
        matched.append(rid)
        status = row.get('status','')
        for e, method in hits:
            e['closure_matches'].append({'record_id':rid, 'method':method, 'status':status,
                'from_date':row.get('from_date'), 'to_date':row.get('to_date'),
                'source_published_at':row.get('source_published_at'), 'extent_verified':False})
            # A reopening is never extrapolated backwards into a closure.
            if status not in ('closed','closed_at_observation','scheduled_total_closure','closed_then_emergency_only'):
                continue
            start = row.get('from_date','')[:10]
            end = row.get('to_date','')[:10]
            published = row.get('source_published_at','')[:10]
            for day in dates:
                if start and published and start <= day and published <= day and (not end or day <= end):
                    if day not in e['closed_dates']:
                        e['closed_dates'].append(day)
    return {'matched': matched, 'unmatched': unmatched}


def query_for(city):
    return ('[out:json][timeout:180];area["ISO3166-2"="BR-RS"]["admin_level"="4"]->.rs;'
            f'area(area.rs)["name"={json.dumps(city,ensure_ascii=False)}]["admin_level"="8"]->.city;'
            f'way(area.city)["highway"~"^({"|".join(HIGHWAYS)})$"];out body geom;')


def dump_gzip(path, value):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    path.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))


def fetch(city, folder, offline=False):
    path = folder / (normalized(city).replace(' ', '_')+'.json.gz')
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    failed = path.with_suffix('.failed.json')
    if failed.exists():
        raise OSError('Cached exhausted Overpass attempts: '+city)
    if offline:
        raise FileNotFoundError(path)
    query = query_for(city)
    for attempt, host in enumerate(('overpass-api.de', 'overpass.kumi.systems')):
        if attempt:
            print('Retry once:', city, 'via', host, flush=True)
            time.sleep(10)
        req = urllib.request.Request('https://'+host+'/api/interpreter',
            data=urllib.parse.urlencode({'data':query}).encode(),
            headers={'User-Agent':'RescueTriageDesk/1.0 (offline road graph research)'})
        try:
            with urllib.request.urlopen(req, timeout=210) as response:
                payload = json.load(response)
            if payload.get('remark') or not payload.get('elements'):
                raise ValueError('Overpass incomplete or empty response')
            record = {'download_date':dt.datetime.now(dt.timezone.utc).isoformat(),
                      'endpoint':req.full_url, 'query':query, 'payload':payload}
            dump_gzip(path, record)
            return record
        except (OSError, ValueError) as exc:
            if attempt:
                failed.write_text(json.dumps({'municipality':city,'attempts':2,
                    'error':type(exc).__name__,'query':query,'date':dt.datetime.now(dt.timezone.utc).isoformat()}),encoding='utf-8')
                raise


def fallback(city, folder, backup):
    """Retain useful local geometry after exhausted network attempts, visibly unroutable.

    The supplied clipped GeoJSON has no OSM node ids. Coordinate-derived ids are
    flagged synthetic; they MUST NOT be treated as validated routing topology.
    """
    from tools.prepare_data import Index
    index = Index()
    for f in json.loads((backup/'D1/clean/census_tracts_2022.geojson').read_text(encoding='utf-8'))['features']:
        if f['properties']['municipality'] == city:
            index.add(f['geometry'],city)
    raw = (backup/'D1/clean/osm_roads.geojson').read_bytes()
    manifest = json.loads((backup/'D1/manifest.json').read_text(encoding='utf-8'))
    provenance = next(r for r in manifest if any(f['path']=='clean/osm_roads.geojson' for f in r.get('files',[])))
    elements = []
    for f in json.loads(raw)['features']:
        p,g = f['properties'],f['geometry']
        if p.get('highway') not in HIGHWAYS or g['type'] != 'LineString':
            continue
        line = g['coordinates']
        points = line + [[(a[0]+b[0])/2,(a[1]+b[1])/2] for a,b in zip(line,line[1:])]
        if not any(index.values(point) for point in points):
            continue
        # Layer prevents obvious bridge/ground crossings; all topology remains unverified.
        nodes = ['derived:'+str(p.get('layer') or '0')+':'+','.join(f'{v:.6f}' for v in point[:2]) for point in line]
        elements.append({'type':'way','id':p['osm_id'],'nodes':nodes,
            'geometry':[{'lon':point[0],'lat':point[1]} for point in line],
            'tags':{k:p[k] for k in ATTRS if p.get(k) is not None}})
    if not elements:
        raise ValueError('No local fallback geometry for '+city)
    record = {'download_date':provenance['retrieved_at'],
        'endpoint':'local D1/clean/osm_roads.geojson (Overpass attempts exhausted)',
        'query':query_for(city),'snapshot_utc':'2024-06-15T23:59:59Z',
        'fallback':True,'synthetic_node_ids':True,'routing_eligible':False,
        'source_sha256':hashlib.sha256(raw).hexdigest(),'payload':{'elements':elements}}
    dump_gzip(folder/(normalized(city).replace(' ','_')+'.json.gz'),record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--fallback-backup',type=Path,help='local D1 backup, only after exhausted Overpass attempts; unverified topology')
    args = parser.parse_args()
    folder = ROOT/'data/roads'
    source = folder/'source'
    source.mkdir(parents=True, exist_ok=True)
    with (ROOT/'data/streets_flood.csv').open(encoding='utf-8', newline='') as stream:
        cities = sorted({r['municipality'] for r in csv.DictReader(stream)})
    records = []
    for city in cities:
        print('OSM:', city, flush=True)
        try:
            record = fetch(city, source, args.offline)
        except (OSError,ValueError):
            if args.offline or not args.fallback_backup:
                raise
            print('LOCAL FALLBACK (unverified topology):',city,flush=True)
            record = fallback(city,source,args.fallback_backup)
        records.append(record)
        if not args.offline:
            time.sleep(3)
    grids = {day:DepthGrid.load(ROOT/'data/depth', day) for day in DATES}
    graphs, launches = [], {d:[] for d in DATES}
    for city, record in zip(cities, records):
        graph = build_graph(record['payload'], city)
        graph['topology_kind'] = 'coordinate_derived_unverified' if record.get('fallback') else 'osm_node_ids'
        graph['synthetic_node_ids'] = bool(record.get('fallback'))
        graph['routing_eligible'] = not record.get('fallback',False)
        for edge in graph['edges']:
            edge['routing_eligible'] = graph['routing_eligible']
            edge['synthetic_node_ids'] = graph['synthetic_node_ids']
        print(city, len(graph['nodes']), 'nodes;', len(graph['edges']), 'edges', flush=True)
        for day, grid in grids.items():
            sampled = {}
            for e in graph['edges']:
                summary, points, values = sample_depth(e['polyline'], grid, day)
                e['depth'][day] = summary
                sampled[e['id']] = points, values
            launches[day].extend(detect_launches(graph, day, sampled))
        graphs.append(graph)
    with (ROOT/'data/road_closures.csv').open(encoding='utf-8', newline='') as stream:
        closures = join_closures(graphs, list(csv.DictReader(stream)))
    for day in launches:
        launches[day] = cluster_launches(launches[day])
        launches[day].sort(key=lambda p:(-p['adjacent_wet_edges'],p['municipality'],p['edge_id']))
    document = {'schema_version':1, 'coordinate_order':'lon,lat', 'license':'ODbL-1.0',
        'osm_kind':'retrospective', 'confidence':CONFIDENCE,
        'depth_sampling':{'spacing_m':25,'radius_m':20/math.sqrt(2)+.01,'wet_threshold_m':0,
                          'unknown_is_dry':False,'bridge_deck_correction':False},
        'closed_dates_semantics':'conservative corridor candidates, not verified segment closures',
        'sources':[{'municipality':c, 'download_date':r['download_date'],'fallback':r.get('fallback',False),
                    'snapshot_utc':r.get('snapshot_utc'),
                    'sha256':hashlib.sha256((source/(normalized(c).replace(' ','_')+'.json.gz')).read_bytes()).hexdigest()}
                   for c,r in zip(cities,records)],
        'graphs':graphs, 'launch_points':launches, 'closure_join':closures}
    dump_gzip(folder/'graph.json.gz', document)
    attribution = ['# Road graph attribution', '', '© OpenStreetMap contributors; Open Database License (ODbL) 1.0.',
        'https://www.openstreetmap.org/copyright ; https://opendatacommons.org/licenses/odbl/1-0/',
        'The derived road database and cached source responses are distributed under ODbL 1.0.',
        'Current geometry is retrospective relative to May 2024. Rebuild offline from source/*.json.gz.',
        'HAND: Copernicus EMS (© 2024 European Union), EMSN194; observed May 6/8, created June 12 2024.',
        'Depth product terms remain unresolved as documented in data/ATTRIBUTION.md.',
        'Unknown is not dry. HAND is ground water, not bridge-deck clearance. Parking/access unverified.', '']
    for city, record in zip(cities,records):
        attribution.extend([f"## {city} — {record['download_date']}", record['endpoint'],
                            '```overpass',record['query'],'```',''])
        if record.get('fallback'):
            attribution.extend(['NETWORK FALLBACK: supplied D1 OSM snapshot 2024-06-15; coordinate-derived',
                'synthetic node ids, unverified topology, routing_eligible=false. The query above failed;',
                'it is not the source of this fallback. Source SHA256: '+record['source_sha256'],''])
    (folder/'ATTRIBUTION.md').write_text('\n'.join(attribution), encoding='utf-8')
    total = sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
    if total > CAP:
        raise ValueError(f'Road directory exceeds {CAP} bytes: {total}')
    print(json.dumps({'cities':cities,'nodes':sum(len(g['nodes']) for g in graphs),
        'edges':sum(len(g['edges']) for g in graphs), 'launches':{d:len(p) for d,p in launches.items()},
        'closures':closures,'bytes':total},ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
