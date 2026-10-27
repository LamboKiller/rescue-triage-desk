"""Planning may price labelled water uncertainty; tracking remains proven-only."""
import copy
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from eval.run_chaining import SyntheticAdapter, prepare
from app.missions.chaining import propose, travel
from tests import test_chaining

LABEL = 'estimativa não comprovada (linha reta na água)'


class WaterAdapter(SyntheticAdapter):
    def for_unit(self, a, b, unit):
        raw = super().for_unit(a, b, unit)
        raw['route'] = {'water': {'basis': 'straight_line_water', 'fallback': True,
                                'grid_verified': False, 'tracking_eligible': False}}
        return raw


class PlanningTests(unittest.TestCase):
    def test_proposal_labels_baseline_and_inserted_legs_without_mutating_source(self):
        plan, cases, unit = prepare({'cases': [{}]})
        before = copy.deepcopy((plan, cases, unit))
        proposal = propose(plan, cases, unit, WaterAdapter())['proposals'][0]
        self.assertEqual(proposal['eta_basis_pt'], LABEL)
        self.assertEqual(proposal['eta_basis'], 'straight_line_water')
        self.assertIn(LABEL, proposal['text_pt'])
        self.assertTrue(proposal['planning_estimate_only'])
        self.assertTrue(proposal['baseline_travel_facts'])
        for leg in proposal['travel_facts'] + proposal['baseline_travel_facts']:
            self.assertFalse(leg['tracking_eligible'])
            self.assertEqual(leg['route']['water']['basis'], 'straight_line_water')
        self.assertEqual((plan, cases, unit), before)

    def test_proven_adapter_path_preferred(self):
        plan, cases, unit = prepare({'cases': [{}]})
        adapter = SyntheticAdapter()
        raw = adapter.for_unit(unit['base_location'], cases[0]['position'], unit)
        raw['route'] = {'water': {'basis': 'depth_grid_water', 'grid_verified': True, 'fallback': False}}
        adapter.for_unit = lambda *args: raw
        with patch('app.geo.routing.water_leg', side_effect=AssertionError('unneeded fallback')):
            self.assertEqual(travel(adapter, unit['base_location'], cases[0]['position'], unit),
                             raw)

    def test_planning_facts_never_become_tracking_segments(self):
        from app.telemetry import Telemetry
        from app.telemetry_routes import ApprovedRoutes
        from tests.support import Scratch
        tmp = Scratch()
        self.addCleanup(tmp.cleanup)
        plan, cases, unit = prepare({'cases': [{}]})
        proposal = propose(plan, cases, unit, WaterAdapter())['proposals'][0]
        water = dict(basis='straight_line_water', fallback=True, grid_verified=False,
                     polyline=[[-51.18, -29.92], [-51.179, -29.92]], review_pt=['NO_WATER_PATH'])
        status = SimpleNamespace(journal=lambda: [dict(kind='approve_mission', mission_id='m', at='2024-05-08T00:00:00Z')],
                                 view=lambda: {'units': [dict(unit_id=unit['id'], mission_id='m')]})
        telemetry = Telemetry(tmp.path/'gps.jsonl', lambda: [unit['id']], lambda: [])
        missions = SimpleNamespace(detail=lambda _: plan)
        with patch('app.geo.routing.case_route', return_value=dict(reachable=True, land=None, water=water)):
            before = ApprovedRoutes(status, missions, telemetry)()[0]
            plan['mission_update'] = proposal
            after = ApprovedRoutes(status, missions, telemetry)()[0]
        self.assertEqual(before['segments'], after['segments'])
        self.assertEqual(after['segments'], [])
        self.assertEqual(after['polyline'], [])
        self.assertFalse(after['tracking_eligible'])
        self.assertTrue(after['preview_segments'])

    def test_unreachable_adapter_uses_only_explicit_straight_line_fallback(self):
        plan, cases, unit = prepare({'cases': [{}]})
        adapter = SyntheticAdapter()
        adapter.for_unit = lambda *args: {'reachable': False}
        water = dict(km=.3, eta_min=2, basis='straight_line_water', fallback=True, grid_verified=False)
        with patch('app.geo.routing.water_leg', return_value=water):
            leg = travel(adapter, unit['base_location'], cases[0]['position'], unit)
        self.assertEqual(leg['eta_seconds'], 120)
        self.assertEqual(leg['basis_pt'], LABEL)
        self.assertNotIn('tracking_eligible', water)
        for changed in (dict(water, basis='depth_grid_water'), dict(water, eta_min=None),
                        dict(water, km=float('nan'))):
            with patch('app.geo.routing.water_leg', return_value=changed):
                self.assertIsNone(travel(adapter, unit['base_location'], cases[0]['position'], unit))

    def test_reroute_card_keeps_warning_and_human_approval(self):
        fixture = test_chaining.LifecycleTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.service.routing_distance = WaterAdapter
        before = fixture.registry.path.read_bytes()
        alert = test_chaining.reroutes.reroutes(fixture.service, test_chaining.DAY)['alerts'][0]
        self.assertIn(LABEL, alert['text_pt'])
        self.assertTrue(alert['human_approval_required'])
        self.assertFalse(alert['auto_applied'])
        self.assertEqual(fixture.registry.path.read_bytes(), before)

    def test_no_land_path_still_prices_reviewable_water_detour(self):
        plan, cases, unit = prepare({'cases': [{'priority': 'P1'}]})
        adapter = SyntheticAdapter()
        adapter.for_unit = lambda *args: {'reachable': False, 'review_pt': ['No proven land access']}
        water = dict(km=.3, eta_min=2, basis='straight_line_water', fallback=True, grid_verified=False)
        with patch('app.geo.routing.water_leg', return_value=water):
            proposal = propose(plan, cases, unit, adapter)['proposals'][0]
        self.assertEqual(proposal['mission_delay_minutes'], 2)
        self.assertIn(LABEL, proposal['text_pt'])
        self.assertTrue(proposal['confirmation_checklist'])
        self.assertFalse(proposal['auto_applied'])

    def test_incomplete_water_search_gets_separate_labelled_planning_fallback(self):
        plan, cases, unit = prepare({'cases': [{'priority': 'P1'}]})
        adapter = SyntheticAdapter()
        adapter.for_unit = lambda *args: {'reachable': False}
        water = dict(basis='water_search_incomplete', fallback=False, grid_verified=False,
                     km=None, eta_min=None, speed_kph=12, speed_estimated=True,
                     draft_m=.4, draft_estimated=True, clearance_m=.1,
                     reason_codes=['SEARCH_LIMIT'], review_pt=['Search inconclusive'])
        with patch('app.geo.routing.water_leg', return_value=water):
            proposal = propose(plan, cases, unit, adapter)['proposals'][0]
        leg = proposal['baseline_travel_facts'][0]
        self.assertFalse(leg['tracking_eligible'])
        self.assertEqual(leg['route']['water']['basis'], 'straight_line_water')
        self.assertEqual(leg['route']['water']['source_water_basis'], 'water_search_incomplete')
        self.assertEqual(leg['route']['water']['source_reason_codes'], ['SEARCH_LIMIT'])
        self.assertIn(LABEL, proposal['text_pt'])
        self.assertIsNone(water['km'])
