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
        full_source = (routes_v2.UI / 'app.js').read_text(encoding='utf-8')
        source += full_source[full_source.index('function liveStep('):full_source.index('async function awaitRun(')]
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

const trace={version:4,agents:{intake:{fields:{people:{value:4},street:{value:'A'}}},critic:{objections:[{field:'people',reason:'citação diz três'}]},revision:{fields:{people:{value:3},street:{value:'A'}}}},calls:[{role:'intake',model:'winner',receipt:'r',status:'ok',seconds:.2}],hazard_check:'deterministic_only',hazard_review:'indisponível',errors:['hazard_critic_failed']};
assert.deepEqual(revisionChanges(trace).map(x=>x.field),['people']);
assert.deepEqual(flowSteps(trace).map(x=>x.role),['intake','critic','revision','location','streets','landmarks','flood','fleet','hazard_critic','duplicate_reviewer','world']);
assert.equal(flowSteps(trace).find(x=>x.role==='hazard_critic').status,'falhou');
const flow=agentFlow(trace);assert.equal(flow.children.length,12);
let rows=new Map();let live=liveStep({stage:'critic_started',role:'critic',case_id:'x'},rows);assert.equal(live.open,1);liveStep({stage:'critic_done',role:'critic',case_id:'x'},rows);assert.equal(live.open,0);liveStep({stage:'critic_started',role:'critic',case_id:'x'},rows);liveStep({stage:'error'},rows);assert.equal(live.open,0);
$('system-light').firstElementChild=new Element('strong');drawQueue();totals();assert.equal($('queue').children.length,1);


