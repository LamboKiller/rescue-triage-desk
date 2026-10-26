"""Routing safety regressions on a hand-checked directed graph."""
import copy
import unittest
from unittest.mock import patch
from app.geo.roads import RoadNetwork
try:
    from app.geo.routing import Router, FleetDistance, water_leg, edge_reasons
except ImportError:
    Router = FleetDistance = water_leg = edge_reasons = None

DAY = '2024-05-06'
TRUCK = {'type': 'caminhao_alto', 'max_wading_depth_m': .6}


def network():
    nodes = {'a': [-51, -30], 'b': [-50.999, -30], 'c': [-50.999, -29.999],
             'd': [-50.998, -30], 'island': [-50.99, -30]}
    edges = []
    for eid, u, v, length, value, one in [
        ('ab','a','b',100,0,'yes'), ('bd','b','d',100,0,'yes'),
        ('ac','a','c',200,0,'no'), ('cd','c','d',200,0,'no')]:
        edges.append(dict(id=eid,u=u,v=v,length_m=length,polyline=[nodes[u],nodes[v]],
            highway='residential',oneway=one,municipality='Test',depth={DAY:{
                'max_depth_m':value,'unknown_fraction':0,'observation_date':DAY,'kind':'retrospective'}},
            closed_dates=[],closure_matches=[],routing_eligible=True))
    return RoadNetwork(dict(schema_version=1,coordinate_order='lon,lat',graphs=[dict(
        municipality='Test',routing_eligible=True,nodes=nodes,edges=edges)], launch_points={DAY:[
            dict(dry_side_node_id='d',edge_id='wet',municipality='Test',lat=-30,lon=-50.998,
                 observation_date=DAY,kind='retrospective',routing_eligible=True,nearest_street_name='Ramp')]}))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Router, 'offline router must be implemented')
        self.net = network()

    def test_fastest_route_and_continuous_polyline(self):
        out = Router(self.net).route('a','d',TRUCK,DAY)
        self.assertTrue(out['reachable'])
        self.assertEqual(out['edge_ids'], ['ab','bd'])
        self.assertEqual(out['land_km'], .2)
        self.assertEqual(out['polyline'], [[-51,-30],[-50.999,-30],[-50.998,-30]])

    def test_closure_detours_and_cites_record(self):
        self.net.edges[1]['closure_matches']=[dict(record_id='closure-test',status='closed',from_date=DAY,to_date='2024-05-07')]
        r=Router(self.net)
        out=r.route('a','d',TRUCK,DAY)
        self.assertEqual(out['edge_ids'],['ac','cd'])
        self.assertIn('closure-test', str(out['blocked_edges']))
        self.assertEqual(r.route('a','d',TRUCK,'2024-05-08')['edge_ids'],['ab','bd'])

    def test_depth_and_partial_unknown_block(self):
        self.net.edges[1]['depth'][DAY]['max_depth_m']=1.4
        self.net.edges[3]['depth'][DAY]['unknown_fraction']=.2
        out=Router(self.net,allow_unknown=False).route('a','d',TRUCK,DAY)
        self.assertFalse(out['reachable'])
        self.assertEqual({x['code'] for x in out['blocked_edges']},{'WADING_LIMIT','DEPTH_UNKNOWN'})
        self.assertEqual(out['decision'],'REVIEW_REQUIRED')
        self.assertEqual(out['polyline'],[])

    def test_unknown_does_not_become_dry_before_observation(self):
        out=Router(self.net,allow_unknown=False).route('a','d',TRUCK,'2024-05-05')
        self.assertFalse(out['reachable'])
        self.assertIn('DEPTH_UNKNOWN',str(out['blocked_edges']))
        # default policy: usable only with a visible warning, never silently dry
        soft=Router(self.net).route('a','d',TRUCK,'2024-05-05')
        self.assertTrue(soft['reachable'])
        self.assertEqual(soft['unknown_edge_ids'],soft['edge_ids'])
        self.assertIn('trecho(s) sem dado',' '.join(soft['review_pt']))

    def test_oneway_reverse_and_missing_topology(self):
        self.net.edges=self.net.edges[:2]
        r=Router(self.net)
        self.assertFalse(r.route('d','a',TRUCK,DAY)['reachable'])
        self.assertFalse(r.route('a','island',TRUCK,DAY)['reachable'])
        self.assertFalse(r.route('a',{'lat':0,'lon':0},TRUCK,DAY)['reachable'])

    def test_reversed_oneway_and_private_access(self):
        self.net.edges=self.net.edges[:1]
        self.net.edges[0]['oneway']='-1'
        r=Router(self.net)
        self.assertTrue(r.route('b','a',TRUCK,DAY)['reachable'])
        self.assertFalse(r.route('a','b',TRUCK,DAY)['reachable'])
        self.net.edges[0]['motor_vehicle']='no'
        self.assertFalse(Router(self.net).route('b','a',TRUCK,DAY)['reachable'])

    def test_unknown_explicit_opt_in_is_flagged(self):
        for e in self.net.edges: e['depth']={}
        out=Router(self.net,allow_unknown=True).route('a','d',TRUCK,DAY)
        self.assertTrue(out['reachable'])
        self.assertEqual(out['decision'],'REVIEW_REQUIRED')
        self.assertTrue(out['unknown_edge_ids'])

    def test_boat_reaches_flooded_case_via_dry_launch(self):
        r=Router(self.net)
        with patch('app.geo.routing.depth.lookup',return_value={'depth_m':1.4,'depth_retrospective':True}):
            out=r.plan('a',{'lat':-30,'lon':-50.997},{'type':'barco_aluminio'},DAY)
        self.assertTrue(out['reachable'])
        self.assertEqual(out['launch_point']['node_id'],'d')
        self.assertEqual(out['water']['max_depth_m'],1.4)
        self.assertEqual(out['water']['label_pt'],'trecho na água em linha reta — estimativa')
        self.assertEqual(len(out['alternatives']),1)
        self.assertTrue(out['human_approval_required'])

    def test_water_unknown_samples_are_visible(self):
        with patch('app.geo.routing.depth.lookup',return_value={'depth_m':None}):
            out=water_leg({'lat':-30,'lon':-51},{'lat':-30,'lon':-50.999},DAY)
        self.assertIsNone(out['max_depth_m'])
        self.assertTrue(out['unknown_samples'])
        self.assertEqual(out['polyline'],[[-51,-30],[-50.999,-30]])

    def test_invalid_date_limit_and_routing_ineligible(self):
        r=Router(self.net)
        for day in ['bad','2024-5-6']:
            with self.assertRaises(ValueError): r.route('a','d',TRUCK,day)
        with self.assertRaises(ValueError): r.route('a','d',{'max_wading_depth_m':float('nan')},DAY)
        for e in self.net.edges: e['routing_eligible']=False
        self.assertFalse(Router(self.net).route('a','d',TRUCK,DAY)['reachable'])

    def test_fleet_adapter_preserves_unreachable(self):
        adapter=FleetDistance(DAY,Router(self.net))
        out=adapter.for_unit({'lat':0,'lon':0},{'lat':-30,'lon':-51},TRUCK)
        self.assertFalse(out['reachable'])
        self.assertIsNone(out['distance_m'])
        self.assertIsNone(out['eta_seconds'])

    def test_allocator_road_failure_falls_back_to_labelled_straight_line(self):
        from app.fleet.allocation import allocate
        from tests.test_allocation import case, unit
        adapter=FleetDistance('2024-05-08',Router(self.net))
        out=allocate(case(),[unit()], '2024-05-08', distance_fn=adapter)
        rows=out['top3']+out['ineligible']
        codes=[x['code'] for r in rows for x in r.get('confirmation_checklist',[])]
        self.assertIn('ROUTE_UNPROVEN',codes)  # "rota não comprovada" goes to the human checklist
        self.assertTrue(all('ROUTE_UNAVAILABLE' not in r.get('reason_codes',[]) for r in rows))  # never ineligible only for routing
        text=str(rows)
        self.assertIn('rota não comprovada',text)
        self.assertIn('linha reta',text)

    def test_adapter_budget_and_cache_bound_work(self):
        import app.geo.routing as rt
        calls=[]
        r=Router(self.net); real=r.plan
        r.plan=lambda *a:(calls.append(1),real(*a))[1]
        ad=FleetDistance(DAY,r); ad.BUDGET_S=0
        base={'lat':-30,'lon':-51};tgt={'lat':-30,'lon':-50.998}
        first=ad.for_unit(base,tgt,TRUCK)       # budget 0 -> never routes, labelled fallback
        self.assertEqual(calls,[]);self.assertFalse(first['reachable']);self.assertIn('não comprovada',first['basis_pt'])
        ad2=FleetDistance(DAY,r)
        ad2.for_unit(base,tgt,TRUCK);ad2.for_unit(base,tgt,TRUCK)
        FleetDistance(DAY,r).for_unit(base,tgt,TRUCK)
        self.assertEqual(len(calls),1)           # cached across calls and requests

    def test_landing_transfers_keep_failed_land_route_as_review(self):
        from app.geo.routing import landing_transfers
        rows=[dict(lat=-30,lon=-51,shelters=[dict(lat=0,lon=0,label='Shelter')],
                   warnings_pt=[],ambulance={'status':'draft'})]
        landing_transfers(rows,DAY,Router(self.net))
        self.assertFalse(rows[0]['shelters'][0]['land_route']['reachable'])
        self.assertIn('REVISAR',rows[0]['ambulance']['status'])


