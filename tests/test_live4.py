"""Synthetic regressions for privacy, incident-city search and degraded review."""
import contextlib
import io
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents import critic, location
from app.agents.location_tools import LocationTools
from app.decide import decide
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline, validate_request
from app.redact import redact, redact_data
from support import Scratch
from test_l1 import REPLAY, place, street


class Privacy(unittest.TestCase):
    def test_distinct_numeric_message_ids_survive_validation(self):
        ids = ['contact-'+str(12000000000+i) for i in range(2)]
        _, messages = validate_request(dict(replay_time=REPLAY, messages=[
            dict(message_id=mid, text='Preciso de ajuda.') for mid in ids]))
        self.assertEqual(len({m['message_id'] for m in messages}), 2)
        self.assertTrue(all(m['message_id'].startswith('external-') for m in messages))

    def test_serialized_structured_values_survive_but_message_pii_does_not(self):
        digits = str(12000000001)
        value = dict(message_id=digits, candidate_id='osm:node:'+digits, osm_id=digits,
                     lat=-30.12345678901, lon=-51.12345678901, result_ids=[digits],
                     text='CPF '+digits, why_quote='Meu CPF '+digits)
        clean = redact_data(value)
        self.assertTrue(clean['message_id'].startswith('external-'))
        for key in ('candidate_id', 'osm_id', 'lat', 'lon', 'result_ids'):
            self.assertEqual(clean[key], value[key])
        self.assertIn('[CPF REDIGIDO]', clean['text'])
        self.assertIn('[CPF REDIGIDO]', clean['why_quote'])

    def test_id_tokens_in_raw_text_cannot_exempt_personal_identifiers(self):
        digits = str(12000000001)
        for text in ('osm:node:'+digits, 'way:'+digits, 'relation:'+digits,
                     'message_id='+digits, 'candidate_id: '+digits):
            with self.subTest(text=text):
                self.assertNotIn(digits, redact(text))
        self.assertNotIn(str(1200000000), redact('Registro '+str(1200000000)))
        self.assertIn('[TELEFONE REDIGIDO]', redact('Telefone '+str(5100000000)))
        self.assertIn('[CPF REDIGIDO]', redact('CPF '+digits))

    def test_location_trace_keeps_ids_and_redacts_message_quotes(self):
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        trace = Path(scratch.name)/'location.jsonl'
        cid = 'osm:node:'+str(12000000001)
        location._record(dict(result_ids=['t1', cid], osm_id=str(12000000001),
                              why_quote='CPF '+str(12000000002)), trace, None)
        saved = json.loads(trace.read_text(encoding='utf-8'))
        self.assertEqual(saved['result_ids'], ['t1', cid])
        self.assertEqual(saved['osm_id'], str(12000000001))
        self.assertIn('[CPF REDIGIDO]', saved['why_quote'])


