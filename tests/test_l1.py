"""Location tools and bounded policy regressions; no provider/network required."""
import json
import time
import unittest
from app.agents.location_tools import LocationTools
from app.agents import location

REPLAY = '2024-05-06T14:00:00-03:00'


def street(name, city='Canoas'):
    return {'display_name': name, 'municipality': city, 'segments': '2',
            'any_in_water_2024-05-06': '1', 'any_in_water_2024-05-08': '0'}


def place(name, city='Canoas', category='amenity:school', osm_id='11', **kw):
    return dict(name=name, municipality=city, category=category, osm_type='node',
                osm_id=osm_id, lat='-29.9', lon='-51.18', alt_names='',
                neighbourhood='', street='', housenumber='', **kw)


class Script:
    def __init__(self, actions, objections=()):
        self.actions = iter(actions)
        self.roles = []
        self.objections = list(objections)

    def call(self, role, system, payload, deadline):
        self.roles.append(role)
        output = {'objections': self.objections} if role == 'critic' else next(self.actions)
        return output, dict(role=role, model='SCRIPTED', receipt='offline', seconds=0)


class LocationToolsTests(unittest.TestCase):
    def tools(self, text='Rua Brasil, Canoas. escola Aurora.', replay=REPLAY):
        return LocationTools([street('Rua Brasil'), street('Rua Brasil', 'Porto Alegre'),
                              street('Avenida Esperança')],
                             [place('Escola Aurora'), place('Mathias Velho', category='place:suburb', osm_id='12')],
                             text, replay)

    def test_city_scope_designators_and_fuzzy(self):
        tools = self.tools()
        self.assertEqual(len(tools.search_street('Av. Brasil', 'Canoas')), 1)
        self.assertEqual(tools.search_street('Rua Espernça', 'Canoas')[0]['name'], 'Avenida Esperança')
        self.assertEqual(len(tools.search_street('Rua Brasil')), 2)
        self.assertEqual(tools.search_street('Rua Brasil', 'Recife'), [])

    def test_water_never_uses_future_or_claims_safety(self):
        for replay, observed, overlap in [('2024-05-05', None, None), ('2024-05-06', '2024-05-06', True),
                                          ('2024-05-07', '2024-05-06', True), ('2024-05-08', '2024-05-08', False)]:
            c = self.tools(replay=replay).search_street('Brasil', 'Canoas')[0]
            self.assertEqual(c['observed_date'], observed)
            self.assertEqual(c['retrospective_water_overlap'], overlap)
            self.assertIsNone(c['in_water_by_date'])
            self.assertTrue(c['retrospective'])

    def test_alias_category_and_bairro_area(self):
        tools = LocationTools([], [place('Escola Aurora', curated_aliases=[{'alias': 'colegio aurora'}]),
                                  place('Mathias Velho', category='place:suburb', osm_id='12')],
                              'colegio aurora no Mathias Velho', REPLAY)
        self.assertEqual(tools.search_landmark('colegio aurora', category='school')[0]['name'], 'Escola Aurora')
        self.assertEqual(tools.search_landmark('Aurora', category='hospital'), [])
        bairro = tools.search_bairro('Mathias Velho')[0]
        self.assertEqual((bairro['city'], bairro['precision']), ('Canoas', 'area'))
        self.assertEqual(bairro['geometry_kind'], 'catalogue_centroid')

    def test_exact_quote_and_caller_only_evidence(self):
        tools = self.tools('Moro em Porto Alegre. Mas 2 pessoas na Rua Brasil em Canoas.')
        self.assertTrue(tools.check_text('Moro em Porto Alegre')['exists'])
        with self.assertRaises(ValueError):
            tools.execute('search_street', {'name': 'Brasil'}, 'Moro em Porto Alegre')
        with self.assertRaises(ValueError):
            tools.execute('search_street', {'name': 'Brasil'}, 'RUA BRASIL')

    def test_near_filters_city_radius_and_category(self):
        tools = LocationTools([], [place('Escola Aurora'), place('Mercado Lua', category='shop:supermarket', osm_id='20'),
                                  place('Outro', city='Porto Alegre', category='shop:supermarket', osm_id='21')], '', REPLAY)
        anchor = tools.search_landmark('Aurora', 'Canoas')[0]
        hits = tools.near(anchor['candidate_id'], 200, 'market')
        self.assertEqual([c['name'] for c in hits], ['Mercado Lua'])
        with self.assertRaises(ValueError):
            tools.near(anchor['candidate_id'], 100000)

    def test_corner_uses_overlap_only_and_labels_proxy(self):
        points = [dict(display_name=n, municipality='Canoas', lat='-29.9', lon='-51.18',
                       bbox='[-51.19,-29.91,-51.17,-29.89]') for n in ('Rua Brasil', 'Rua Aurora')]
        tools = LocationTools([street('Rua Brasil'), street('Rua Aurora')], [], '', REPLAY, points=points)
        a, b = (tools.search_street(n, 'Canoas')[0] for n in ('Brasil', 'Aurora'))
        c = tools.near(a['candidate_id'], 200, 'intersection', other_anchor_id=b['candidate_id'])[0]
        self.assertEqual(c['precision'], 'approximate')
        self.assertEqual(c['geometry_kind'], 'bbox_overlap_proxy')

    def test_city_inside_street_name_is_not_a_city_scope(self):
        tools = LocationTools([street('Rua Porto Alegre')], [], 'Socorro na Rua Porto Alegre.', REPLAY)
        with self.assertRaises(ValueError):
            tools.execute('search_street', {'name': 'Rua Porto Alegre', 'city': 'Porto Alegre'}, 'Rua Porto Alegre')

    def test_unique_bairro_can_scope_a_street_search(self):
        tools = self.tools('Rua Brasil no bairro Mathias Velho, socorro.')
        result = tools.execute('search_street', {'name': 'Brasil', 'city': 'Canoas'}, 'Rua Brasil')
        self.assertEqual(len(result['candidates']), 1)

    def test_search_quote_cannot_authorize_an_unrelated_name(self):
        tools = self.tools('Rua Brasil em Canoas, socorro.')
        with self.assertRaises(ValueError):
            tools.execute('search_street', {'name': 'Esperança', 'city': 'Canoas'}, 'socorro')

    def test_near_requires_an_anchor_returned_in_this_conversation(self):
        tools = self.tools()
        cid = tools.search_landmark('Aurora', 'Canoas')[0]['candidate_id']
        with self.assertRaises(ValueError):
            tools.execute('near', {'anchor_id': cid, 'radius_m': 200}, 'escola Aurora')

    def test_city_name_alone_cannot_mean_a_station_or_street(self):
        tools = LocationTools([street('Rua Canoas')], [place('Canoas', category='public_transport:station')],
                              'Socorro em Canoas.', REPLAY)
        for tool in ('search_street', 'search_landmark'):
            with self.subTest(tool=tool), self.assertRaises(ValueError):
                tools.execute(tool, {'name': 'Canoas'}, 'Canoas')

    def test_bairro_from_landmark_search_still_has_area_precision(self):
        tools = self.tools()
        c = tools.search_landmark('Mathias Velho', 'Canoas')[0]
        self.assertEqual(c['precision'], 'area')
        self.assertEqual(c['kind'], 'bairro')

    def test_caller_near_landmark_is_not_an_incident_anchor(self):
        from app.geo.incident import incident_text
        for phrase in ('Moro perto da Escola Aurora em Canoas.', 'Moro ao lado da Escola Aurora em Canoas.',
                       'Estou ligando de Canoas.'):
            scoped = incident_text(phrase+' Mas as vítimas estão sem endereço conhecido.')
            self.assertNotIn('canoas', scoped)


