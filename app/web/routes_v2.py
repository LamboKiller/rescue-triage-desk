"""Offline workstation GET hook. No backend state or network access."""
import gzip
import json
import mimetypes
import re
import sqlite3
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
UI = Path(__file__).resolve().parent / 'v2'
MAP = ROOT / 'data' / 'map3d'


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
            '.md': 'text/plain; charset=utf-8', '.pbf': 'application/x-protobuf'}.get(path.suffix)
    return _send(handler, path.read_bytes(), mime or mimetypes.guess_type(path)[0] or 'application/octet-stream')


def handle_get(handler, path, query):
    """Return False for routes owned by the original server; True when served."""
    if path not in ('/v2', '/v2/') and not path.startswith('/v2/'):
        return False
    name = unquote(path)
    if '\\' in name or '..' in name.split('/'):
        return _missing(handler)
    if name in ('/v2', '/v2/'):
        return _file(handler, UI, 'index.html')
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
    for prefix, folder in [('/v2/map/terrain-rgb/', 'terrain-rgb'), ('/v2/map/fonts/', 'fonts'),
                           ('/v2/map/sprites/', 'sprites')]:
        if name.startswith(prefix):
            return _file(handler, MAP / folder, name[len(prefix):])
    if name == '/v2/map/MANIFEST.md':
        return _file(handler, MAP, 'MANIFEST.md')
    if name in ('/v2/app.js', '/v2/map.js', '/v2/styles.css') or name.startswith('/v2/vendor/'):
        return _file(handler, UI, name[len('/v2/'):])
    return _missing(handler)
