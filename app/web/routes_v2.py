"""Offline workstation GET hook. No backend state or network access."""
import gzip
import json
import mimetypes
import re
import sqlite3
import csv
import math
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
UI = Path(__file__).resolve().parent / 'v2'
MAP = ROOT / 'data' / 'map3d'


def _day(query):
    values = query.get('date', [])
    if len(values) != 1 or date.fromisoformat(values[0]).isoformat() != values[0]:
        raise ValueError('Provide exactly one ISO date')
    return values[0]


def water_data(day):
    """Same rule as the pipeline (app/geo/depth.py): retrospective EMSN194 HAND grid selected by observation date <= replay day,
    always labelled retrospective / low confidence (created 12/06/2024; it never authorizes access)."""
    manifest = json.loads((MAP/'water/manifest.json').read_text(encoding='utf-8'))
    eligible = [x for x in manifest['images'] if x['observation_date'] <= day]
    return {**{k:v for k,v in manifest.items() if k != 'images'},
            'date':day, 'image':max(eligible,key=lambda x:x['observation_date'],default=None), 'retrospective':True,
            'note':'Sem observação até esta data.' if not eligible else 'HAND retrospectivo (Copernicus EMSN194, criado 12/06/2024); confiança baixa; não autoriza acesso.'}


def photos_data(day, lon, lat):
    path = ROOT/'data/photos/photos.csv'
    if not path.is_file():
        return {'available':False, 'photos':[]}
    found = []
    with path.open(encoding='utf-8-sig', newline='') as src:
        for row in csv.DictReader(src):
            try:
                taken = datetime.fromisoformat(row['taken_at'].replace('Z','+00:00'))
                if taken.date().isoformat() > day:
                    continue
                x, y = float(row['lon']), float(row['lat'])
                if not math.isfinite(x+y) or not (-180<=x<=180 and -90<=y<=90):
                    continue
                a = math.sin(math.radians(y-lat)/2)**2+math.cos(math.radians(y))*math.cos(math.radians(lat))*math.sin(math.radians(x-lon)/2)**2
                distance = 6371000*2*math.asin(min(1,math.sqrt(a)))
                if distance <= 300:
                    # Images are strictly local: no external thumbnail requests.
                    thumb = row.get('thumb','')
                    if not thumb.startswith('/v2/photos/') or '..' in thumb or '\\' in thumb:
                        row['thumb'] = None
                    found.append({**row, 'distance_m':round(distance,1)})
            except (KeyError, ValueError, TypeError):
                continue
    return {'available':True, 'photos':sorted(found,key=lambda x:(x['distance_m'],x['id']))[:3]}


def _gzip_allowed(handler):
    enc = {}
    for item in handler.headers.get('Accept-Encoding', '').lower().split(','):
        parts = item.strip().split(';')
        try:
            enc[parts[0]] = float(next((p.strip()[2:] for p in parts[1:] if p.strip().startswith('q=')), '1'))
        except ValueError:
            enc[parts[0]] = 0
    return enc.get('gzip', enc.get('*', 0)) > 0


def _send(handler, body, mime, *, compressed=False, status=200):
    if compressed and not _gzip_allowed(handler):
        body = gzip.decompress(body)
        compressed = False
    handler.send_response(status)
    handler.send_header('Content-Type', mime)
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('Vary', 'Accept-Encoding')
    if compressed:
        handler.send_header('Content-Encoding', 'gzip')
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _missing(handler):
    return _send(handler, b'{"error":"Recurso offline indisponivel."}', 'application/json', status=404)


def _file(handler, root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return _missing(handler)
    mime = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
            '.md': 'text/plain; charset=utf-8', '.woff2': 'font/woff2', '.pbf': 'application/x-protobuf'}.get(path.suffix)
    return _send(handler, path.read_bytes(), mime or mimetypes.guess_type(path)[0] or 'application/octet-stream')


