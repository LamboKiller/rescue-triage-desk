"""Real-data date isolation, geometry, pipeline and HTTP map contracts."""
import csv
import gzip
import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from app.geo.hazards import (STREET_POSITION, PolygonIndex, assess, attach, get_data,
                             map_data, ring_contains)
from app.data.source import LocalSource, ZetarisSource
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline
from run import create_server
from support import Scratch


class HazardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=get_data()
        from app.geo.landmarks import match
        source=LocalSource()
        cls.station=match(source.landmarks(),place_name='rodoviaria',landmark_quote='rodoviaria de porto alegre',
                          municipality='Porto Alegre',message='socorro dentro da rodoviaria de porto alegre',
                          streets=source.streets())['matched']

    def point(self,day,excluded=None):
        index=self.data.indices[day]
        for f in self.data.flood[day]:
            for poly in f['geometry']['coordinates']:
                ring=poly[0];xs,ys=zip(*ring)
                candidates=[(sum(ys)/len(ys),sum(xs)/len(xs)),((min(ys)+max(ys))/2,(min(xs)+max(xs))/2)]
                for lat,lon in candidates:
                    if index.contains(lat,lon) and (excluded is None or not self.data.indices[excluded].contains(lat,lon)):
                        return lat,lon
        self.fail('No real polygon test point found')

    def test_inside_real_may6_and_no_observation_before(self):
        lat,lon=self.point('2024-05-06')
        self.assertTrue(assess(lat,lon,'2024-05-06','landmark')['in_flood_any'])
        self.assertIsNone(assess(lat,lon,'2024-05-05','landmark')['in_flood_any'])

    def test_may8_only_extent_not_backdated(self):
        lat,lon=self.point('2024-05-08','2024-05-06')
        self.assertTrue(assess(lat,lon,'2024-05-08','landmark')['in_flood_any'])
        older=assess(lat,lon,'2024-05-06','landmark')
        self.assertFalse(older['in_flood_any'])
        self.assertEqual(set(older['flood_by_date']),{'2024-05-06'})

    def test_rodoviaria_both_dates_facts_and_depth(self):
        outputs=[]
        for day in ('2024-05-06','2024-05-08'):
            a=assess(float(self.station['lat']),float(self.station['lon']),day,'landmark');outputs.append(a)
            self.assertIn(day,a['flood_by_date'])
            self.assertIn('EMSN194',a['depth_source'])
            self.assertIn(a['depth_status'],('estimada','desconhecida'))
            self.assertTrue(all(set(f)=={'id','text_pt','source'} and f['source'] for f in a['facts']))
            self.assertEqual(a,assess(float(self.station['lat']),float(self.station['lon']),day,'landmark'))
        self.assertTrue(outputs[0]['in_flood_any'])
        # Different coverage must not be interpreted as recession or safety.
        self.assertTrue(outputs[1]['flood_by_date']['2024-05-06'])
        self.assertTrue(outputs[1]['in_flood_any'])

    def test_closure_publication_and_active_interval(self):
        for day in ('2024-05-02','2024-05-06','2024-05-08'):
            _,layers=self.data.dated_layers(day)
            for f in layers['closures']:
                p=f['properties'];self.assertLessEqual(p['source_published_at'][:10],day)
                self.assertLessEqual(p['from_date'],day)
                if p['to_date']: self.assertGreaterEqual(p['to_date'],day)
        late=next(f for f in self.data.layers['closures'] if f['properties']['source_published_at'][:10]>'2024-05-06')
        _,layers=self.data.dated_layers('2024-05-06')
        self.assertNotIn(late['id'],[f['id'] for f in layers['closures']])

    def test_shelters_no_hindsight_and_top3(self):
        self.assertEqual(map_data('2024-05-06')['layers']['shelters']['features'],[])
        self.assertEqual(assess(-30.02,-51.22,'2024-05-06','landmark')['nearest_shelters'],[])
        for day in ('2024-05-08','2024-05-10','2024-05-24'):
            a=assess(-30.02,-51.22,day,'landmark')
            self.assertLessEqual(len(a['nearest_shelters']),3)
            if day=='2024-05-10': self.assertEqual(len(a['nearest_shelters']),3)
            self.assertEqual([s['distance_km'] for s in a['nearest_shelters']], sorted(s['distance_km'] for s in a['nearest_shelters']))
            for s in a['nearest_shelters']:
                self.assertLessEqual(s['snapshot_local'][:10],day)
                self.assertGreater(float(s['vacancies']),0)
                self.assertEqual(s['distance_label'],'straight-line, not a route')

    def test_pump_apurar_unknown_exact_day(self):
        _,layers=self.data.dated_layers('2024-05-06')
        pump=next(f for f in layers['pumps'] if f['properties']['source_status']=='APURAR')
        lon,lat=pump['geometry']['coordinates']
        a=assess(lat,lon,'2024-05-06','landmark')
        r=next(r for r in a['pumps_nearby'] if r['id']==pump['id'])
        self.assertEqual(r['status'],'unknown')
        self.assertTrue(all(r['status']=='unknown' for r in assess(lat,lon,'2024-05-27','landmark')['pumps_nearby']))

    def test_street_median_vertex_and_null_position(self):
        point=self.data.street_point('Avenida Farrapos','Porto Alegre')
        self.assertIsNotNone(point)
        case={'fields':{'street':{'value':'Avenida Farrapos'},'municipality':{'value':'Porto Alegre'},'number':{'value':'120'}},
              'checks':{'found':True},'replay_time':'2024-05-08T14:00:00-03:00'}
        attach(case)
        self.assertEqual(case['position']['position_kind'],STREET_POSITION)
        self.assertEqual(case['position']['lat'],float(point['lat']))
        empty={'replay_time':case['replay_time']};attach(empty)
        self.assertIsNone(empty['hazards']);self.assertTrue(empty['hazards_reason'])

    def test_grid_holes_and_boundaries(self):
        g={'type':'Polygon','coordinates':[[[0,0],[.1,0],[.1,.1],[0,.1],[0,0]],[[.04,.04],[.06,.04],[.06,.06],[.04,.06],[.04,.04]]]}
        idx=PolygonIndex([{'geometry':g}])
        self.assertTrue(idx.contains(.02,.02));self.assertFalse(idx.contains(.05,.05))
        self.assertTrue(idx.contains(.0,.05));self.assertFalse(idx.contains(.2,.2))

    def test_events_no_hindsight(self):
        for day in ('2024-05-02','2024-05-06','2024-05-08'):
            for f in map_data(day)['layers']['events']['features']:
                self.assertLessEqual(f['properties']['published_at'][:10],day)
                self.assertLessEqual(f['properties']['observed_at'][:10],day)

    def test_assessment_warm_budget(self):
        start=time.perf_counter()
        for _ in range(10): assess(-30.022194,-51.2198891,'2024-05-08','landmark')
        self.assertLess((time.perf_counter()-start)/10,.3)

    def test_local_and_zetaris_tables_null_contract(self):
        for name in ('closures','pump_status_daily','pumps','events','shelters','street_points'):
            rows=getattr(LocalSource(),name)();self.assertTrue(rows)
            with patch('app.data.source.Zetaris') as z:
                z.return_value.rows.return_value=[{'a':None,'b':4}]
                self.assertEqual(getattr(ZetarisSource(),name)(),[{'a':'','b':'4'}])

    def test_data_size_and_manifest(self):
        root=self.data.root
        self.assertLessEqual(sum(p.stat().st_size for p in root.iterdir() if p.is_file()),15_000_000)
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        for s in manifest['sources'].values(): self.assertEqual(len(s['sha256']),64)
        for name,info in manifest['outputs'].items():self.assertEqual((root/name).stat().st_size,info['bytes'])

    def test_map_filters_case_history(self):
        base={'fields':{},'result':{'decision':'REVIEW_REQUIRED','priority':0},'replay_time':'2024-05-06T14:00:00-03:00','received_at':'2024-05-06T12:00:00-03:00'}
        future={**base,'replay_time':'2024-05-08T14:00:00-03:00','received_at':'2024-05-08T12:00:00-03:00','result':{'decision':'ASK_FOR_INFO','priority':5}}
        case={**future,'case_id':'history','facts':[base,future]}
        self.assertEqual(map_data('2024-05-06',[case])['cases'][0]['decision'],'REVIEW_REQUIRED')
        self.assertEqual(map_data('2024-05-05',[case])['cases'],[])
        self.assertEqual(map_data('2024-05-08',[case])['cases'][0]['decision'],'ASK_FOR_INFO')

    def test_http_map_date_gzip_size_and_pipeline(self):
        scratch=Scratch();self.addCleanup(scratch.cleanup)
        registry=Registry(Path(scratch.name)/'events.jsonl');pipeline=Pipeline(registry,sample=True)
        request={'replay_time':'2024-05-08T14:00:00-03:00','messages':[{'message_id':'hazard-test','text':'3 pessoas na Avenida Farrapos, número 120, Porto Alegre. socorro'}]}
        with redirect_stdout(io.StringIO()):case=pipeline.run(request)['cases'][0]
        self.assertIsNotNone(case['hazards'])
        server=create_server('127.0.0.1',0,pipeline=pipeline,sample=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)+'/api/map'
        counts=[]
        for day in ('2024-05-06','2024-05-08'):
            with urllib.request.urlopen(base+'?date='+day) as response:
                body=response.read();self.assertLess(len(body),6_000_000);data=json.loads(body)
            counts.append({k:len(v['features']) for k,v in data['layers'].items()})
            req=urllib.request.Request(base+'?date='+day,headers={'Accept-Encoding':'gzip'})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.headers['Content-Encoding'],'gzip')
                self.assertEqual(gzip.decompress(response.read()),body)
        self.assertNotEqual(counts[0],counts[1])
        for query in ('','?date=bad','?date=2024-02-30','?date=2024-05-06&date=2024-05-08'):
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(base+query)
            self.assertEqual(error.exception.code,400)
        with urllib.request.urlopen(urllib.request.Request(base+'?date=2024-05-08',headers={'Accept-Encoding':'gzip;q=0'})) as response:
            self.assertIsNone(response.headers.get('Content-Encoding'))

if __name__=='__main__':unittest.main()