class CitySearch(unittest.TestCase):
    def setUp(self):
        self.places = [place('Jardim Lunar', category='place:suburb', osm_id='11'),
                       place('Jardim Lunar', 'Guaíba', category='place:suburb', osm_id='12'),
                       place('Balneário Jardim Lunar', category='place:suburb', osm_id='13'),
                       place('Mercado Estelar', osm_id='14'),
                       place('Mercado Estelar', 'Guaíba', osm_id='15')]

    def tools(self, text):
        return LocationTools([], self.places, text, REPLAY)

    def test_omitted_tool_city_uses_stated_incident_city(self):
        tools = self.tools('Moro em Guaíba. Mas 4 pessoas no Jardim Lunar em Canoas, água subindo.')
        for tool, name in (('search_bairro', 'Jardim Lunar'), ('search_landmark', 'Mercado Estelar')):
            text = '4 pessoas no '+name+' em Canoas, água subindo.'
            scoped = tools if tool == 'search_bairro' else self.tools(text)
            found = scoped.execute(tool, {'name': name}, name)
            self.assertTrue(found['candidates'])
            self.assertEqual({c['city'] for c in found['candidates']}, {'Canoas'})

    def test_bairro_city_argument_and_exact_name_preference(self):
        hits = self.tools('Jardim Lunar em Canoas').search_bairro('Jardim Lunar', city='Canoas')
        self.assertEqual([(c['name'], c['city']) for c in hits], [('Jardim Lunar', 'Canoas')])

    def test_no_city_keeps_cross_city_ambiguity(self):
        hits = self.tools('Jardim Lunar, água subindo.').search_bairro('Jardim Lunar')
        self.assertEqual({c['city'] for c in hits}, {'Canoas', 'Guaíba'})

    def test_explicit_wrong_tool_city_is_rejected(self):
        tools = self.tools('Jardim Lunar em Canoas, água subindo.')
        with self.assertRaises(ValueError):
            tools.execute('search_bairro', dict(name='Jardim Lunar', city='Guaíba'), 'Jardim Lunar')

    def test_life_safety_bairro_uses_flooded_area_point(self):
        text = '4 pessoas no bairro Jardim Lunar em Canoas, um idoso, água subindo.'
        fields = dict(people=dict(value=4, quote='4 pessoas'), municipality=dict(value='Canoas', quote='Canoas'))
        area = dict(flooded=True, point=dict(lat=-29.91, lon=-51.19), bbox=[-51.2, -29.92, -51.18, -29.9],
                    label='Área alagada retrospectiva; confirmar ponto.')
        with patch('app.geo.hydro.area_point', return_value=area):
            loc, cross, lm, stage, _ = location.locate([], self.places, fields, text, REPLAY,
                                                     None, time.monotonic()+10)
        result = decide(fields, loc, REPLAY, REPLAY, landmark_location=lm, life_safety=True)
        self.assertEqual(result['decision'], 'SEND_CANDIDATE')
        self.assertTrue(result['location_approximate'])
        self.assertEqual(lm['matched']['lat'], -29.91)
        self.assertEqual(lm['matched']['geometry_kind'], 'estimated_flooded_bairro')

    def test_unresolved_given_landmark_asks_for_missing_detail(self):
        fields = dict(people=dict(value=4), municipality=dict(value='Canoas'),
                      landmark=dict(value='Jardim Lunar', quote='Jardim Lunar'))
        result = decide(fields, {'found': False}, REPLAY, REPLAY,
                        landmark_location=dict(status='unresolved', requested=True))
        self.assertEqual(result['decision'], 'CALLBACK')
        self.assertNotIn('Qual o nome do lugar/bairro?', result['questions'])
        self.assertTrue(result['questions'])


class DegradedReview(unittest.TestCase):
    def test_critic_failure_keeps_completed_non_rescue_review(self):
        class Source:
            def streets(self, **kwargs):
                return [street('Rua Boreal')]
        class Reader:
            def call(self, role, system, payload, deadline):
                if role == 'intake':
                    return {'municipality': 'Canoas', 'landmark': 'Mercado Estelar', 'confidence': 'low'}, {'role': role}
                if role == 'critic':
                    raise TimeoutError('synthetic provider outage')
                raise AssertionError('Non-rescue does not need '+role)
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        with contextlib.redirect_stdout(io.StringIO()):
            output = Pipeline(Registry(Path(scratch.name)/'events.jsonl'), source=Source(), client=Reader()).run(
                dict(replay_time=REPLAY, messages=[dict(message_id='donation',
                     text='Coleta de mantimentos no Mercado Estelar em Canoas, quem puder doar agradeço.')]))
        case = output['cases'][0]
        self.assertEqual(case['route']['id'], 'not_a_rescue')
        self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')
        self.assertTrue(case['complete'])
        self.assertEqual(case['errors'], [])
        self.assertEqual(case['result']['questions'], [])
        self.assertIn('crítico indisponível', ' '.join(case['result']['warnings']))
        self.assertEqual(case['agents']['critic'], 'failed')
        self.assertEqual(case['agents']['location']['location_path'], 'not_required')

    def test_critic_receives_bounded_remaining_budget(self):
        deadlines = []
        class Reader:
            def call(self, role, system, payload, deadline):
                deadlines.append(deadline)
                return {'objections': []}, {'role': role}
        with patch('app.agents.critic.time.monotonic', return_value=100):
            critic.run(Reader(), 'Ajuda', {}, 580)
            critic.run(Reader(), 'Ajuda', {}, 104)
        self.assertLessEqual(deadlines[0], 130)
        self.assertLess(deadlines[1], 104)

    def test_location_loop_stops_at_its_stage_deadline(self):
        clock = [100]
        class Reader:
            def call(self, role, system, payload, deadline):
                clock[0] += 61
                return {'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}, {'role': role}
        tools = LocationTools([], [], 'Local desconhecido em Canoas', REPLAY)
        with patch('app.agents.location.time.monotonic', side_effect=lambda: clock[0]):
            result, _ = location.run(Reader(), tools.text, 'Canoas', 580, tools=tools)
        self.assertTrue(result['fallback'])
        self.assertEqual(result['error'], 'TimeoutError')

    def test_critic_rejects_a_response_after_remaining_stage_budget(self):
        clock = [100]
        class Reader:
            def call(self, role, system, payload, deadline):
                clock[0] = 102
                return {'objections': []}, {'role': role}
        with patch('time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                critic.run(Reader(), 'Ajuda', {}, 104)
