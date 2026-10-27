"""CODEFIXB regressions: number binding, physical ETA vs risk cost, common ranking metric, cold routing, journal index."""
import copy
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import Scratch
from tests.test_missions import make_case
from tests.test_routing import network, DAY as ROUTE_DAY, TRUCK
from tests.test_allocation import case as alloc_case, unit as alloc_unit

from app.agents.counts import count
from app.engines.world_model import registry as reg
from app.engines.world_model.registry import Registry
from app.geo.routing import Router, FleetDistance


class NumberBindingTests(unittest.TestCase):
    def test_ages_are_not_head_counts(self):
        # A singular relative carrying an age is ONE person of that group; the age is never the count.
        for quote, key in [('filho de 8 anos', 'children'), ('bebe de 8 meses', 'children'),
                           ('mae de 75 anos', 'elderly'), ('meu pai de 82', 'elderly'),
                           ('minha filha tem 6', 'children'), ('menina de dez anos', 'children')]:
            with self.subTest(quote=quote):
                self.assertEqual(count(quote, key), 1)
        # Plural/anonymous ages stay unknown rather than guessed.
        for quote, key in [('meus filhos de 8 e 10 anos', 'children'), ('tem 6 e 9 anos', 'children')]:
            with self.subTest(quote=quote):
                self.assertIsNone(count(quote, key))

    def test_grandmother_age_keeps_single_relative(self):
        self.assertEqual(count('minha vó de 75', 'elderly'), 1)

    def test_address_phone_time_depth_floor_are_not_counts(self):
        cases = [('rua das flores, 123 somos 5', 5), ('casa 45, 4 pessoas', 4), ('telefone 51 99999-1234 e 2 idosos', 2),
                 ('ligue 51 3333-4444, tem 3 criancas', 3), ('desde as 14h somos 3', 3),
                 ('agua a 80 cm, 6 pessoas', 6), ('segundo andar, 4 pessoas', 4), ('apto 12 temos 2 idosos', 2)]
        for quote, expected in cases:
            with self.subTest(quote=quote):
                self.assertEqual(count(quote, 'people'), expected)
        for quote in ('agua 1,5 m', 'moro na rua tal, 780', 'whatsapp 51 98765 4321', 'chegou as 14:30', 'no 3 andar'):
            with self.subTest(quote=quote):
                self.assertIsNone(count(quote, 'people'))

    def test_count_next_to_noun_beats_age_in_same_quote(self):
        self.assertEqual(count('2 criancas de 5 e 7 anos', 'children'), 2)
        self.assertEqual(count('tem 3 criancas, a menor com 2 anos', 'children'), 3)

    def test_compound_number_words(self):
        self.assertEqual(count('vinte e cinco pessoas', 'people'), 25)
        self.assertEqual(count('trinta pessoas', 'people'), 30)
        self.assertEqual(count('duas criancas', 'children'), 2)

    def test_validator_rejects_age_as_count(self):
        from app.agents.spans import validate
        text = 'Meu filho de 8 anos esta comigo na rua Alfa 10'
        out = dict(fields={'children': {'value': 8, 'quote': 'filho de 8 anos', 'source': 'text'}})
        res = validate(out, text)
        self.assertNotIn('children', (res[0] if isinstance(res, tuple) else res).get('fields', {}))


class RoutingArithmeticTests(unittest.TestCase):
    def test_penalty_is_risk_cost_not_travel_time(self):
        net = network()
        for e in net.edges:
            e['depth'][ROUTE_DAY]['unknown_fraction'] = 1  # unknown coverage -> penalised search cost
        for e in net.edges:
            e['highway'] = 'residential'
        out = Router(net).route('a', 'd', TRUCK, ROUTE_DAY)
        self.assertTrue(out['reachable'])
        seconds = out['land_km'] * 1000 / (20 / 3.6)
        self.assertAlmostEqual(out['land_eta_min'] * 60, seconds, delta=0.5)
        self.assertGreater(out['land_risk_cost_min'], out['land_eta_min'] * 5)
        self.assertLess(out['land_eta_min'] * 60, 40)  # 200 m @ 20 km/h = 36 s, not 12 min

    def test_hundred_metres_at_20kmh_is_18_seconds(self):
        net = network()
        net.edges = [net.edges[0]]
        net.edges[0]['depth'][ROUTE_DAY]['unknown_fraction'] = 1
        r = Router(net).route('a', 'b', TRUCK, ROUTE_DAY)
        self.assertAlmostEqual(r['land_eta_min'] * 60, 18, delta=0.1)


class FleetRankingTests(unittest.TestCase):
    def rank(self, travel):
        from app.fleet.allocation import allocate

        class Dist:
            def __call__(self, base, target): return 0
            def for_unit(self, base, target, u): return travel[u['id']]
        units = [alloc_unit(i) for i in travel]
        out = allocate(alloc_case(), units, '2024-05-08', distance_fn=Dist())
        return out

    def test_mixed_eta_and_distance_never_compares_seconds_with_metres(self):
        travel = {'far': dict(reachable=True, distance_m=1000, eta_seconds=60, basis_pt='x', route={}),
                  'near': dict(reachable=True, distance_m=100, eta_seconds=None, basis_pt='x', route={})}
        out = self.rank(travel)
        self.assertEqual([r['id'] for r in out['top3']][0], 'near')  # metres for everyone; 100 m < 1000 m
        self.assertTrue(all(r['ranking_metric'] == 'distance_m' for r in out['top3']))

    def test_all_eta_ranks_by_seconds(self):
        travel = {'a': dict(reachable=True, distance_m=100, eta_seconds=90, basis_pt='x', route={}),
                  'b': dict(reachable=True, distance_m=900, eta_seconds=30, basis_pt='x', route={})}
        out = self.rank(travel)
        self.assertEqual(out['top3'][0]['id'], 'b')
        self.assertEqual(out['top3'][0]['ranking_metric'], 'eta_seconds')