class StubExtent:
    """Observed-extent stand-in: edge id -> inside / outside / uncovered."""
    def __init__(self, table): self.table=table
    def classify(self, edge, day): return self.table.get(edge['id'],'uncovered'), '2024-05-06'


class ObservedExtentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.net=network()
        for e in self.net.edges: e['depth']={}  # HAND has no value anywhere

    def route(self, table, vehicle=TRUCK, **kw):
        return Router(self.net,extent=StubExtent(table),**kw).route('a','d',vehicle,DAY)

    def test_street_outside_observed_extent_is_dry_estimate_and_passable(self):
        out=self.route({e['id']:'outside' for e in self.net.edges},allow_unknown=False)
        self.assertTrue(out['reachable'])  # passable even under the strict-unknown policy
        self.assertEqual(out['dry_estimate_edge_ids'],out['edge_ids'])
        self.assertEqual(out['unknown_edge_ids'],[])
        self.assertIn('seco estimado: fora da mancha observada (Copernicus), retrospectivo',' '.join(out['review_pt']))
        self.assertEqual(out['confidence'],'low')

    def test_street_inside_extent_with_unknown_depth_is_blocked_for_truck(self):
        out=self.route({'ab':'inside','ac':'inside','bd':'outside','cd':'outside'})
        self.assertFalse(out['reachable'])
        self.assertEqual({x['code'] for x in out['blocked_edges']},{'WET_DEPTH_UNKNOWN'})

    def test_measured_1p2m_blocks_truck_but_not_vehicle_with_1p4_limit(self):
        for e in self.net.edges: e['depth']={DAY:{'max_depth_m':1.2,'unknown_fraction':0,'observation_date':DAY}}
        table={e['id']:'inside' for e in self.net.edges}
        out=self.route(table)
        self.assertFalse(out['reachable'])
        self.assertIn('WADING_LIMIT',str(out['blocked_edges']))
        ok=self.route(table,{'type':'anfibio','max_wading_depth_m':1.4})
        self.assertTrue(ok['reachable'])

    def test_street_without_any_layer_is_warned_and_penalised_not_dry(self):
        table={e['id']:'uncovered' for e in self.net.edges}
        out=self.route(table)
        self.assertTrue(out['reachable'])
        self.assertEqual(out['unknown_edge_ids'],out['edge_ids'])
        self.assertEqual(out['dry_estimate_edge_ids'],[])
        self.assertIn('trecho sem dado',' '.join(out['review_pt']))
        # 20x penalty: ETA is far above the dry-estimate route over the same streets
        dry=self.route({e['id']:'outside' for e in self.net.edges})
        self.assertGreater(out['land_eta_min'],10*dry['land_eta_min'])
        self.assertFalse(self.route(table,allow_unknown=False)['reachable'])

    def test_unknown_layer_prefers_detour_over_penalised_street(self):
        out=self.route({'ab':'uncovered','bd':'uncovered','ac':'outside','cd':'outside'})
        self.assertEqual(out['edge_ids'],['ac','cd'])

    def test_edge_reasons_state_labels(self):
        e=self.net.edges[0]
        self.assertEqual(edge_reasons(e,TRUCK,DAY,None,StubExtent({'ab':'outside'}))[1],'dry_estimate')
        self.assertEqual(edge_reasons(e,TRUCK,DAY,None,StubExtent({'ab':'inside'}))[1],'wet')
        self.assertEqual(edge_reasons(e,TRUCK,DAY,None,None)[1],'unknown')
        e['depth']={DAY:{'max_depth_m':0,'unknown_fraction':0,'observation_date':DAY}}
        self.assertEqual(edge_reasons(e,TRUCK,DAY,None,None)[1],'dry')