class LocationLoopTests(unittest.TestCase):
    def setUp(self):
        self.text = 'Socorro, 2 pessoas perto da Escola Aurora em Canoas.'
        self.tools = LocationTools([], [place('Escola Aurora')], self.text, REPLAY)
        self.cid = self.tools.search_landmark('Escola Aurora', 'Canoas')[0]['candidate_id']

    def answer(self, evidence=None, precision='approximate', candidate_id=None):
        return {'answer': {'candidate_id': candidate_id or self.cid, 'precision': precision,
                           'evidence': evidence if evidence is not None else ['Escola Aurora', 't1']}}

    def run_agent(self, client, tools=None):
        return location.run(client, (tools or self.tools).text, '', time.monotonic()+10,
                            tools=tools or self.tools)

    def test_tools_answer_critic_and_auditable_steps(self):
        client = Script([{'tool': 'search_landmark', 'args': {'name': 'Escola Aurora', 'city': 'Canoas'},
                          'why_quote': 'Escola Aurora'}, self.answer()])
        result, metas = self.run_agent(client)
        self.assertEqual(result['answer']['candidate_id'], self.cid)
        self.assertEqual(client.roles, ['location_agent', 'location_agent', 'critic'])
        event = result['steps'][0]
        for field in ('role', 'step', 'tool', 'args', 'result_ids', 'model', 'receipt', 'seconds'):
            self.assertIn(field, event)
        self.assertEqual(event['role'], 'location_agent')
        self.assertEqual(len(metas), 3)

    def test_four_tools_then_forced_answer(self):
        action = {'tool': 'check_text', 'args': {'quote': 'Socorro'}, 'why_quote': 'Socorro'}
        result, _ = self.run_agent(Script([action]*5))
        self.assertEqual(result['tool_steps'], 4)
        self.assertIsNone(result['answer']['candidate_id'])
        self.assertTrue(result['fallback'])

    def test_unseen_candidate_and_fake_evidence_are_rejected(self):
        for evidence in (['Escola Aurora'], ['Escola Aurora', 't999'], ['frase inventada', 't1']):
            with self.subTest(evidence=evidence):
                result, _ = self.run_agent(Script([self.answer(evidence), self.answer(evidence)]))
                self.assertIsNone(result['answer']['candidate_id'])

    def test_wrong_city_cannot_be_approved_by_empty_critic(self):
        text = 'Socorro na Escola Aurora em Canoas.'
        tools = LocationTools([], [place('Escola Aurora', city='Porto Alegre')], text, REPLAY)
        cid = tools.search_landmark('Aurora')[0]['candidate_id']
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora'}, 'why_quote': 'Escola Aurora'}
        bad = self.answer(candidate_id=cid)
        result, _ = self.run_agent(Script([action, bad, bad]), tools)
        self.assertIsNone(result['answer']['candidate_id'])
        self.assertTrue(any(o['reason'] == 'wrong_city' for o in result['objections']))

    def test_critic_objection_allows_only_one_revision(self):
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora'}, 'why_quote': 'Escola Aurora'}
        client = Script([action, self.answer(), {'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}],
                        [{'field': 'location', 'reason': 'overstated', 'quote': 'perto da'}])
        result, _ = self.run_agent(client)
        self.assertIsNone(result['answer']['candidate_id'])
        self.assertEqual(client.roles.count('critic'), 1)
        self.assertTrue(result['revision'])

    def test_model_cannot_promote_nearby_to_exact(self):
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora'}, 'why_quote': 'Escola Aurora'}
        result, _ = self.run_agent(Script([action, self.answer(precision='exact'), self.answer(precision='exact')]))
        self.assertIsNone(result['answer']['candidate_id'])

    def test_expired_deadline_never_calls_provider(self):
        client = Script([])
        result, _ = location.run(client, self.text, '', time.monotonic()-1, tools=self.tools)
        self.assertEqual(client.roles, [])
        self.assertTrue(result['fallback'])

    def test_city_outside_catalogue_cannot_be_overridden(self):
        tools = LocationTools([], [place('Escola Aurora')], 'Socorro na Escola Aurora em Recife.', REPLAY)
        cid = tools.search_landmark('Aurora')[0]['candidate_id']
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora'}, 'why_quote': 'Escola Aurora'}
        result, _ = self.run_agent(Script([action, self.answer(candidate_id=cid), self.answer(candidate_id=cid)]), tools)
        self.assertIsNone(result['answer']['candidate_id'])

    def test_repeated_wrong_city_cannot_dispatch_via_fallback(self):
        from app.decide import decide
        fields = {'street': {'value': 'Rua Brasil', 'quote': 'Rua Brasil'},
                  'municipality': {'value': 'Canoas', 'quote': 'Canoas'},
                  'people': {'value': 2, 'quote': '2 pessoas'}}
        rows = [street('Rua Brasil')]
        lm = [place('Escola Aurora', city='Porto Alegre')]
        text = 'Socorro 2 pessoas na Rua Brasil, Canoas, perto da Escola Aurora.'
        tools = LocationTools(rows, lm, text, REPLAY)
        cid = tools.search_landmark('Aurora')[0]['candidate_id']
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora'}, 'why_quote': 'Escola Aurora'}
        checks, cross, landmark, stage, _ = location.locate(rows, lm, fields, text, REPLAY,
            Script([action, self.answer(candidate_id=cid), self.answer(candidate_id=cid)]), time.monotonic()+10)
        decision = decide(fields, checks, REPLAY, REPLAY, cross_location=cross, landmark_location=landmark, life_safety=True)
        self.assertEqual(decision['decision'], 'CALLBACK')

    def test_fast_path_must_not_use_callers_address(self):
        fields = {'street': {'value': 'Rua Brasil', 'quote': 'Rua Brasil'},
                  'number': {'value': '90', 'quote': '90'},
                  'municipality': {'value': 'Canoas', 'quote': 'Canoas'}}
        text = 'Moro na Rua Brasil 90 em Canoas. Mas as vítimas estão num lugar que não conheço.'
        client = Script([{'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}])
        checks, _, _, stage, _ = location.locate([street('Rua Brasil')], [], fields, text, REPLAY,
                                               client, time.monotonic()+10)
        self.assertEqual(stage['location_path'], 'agent')
        self.assertFalse(checks['found'])

    def test_exact_address_fast_path_has_zero_calls(self):
        fields = {k: {'value': v, 'quote': v} for k, v in
                  [('street', 'Rua Brasil'), ('number', '90'), ('municipality', 'Canoas')]}
        client = Script([])
        checks, _, _, stage, _ = location.locate([street('Rua Brasil')], [], fields,
            'Socorro na Rua Brasil 90, Canoas.', REPLAY, client, time.monotonic()+10)
        self.assertTrue(checks['found'])
        self.assertEqual(stage['location_path'], 'deterministic')
        self.assertEqual(client.roles, [])

    def test_stale_city_field_cannot_take_exact_fast_path(self):
        fields = {k: {'value': v, 'quote': v} for k, v in
                  [('street', 'Rua Brasil'), ('number', '90'), ('municipality', 'Porto Alegre')]}
        client = Script([{'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}])
        checks, _, _, stage, _ = location.locate([street('Rua Brasil'), street('Rua Brasil', 'Porto Alegre')], [], fields,
            'Socorro na Rua Brasil 90, Canoas.', REPLAY, client, time.monotonic()+10)
        self.assertFalse(checks['found'])
        self.assertEqual(stage['location_path'], 'agent')

    def test_approximate_landmark_keeps_h3_life_safety_send(self):
        from app.decide import decide
        fields = {'people': {'value': 2, 'quote': '2 pessoas'}}
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora', 'city': 'Canoas'}, 'why_quote': 'Escola Aurora'}
        checks, cross, landmark, stage, _ = location.locate([], [place('Escola Aurora')], fields, self.text, REPLAY,
            Script([action, self.answer()]), time.monotonic()+10)
        result = decide(fields, checks, REPLAY, REPLAY, cross_location=cross, landmark_location=landmark, life_safety=True)
        self.assertEqual(result['decision'], 'SEND_CANDIDATE')
        self.assertTrue(result['location_approximate'])
        self.assertEqual(stage['precision'], 'approximate')

    def test_bairro_area_is_not_a_precise_dispatch_position(self):
        from app.decide import decide
        text = '2 pessoas no bairro Mathias Velho, Canoas.'
        tools = LocationTools([], [place('Mathias Velho', category='place:suburb')], text, REPLAY)
        cid = tools.search_bairro('Mathias Velho')[0]['candidate_id']
        action = {'tool': 'search_bairro', 'args': {'name': 'Mathias Velho'}, 'why_quote': 'Mathias Velho'}
        answer = {'answer': {'candidate_id': cid, 'precision': 'area', 'evidence': ['Mathias Velho', 't1']}}
        fields = {'people': {'value': 2, 'quote': '2 pessoas'}}
        checks, cross, landmark, stage, _ = location.locate([], tools.landmarks, fields, text, REPLAY,
            Script([action, answer]), time.monotonic()+10)
        result = decide(fields, checks, REPLAY, REPLAY, cross_location=cross, landmark_location=landmark, life_safety=True)
        self.assertEqual(result['decision'], 'CALLBACK')
        self.assertEqual(stage['candidate']['city'], 'Canoas')

    def test_two_branches_in_same_city_require_disambiguation(self):
        tools = LocationTools([], [place('Escola Aurora'),
            {**place('Escola Aurora', osm_id='22'), 'lat': '-29.95'}], self.text, REPLAY)
        cid = tools.search_landmark('Aurora', 'Canoas')[0]['candidate_id']
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora', 'city': 'Canoas'}, 'why_quote': 'Escola Aurora'}
        bad = self.answer(candidate_id=cid)
        result, _ = self.run_agent(Script([action, bad, bad]), tools)
        self.assertIsNone(result['answer']['candidate_id'])

    def test_tool_steps_are_written_to_trace(self):
        from pathlib import Path
        from support import Scratch
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        trace = Path(scratch.name)/'location.jsonl'
        action = {'tool': 'search_landmark', 'args': {'name': 'Aurora'}, 'why_quote': 'Escola Aurora'}
        result, _ = location.run(Script([action, self.answer()]), self.text, '', time.monotonic()+10,
                                 tools=self.tools, trace=trace)
        events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(events), len(result['steps']))
        self.assertEqual(events[0]['result_ids'][0], 't1')
        self.assertEqual(events[0]['why_quote'], 'Escola Aurora')


if __name__ == '__main__':
    unittest.main()
