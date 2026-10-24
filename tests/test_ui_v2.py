"""Offline UI contract tests. Python stdlib; JS checks use existing Node only."""
import gzip
import http.client
import json
import shutil
import sqlite3
import subprocess
import threading
import unittest
import contextlib
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from app.web import routes_v2
from support import Scratch

ROOT = Path(__file__).resolve().parents[1]


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                u = urlsplit(self.path)
                if not routes_v2.handle_get(self, u.path, parse_qs(u.query)):
                    self.send_error(404)

            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def get(self, path, encoding='identity'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            connection.request('GET', path, headers={'Accept-Encoding': encoding})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_entry_and_assets(self):
        for path, content_type in [('/v2', 'text/html'), ('/v2/', 'text/html'),
                                    ('/v2/app.js', 'text/javascript'), ('/v2/map.js', 'text/javascript'),
                                    ('/v2/styles.css', 'text/css')]:
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers['Content-Type'].startswith(content_type))
            self.assertEqual(int(headers['Content-Length']), len(body))
        self.assertIn('lang="pt-BR"', self.get('/v2')[2].decode())
        self.assertFalse(routes_v2.handle_get(None, '/', {}))
        self.assertFalse(routes_v2.handle_get(None, '/api/map', {}))

    def test_path_boundaries(self):
        for path in ['/v2/../run.py', '/v2/map/fonts/%2e%2e/%2e%2e/run.py',
                     '/v2/map/fonts/..%5crun.py', '/v2/map/tiles/99/0/0.pbf',
                     '/v2/map/tiles/1/9/0.pbf', '/v2/map/buildings/recommended_unknown.geojson',
                     '/v2/map/basemap.mbtiles']:
            self.assertEqual(self.get(path)[0], 404, path)

    def test_xyz_tiles_and_compression_negotiation(self):
        with sqlite3.connect(routes_v2.MAP / 'basemap.mbtiles') as db:
            z, x, row, original = db.execute('SELECT zoom_level,tile_column,tile_row,tile_data FROM tiles LIMIT 1').fetchone()
        path = f'/v2/map/tiles/{z}/{x}/{(1 << z) - 1 - row}.pbf'
        status, headers, body = self.get(path, 'gzip')
        self.assertEqual(status, 200)
        self.assertEqual(body, original)
        self.assertEqual(headers.get('Content-Encoding'), 'gzip' if original[:2] == b'\x1f\x8b' else None)
        expected = gzip.decompress(original) if original[:2] == b'\x1f\x8b' else original
        for encoding in ('identity', 'gzip;q=0', '*;q=1,gzip;q=0', 'gzip;q=bad'):
            status, headers, body = self.get(path, encoding)
            self.assertEqual(status, 200)
            self.assertNotIn('Content-Encoding', headers)
            self.assertEqual(body, expected)
        self.assertEqual(self.get(path, '*;q=.5')[1].get('Content-Encoding'), 'gzip')

    def test_terrain_building_zones_and_support_assets(self):
        png = next((routes_v2.MAP / 'terrain-rgb').rglob('*.png'))
        status, headers, body = self.get('/v2/map/terrain-rgb/' + png.relative_to(routes_v2.MAP / 'terrain-rgb').as_posix())
        self.assertEqual(status, 200)
        self.assertEqual(body[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(headers['Content-Type'], 'image/png')
        for source in (routes_v2.MAP / 'buildings').glob('recommended_*.geojson.gz'):
            status, headers, body = self.get('/v2/map/buildings/' + source.name[:-3], 'gzip')
            self.assertEqual(status, 200)
            self.assertEqual(headers.get('Content-Encoding'), 'gzip')
            payload = json.loads(gzip.decompress(body))
            self.assertEqual(payload['type'], 'FeatureCollection')
            self.assertIn('height_m', payload['features'][0]['properties'])
            self.assertIn('height_source', payload['features'][0]['properties'])
        source = next((routes_v2.MAP / 'buildings').glob('*.gz'))
        self.assertNotIn('Content-Encoding', self.get('/v2/map/buildings/' + source.name[:-3])[1])
        font = next((routes_v2.MAP / 'fonts').rglob('*.pbf'))
        self.assertEqual(self.get('/v2/map/fonts/' + font.relative_to(routes_v2.MAP / 'fonts').as_posix().replace(' ', '%20'))[0], 200)
        self.assertEqual(self.get('/v2/map/sprites/light.json')[0], 200)

    def test_style_catalogue_and_size_caps(self):
        status, _, body = self.get('/v2/map/style.json')
        self.assertEqual(status, 200)
        style = json.loads(body)
        self.assertEqual(style['sources']['protomaps']['tiles'], ['/v2/map/tiles/{z}/{x}/{y}.pbf'])
        self.assertTrue(style['glyphs'].startswith('/v2/map/fonts/'))
        self.assertTrue(style['sprite'].startswith('/v2/map/sprites/'))
        status, _, body = self.get('/v2/catalogue')
        self.assertEqual(status, 200)
        self.assertIn('sources', json.loads(body)['hazards'])
        self.assertIn('ODbL', json.loads(body)['map3d'])
        ui = sum(p.stat().st_size for p in routes_v2.UI.rglob('*') if p.suffix in ('.html', '.css', '.js') and 'vendor' not in p.relative_to(routes_v2.UI).parts)
        self.assertLessEqual(ui, 150000)
        self.assertLessEqual(sum(p.stat().st_size for p in routes_v2.MAP.rglob('*') if p.is_file()), 60000000)

    def test_javascript_syntax_and_safety_gates(self):
        node = shutil.which('node.exe') or shutil.which('node')
        if not node:
            self.skipTest('Node local não encontrado')
        for path in routes_v2.UI.glob('*.js'):
            p = subprocess.run([node, '--check', str(path)], capture_output=True, text=True, timeout=20)
            self.assertEqual(p.returncode, 0, p.stderr)
        # Exercise real queue/action decisions in a VM, with no DOM rendering or network.
        source = (routes_v2.UI / 'app.js').read_text(encoding='utf-8').split("document.querySelectorAll('[data-mode]')")[0]
        script = source + r'''
const assert=require('assert');
const c={case_id:'x',version:2,status:'proposed',location_confirmed:true,result:{decision:'SEND_CANDIDATE',questions:[]},fields:{},fleet:[{asset:'boat',label_pt:'Barco',verdict:'caution',reasons_pt:['Equipe treinada']}]};
assert.equal(primary(c).reason,'Escolha um meio');
S.assets.set('x','boat');assert.ok(primary(c).reason.includes('cautelas'));
S.acks.add('x:boat:2');assert.equal(primary(c).action,'approve_dispatch');
c.version=3;assert.ok(primary(c).reason.includes('cautelas'));
c.fleet[0].verdict='unsafe';assert.equal(group(c),1);
assert.ok(primary(c).action!=='approve_dispatch');
c.fleet=[];c.result.decision='CALLBACK';assert.equal(group(c),2);
assert.equal(primary(c).action,'request_callback');
c.status='reported_rescued_unconfirmed';assert.equal(group(c),3);
assert.ok(!primary(c).action);
c.status='dispatched';assert.equal(primary(c).action,'field_confirm');
c.fields={people:{value:3,derived:true}};assert.ok(openItems(c).some(x=>x.key==='people'));
assert.equal(val(c,'children'),null);
'''
        # Only lookup of $ is deferred; all assertions above are pure data logic.
        p = subprocess.run([node, '-e', 'global.document={};\n' + script], capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_real_server_hook_and_offline_run(self):
        from run import create_server
        with contextlib.ExitStack() as cleanup:
            temporary = Scratch()
            cleanup.callback(temporary.cleanup)
            scratch = temporary.path
            server = create_server('127.0.0.1', 0, sample=True, registry_path=scratch / 'events.jsonl')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
            try:
                for path in ('/', '/v2', '/v2/map/style.json'):
                    connection.request('GET', path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200, path)
                    self.assertTrue(response.read())
                # Real regex baseline and backend screening, with test-only event log.
                payload = {'replay_time': '2024-05-08T18:00:00-03:00', 'messages': [
                    {'text': 'Somos 3 pessoas na Rua dos Andradas, 120, Porto Alegre. Precisamos de resgate.'}]}
                with patch('app.pipeline.ROOT', scratch), contextlib.redirect_stdout(io.StringIO()):
                    connection.request('POST', '/run', json.dumps(payload), {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    cases = json.loads(response.read())['cases']
                self.assertEqual(len(cases), 1)
                self.assertIn('fleet', cases[0])
                connection.request('GET', '/api/cases')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())['cases'][0]['case_id'], cases[0]['case_id'])
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(5)


if __name__ == '__main__':
    unittest.main()
