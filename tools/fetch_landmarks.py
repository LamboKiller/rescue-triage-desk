"""Fetch named OSM landmarks; at most six HTTP requests, no invented fallback."""
import argparse
import collections
import csv
import json
import sys
import urllib.parse
import urllib.request
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from tools.prepare_data import CITIES, DATES, Index

FILTERS = {
    'amenity': 'bus_station|hospital|clinic|school|university|place_of_worship|marketplace|fire_station|police|townhall|community_centre|pharmacy|fuel',
    'shop': 'supermarket|mall', 'public_transport': 'station', 'railway': 'station',
    'leisure': 'stadium|park', 'place': 'square|neighbourhood|suburb', 'tourism': 'attraction|museum',
    'aeroway': 'aerodrome|terminal'}
ENDPOINTS = ('https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter')
COLUMNS = ['osm_type', 'osm_id', 'name', 'alt_names', 'category', 'municipality', 'neighbourhood',
           'street', 'housenumber', 'lat', 'lon'] + ['in_water_'+d for d in DATES] + ['snapshot_utc']


# One bounding box around the six municipalities (census polygons then assign each place to its city).
# Area-by-name lookups were too slow on the public Overpass servers (24/10: 60 s for a tiny query, batches timed out).
BBOX = (-30.35, -51.70, -29.55, -50.98)  # south, west, north, east
# Small queries (one category each): the public servers answer these in ~40 s but time out on big batches (24/10).
GROUPS = [{k: v} for k, values in FILTERS.items() for v in values.split('|')]


def query(group):
    box = ','.join(str(v) for v in BBOX)
    selectors = ''.join(f'nwr["name"]["{key}"~"^({values})$"]({box});' for key, values in group.items())
    return f'[out:json][timeout:180];({selectors});out tags center;'


def fetch(backup):
    water, cities = Index(), Index()
    clean = backup/'D1/clean'
    for f in json.loads((clean/'flood_observed.geojson').read_text(encoding='utf-8'))['features']:
        p = f['properties']
        if p.get('surface') == 'water' and p.get('observation_date') in DATES:
            water.add(f['geometry'], p['observation_date'])
    for f in json.loads((clean/'census_tracts_2022.geojson').read_text(encoding='utf-8'))['features']:
        if f['properties']['municipality'] in CITIES:
            cities.add(f['geometry'], f['properties']['municipality'])
    snapshot = datetime.now(timezone.utc).isoformat()
    queries, elements = [], {}
    # One small query per category, sequential, polite pause; second endpoint only as a fallback.
    failed = []
    for batch in GROUPS:
        q = query(batch)
        queries.append(q)
        ok = False
        # Up to 3 rounds over both endpoints with growing waits: the public servers return 502/504 under load.
        for wait in (0, 20, 60):
            time.sleep(wait)
            for endpoint in ENDPOINTS:
                try:
                    req = urllib.request.Request(endpoint, data=urllib.parse.urlencode({'data': q}).encode(),
                        headers={'User-Agent': 'rescue-triage-desk-hackathon'})
                    with urllib.request.urlopen(req, timeout=240) as response:
                        result = json.load(response)
                    if result.get('remark') or 'elements' not in result:
                        raise ValueError('Incomplete Overpass response')
                    for e in result['elements']:
                        elements[e['type'], e['id']] = e
                    print(f'Overpass {list(batch.items())[0]}: {len(result["elements"])} named features', flush=True)
                    ok = True
                    break
                except Exception as exc:
                    print(f'Overpass {list(batch.items())[0]}: {type(exc).__name__} {getattr(exc, "code", "")}', flush=True)
            if ok:
                break
        if not ok:
            failed.append(list(batch.items())[0])
        time.sleep(3)
    if not elements:
        raise RuntimeError('Overpass unreachable; no landmark CSV written')
    rows = []
    for (kind, oid), e in sorted(elements.items()):
        t, point = e['tags'], e.get('center', e)
        if 'lat' not in point or 'lon' not in point:
            continue
        memberships = cities.values((point['lon'], point['lat']))
        wet = water.values((point['lon'], point['lat']))
        for city in sorted(memberships):
            rows.append(dict(zip(COLUMNS, [kind, str(oid), t['name'],
                '|'.join(t[k] for k in ('name:pt', 'alt_name', 'official_name', 'short_name') if t.get(k)),
                next((k+':'+t[k] for k in FILTERS if t.get(k) in FILTERS[k].split('|')), ''), city,
                t.get('addr:suburb', ''), t.get('addr:street', ''), t.get('addr:housenumber', ''),
                point['lat'], point['lon'], *[int(d in wet) for d in DATES], snapshot])))
    import io
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    payload = out.getvalue().encode('utf-8')
    if len(payload) >= 3_000_000:
        raise ValueError('Landmarks exceed 3 MB; no truncated dataset written')
    (ROOT/'data/landmarks.csv').write_bytes(payload)
    attribution = ROOT/'data/ATTRIBUTION.md'
    with attribution.open('a', encoding='utf-8') as f:
        f.write('\n## Named landmarks snapshot '+snapshot+'\n\n© OpenStreetMap contributors; ODbL 1.0 '
                '(https://www.openstreetmap.org/copyright). Current Overpass snapshot is retrospective '
                'relative to May 2024; names and geometry may have changed. Way/relation centers are '
                'representative points, not entrances. Membership uses the same census and observed-water '
                'layers and indexed point-in-polygon code as prepare_data (holes respected). Unknown '
                'publication times exclude water flags from contemporaneous priority. Features whose '
                'center is outside census coverage are excluded. Queries:\n\n```overpass\n'+'\n'.join(queries)+'\n```\n')
    summary = {'snapshot_utc': snapshot, 'rows': len(rows), 'bytes': len(payload), 'failed_categories': failed,
               'municipality': dict(collections.Counter(r['municipality'] for r in rows)),
               'category': dict(collections.Counter(r['category'] for r in rows))}
    from app.geo.landmarks import normalize
    summary['famous_present'] = {name: any(normalize(name) in normalize(r['name']+' '+r['alt_names']) for r in rows)
        for name in ('Rodoviária', 'Arena do Grêmio', 'Beira-Rio', 'Mercado Público', 'Salgado Filho', 'Hospital de Clínicas')}
    (ROOT/'data/landmark_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', type=Path, default=Path('C:/Users/yusse/Projects/open-agent-hackathon-2026/data-backup'))
    try:
        fetch(parser.parse_args().backup)
    except Exception as exc:
        sys.exit('Landmark fetch stopped: '+str(exc))