class ObservedExtentLayerTests(unittest.TestCase):
    def test_launch_frontier_uses_current_policy_without_crossing_wet_road(self):
        net=network()
        for e in net.edges: e['depth']={}
        extent=StubExtent({'ab':'outside','ac':'outside','bd':'inside','cd':'inside'})
        r=Router(net,extent=extent)
        target={'lat':-30,'lon':-50.997}
        out=r.plan('a',target,{'type':'bote_inflavel'},DAY)
        self.assertTrue(out['reachable'])
        self.assertIn(out['launch_point']['node_id'],('b','c'))
        self.assertTrue(out['launch_point']['derived'])
        self.assertEqual(out['launch_point']['observation_date'],DAY)
        self.assertTrue(set(out['land']['edge_ids']) <= {'ab','ac'})
        self.assertTrue(any('lançamento estimado' in s for s in out['review_pt']))
        later=r.plan('a',target,{'type':'bote_inflavel'},'2024-05-07')
        self.assertEqual(later['launch_point']['observation_date'],DAY)
        for e in net.edges:
            if e['id'] in ('bd','cd'): e['closed_dates']=[DAY]
        self.assertFalse(Router(net,extent=extent).plan('a',target,{'type':'bote_inflavel'},DAY)['reachable'])
        for e in net.edges: e['closed_dates']=[]
        for e in net.edges:
            if e['id'] in ('ab','ac'): e['closed_dates']=[DAY]
        self.assertFalse(Router(net,extent=extent).plan('a',target,{'type':'bote_inflavel'},DAY)['reachable'])
        self.assertFalse(Router(net,extent=StubExtent({'bd':'inside','cd':'inside'})).plan(
            'a',target,{'type':'bote_inflavel'},DAY)['reachable'])

    def test_future_wet_observation_cannot_create_launch_frontier(self):
        net=network();net.document['launch_points']={}
        for e in net.edges:
            e['depth']={'2024-05-08':{'observation_date':'2024-05-08','max_depth_m':1.2}}
        self.assertFalse(Router(net).plan('a',{'lat':-30,'lon':-50.997},
            {'type':'bote_inflavel'},DAY)['reachable'])

    def test_no_hindsight_and_coverage_on_real_layers(self):
        from app.geo.routing import ObservedExtent
        ex=ObservedExtent()
        edge=dict(id='x',polyline=[[-51.2,-29.99],[-51.2,-29.99]])
        self.assertEqual(ex.classify(edge,'2024-05-05'),('uncovered',None))  # before first observation
        self.assertEqual(ex.classify(edge,'2024-05-07')[1],'2024-05-06')      # uses the earlier layer
        far=dict(id='far',polyline=[[-40.0,-5.0],[-40.0,-5.0]])
        self.assertEqual(ex.classify(far,'2024-05-08')[0],'uncovered')       # outside the footprint
        self.assertIn(ex.classify(edge,'2024-05-08')[0],('inside','outside'))

if __name__=='__main__': unittest.main()