class ColdRoutingTests(unittest.TestCase):
    def test_cold_land_graph_returns_pending_within_a_second(self):
        warmed = []
        with patch('app.geo.routing.router_ready', return_value=False), patch('app.geo.routing.warm_async', lambda: warmed.append(1)):
            t = time.monotonic()
            out = FleetDistance('2024-05-08').for_unit({'lat': -30, 'lon': -51}, {'lat': -30.01, 'lon': -51.01}, TRUCK)
        self.assertLess(time.monotonic() - t, 1)
        self.assertTrue(out['pending']); self.assertFalse(out['reachable']); self.assertEqual(warmed, [1])
        self.assertIn('não comprovada', out['basis_pt'])

    def test_cold_water_grid_returns_pending_and_starts_one_warmup(self):
        warmed = []
        boat = {'type': 'barco_aluminio', 'id': 'b'}
        with patch('app.geo.routing.router_ready', return_value=True), \
                patch('app.geo.water_routing.water_ready', return_value=False), \
                patch('app.geo.water_routing.warm_water', lambda day: warmed.append(day)):
            t = time.monotonic()
            out = FleetDistance('2024-05-08', Router(network())).for_unit({'lat': -30, 'lon': -51}, {'lat': -30.01, 'lon': -51.01}, boat)
        self.assertLess(time.monotonic() - t, 1)
        self.assertTrue(out['pending']); self.assertEqual(warmed, ['2024-05-08']); self.assertIsNone(out['eta_seconds'])

    def test_over_budget_call_is_declared_not_hidden(self):
        r = Router(network()); real = r.plan
        def slow(*a):
            time.sleep(0.05); return real(*a)
        r.plan = slow
        ad = FleetDistance(ROUTE_DAY, r); ad.BUDGET_S = 0.01
        ad.for_unit({'lat': -30, 'lon': -51}, {'lat': -30, 'lon': -50.998}, TRUCK)
        self.assertGreater(ad.overshoot_s, 0)


class JournalIndexTests(unittest.TestCase):
    def setUp(self):
        self.s = Scratch(); self.addCleanup(self.s.cleanup)
        self.path = self.s.path / 'events.jsonl'
        self.reg = Registry(self.path)
        reg._INDEX.clear()

    def add(self, i):
        c = make_case(cid='m%d' % i, text='Pedido %d' % i)
        c.pop('case_id', None)
        return self.reg.ingest(c)

    def test_tail_replay_matches_full_replay(self):
        ids = [self.add(i)['case_id'] for i in range(25)]
        self.reg.action(ids[3], 'confirm_location', 1, 'Ana', human=True)
        fast = self.reg.read()
        reg._INDEX.clear()
        full = Registry(self.path).read()
        self.assertEqual(fast, full)

    def test_one_case_read_replays_only_the_new_tail(self):
        for i in range(60):
            self.add(i)
        key = str(self.path.resolve())
        before = reg._INDEX[key]['replayed']
        self.assertEqual(before, 60)
        cid = self.add(60)['case_id']
        self.assertEqual(reg._INDEX[key]['replayed'] - before, 1)  # one appended event, not 61
        self.reg.read(cid); self.reg.read(cid)
        self.assertEqual(reg._INDEX[key]['replayed'] - before, 1)

    def test_second_instance_and_external_rewrite_are_detected(self):
        self.add(1)
        other = Registry(self.path)
        other.ingest(dict(make_case(cid='z', text='outro'), case_id=None))
        self.assertEqual(len(self.reg.read()), 2)
        self.path.write_text('', encoding='utf-8')  # journal reset behind our back
        self.assertEqual(self.reg.read(), [])
        self.add(2)
        self.assertEqual(len(self.reg.read()), 1)

    def test_returned_cases_are_detached_copies(self):
        cid = self.add(1)['case_id']
        got = self.reg.read(cid); got['status'] = 'tampered'
        self.assertNotEqual(self.reg.read(cid)['status'], 'tampered')

    def test_damaged_row_still_fails_closed(self):
        self.add(1)
        with self.path.open('a', encoding='utf-8') as f: f.write('{not json\n')
        with self.assertRaises(ValueError):
            self.reg.read()

    def test_read_latency_is_flat_in_journal_size(self):
        for i in range(150):
            self.add(i)
        cid = self.add(150)['case_id']
        samples = []
        for _ in range(30):
            t = time.perf_counter(); self.reg.read(cid); samples.append(time.perf_counter() - t)
        samples.sort()
        self.assertLess(samples[int(len(samples) * .95) - 1], 0.05)


if __name__ == '__main__':
    unittest.main()
