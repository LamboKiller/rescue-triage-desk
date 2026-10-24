"""Curated aliases and airport dispatch targets on the real snapshot."""
import csv
import unittest
from app.config import ROOT
from app.data.source import LocalSource, ZetarisSource
from app.geo.landmarks import match
from unittest.mock import patch


class Aliases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = LocalSource().landmarks()

    def resolve(self, query, city='Porto Alegre'):
        return match(self.rows, query, municipality=city, message=query)

    def test_popular_names(self):
        for query, oid in [('salgado filho','5320213'), ('aeroporto salgado filho','5320213'),
                           ('redenção','3190472'), ('parque da redenção','3190472'),
                           ('gasômetro','8440037'), ('beira rio','4587043'),
                           ('hps','244644162'), ('ghc','237709751')]:
            with self.subTest(query=query):
                result = self.resolve(query)
                self.assertEqual(result['status'], 'resolved')
                self.assertEqual(result['matched']['osm_id'], oid)
                self.assertGreaterEqual(result['matched']['score'], 100)
                self.assertTrue(result['reason'].startswith('alias:'))

    def test_unknown_city_and_whole_words(self):
        self.assertEqual(self.resolve('estamos no salgado-filho', '')['matched']['osm_id'], '5320213')
        self.assertEqual(self.resolve('xhpsx')['status'], 'unresolved')

    def test_longest_alias(self):
        self.assertEqual(self.resolve('aeroporto salgado filho')['reason'], 'alias:aeroporto salgado filho')

    def test_exceptions(self):
        for query in ('escola salgado filho', 'colégio salgado filho'):
            self.assertEqual(self.resolve(query)['matched']['osm_id'], '244050553')
        self.assertIn('Brique', self.resolve('brique da redenção')['matched']['name'])
        for query in ('estação aeroporto', 'trensurb aeroporto'):
            self.assertEqual(self.resolve(query)['matched']['category'], 'public_transport:station')
        for query in ('pronto socorro', 'conceição'):
            self.assertNotEqual(self.resolve(query)['status'], 'resolved')
        result = self.resolve('rodoviária', 'Canoas')
        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['matched']['municipality'], 'Canoas')

    def test_terminal_dispatch(self):
        for query in ('terminal 1 do aeroporto', 'no terminal do salgado filho'):
            result = self.resolve(query)
            self.assertEqual(result['status'], 'resolved')
            self.assertEqual(result['matched']['osm_id'], '5320213')
            self.assertEqual(result['sub_place']['name'], 'Terminal 1')
            self.assertEqual(result['sub_place']['osm_url'], 'https://www.openstreetmap.org/way/89383738')
        self.assertNotIn('sub_place', self.resolve('rodoviária')['matched'])
        # No terminal mentioned -> airport only, no invented terminal detail.
        for query in ('salgado filho', 'aeroporto salgado filho'):
            result = self.resolve(query)
            self.assertEqual(result['matched']['osm_id'], '5320213')
            self.assertFalse(result.get('sub_place'))

    def test_alias_ids_and_sources(self):
        ids = {(r['osm_type'], r['osm_id']) for r in self.rows}
        with (ROOT/'data/landmark_aliases.csv').open(encoding='utf-8', newline='') as f:
            aliases = list(csv.DictReader(f))
        for alias in aliases:
            self.assertIn((alias['osm_type'], alias['osm_id']), ids)
            with self.subTest(alias=alias['alias']):
                result = self.resolve(alias['alias'], alias['municipality'])
                self.assertEqual(result['status'], 'resolved')
                self.assertEqual((result['matched']['osm_type'], result['matched']['osm_id']),
                                 (alias['osm_type'], alias['osm_id']))
        # Zetaris REST returns empty cells as null: the source must hand the app '' like the local CSV.
        raw = [{k: (None if v == '' else v) for k, v in r.items() if k != 'curated_aliases'} for r in self.rows]
        with patch('app.data.source.Zetaris') as api:
            api.return_value.rows.return_value = raw
            zrows = ZetarisSource().landmarks()
        self.assertEqual(zrows, self.rows)
        result = match(zrows, 'Rodoviária de Porto Alegre', 'rodoviaria de porto alegre', 'Porto Alegre',
                       message='socorro estamos dentro da rodoviaria de porto alegre')
        self.assertEqual(result['status'], 'resolved')

    def test_terminal_distance_and_bus_exclusion(self):
        base = dict(alt_names='', municipality='Porto Alegre', lat='-30', lon='-51', osm_type='way')
        airport = dict(base, name='Aeroporto Aurora', category='aeroway:aerodrome', osm_id='1')
        terminal = dict(base, name='Terminal Aurora', category='aeroway:terminal', osm_id='2')
        for category, lat, expected in [('aeroway:terminal','-30.01','1'),
                                         ('aeroway:terminal','-30.04','2'),
                                         ('amenity:bus_station','-30.01','2')]:
            with self.subTest(category=category, lat=lat):
                result = match([airport, dict(terminal, category=category, lat=lat)],
                               'Terminal Aurora', municipality='Porto Alegre')
                self.assertEqual(result['status'], 'resolved')
                self.assertEqual(result['matched']['osm_id'], expected)
                self.assertEqual(bool(result['sub_place']), expected == '1')
