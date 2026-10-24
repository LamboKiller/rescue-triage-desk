"""Derive small CSVs from read-only geography using only the standard library.

Membership samples every road vertex and segment midpoint. This is not an exact
line/polygon overlay: very narrow crossings between samples can be missed.
"""
import os
import argparse
import collections
import csv
import json
import math
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.geo.streets import normalize

CITIES = ('Porto Alegre', 'Canoas', 'Eldorado do Sul', 'São Leopoldo', 'Novo Hamburgo', 'Guaíba')
DATES = ('2024-05-06', '2024-05-08')


def in_ring(x, y, ring):
    inside = False
    a = ring[-1]
    for b in ring:
        ax, ay = a[:2]
        bx, by = b[:2]
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
        a = b
    return inside


def in_polygon(x, y, polygon):
    return in_ring(x, y, polygon[0]) and not any(in_ring(x, y, r) for r in polygon[1:])


def ring_index(ring):
    """Only edges spanning the point's latitude can cross its horizontal ray."""
    bins = collections.defaultdict(list)
    a = ring[-1]
    for b in ring:
        ax, ay = a[:2]
        bx, by = b[:2]
        if ay != by:
            for iy in range(math.floor(min(ay, by)*1000), math.floor(max(ay, by)*1000)+1):
                bins[iy].append((ax, ay, bx, by))
        a = b
    return bins


def indexed_ring(x, y, bins):
    inside = False
    for ax, ay, bx, by in bins.get(math.floor(y*1000), ()):
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
    return inside


class Index:
    def __init__(self):
        self.grid = collections.defaultdict(list)

    def add(self, geometry, value):
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        for polygon in polygons:
            xs, ys = zip(*[(p[0], p[1]) for p in polygon[0]])
            bbox = min(xs), min(ys), max(xs), max(ys)
            item = bbox, [ring_index(r) for r in polygon], value
            for ix in range(math.floor(bbox[0]*100), math.floor(bbox[2]*100)+1):
                for iy in range(math.floor(bbox[1]*100), math.floor(bbox[3]*100)+1):
                    self.grid[ix, iy].append(item)

    def values(self, point):
        x, y = point[:2]
        found = set()
        for (a, b, c, d), rings, value in self.grid.get((math.floor(x*100), math.floor(y*100)), ()):
            if (value not in found and a <= x <= c and b <= y <= d
                    and indexed_ring(x, y, rings[0]) and not any(indexed_ring(x, y, r) for r in rings[1:])):
                found.add(value)
        return found