'''
        # Only lookup of $ is deferred; all assertions above are pure data logic.
        p = subprocess.run([node, '-'], input='global.document={};\n' + script, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_water_publication_gate_and_click_depth(self):
        manifest = json.loads((routes_v2.MAP/'water/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['bands']), 4)
        self.assertTrue(manifest['bands'][2]['upper_inclusive'])
        self.assertEqual(manifest['bands'][3]['label'], '> 2,5 m')
        # Same rule as app/geo/depth.py: retrospective grid by observation date <= replay, always flagged retrospective.
        expect={'2024-05-05':None,'2024-05-06':'2024-05-06','2024-05-07':'2024-05-06','2024-05-08':'2024-05-08'}
        for day,obs in expect.items():
            status, _, body = self.get('/api/water?date='+day)
            self.assertEqual(status, 200)
            data=json.loads(body)
            self.assertEqual(data['image'] and data['image']['observation_date'], obs)
            self.assertTrue(data['retrospective'])
        fixture = {**manifest, 'images':[{**x, 'published_at':'2024-06-12'} for x in manifest['images']]}
        # Future-observed entries never leak.
        with patch('app.web.routes_v2.json.loads', return_value={'images':[{'observation_date':'2024-07-01','published_at':'2024-06-01'}]}):
            self.assertIsNone(routes_v2.water_data('2024-06-12')['image'])
        for entry in manifest['images']:
            status, headers, body = self.get(entry['url'])
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'image/png')
            self.assertEqual(body[:8], b'\x89PNG\r\n\x1a\n')
            self.assertLessEqual(len(body), 3_000_000)
            self.assertEqual(len(body), entry['bytes'])
        for query in ('', '?date=oops', '?date=2024-05-08&date=2024-06-12'):
            self.assertEqual(self.get('/api/water'+query)[0],400)
        payload = json.loads(self.get('/api/depth?date=2024-05-08&lon=-51.21&lat=-30.01')[2])
        self.assertTrue(payload['point']['depth_retrospective'])
        self.assertEqual(payload['point']['depth_observed_date'],'2024-05-08')
        with patch.object(routes_v2,'water_data',return_value={'image':fixture['images'][-1]}):
            payload = json.loads(self.get('/api/depth?date=2024-06-12&lon=-51.21&lat=-30.01')[2])
        self.assertIn('depth_band', payload['point'])
        self.assertEqual(payload['published_at'],'2024-06-12')

    def test_photos_fixture_dates_distance_and_absence(self):
        with contextlib.ExitStack() as cleanup:
            scratch = Scratch()
            cleanup.callback(scratch.cleanup)
            root = scratch.path
            (root/'data/photos').mkdir(parents=True)
            csv = root/'data/photos/photos.csv'
            csv.write_text('id,lon,lat,taken_at,author,license,source_url,thumb\n'
                           'past,-51.21,-30.01,2024-05-06T12:00:00-03:00,A,CC BY,https://example.test/a,/v2/photos/a.jpg\n'
                           'future,-51.21,-30.01,2024-05-09T12:00:00-03:00,B,CC0,https://example.test/b,/v2/photos/b.jpg\n',encoding='utf-8')
            with patch.object(routes_v2,'ROOT',root):
                data = json.loads(self.get('/api/photos?date=2024-05-08&lon=-51.21&lat=-30.01')[2])
                self.assertTrue(data['available'])
                self.assertEqual([p['id'] for p in data['photos']],['past'])
                self.assertEqual(data['photos'][0]['license'],'CC BY')
                data = json.loads(self.get('/api/photos?date=2024-05-09&lon=-51.21&lat=-30.01')[2])
                self.assertEqual(len(data['photos']),2)
                self.assertEqual(json.loads(self.get('/api/photos?date=2024-05-09&lon=0&lat=0')[2])['photos'],[])
                csv.unlink()
                self.assertFalse(json.loads(self.get('/api/photos?date=2024-05-08&lon=0&lat=0')[2])['available'])
        for query in ('', '?date=2024-05-08&lon=nan&lat=0','?date=2024-05-08&lon=0&lat=91'):
            self.assertEqual(self.get('/api/photos'+query)[0],400)

    def test_bilinear_water_does_not_colour_unknown(self):
        from tools.prepare_water_tiles import rgba
        from app.geo.depth import DepthGrid, utm22s_to_lonlat
        import struct
        grid = DepthGrid({'width':2,'height':2,'pixel_m':20,'origin_x':480000,'origin_y':6680000},
                         struct.pack('<HHHH',100,65535,100,65535))
        self.assertEqual(rgba(grid,*utm22s_to_lonlat(480030,6679990)),b'\0\0\0\0')
        self.assertGreater(rgba(grid,*utm22s_to_lonlat(480010,6679990))[3],200)
        self.assertLess(rgba(grid,*utm22s_to_lonlat(480019,6679990))[3],220)
        constant = DepthGrid(grid.h, struct.pack('<HHHH',250,250,250,250))
        self.assertEqual(rgba(constant,*utm22s_to_lonlat(480020,6679980))[:3], bytes.fromhex('398ac1'))

    def test_map_date_cache_pan_and_rendering_contract(self):
        node = shutil.which('node.exe') or shutil.which('node')
        if not node:
            self.skipTest('Node local não encontrado')
        script = r"""
const assert=require('assert'),fs=require('fs'),vm=require('vm');
let requests=[];const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{checked:false,hidden:false,textContent:'',getAttribute:()=> 'false',getBoundingClientRect:()=>({width:0,height:0}),replaceChildren(){},append(){}});return nodes.get(id);}
const document={getElementById:node,createElement:()=>({style:{},append(){}})};
const payload={image:{url:'/v2/map/water/2024-05-08.png',coordinates:[[0,1],[1,1],[1,0],[0,0]]},bands:[],missing:'unknown',note:'test'};
const context={document,window:{devicePixelRatio:2,innerWidth:1920},location:{search:''},performance,console,URLSearchParams,setTimeout,clearTimeout,AbortController,fetch:async(url)=>{requests.push(url);return {ok:true,json:async()=>payload};}};
context.window.window=context.window;
let source=fs.readFileSync(process.argv[1],'utf8').replace('return {init,update,focus,resize,',`return {test:{onMoveEnd,loadWater,loadBuildings,visibility,featureInView,install:(m,d)=>{gl=m;loaded=true;data=d;},terrain:()=>terrainEnabled},init,update,focus,resize,`);
vm.runInNewContext(source,context);const desk=context.window.DeskMap,t=desk.test;
const sources=new Map(),layers=[],layout={};let terrain;
const m={getLayer:id=>layers.find(l=>l.id===id),removeLayer:id=>layers.splice(layers.findIndex(l=>l.id===id),1),removeSource:id=>sources.delete(id),addSource:(id,s)=>sources.set(id,s),addLayer:l=>layers.push(l),getBounds:()=>({getWest:()=>-51.22,getSouth:()=>-30.02,getEast:()=>-51.20,getNorth:()=>-30}),getZoom:()=>14,getStyle:()=>({layers}),getSource:n=>sources.get(n)||{setData(){}},setLayoutProperty:(id,k,v)=>layout[id]=v,setTerrain:v=>terrain=v};
t.install(m,{layers:{},cases:[]});
(async()=>{await t.loadWater();assert.equal(requests.length,1);await t.loadWater();assert.equal(requests.length,1);assert.equal(sources.get('water').type,'image');assert.equal(layers[0].paint['raster-opacity'],.5);assert.equal(layers[0].paint['raster-resampling'],'linear');assert.equal(terrain,null);
for(let i=0;i<30;i++)t.onMoveEnd();await new Promise(r=>setTimeout(r,380));assert.equal(requests.length,1,'pan must not request water, depth, or buildings in 2D');assert.ok(!requests.some(u=>u.includes('/api/depth')));assert.equal(t.terrain(),false);
const inside={geometry:{type:'Polygon',coordinates:[[[-51.215,-30.015],[-51.205,-30.015],[-51.205,-30.005],[-51.215,-30.015]]]}};assert.ok(t.featureInView(inside,[-51.22,-30.02,-51.20,-30]));assert.ok(!t.featureInView(inside,[0,0,1,1]));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        p = subprocess.run([node, '-e', script, str(routes_v2.UI/'map.js')],capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)

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
