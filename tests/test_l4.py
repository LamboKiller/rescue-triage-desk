"""General address, evidence preservation, budget and diagnostic regressions."""
import contextlib
import importlib.util
import io
import json
import queue
from pathlib import Path
import time
import unittest
from unittest.mock import patch
from app.agents import intake, location
from app.geo.incident import IncidentIndex
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry
from support import Scratch
from test_l1 import street, place, Script, REPLAY


class AddressTests(unittest.TestCase):
    def resolve(self, text, roads, landmarks=(), fields=None):
        fields = fields if fields is not None else {}
        index = IncidentIndex(roads, landmarks)
        index.resolve(fields, text)
        client = Script([{'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}])
        out = location.locate(roads, landmarks, fields, text, REPLAY, client,
                              time.monotonic()+10, index=index)
        return fields, out, client

    def test_city_aliases_and_number_after_street(self):
        for alias, city in [('poa', 'Porto Alegre'), ('porto alegre/rs', 'Porto Alegre'),
                            ('sl', 'São Leopoldo'), ('nh', 'Novo Hamburgo')]:
            for separator in (' ', ', ', ', nº ', ' número '):
                text = 'Necesitamos ajuda na rua Aurora'+separator+'743 em '+alias+'.'
                rival = 'Canoas' if city != 'Canoas' else 'Porto Alegre'
                fields, out, client = self.resolve(text, [street('Rua Aurora', city), street('Rua Aurora', rival)])
                self.assertEqual(fields['municipality']['value'], city)
                self.assertEqual(fields['number']['value'], '743')
                self.assertTrue(out[0]['found'])
                self.assertEqual(client.roles, [])

    def test_designator_difference_and_unrelated_other_city_street(self):
        text = 'Socorro na rua Aurora 638 em São Leopoldo, água na rua e vento forte.'
        fields, out, client = self.resolve(text, [street('Avenida Aurora', 'São Leopoldo'),
                                                      street('Rua E', 'Canoas')])
        self.assertTrue(out[0]['found'])
        self.assertEqual(out[3]['location_path'], 'deterministic')
        self.assertEqual(client.roles, [])

    def test_number_and_landmark_do_not_disable_deterministic_match(self):
        text = '2 pessoas na Rua Aurora 742 em Canoas perto do mercado.'
        fields = {'landmark': {'value': 'perto do mercado', 'quote': 'perto do mercado'}}
        fields, out, client = self.resolve(text, [street('Rua Aurora')], fields=fields)
        self.assertTrue(out[0]['found'])
        self.assertEqual(fields['number']['value'], '742')
        self.assertEqual(client.roles, [])

    def test_avenue_without_number_keeps_street_evidence(self):
        text = 'Socorro, 2 pessoas no telhado na Avenida Aurora no bairro Jardim Lunar.'
        roads = [street('Avenida Aurora'), street('Avenida Aurora', 'Porto Alegre')]
        landmarks = [place('Jardim Lunar', category='place:suburb')]
        fields, out, client = self.resolve(text, roads, landmarks)
        self.assertTrue(out[0]['found'])
        self.assertEqual(out[3]['precision'], 'approximate')
        self.assertEqual(client.roles, [])

    def test_street_and_bairro_intersection_disambiguates_city(self):
        text = 'Socorro na Rua Aurora 734 no bairro Jardim Lunar.'
        roads = [street('Rua Aurora'), street('Rua Aurora', 'Porto Alegre')]
        landmarks = [place('Jardim Lunar', category='place:suburb'),
                     place('Jardim Lunar', city='Novo Hamburgo', category='place:suburb', osm_id='22')]
        fields, out, client = self.resolve(text, roads, landmarks)
        self.assertEqual(fields['municipality']['value'], 'Canoas')
        self.assertTrue(out[0]['found'])
        self.assertEqual(client.roles, [])

    def test_explicit_contradiction_or_two_places_cannot_fast_path(self):
        roads = [street('Rua Aurora'), street('Rua Boreal')]
        for text in ('Socorro na Rua Aurora 742 em Canoas ou na Rua Boreal 931 em Canoas.',
                     'Ligo da Rua Aurora 742 em Canoas. Mas o resgate é em Recife.'):
            _, out, _ = self.resolve(text, roads)
            self.assertFalse(out[0]['found'])

    def test_scoped_landmark_ignores_caller_and_preserves_evidence(self):
        text = 'Ligo da Rua Boreal em Porto Alegre. Mas resgatem na Escola Aurora em Canoas.'
        _, out, client = self.resolve(text, [street('Rua Boreal', 'Porto Alegre')],
                                      [place('Escola Aurora')])
        self.assertEqual(out[2]['status'], 'resolved')
        self.assertEqual(client.roles, [])

    def test_cross_street_policy_abstention_cannot_erase_primary_match(self):
        text = 'Socorro na Rua Aurora com Rua Boreal em Canoas, 2 pessoas.'
        fields = {k: dict(value=v, quote=v) for k, v in
                  [('street', 'Rua Aurora'), ('cross_street', 'Rua Boreal'), ('municipality', 'Canoas')]}
        _, out, client = self.resolve(text, [street('Rua Aurora'), street('Rua Boreal')], fields=fields)
        self.assertTrue(client.roles)
        self.assertTrue(out[0]['found'])
        self.assertTrue(out[1]['found'])

    def test_landmark_island_context_resolves_before_policy(self):
        text = 'Socorro perto da Igreja Aurora Boreal na Ilha Lunar em Canoas.'
        landmarks = [place('Igreja Aurora Boreal', category='amenity:place_of_worship'),
                     place('Igreja Aurora Boreal', category='amenity:place_of_worship', osm_id='22'),
                     place('Ilha Lunar', category='place:island', osm_id='33')]
        landmarks[1].update(lat='-30.1', lon='-51.4')
        fields = dict(landmark=dict(value='Igreja Aurora Boreal na Ilha Lunar', quote='Igreja Aurora Boreal na Ilha Lunar'))
        _, out, client = self.resolve(text, [], landmarks, fields)
        self.assertEqual(out[2]['status'], 'resolved')
        self.assertEqual(out[2]['matched']['osm_id'], '11')
        self.assertEqual(client.roles, [])


class BudgetTests(unittest.TestCase):
    def test_queued_messages_receive_full_budget_and_critic_is_kept(self):
        class Source:
            def streets(self, **kwargs):
                return [street('Rua Aurora')]
        class Reader:
            def __init__(self):
                self.roles = []
                self.remaining = []
            def call(self, role, system, payload, deadline):
                self.roles.append(role)
                if role == 'intake':
                    return {'people': '2 pessoas', 'street': 'Rua Aurora', 'number': '473',
                            'municipality': 'Canoas'}, {'role': role}
                return {'objections': []}, {'role': role}
        reader = Reader()
        run_intake = intake.run
        def delayed_intake(client, text, deadline, objections=None):
            # Observe the message deadline, before StageBudget caps the call.
            reader.remaining.append(deadline-time.monotonic())
            # Worker time outside the provider stage still consumes this message's budget.
            time.sleep(.3)
            return run_intake(client, text, deadline, objections)
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        with patch('app.pipeline.intake.run', side_effect=delayed_intake), \
                patch('app.pipeline.hazard_critic.attach'), contextlib.redirect_stdout(io.StringIO()):
            output = Pipeline(Registry(Path(scratch.name)/'events.jsonl'), source=Source(),
                              client=reader, budget_seconds=.8, max_workers=1).run({
                'replay_time': REPLAY, 'messages': [dict(message_id=str(i),
                    text='2 pessoas na Rua Aurora 473 em Canoas.') for i in range(4)]})
        self.assertTrue(all(c['complete'] for c in output['cases']))
        self.assertEqual(len(reader.remaining), 4)
        self.assertTrue(all(r > .6 for r in reader.remaining))
        self.assertEqual(reader.roles.count('critic'), 0)
        self.assertNotIn('revision', reader.roles)
        self.assertNotIn('location_agent', reader.roles)

    def test_critic_without_objections_skips_revision_after_rejected_field(self):
        class Source:
            def streets(self, **kwargs):
                return [street('Rua Aurora')]
        roles = []
        class Reader:
            def call(self, role, system, payload, deadline):
                roles.append(role)
                return ({'people': '2 pessoas', 'street': 'Rua Aurora', 'number': '381',
                         'municipality': 'Canoas', 'elderly': '3 idosos'} if role == 'intake'
                        else {'objections': []}), {'role': role}
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        with patch('app.pipeline.hazard_critic.attach'), contextlib.redirect_stdout(io.StringIO()):
            case = Pipeline(Registry(Path(scratch.name)/'events.jsonl'), source=Source(), client=Reader()).run({
                'replay_time': REPLAY, 'messages': [dict(message_id='clean-critic',
                    text='2 pessoas na Rua Aurora 381 em Canoas.')]})['cases'][0]
        self.assertTrue(case['unsupported'])
        self.assertNotIn('elderly', case['fields'])
        self.assertEqual(roles, ['intake', 'critic'])

    def test_expired_message_does_not_expire_queued_successor(self):
        class Source:
            def streets(self, **kwargs):
                return [street('Rua Aurora')]
        class Reader:
            def call(self, role, system, payload, deadline):
                if role == 'intake':
                    time.sleep(.4 if 'lento' in payload else .03)
                    return {'people': '2 pessoas', 'street': 'Rua Aurora', 'number': '935',
                            'municipality': 'Canoas'}, {'role': role}
                return {'objections': []}, {'role': role}
        remaining = []
        run_intake = intake.run
        def delayed_intake(client, text, deadline, objections=None):
            remaining.append(deadline-time.monotonic())
            if 'lento' in text:
                # Force the message deadline itself to expire, independently of
                # the earlier provider-stage fallback introduced by A1L.
                time.sleep(.4)
            return run_intake(client, text, deadline, objections)
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        with patch('app.pipeline.intake.run', side_effect=delayed_intake), \
                patch('app.pipeline.hazard_critic.attach'), contextlib.redirect_stdout(io.StringIO()):
            output = Pipeline(Registry(Path(scratch.name)/'events.jsonl'), source=Source(),
                              client=Reader(), budget_seconds=.25, max_workers=1).run({
                'replay_time': REPLAY, 'messages': [dict(message_id=str(i),
                    text='2 pessoas na Rua Aurora 935 em Canoas. '+label)
                    for i, label in enumerate(('lento', 'rápido'))]})
        cases = {c['message_id']: c for c in output['cases']}
        self.assertTrue(cases['0']['intake_degraded'])
        self.assertNotEqual(cases['0']['result']['decision'], 'SEND_CANDIDATE')
        self.assertTrue(set(cases['0']['errors']) <= {'message_deadline'})
        self.assertTrue(cases['1']['complete'])
        self.assertEqual(len(remaining), 2)
        self.assertTrue(all(r > .2 for r in remaining))


def runner_module():
    path = Path(__file__).resolve().parents[2]/'open-agent-hackathon-2026/tools/run_holdout.py'
    if not path.is_file():
        raise unittest.SkipTest('External planning runner is not installed in this checkout.')
    spec = importlib.util.spec_from_file_location('l4_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerTests(unittest.TestCase):
    def test_location_eval_script_accepts_compact_protocol(self):
        from eval.run_location import ScriptedPolicy
        from app.agents.location_tools import LocationTools
        roads = [street('Rua Aurora')]
        text = 'Socorro na Rua Aurora em Canoas.'
        index = IncidentIndex(roads, [])
        fixture = ScriptedPolicy(roads, [], index)
        action, _ = fixture.call('location_agent', '', location.step_prompt(text, 'Canoas', [], 3), 0)
        tools = LocationTools(roads, [], text, REPLAY, index=index)
        result = tools.execute(action['tool'], action['args'], action['why_quote'])
        answer, _ = fixture.call('location_agent', '', location.step_prompt(text, 'Canoas', [result], 2), 0)
        self.assertEqual(answer['answer']['candidate_id'], result['candidates'][0]['candidate_id'])

    def test_evidence_dump_contains_extraction_and_location(self):
        runner = runner_module()
        fields = dict(street=dict(value='Rua Aurora', quote='rua aurora'))
        stage = dict(steps=[dict(tool='search_street', args=dict(name='Aurora'), result_ids=['t1'])],
                     answer=dict(candidate_id='street:1', precision='approximate'), objections=[])
        dump = runner.diagnostic_case(dict(fields=fields, agents=dict(intake=dict(fields=fields), location=stage),
                                           result=dict(decision_reason='Confirmar ponto exato.'), checks=dict(found=True)))
        self.assertEqual(dump['intake_fields'], fields)
        self.assertEqual(dump['location'], stage)
        self.assertTrue(dump['checks']['found'])
        self.assertEqual(dump['decision_reason'], 'Confirmar ponto exato.')

    def test_runner_timers_start_per_message_and_keep_finished_siblings(self):
        runner = runner_module()
        worker = object.__new__(runner.Worker)
        class Events:
            def __init__(self):
                self.items = iter([dict(event='message_started', message_id='a', budget_seconds=480),
                    dict(event='message_result', message_id='a', result=dict(status='result')),
                    dict(event='message_started', message_id='b', budget_seconds=480)])
                self.timeouts = []
            def get(self, timeout):
                self.timeouts.append(timeout)
                item = next(self.items, None)
                if item is None:
                    raise queue.Empty()
                return json.dumps(item)
        worker.queue = Events()
        with patch.object(runner.time, 'monotonic', side_effect=[0, 0, 0, 0, 400, 400, 400, 400, 400, 400, 400, 400]):
            with self.assertRaises(runner.BatchTimeout) as caught:
                worker.receive_batch([dict(message_id='a'), dict(message_id='b')])
        self.assertIn('a', caught.exception.completed)
        self.assertNotIn('b', caught.exception.completed)
        self.assertGreater(worker.queue.timeouts[-1], 480)


if __name__ == '__main__':
    unittest.main()