def handle_get(handler, path, query):
    """Return False for routes owned by the original server; True when served."""
    if path == '/api/depth' and ('lon' in query or 'lat' in query):
        try:
            day = _day(query)
            if any(len(query.get(k,[])) != 1 for k in ('lon','lat')):
                raise ValueError('Invalid coordinates')
            lon,lat = float(query['lon'][0]),float(query['lat'][0])
            if not math.isfinite(lon+lat) or not (-180<=lon<=180 and -90<=lat<=90):
                raise ValueError('Invalid coordinates')
            from app.geo.depth import lookup, ATTRIBUTION
            image = water_data(day)['image']
            point = lookup(lon,lat,day) if image else None
            payload = {'point':point, 'source':ATTRIBUTION,
                       'observation_date':image['observation_date'] if image else None,
                       'published_at':image['published_at'] if image else None,
                       'note':'Estimativa HAND; sem dado não significa seco.' if image else water_data(day)['note']}
            return _send(handler,json.dumps(payload,ensure_ascii=False).encode(),'application/json; charset=utf-8')
        except (ValueError,TypeError):
            return _send(handler,b'{"error":"Invalid date or coordinates"}','application/json',status=400)
    if path in ('/api/photos', '/api/water'):
        try:
            day = _day(query)
            if path == '/api/water':
                payload = water_data(day)
            else:
                if any(len(query.get(k,[])) != 1 for k in ('lon','lat')):
                    raise ValueError('Provide exactly one lon and lat')
                lon,lat = float(query['lon'][0]),float(query['lat'][0])
                if not math.isfinite(lon+lat) or not (-180<=lon<=180 and -90<=lat<=90):
                    raise ValueError('Invalid coordinates')
                payload = photos_data(day,lon,lat)
            return _send(handler,json.dumps(payload,ensure_ascii=False).encode(),'application/json; charset=utf-8')
        except (ValueError, TypeError):
            return _send(handler,b'{"error":"Invalid date or coordinates"}','application/json',status=400)
    if path not in ('/v2', '/v2/') and not path.startswith('/v2/'):
        return False
    name = unquote(path)
    if '\\' in name or '..' in name.split('/'):
        return _missing(handler)
    if name in ('/v2', '/v2/'):
        return _file(handler, UI, 'index.html')
    if name.startswith('/v2/photos/'):
        if Path(name).suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):
            return _missing(handler)
        return _file(handler, ROOT/'data/photos', name[len('/v2/photos/'):])
    if name == '/v2/map/style.json':
        style = json.loads((MAP / 'offline_style.json').read_text(encoding='utf-8'))
        style['sources']['protomaps']['tiles'] = ['/v2/map/tiles/{z}/{x}/{y}.pbf']
        style['sources']['protomaps']['attribution'] = '© OpenStreetMap contributors · Protomaps'
        style['glyphs'] = '/v2/map/fonts/{fontstack}/{range}.pbf'
        style['sprite'] = '/v2/map/sprites/light'
        return _send(handler, json.dumps(style).encode(), 'application/json')
    if name == '/v2/catalogue':
        payload = {'hazards': json.loads((ROOT / 'data/hazards/manifest.json').read_text(encoding='utf-8')),
                   'map3d': (MAP / 'MANIFEST.md').read_text(encoding='utf-8')}
        return _send(handler, json.dumps(payload, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
    match = re.fullmatch(r'/v2/map/tiles/(\d{1,2})/(\d{1,5})/(\d{1,5})\.pbf', name)
    if match:
        z, x, y = map(int, match.groups())
        if z > 15 or x >= 1 << z or y >= 1 << z or not (MAP / 'basemap.mbtiles').is_file():
            return _missing(handler)
        with sqlite3.connect((MAP / 'basemap.mbtiles').resolve().as_uri() + '?mode=ro', uri=True) as db:
            row = db.execute('SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?',
                             (z, x, (1 << z) - 1 - y)).fetchone()
        if not row:
            return _missing(handler)
        return _send(handler, row[0], 'application/vnd.mapbox-vector-tile', compressed=row[0][:2] == b'\x1f\x8b')
    match = re.fullmatch(r'/v2/map/buildings/(recommended_[a-z_0-9]+)\.geojson', name)
    if match:
        asset = MAP / 'buildings' / (match[1] + '.geojson.gz')
        if not asset.is_file():
            return _missing(handler)
        return _send(handler, asset.read_bytes(), 'application/geo+json', compressed=True)
    for prefix, folder in [('/v2/map/water/', 'water'), ('/v2/map/terrain-rgb/', 'terrain-rgb'), ('/v2/map/fonts/', 'fonts'),
                           ('/v2/map/sprites/', 'sprites')]:
        if name.startswith(prefix):
            return _file(handler, MAP / folder, name[len(prefix):])
    if name == '/v2/map/MANIFEST.md':
        return _file(handler, MAP, 'MANIFEST.md')
    if name in ('/v2/app.js', '/v2/map.js', '/v2/missions.js', '/v2/feedback.js', '/v2/styles.css') or name.startswith('/v2/vendor/'):
        return _file(handler, UI, name[len('/v2/'):])
    return _missing(handler)
