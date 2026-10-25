"""Date, missing-data, geometry and city constraints, with no live calls."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from app.geo import hydro as h


class HydroTests(unittest.TestCase):
    def point(self, values, contains=False):
        lookup = {'depth_by_date': {d: {'depth_m': v} for d, v in values.items()}}
        index = SimpleNamespace(contains=lambda lat, lon: contains)
        return patch.object(h.depthmod, 'lookup', return_value=lookup), patch.object(
            h, 'get_data', return_value=SimpleNamespace(indices={d: index for d in values}))

    def test_latest_observation_not_union(self):
        a, b = self.point({'2024-05-06': 2, '2024-05-08': 0})
        with a, b:
            r = h.classify_point(-30, -51, '2024-05-08')
        self.assertEqual(r['state'], 'dry')
        self.assertEqual(r['observed_date'], '2024-05-08')
        self.assertTrue(r['retrospective'])

    def test_unknown_never_dry(self):
        a, b = self.point({'2024-05-08': None})
        with a, b:
            self.assertEqual(h.classify_point(-30, -51, '2024-05-08')['state'], 'unknown')
        for lat, lon in ((None, None), ('', -51), (float('nan'), -51), (100, -51)):
            self.assertEqual(h.classify_point(lat, lon, '2024-05-08')['state'], 'unknown')

    def test_no_hindsight(self):
        with patch.object(h.depthmod, 'lookup') as lookup:
            r = h.classify_point(-30, -51, '2024-05-05')
            lookup.assert_not_called()
        self.assertIsNone(r['observed_date'])
        with self.assertRaises(ValueError):
            h.classify_point(-30, -51, 'yesterday')
        self.assertEqual(h.observed_date('2024-05-07'), '2024-05-06')

    def test_water_height_quotes_preserve_accents_and_gender(self):
        for phrase in ('água na cintura', 'água no pescoço'):
            self.assertEqual(h.life_safety_quote('socorro ' + phrase), phrase)

    def test_extent_positive_without_depth(self):
        a, b = self.point({'2024-05-08': None}, True)
        with a, b:
            r = h.classify_point(-30, -51, '2024-05-08')
        self.assertEqual(r['state'], 'wet')
        self.assertEqual(r['depth_band'], 'unknown')

    def test_rank_city_stability_and_candidate_ids(self):
        candidates = [dict(candidate_id='a', municipality='Canoas', lat=0, lon=0),
                      dict(candidate_id='b', municipality='Canoas', lat=1, lon=0),
                      dict(candidate_id='c', municipality='Porto Alegre', lat=1, lon=0)]
        with patch.object(h, 'classify_point', side_effect=lambda lat, lon, day: {'state': 'wet' if lat else 'dry'}):
            r = h.rank_candidates(candidates, 'água subindo', '2024-05-08', 'Canoas')
            normal = h.rank_candidates(candidates, 'preciso comida', '2024-05-08', 'Canoas')
        self.assertEqual([c['candidate_id'] for c in r['ranked']], ['b', 'a', 'c'])
        self.assertTrue(r['reordered'])
        self.assertFalse(normal['reordered'])
        self.assertNotIn('hydro', candidates[0])

    def test_missing_city_cannot_outrank_stated_city(self):
        candidates = [dict(id='missing', lat=1, lon=0),
                      dict(id='same', city='Canoas', lat=0, lon=0)]
        with patch.object(h, 'classify_point', side_effect=lambda lat, lon, day: {'state': 'wet' if lat else 'unknown'}):
            r = h.rank_candidates(candidates, 'no telhado', '2024-05-08', 'Canoas')
        self.assertEqual(r['ranked'][0]['id'], 'same')

    def test_conflict_only_explicit_dry_and_not_area(self):
        for state in ('wet', 'unknown', 'dry'):
            with patch.object(h, 'classify_point', return_value={'state': state, 'observed_date': '2024-05-08'}):
                r = h.hydro_conflict('no telhado', -30, -51, '2024-05-08')
                self.assertEqual(bool(r), state == 'dry')
                if r:
                    self.assertEqual(r['impact'], 'doubtful_only')
                    self.assertTrue(r['retrospective'])
                self.assertIsNone(h.hydro_conflict('no telhado', -30, -51, '2024-05-08', precision='AREA'))
        self.assertIsNone(h.hydro_conflict('sem água potável', -30, -51, '2024-05-08'))

    def test_area_real_data_proxy_bounds_and_wet_point(self):
        r = h.area_point('Mathias Velho', 'Canoas', '2024-05-08')
        self.assertTrue(r['flooded'])
        self.assertEqual(r['label'], h.AREA_LABEL)
        self.assertTrue(r['boundary_estimated'])
        p = r['point']; w, s, e, n = r['bbox']
        self.assertTrue(w <= p['lon'] <= e and s <= p['lat'] <= n)
        self.assertEqual(h.classify_point(p['lat'], p['lon'], '2024-05-08')['state'], 'wet')
        nodes = h.find_bairro('Mathias Velho', 'Canoas')
        nearest = min((x for x in h._places() if x['mun'] == h.key('Canoas')),
                      key=lambda x: h._metres(p['lat'], p['lon'], x['lat'], x['lon']))
        self.assertIn(nearest, nodes)
        self.assertLessEqual(h._metres(p['lat'], p['lon'], nearest['lat'], nearest['lon']), h.BAIRRO_RADIUS_M)

    def test_missing_bairro_and_date_fallback(self):
        self.assertIsNone(h.area_point('Bairro inventado', 'Canoas', '2024-05-08')['point'])
        r = h.area_point('Mathias Velho', 'Canoas', '2024-05-05')
        self.assertFalse(r['flooded'])
        self.assertNotEqual(r['label'], h.AREA_LABEL)

    def test_descriptors_real_catalogue_scoped_city_and_evidence(self):
        for text, city in [('depois da Ponte do Rio Jacuí', 'Eldorado do Sul'),
                           ('próximo da Igreja João Wesley', 'Porto Alegre'),
                           ('na parte mais baixa', 'Canoas')]:
            items = h.resolve_descriptors(text, city, '2024-05-08', 'Mathias Velho' if city == 'Canoas' else None)
            candidates = [c for item in items for c in item['candidates']]
            self.assertTrue(candidates, text)
            for item in items:
                self.assertIn(item['quote'], text)
            for c in candidates:
                self.assertEqual(c['municipality'], city)
                self.assertIn(c['precision'], ('LANDMARK', 'AREA'))
                self.assertTrue(c['evidence']['source'])
        self.assertFalse(h.resolve_descriptors('depois da ponte', None, '2024-05-08')[0]['candidates'])
        self.assertFalse(h.resolve_descriptors('depois da Ponte Inexistente', 'Canoas', '2024-05-08')[0]['candidates'])

    def test_intersections_are_approximate_not_surveyed(self):
        a = {'bbox_v': [-51.1, -30.1, -51, -30]}
        b = {'bbox_v': [-51.05, -30.05, -50.95, -29.95]}
        self.assertIsNotNone(h._intersection(a, b))
        self.assertIsNone(h._intersection(a, {'bbox_v': [-52, -31, -51.9, -30.9]}))

    def test_generic_reference_stops_before_rescue_prose(self):
        r = h.resolve_descriptors('depois da ponte estamos no telhado', 'Canoas', '2024-05-08')
        self.assertTrue(r[0]['candidates'])
        self.assertTrue(r[0]['ambiguous'])
        self.assertTrue(all(c['precision'] == 'AREA' for c in r[0]['candidates']))

    def test_water_tower_category_without_name(self):
        poi = [dict(name='', category='man_made:water_tower', municipality='Canoas',
                    lat='-29.9', lon='-51.2', neighbourhood='', osm_type='node', osm_id='example')]
        with patch.object(h, '_poi', return_value=poi), patch.object(h, '_hydro', return_value={}):
            r = h.resolve_descriptors("perto da caixa d'água", 'Canoas', '2024-05-08')
        self.assertEqual(r[0]['candidates'][0]['precision'], 'LANDMARK')
        self.assertEqual(r[0]['candidates'][0]['evidence']['category'], 'man_made:water_tower')

    def test_landmark_reference_with_unpunctuated_rescue_prose(self):
        for text in ('depois da ponte meu pai esta ilhado',
                     'perto da igreja precisamos de barco'):
            with self.subTest(text=text):
                items = h.resolve_descriptors(text, 'Canoas', '2024-05-08')
                self.assertTrue(items[0]['candidates'])

    def test_coarse_flood_cell_does_not_prove_its_center_is_wet(self):
        node = dict(name='Teste', key='teste', mun='canoas', municipality='Canoas',
                    lat=-30, lon=-51, osm_id='test')
        with patch.object(h, '_places', return_value=[node]), patch.object(
                h.depthmod, 'aggregated', return_value=[(-51, -30, 'test', 2)]), patch.object(
                h, 'classify_point', return_value={'state': 'unknown'}):
            area = h.area_point('Teste', 'Canoas', '2024-05-08')
        self.assertFalse(area['flooded'])
        self.assertNotEqual(area['label'], h.AREA_LABEL)


if __name__ == '__main__':
    unittest.main()
