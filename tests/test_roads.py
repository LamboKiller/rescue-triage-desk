"""Offline graph, no-data, provenance, launch and closure regressions."""
import gzip
import json
import math
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from app.geo import roads
from app.geo.depth import DepthGrid, lonlat_to_utm22s
from tools import prepare_roads as prep

FIXTURE = Path(__file__).parent/'fixtures/roads_osm.json'
DAY = '2024-05-06'


class Grid:
    h = {'pixel_m':20}

    def nearest(self,lon,lat,radius):
        return {'depth_m':0 if lon < -50.9997 else .8}


class RoadTests(unittest.TestCase):
    def graph(self):
        return prep.build_graph(json.loads(FIXTURE.read_text()),'Test City')

    def water(self, graph, grid=None):
        sampled = {}
        for e in graph['edges']:
            summary,points,values = prep.sample_depth(e['polyline'], grid or Grid(), DAY)
            e['depth'][DAY] = summary
            sampled[e['id']] = points,values
        return sampled

    def test_topology_and_attributes(self):
        g = self.graph()
        self.assertEqual(len(g['edges']),3)
        self.assertEqual(set(g['nodes']),{'1','2','4','5'})
        self.assertEqual(g['edges'][1]['oneway'],'-1')
        self.assertEqual(g['edges'][1]['surface'],'asphalt')
        self.assertEqual(len(g['edges'][1]['polyline']),3)
        self.assertGreater(g['edges'][1]['length_m'],30)

    def test_grade_separated_crossings_not_connected(self):
        payload = json.loads(FIXTURE.read_text())
        payload['elements'].append({'type':'way','id':50,'nodes':[50,51],
            'geometry':[{'lon':-50.9998,'lat':-30},{'lon':-50.9998,'lat':-30.001}],
            'tags':{'highway':'primary','bridge':'yes'}})
        graph = prep.build_graph(payload,'Test City')
        self.assertIn('50',graph['nodes'])
        self.assertNotEqual(graph['edges'][-1]['u'],'2')

    def test_access_override_and_incomplete_response(self):
        payload = json.loads(FIXTURE.read_text())
        payload['elements'][-1]['tags']['motor_vehicle'] = 'yes'
        self.assertEqual(len(prep.build_graph(payload,'Test City')['edges']),4)
        payload['elements'][0]['geometry'] = []
        with self.assertRaises(ValueError):
            prep.build_graph(payload,'Test City')

    def test_sampling_interval(self):
        points = prep.samples([[-51,-30],[-51.003,-30],[-51.003,-30.003]])
        self.assertTrue(all(prep.distance(a,b)<=25.001 for a,b in zip(points,points[1:])))

    def test_unknown_existing_depth_reader(self):
        x,y = lonlat_to_utm22s(-51,-30)
        h = {'width':1,'height':1,'pixel_m':20,'origin_x':x-10,'origin_y':y+10}
        grid = DepthGrid(h,struct.pack('<H',65535))
        summary,_,values = prep.sample_depth([[-51,-30],[-51,-30.00001]],grid,DAY)
        self.assertIsNone(summary['max_depth_m'])
        self.assertEqual(summary['unknown_fraction'],1)
        self.assertEqual(summary['wet_fraction'],0)
        self.assertTrue(all(v is None for v in values))
        self.assertEqual(summary['kind'],'retrospective')
        self.assertEqual(summary['observation_date'],DAY)
        dry = DepthGrid(h,struct.pack('<H',0))
        self.assertEqual(prep.sample_depth([[-51,-30]],dry,DAY)[0]['unknown_fraction'],0)

    def test_launch_and_unknown_gap(self):
        g = self.graph()
        sampled = self.water(g)
        points = prep.detect_launches(g,DAY,sampled)
        self.assertEqual(len(points),1)  # Nearby entrances cluster within 150m.
        p = points[0]
        self.assertEqual(p['dry_side_node_id'],'2')
        self.assertEqual(p['label'],prep.LABEL)
        self.assertEqual(p['depth_beyond_m'],.8)
        for edge in g['edges']:
            coords,values = sampled[edge['id']]
            sampled[edge['id']] = coords,[None]*len(values)
        self.assertEqual(prep.detect_launches(g,DAY,sampled),[])
        e = g['edges'][1]
        g['edges'] = [e]
        self.assertEqual(prep.detect_launches(g,DAY,{e['id']:(e['polyline'],[0,None,.8])}),[])

    def test_mixed_unknown_depth_not_zero(self):
        grid = Grid()
        with patch.object(grid,'nearest',side_effect=[{'depth_m':None},{'depth_m':0},{'depth_m':.8}]):
            summary,_,_ = prep.sample_depth([[-51,-30],[-50.9998,-30],[-50.9996,-30]],grid,DAY)
        self.assertEqual(summary['max_depth_m'],.8)
        self.assertAlmostEqual(summary['wet_fraction'],1/3,places=6)
        self.assertAlmostEqual(summary['unknown_fraction'],1/3,places=6)

    def test_unnamed_launch_uses_nearest_named_street(self):
        g = self.graph()
        g['edges'][0]['name'] = None
        g['edges'][1]['name'] = None
        points = prep.detect_launches(g,DAY,self.water(g))
        self.assertEqual(points[0]['nearest_street_name'],'Acesso')
        self.assertEqual(points[0]['street_name_distance_m'],0)

    def test_closure_join_scope_dates_and_source(self):
        g = self.graph()
        rows = [dict(record_id='a',road='Rua Teste',municipality='Test City',status='closed',
                     from_date=DAY,to_date='2024-05-07',source_published_at=DAY),
                dict(record_id='b',road='Rua Teste',municipality='Other',status='closed'),
                dict(record_id='c',road='Rua Teste',municipality='Test City',status='reopened',from_date=DAY),
                dict(record_id='d',road='Rua Teste',municipality='Test City',status='closed',
                     from_date=DAY,source_published_at='2024-06-07')]
        report = prep.join_closures([g],rows)
        self.assertEqual(report['unmatched'],['b'])
        self.assertEqual(g['edges'][0]['closed_dates'],[DAY])
        self.assertEqual(g['edges'][1]['closed_dates'],[DAY])
        self.assertEqual(g['edges'][2]['closed_dates'],[])

    def test_closure_nearest_segment_not_vertex(self):
        g = self.graph()
        e = g['edges'][0]
        e['polyline'] = [[-51.002,-30],[-50.998,-30]]
        self.assertLess(prep.point_edge_distance((-50.9999,-30),e),1)
        rows = [dict(record_id='near',lon=-50.9999,lat=-30,status='closed',from_date=DAY,
                     source_published_at=DAY),dict(record_id='far',lon=-52,lat=-31)]
        result = prep.join_closures([g],rows)
        self.assertEqual(result['matched'],['near'])
        self.assertEqual(result['unmatched'],['far'])

    def test_loader_cache_lookup_and_replay(self):
        g = self.graph()
        points = prep.detect_launches(g,DAY,self.water(g))
        doc = dict(schema_version=1,coordinate_order='lon,lat',graphs=[g],
                   launch_points={DAY:points,'2024-05-08':[]})
        path = FIXTURE.with_name('roads_graph.json.gz')
        with patch.object(Path,'read_bytes',return_value=gzip.compress(json.dumps(doc).encode())):
            net = roads.load(path)
            self.assertIs(net,roads.load(path))
            self.assertEqual(net.nearest_node(-30,-51)['id'],'1')
            self.assertEqual(len(net.edges_near(-30,-51,1)),1)
            self.assertEqual(net.launch_points('2024-05-05'),[])
            self.assertEqual(len(net.launch_points('2024-05-07')),1)
            self.assertEqual(net.launch_points('2024-05-08'),[])
            with patch.object(roads,'load',return_value=net):
                self.assertEqual(roads.nearest_node(-30,-51)['id'],'1')
                self.assertEqual(len(roads.edges_near(-30,-51,1)),1)
                self.assertEqual(roads.launch_points('2024-05-08'),[])
            for lat,lon in [(math.nan,-51),(-91,-51),(0,181)]:
                with self.assertRaises(ValueError):
                    net.nearest_node(lat,lon)
            with self.assertRaises(ValueError):
                net.launch_points('2024-5-6')
        roads.load.cache_clear()

    def test_reproducible_gzip(self):
        with patch.object(Path,'write_bytes') as write:
            a,b = Path('roads_a.gz'),Path('roads_b.gz')
            prep.dump_gzip(a,{'a':1})
            prep.dump_gzip(b,{'a':1})
            self.assertEqual(write.call_args_list[0].args,write.call_args_list[1].args)

    def test_json_fixture_loader(self):
        net = roads.load(FIXTURE.with_name('roads_graph.json'))
        self.assertEqual(net.nearest_node(-30,-51)['id'],'1')
        self.assertEqual(len(net.edges),3)

    def test_shipped_size_and_integrity(self):
        folder = prep.ROOT/'data/roads'
        self.assertTrue((folder/'graph.json.gz').exists())
        self.assertLessEqual(sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),20_000_000)
        net = roads.load()
        self.assertTrue(net.edges)
        self.assertEqual(len(net.document['graphs']),6)
        for graph in net.document['graphs']:
            self.assertTrue(graph['nodes'])
            if graph['synthetic_node_ids']:
                self.assertFalse(graph['routing_eligible'])
                self.assertTrue(all(n.startswith('derived:') for n in graph['nodes']))
            for e in graph['edges']:
                self.assertEqual(e['routing_eligible'],graph['routing_eligible'])
                self.assertIn(e['u'],graph['nodes'])
                self.assertIn(e['v'],graph['nodes'])
                for day in prep.DATES:
                    s = e['depth'][day]
                    self.assertLessEqual(s['wet_fraction']+s['unknown_fraction'],1.000001)
                    self.assertEqual(s['observation_date'],day)
                    self.assertEqual(s['kind'],'retrospective')


if __name__ == '__main__':
    unittest.main()
