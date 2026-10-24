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

    def test_vendored_plex_fonts(self):
        fonts = list((routes_v2.UI / 'vendor/fonts').glob('*.woff2'))
        self.assertEqual(len(fonts), 7)
        for font in fonts:
            status, headers, body = self.get('/v2/vendor/fonts/' + font.name)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'font/woff2')
            self.assertEqual(body[:4], b'wOF2')
        self.assertEqual(self.get('/v2/vendor/fonts/OFL.txt')[0], 200)

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
        self.assertLessEqual(ui, 180000)
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
c.status='proposed';c.result.priority=0;c.text='Bebê no telhado; água subindo';assert.equal(priority(c),1);assert.equal(safetyFlags(c).length,3);
c.text='';c.result.priority=18;assert.equal(priority(c),2);
S.cases=[{case_id:'new',received_at:'2024-05-08T12:00:00-03:00',result:{priority:18}}, {case_id:'old',received_at:'2024-05-08T11:00:00-03:00',result:{priority:18}}];assert.equal(sorted()[0].case_id,'old');
// Render every incident tab with a small DOM implementation to catch integration errors.
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';this.classList={toggle(){},remove(){},add(){}};}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 setAttribute(k,v){this[k]=v;}
 contains(){return false;}
 querySelector(){return null;}
 cloneNode(){return this;}
 focus(){} scrollIntoView(){}
}
const nodes=new Map();global.document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);},createElement:tag=>new Element(tag),createTextNode:t=>({textContent:t})};
$('date').value='2024-05-08';$('search').value='';
S.cases=[{case_id:'render',version:1,status:'proposed',received_at:'2024-05-08T12:00:00-03:00',replay_time:'2024-05-08T18:00:00-03:00',text:'Bebê no telhado',location_confirmed:true,fields:{people:{value:3}},result:{priority:18,decision:'SEND_CANDIDATE',questions:[]},fleet:[{asset:'boat',label_pt:'Barco',verdict:'caution',reasons_pt:['Equipe treinada']}],calls:[{role:'intake',model:'local',seconds:1,receipt:'r'}]}];S.selected='render';
for(const name of ['Resumo','Meios','Mensagens','Agentes','Histórico']){S.tab=name;drawCase();assert.ok($('case').children.length>=5,name);}
$('system-light').firstElementChild=new Element('strong');drawQueue();totals();assert.equal($('queue').children.length,1);


'''
        # Only lookup of $ is deferred; all assertions above are pure data logic.
        p = subprocess.run([node, '-'], input='global.document={};\n' + script, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_map_viewport_cache_and_rendering_contract(self):
        node = shutil.which('node.exe') or shutil.which('node')
        if not node:
            self.skipTest('Node local não encontrado')
        script = r"""
const assert=require('assert'),fs=require('fs'),vm=require('vm');
let requests=0,abortCount=0;
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{checked:false,hidden:false,textContent:'',getAttribute:()=> 'false',getBoundingClientRect:()=>({width:0,height:0})});return nodes.get(id);}
const document={getElementById:node};
const context={document,window:{devicePixelRatio:2,innerWidth:1920},location:{search:''},performance,console,URLSearchParams,setTimeout,clearTimeout,AbortController,fetch:async(url,opts)=>{requests++;if(opts?.signal)opts.signal.addEventListener('abort',()=>abortCount++);return {ok:true,json:async()=>({cells:[[-51.21,-30.01,'d_1_2_to_2_5',1.5]],source:'test'})};}};
context.window.window=context.window;
let source=fs.readFileSync(process.argv[1],'utf8').replace('return {init,update,focus,resize,',`return {test:{makeCells,tileBounds,viewTiles,loadDepth,scheduleDepth,loadBuildings,visibility,featureInView,install:(m,d)=>{gl=m;loaded=true;data=d;},geo:()=>depthGeo,terrain:()=>terrainEnabled},init,update,focus,resize,`);
vm.runInNewContext(source,context);const desk=context.window.DeskMap,t=desk.test;
assert.equal(t.terrain(),false);
const sources=new Map(),layout={};let terrain;
const layers=[{id:'desk-depth-fill-extrusion',metadata:{deskLayer:'depth'}},{id:'desk-depth-known',metadata:{deskLayer:'depth'}},{id:'desk-flood-fill',metadata:{deskLayer:'flood'}}];
const m={getBounds:()=>({getWest:()=>-51.22,getSouth:()=>-30.02,getEast:()=>-51.20,getNorth:()=>-30}),getZoom:()=>14,getStyle:()=>({layers}),getSource:n=>({setData:d=>sources.set(n,d)}),setLayoutProperty:(id,k,v)=>layout[id]=v,setTerrain:v=>terrain=v};
t.install(m,{layers:{},cases:[]});
(async()=>{await t.loadDepth();const first=requests;assert.ok(first>0);await t.loadDepth();assert.equal(requests,first,'same date+tiles must use cache');
assert.ok(t.geo().features.length>1);assert.equal(layout['desk-flood-fill'],'none');assert.equal(layout['desk-depth-known'],'visible');assert.equal(layout['desk-depth-fill-extrusion'],'none');assert.equal(terrain,null);
const cells=t.makeCells({cells:[[-51.21,-30.01,'d_1_2_to_2_5',1.5],[-51.21,-30.01,'d_1_2_to_2_5',1.5]]},[-51.22,-30.02,-51.20,-30]);const keys=cells.features.map(f=>JSON.stringify(f.geometry.coordinates));assert.equal(new Set(keys).size,keys.length,'unknown and known cells cannot overlap');
assert.ok(sources.get('depth3d').features.length<=4000);
node('light').checked=true;await t.loadBuildings();assert.equal(sources.get('buildings').features.length,0);
for(let i=0;i<10;i++)t.scheduleDepth();assert.equal(requests,first,'move must debounce fetches');await new Promise(r=>setTimeout(r,350));assert.equal(requests,first,'debounced fetches reuse cache');assert.ok(abortCount>0);
const inside={geometry:{type:'Polygon',coordinates:[[[-51.215,-30.015],[-51.205,-30.015],[-51.205,-30.005],[-51.215,-30.015]]]}};assert.ok(t.featureInView(inside,[-51.22,-30.02,-51.20,-30]));assert.ok(!t.featureInView(inside,[0,0,1,1]));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        p = subprocess.run([node, '-e', script, str(routes_v2.UI / 'map.js')],
                           capture_output=True, text=True, timeout=20)
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