def prepare(backup):
    dest = ROOT / 'data'
    dest.mkdir(exist_ok=True)
    def features(name):
        return json.loads((backup/'D1/clean'/name).read_text(encoding='utf-8'))['features']
    cities, water = Index(), Index()
    for f in features('census_tracts_2022.geojson'):
        city = f['properties']['municipality']
        if city in CITIES:
            cities.add(f['geometry'], city)
    for f in features('flood_observed.geojson'):
        p = f['properties']
        if p.get('surface') == 'water' and p.get('observation_date') in DATES:
            water.add(f['geometry'], p['observation_date'])
    rows = {}
    for index, f in enumerate(features('osm_roads.geojson')):
        if index % 20000 == 0:
            print(f'Road ways processed: {index}', flush=True)
        p, g = f['properties'], f['geometry']
        if not p.get('name') or not p.get('highway') or g['type'] not in ('LineString', 'MultiLineString'):
            continue
        lines = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
        touched = collections.defaultdict(set)
        for line in lines:
            samples = list(line)
            samples.extend(((a[0]+b[0])/2, (a[1]+b[1])/2) for a, b in zip(line, line[1:]))
            for point in samples:
                at = cities.values(point)
                if at:
                    wet = water.values(point)
                    for city in at:
                        touched[city].update(wet)
        for city, wet in touched.items():
            key = normalize(p['name']), city
            row = rows.setdefault(key, {'normalized_name': key[0], 'display_name': p['name'],
                                       'municipality': city, 'segments': 0,
                                       **{'segments_in_water_'+d: 0 for d in DATES}})
            row['segments'] += 1
            for d in wet:
                row['segments_in_water_'+d] += 1
    columns = ['normalized_name', 'display_name', 'municipality', 'segments']
    columns += ['segments_in_water_'+d for d in DATES] + ['any_in_water_'+d for d in DATES]
    with (dest/'streets_flood.csv').open('w', encoding='utf-8', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for key in sorted(rows):
            row = rows[key]
            for d in DATES:
                row['any_in_water_'+d] = int(row['segments_in_water_'+d] > 0)
            writer.writerow(row)
    shutil.copyfile(backup/'D3/clean/road_closures.csv', dest/'road_closures.csv')
    summary = {}
    for city in CITIES:
        group = [r for r in rows.values() if r['municipality'] == city]
        summary[city] = {'streets': len(group), **{d: sum(r['any_in_water_'+d] for r in group) for d in DATES}}
    (dest/'preparation_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    # Preserve supplied manifests verbatim when available; do not invent missing ones.
    manifests = {}
    for d in ('D1', 'D2', 'D3'):
        for path in (backup/d/'manifest.json', backup/d/'clean/manifest.json'):
            if path.exists():
                manifests[d] = json.loads(path.read_text(encoding='utf-8'))
    (dest/'ATTRIBUTION.md').write_text('''# Derived data attribution

Only derived CSVs are distributed. Source packs D1–D3 were prepared 21–23 October 2026.
The supplied backup contains no D1–D3 REPORT.md or manifest.json. Full manifest-based
attribution could not be verified; do not describe it as complete. Available source
research and inventories support the following credits:

* Street names/geometries: © OpenStreetMap contributors, Open Database License 1.0
  (https://www.openstreetmap.org/copyright). Derived database streets_flood.csv is
  distributed under ODbL 1.0, separately from the MIT application code.
  D1 snapshot 2024-06-15 is retrospective, later than the replay window.
* Census tracts/municipalities: IBGE, Censo Demográfico 2022; supplied D1 export.
  https://www.ibge.gov.br/estatisticas/sociais/populacao/22827-censo-demografico-2022.html
* Observed water: Possantti et al., UFRGS and collaborators, Banco de dados das
  cheias na Região Hidrográfica do Lago Guaíba em Maio de 2024, CC BY 4.0 per the
  supplied source brief. D1 gpkg_layer_inventory.json links the observed-water
  layers and IBGE input to Zenodo record 14617475 (v1.4, published 2025-01-08):
  https://doi.org/10.5281/zenodo.14617475 . Collection DOI:
  https://doi.org/10.5281/zenodo.11164049 . Earliest supplied version is record
  11164050 (2024-05-09); original per-layer publication remains unverified.
  The public record confirms version/date/authors; its extracted rights section
  did not expose a license identifier, so the license statement relies on the brief.
* Road closures: supplied D3 road_closures.csv, 31 rows. Each row preserves source,
  source_locator, published timestamp and quality notes. Sources include DNIT and
  public official bulletins. Research also identifies Fiocruz GIS Zenodo 11193971,
  CC BY 4.0 (https://doi.org/10.5281/zenodo.11193971); it is not claimed as D1's record.

Method: named OSM highway ways, street normalization, census polygon membership of
all road vertices and segment midpoints (bbox grid prefilter + ray casting, holes
respected); count a way once per municipality/name and once per observed-water date.
Narrow polygon crossings between sample points can be missed. Normalization merges
aliases differing only by road type, accents and de/da/do/das/dos; counts therefore
differ from the R3 intersecting-way calculation. No household location is inferred.
Unknown publication times exclude flood overlap from contemporaneous decisions.
No permanent-water mask: overlap is not flood depth, passability or a route check.
May 8 coverage differs substantially; zero overlap never establishes recession.
''' + ('\nSupplied manifests:\n```json\n'+json.dumps(manifests, indent=2)+'\n```\n' if manifests else ''), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('road_closures:', sum(1 for _ in csv.DictReader((dest/'road_closures.csv').open(encoding='utf-8'))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', type=Path, default=Path(os.environ.get('RTD_BACKUP_DIR', 'data-backup')),
                        help='folder with the D1-D3 data backup (or set RTD_BACKUP_DIR)')
    prepare(parser.parse_args().backup)
