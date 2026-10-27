"""Boat routing regressions; all maps here are deliberately synthetic, in metres."""
import math
import struct
import unittest
from unittest.mock import patch

from app.geo import depth, routing


def grid(rows, legend=None, pixel=20):
    legend = legend or {'~': 2., '#': 0., 's': .45, '?': None}
    header = dict(width=len(rows[0]), height=len(rows), pixel_m=pixel,
                  origin_x=500000., origin_y=6680000., date_observed='2024-05-06')
    values = [65535 if legend[c] is None else round(legend[c]*100) for row in rows for c in row]
    return depth.DepthGrid(header, struct.pack('<'+'H'*len(values), *values))


def point(g, col, row):
    lon, lat = depth.utm22s_to_lonlat(g.h['origin_x']+(col+.5)*g.h['pixel_m'],
                                    g.h['origin_y']-(row+.5)*g.h['pixel_m'])
    return dict(lon=lon, lat=lat)


class WaterRouteTests(unittest.TestCase):
    def router(self, rows, **kwargs):
        from app.geo import water_routing
        return water_routing.WaterRouter(grid(rows), **kwargs)

    def route(self, router, start, end, **kwargs):
        return router.route(point(router.grid, *start), point(router.grid, *end), **kwargs)

    def assert_passable(self, r, g, draft=.4, clearance=.1, blocked=()):
        # Independent dense segment sampling (not the router's LOS/search helpers).
        self.assertEqual(r['basis'], 'depth_grid_water')
        seen = set()
        for a, b in zip(r['polyline'], r['polyline'][1:]):
            ax, ay = depth.lonlat_to_utm22s(*a); bx, by = depth.lonlat_to_utm22s(*b)
            n = max(1, math.ceil(math.hypot(bx-ax, by-ay)/.5))
            for i in range(n+1):
                x=ax+(bx-ax)*i/n; y=ay+(by-ay)*i/n
                c=math.floor((x-g.h['origin_x'])/g.h['pixel_m'])
                row=math.floor((g.h['origin_y']-y)/g.h['pixel_m']); idx=row*g.h['width']+c
                self.assertNotIn(idx, blocked)
                cm=struct.unpack_from('<H', g.data, idx*2)[0];seen.add(idx)
                self.assertNotEqual(cm, 65535)
                self.assertGreaterEqual(cm/100+1e-9, draft+clearance)
        self.assertTrue(seen)

    def test_open_water_smooths_and_reports_depth_and_eta(self):
        r=self.router(['~~~~~~~~~~~~']*8)
        out=self.route(r,(1,3),(10,3),speed=6,draft_m=.3)
        self.assert_passable(out,r.grid,.3)
        self.assertEqual(len(out['polyline']),2)
        self.assertAlmostEqual(out['water_km'],.18,places=3)
        self.assertAlmostEqual(out['water_eta_min'],1.8,places=2)
        self.assertEqual(out['min_depth_m'],2)
        self.assertEqual(out['max_depth_m'],2)
        self.assertIn('HAND retrospectivo',out['label_pt'])

    def test_export_keeps_submillimetre_grid_centre_precision(self):
        r=self.router(['~~~~~~~~~~~~']*8)
        out=self.route(r,(1,1),(10,6))
        # Coarse lon/lat rounding can move a long shortcut across an unchecked
        # neighbouring cell near a corner. Keep the exact grid geometry at export.
        for lon,lat in out['polyline']:
            x,y=depth.lonlat_to_utm22s(lon,lat)
            col=(x-r.h['origin_x'])/r.p-.5;row=(r.h['origin_y']-y)/r.p-.5
            self.assertLess(abs(col-round(col))*r.p,.001)
            self.assertLess(abs(row-round(row))*r.p,.001)

    def test_dry_island_forces_detour_and_smoothing_does_not_cut_it(self):
        r=self.router(['~~~~~~~~~~~~','~~~~####~~~~','~~~~####~~~~','~~~~####~~~~','~~~~~~~~~~~~'])
        out=self.route(r,(1,2),(10,2))
        self.assert_passable(out,r.grid)
        self.assertGreater(len(out['polyline']),2)
        self.assertGreater(out['water_km'],.19)

    def test_shallow_channel_passes_inflatable_but_blocks_deep_draft(self):
        r=self.router(['~~~~s~~~~']*20)
        a=self.route(r,(1,10),(7,10),draft_m=.18)
        b=self.route(r,(1,10),(7,10),draft_m=.6)
        self.assert_passable(a,r.grid,.18)
        self.assertEqual(b['basis'],'straight_line_water')
        self.assertTrue(b['fallback'])
        self.assertIn('NO_WATER_PATH',b['reason_codes'])
        self.assertTrue(b['review_pt'])

    def test_dry_target_ends_at_nearest_reachable_wet_cell(self):
        r=self.router(['~~~~~########']*12)
        out=self.route(r,(1,5),(6,5))
        self.assert_passable(out,r.grid)
        self.assertAlmostEqual(out['end_gap_m'],40,delta=1)
        self.assertIn('último trecho a pé/raso — confirmar',' '.join(out['review_pt']))
        far=self.route(r,(1,5),(12,5))
        self.assertTrue(far['fallback'])
        self.assertIn('NO_WET_ENDPOINT',far['reason_codes'])

    def test_nearest_wet_cell_must_also_be_reachable(self):
        r=self.router(['~~~~~#~#####']*8)
        out=self.route(r,(1,3),(7,3))
        self.assert_passable(out,r.grid)
        # The isolated strip is only 20 m away; the reachable left bank is 60 m.
        self.assertAlmostEqual(out['end_gap_m'],60,delta=1)

    def test_target_just_outside_grid_uses_nearest_reachable_water(self):
        r=self.router(['~~~~~~~~~~~~']*8)
        out=self.route(r,(1,3),(13,3))
        self.assert_passable(out,r.grid)
        self.assertAlmostEqual(out['end_gap_m'],40,delta=1)
        self.assertIn('LAST_METRES_SHALLOW',out['reason_codes'])
        reverse=self.route(r,(13,3),(1,3))
        self.assert_passable(reverse,r.grid)
        self.assertIn('START_SHORE_ACCESS',reverse['reason_codes'])

    def test_zero_draft_and_margin_never_make_dry_cells_navigable(self):
        r=self.router(['~~~~#~~~~~~~']*8)
        out=self.route(r,(1,3),(10,3),draft_m=0,clearance_m=0,allow_unknown=False)
        self.assertTrue(out['fallback'])
        self.assertIn('NO_WATER_PATH',out['reason_codes'])

    def test_unknown_is_last_resort_and_never_silent(self):
        r=self.router(['~~~~?~~~~']*5)
        out=self.route(r,(1,2),(7,2))
        self.assertEqual(out['basis'],'depth_grid_water')
        self.assertGreater(out['unknown_samples'],0)
        self.assertIn('trecho sem dado',' '.join(out['review_pt']))
        self.assertFalse(out['grid_verified'])
        strict=self.route(r,(1,2),(7,2),allow_unknown=False)
        self.assertTrue(strict['fallback'])
        detour=self.router(['~~~~~~~~~','~~~~?~~~~','~~~~?~~~~','~~~~?~~~~','~~~~~~~~~'])
        known=self.route(detour,(1,2),(7,2))
        self.assertEqual(known['unknown_samples'],0)
        self.assert_passable(known,detour.grid)

    def test_buildings_and_diagonal_corner_cut_are_blocked(self):
        blocked=bytearray(60)
        for row in range(1,4): blocked[row*12+5]=1
        r=self.router(['~~~~~~~~~~~~']*5, buildings=blocked)
        out=self.route(r,(1,2),(10,2))
        self.assert_passable(out,r.grid,blocked={i for i,v in enumerate(blocked) if v})
        self.assertGreater(len(out['polyline']),2)
        corner=self.router(['~#','#~'])
        self.assertTrue(self.route(corner,(0,0),(1,1),allow_unknown=False)['fallback'])

    def test_no_hindsight_and_fleet_profile_cache(self):
        from app.geo import water_routing
        a={'lon':-51.2,'lat':-30};b={'lon':-51.201,'lat':-30}
        with patch.object(depth,'grid',side_effect=AssertionError('future grid loaded')):
            out=water_routing.water_route(a,b,'2024-05-05')
        self.assertTrue(out['fallback'])
        self.assertIsNone(out['observation_date'])
        self.assertIn('NO_OBSERVATION',out['reason_codes'])

    def test_budget_exhaustion_is_not_claimed_as_no_path(self):
        r=self.router(['~~~~~~~~~~~~']*8)
        out=self.route(r,(1,1),(10,6),max_seconds=0)
        self.assertEqual(out['basis'],'water_search_incomplete')
        self.assertFalse(out['fallback'])
        self.assertIsNone(out['water_km'])
        self.assertIn('SEARCH_LIMIT',out['reason_codes'])

    def test_invalid_profile_rejected(self):
        r=self.router(['~~~~~~~~~~~~']*8)
        for kwargs in ({'draft_m':-1},{'clearance_m':float('nan')},{'speed':0},{'draft_m':True}):
            with self.assertRaises(ValueError): self.route(r,(1,1),(10,6),**kwargs)

    def test_fleet_and_landing_use_water_path_distance_and_asset_profile(self):
        from app.geo import water_routing
        from tests.test_routing import network, DAY
        g=grid(['~'*32]*32)
        x,y=depth.lonlat_to_utm22s(-51,-30)
        g.h.update(origin_x=x-100,origin_y=y+300)
        wr=water_routing.WaterRouter(g)
        boat={'type':'barco_aluminio','draft_m':.3,'boat_speed_kph':6}
        router=routing.Router(network())
        a={'lat':-30,'lon':-51};b={'lat':-30,'lon':-50.997}
        with patch.object(water_routing,'default_water_router',return_value=wr):
            out=routing.FleetDistance(DAY,router).for_unit(a,b,boat)
            self.assertEqual(out['route']['water']['draft_m'],.3)
            self.assertFalse(out['route']['water']['speed_estimated'])
            water=out['route']['water']
            self.assertAlmostEqual(out['eta_seconds'],out['route']['land_eta_min']*60+water['eta_min']*60,delta=.1)
            other=routing.FleetDistance(DAY,router).for_unit(a,b,dict(boat,draft_m=3))
            self.assertTrue(other['route']['water']['fallback'])
            self.assertEqual(other['route']['water']['draft_m'],3)
            landing=routing.landing_distance(DAY,boat)(a,b)
            self.assertEqual(landing['basis'],'depth_grid_water')
            self.assertEqual(landing['m'],round(landing['water_km']*1000))
            self.assertEqual(landing['draft_m'],.3)

    def test_f5_displays_water_warnings_and_excludes_inconclusive_distance(self):
        import json
        from eval import run_landing
        item=next(json.loads(line) for line in (run_landing.ROOT/'eval/landing_set.jsonl').read_text(encoding='utf-8').splitlines()
                  if json.loads(line)['id']=='full-shelter-skipped')
        svc,_=run_landing.build(item)
        svc.distance_fn=lambda a,b: dict(m=None if b['landing_id']=='L1' else 120,basis='depth_grid_water',
            label_pt='estimativa (HAND retrospectivo)',review_pt=['trecho sem dado; confirmar'])
        out=svc.view(item['id'],item['now'])
        self.assertNotIn('L1',[o['landing_id'] for o in out['options']])
        self.assertIn('trecho sem dado',' '.join(out['options'][0]['warnings_pt']))
        self.assertIn('HAND retrospectivo',out['labels_pt']['distance'])


if __name__=='__main__': unittest.main()
