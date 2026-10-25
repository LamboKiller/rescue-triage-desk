"""Exact catalogue evidence regressions; synthetic messages, no provider calls."""
import time
import unittest
from app.agents import location
from app.agents.location_tools import LocationTools
from test_l1 import place, Script, REPLAY


def terminal(city='Porto Alegre', note='within Porto Alegre only; other cities have their own'):
    alias = dict(alias='terminal popular', municipality=city, osm_type='node',
                 osm_id='11', target_name='Estação Central', note=note)
    return place('Estação Central', city, category='amenity:bus_station', curated_aliases=[alias])


class ExactEvidenceTests(unittest.TestCase):
    def locate(self, text, rows=None, roads=()):
        client = Script([{'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}])
        fields = {}
        out = location.locate(roads, rows or [terminal()], fields, text, REPLAY, client, time.monotonic()+10)
        return out, client, fields

    def test_alias_fast_path_and_caller_ignored(self):
        out, client, fields = self.locate('Ligo de Canoas. Há famílias no TERMINAL POPULAR, Porto Alegre.')
        self.assertEqual(out[3]['location_path'], 'deterministic_alias')
        self.assertEqual(client.roles, [])
        self.assertEqual(out[2]['status'], 'resolved')
        self.assertEqual(out[3]['evidence']['alias_row']['alias'], 'terminal popular')
        self.assertEqual(out[3]['evidence']['quote'], 'TERMINAL POPULAR')
        self.assertEqual(fields['municipality']['value'], 'Porto Alegre')

    def test_competing_city_stays_agent(self):
        out, client, _ = self.locate('Pedido no terminal popular em Porto Alegre ou Canoas.')
        self.assertEqual(out[3]['location_path'], 'agent')
        self.assertTrue(client.roles)

    def test_note_requires_explicit_city(self):
        for text in ('Socorro no terminal popular.', 'Socorro no terminal popular em Canoas.'):
            out, client, _ = self.locate(text)
            self.assertEqual(out[3]['location_path'], 'agent')
            self.assertTrue(client.roles)

    def test_unique_name_and_alt_name(self):
        row = {**place('Escola Horizonte'), 'alt_names': 'Colégio Novo Horizonte'}
        for name in ('Escola Horizonte', 'Colégio Novo Horizonte'):
            out, client, _ = self.locate('Abrigo na '+name+', Canoas.', [row])
            self.assertEqual(out[3]['location_path'], 'deterministic_alias')
            self.assertEqual(client.roles, [])

    def test_competing_place_and_word_boundary(self):
        rows = [place('Escola Horizonte'), place('Mercado Lunar', osm_id='22')]
        for text in ('Escola Horizonte ou Mercado Lunar em Canoas.', 'Escola Horizontes em Canoas.'):
            out, _, _ = self.locate(text, rows)
            self.assertEqual(out[3]['location_path'], 'agent')

    def test_city_name_alone_is_not_a_landmark(self):
        out, _, _ = self.locate('Famílias precisam de ajuda em Canoas.',
            [place('Canoas', category='public_transport:station')])
        self.assertEqual(out[3]['location_path'], 'agent')

    def test_alias_supported_candidate_and_trace(self):
        text = 'Famílias no terminal popular em Porto Alegre.'
        tools = LocationTools([], [terminal()], text, REPLAY)
        action = dict(tool='search_landmark', args={'name': 'terminal popular'}, why_quote='terminal popular')
        answer = {'answer': dict(candidate_id='osm:node:11', precision='approximate', evidence=['terminal popular', 't1'])}
        client = Script([action, answer], [{'field': 'location', 'reason': 'unsupported', 'quote': 'terminal popular'}])
        out, _ = location.run(client, text, '', time.monotonic()+10, tools=tools)
        self.assertIsNotNone(out['candidate'])
        review = next(s for s in out['steps'] if s['tool'] == 'critic')
        self.assertEqual(review['raw_objections'][0]['quote'], 'terminal popular')
        self.assertEqual(review['objections'], [])

    def test_alias_cannot_override_wrong_city(self):
        text = 'Famílias no terminal popular em Canoas.'
        tools = LocationTools([], [terminal()], text, REPLAY)
        tools.execute('search_landmark', {'name': 'terminal popular'}, 'terminal popular')
        objections = location._objections(dict(candidate_id='osm:node:11', precision='approximate',
            evidence=['terminal popular', 't1']), tools)
        self.assertIn('wrong_city', [o['reason'] for o in objections])

    def test_alias_does_not_suppress_precision_or_city_reviews(self):
        candidate = dict(osm_type='node', osm_id='11')
        for reason in ('wrong_city', 'overstated', 'caller_location'):
            obj = dict(field='location', reason=reason, quote='terminal popular')
            reviewer = location._CandidateCritic(Script([], [obj]), candidate,
                [dict(quote='terminal popular', alias_row=terminal()['curated_aliases'][0])])
            out, _ = reviewer.call('critic', '', '', time.monotonic()+10)
            self.assertEqual(out['objections'], [obj])

    def test_catalogue_alias_target_and_context_exceptions(self):
        from app.data.source import LocalSource
        rows = LocalSource().landmarks()
        text = 'Há vizinhos aguardando junto da rodoviária de Porto Alegre.'
        out, client, _ = self.locate(text, rows)
        self.assertEqual(out[3]['candidate']['candidate_id'], 'osm:way:236479491')
        self.assertEqual(client.roles, [])
        from app.geo.landmarks import exact_evidence
        for text, forbidden in (
            ('Socorro na Escola Salgado Filho em Porto Alegre.', '5320213'),
            ('Socorro na estação aeroporto em Porto Alegre.', '5320213'),
            ('Socorro no Brique da Redenção em Porto Alegre.', '3190472'),
            ('Socorro no banco de sangue do Clínicas em Porto Alegre.', '126014206'),
        ):
            with self.subTest(text=text):
                hits = exact_evidence(rows, text, {'Porto Alegre'})
                self.assertFalse(any(h['alias_row'] and h['row']['osm_id'] == forbidden for h in hits))


if __name__ == '__main__':
    unittest.main()
