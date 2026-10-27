"""Offline reproductions of missing journals and location budget starvation."""
import contextlib
import io
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents import intake, location
from app.engines.world_model.registry import Registry
from app.llm.nightshift import Nightshift, ProviderRefused
from app.pipeline import Pipeline, StageBudget
from tools.scratch import scratch as Scratch
from test_core import ROWS, TIME
from test_providers import Response


class Livefix6Tests(unittest.TestCase):
    def budget(self, client, seconds=60):
        end = time.monotonic()+seconds
        return StageBudget(client, end, seconds), end

    def case(self, client, seconds=60, text=None):
        class Source:
            def streets(self, **kwargs): return ROWS
        with Scratch() as folder, contextlib.redirect_stdout(io.StringIO()), \
             patch('app.contradictions.hook.after_decision'):
            return Pipeline(Registry(Path(folder)/'events.jsonl'), source=Source(), client=client,
                            budget_seconds=seconds).run(dict(replay_time=TIME, messages=[dict(
                message_id='lf6-synthetic', text=text or '4 pessoas na Rua das Flores 20 em Porto Alegre.')]))['cases'][0]

    def test_fake_failure_has_safe_call_and_stage_record(self):
        class Broken:
            def call(self, *args): raise ValueError('PRIVATE provider body sk-secret')
        case = self.case(Broken())
        self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')
        self.assertTrue(case['calls'])
        record = case['calls'][0]
        self.assertEqual(record['role'], 'intake')
        self.assertEqual(record['error_class'], 'ValueError')
        self.assertTrue(record['message'])
        self.assertNotIn('PRIVATE', json.dumps(case))
        for field in ('role', 'seconds', 'queue_seconds', 'error_class', 'message'):
            self.assertIn(field, case['latency_budget']['stages'][0])

    def test_worker_setup_failure_is_not_an_empty_journal(self):
        class BrokenSetup(Nightshift):
            def start_message(self, mid): raise RuntimeError('PRIVATE setup failure')
        with Scratch() as folder:
            case = self.case(BrokenSetup(Path(folder)/'trace.jsonl'))
        self.assertTrue(case['calls'])
        self.assertEqual(case['calls'][0]['error_class'], 'RuntimeError')

    def test_pool_setup_failure_is_recorded(self):
        class Client:
            def call(self, *args): return {}, {}
        budget, end = self.budget(Client())
        with patch('app.pipeline.concurrent.futures.ThreadPoolExecutor', side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(RuntimeError): budget.call('intake', '', '', end)
        self.assertEqual(budget.receipts[0]['error_class'], 'RuntimeError')

    def test_timeout_keeps_completed_attempt_and_freezes_late_worker(self):
        entered, release = threading.Event(), threading.Event()
        class SlowRetry(Nightshift):
            def call(self, role, *args): return self._call(role, *args)
            def _call(self, role, *args):
                self._record(dict(role=role, status='failed', attempt=1, seconds=.01,
                                  error='ValueError', detail='empty_or_invalid_json'))
                entered.set()
                release.wait(2)
                self._record(dict(role=role, status='ok', attempt=2, seconds=.01))
                return {}, dict(role=role)
        with Scratch() as folder, contextlib.redirect_stdout(io.StringIO()):
            budget, end = self.budget(SlowRetry(Path(folder)/'trace.jsonl'), .3)
            try:
                with self.assertRaises(TimeoutError): budget.call('intake', '', '', end)
                self.assertTrue(entered.is_set())
                self.assertTrue(any(r.get('attempt') == 1 for r in budget.receipts))
                self.assertTrue(any(r.get('status') == 'timeout' for r in budget.receipts))
                saved = list(budget.receipts)
            finally:
                release.set()
                time.sleep(.04)
            self.assertEqual(budget.receipts, saved)

    def test_invalid_intake_shape_is_not_a_successful_empty_extraction(self):
        for raw in ([], {'fields': {'people': {'value': 4}}}, {'people': {'quote': '4 pessoas'}},
                    {'answer': {'people': '4 pessoas'}}):
            class Client:
                def call(self, role, *args): return raw, dict(role=role)
            with self.subTest(raw=raw):
                case = self.case(Client())
                self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')
                self.assertFalse(case['complete'])
                self.assertTrue(any(r['error_class'] == 'ValueError'
                                    for r in case['latency_budget']['stages']))

    def test_schema_and_json_retry_are_short_and_visible(self):
        for bad in ('[]', '{broken'):
            with self.subTest(bad=bad), Scratch() as folder, \
                 patch.dict('os.environ', {'NIGHTSHIFT_API_KEY': 'TEST-ONLY'}), \
                 patch('app.llm.nightshift.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
                responses = [Response(json.dumps({'choices':[{'message':{'content':value}}]}).encode())
                             for value in (bad, '{"people":"4 pessoas"}')]
                with patch('urllib.request.urlopen', side_effect=responses) as send:
                    client = Nightshift(Path(folder)/'trace.jsonl')
                    budget, end = self.budget(client)
                    output, _ = intake.run(budget, '4 pessoas', end)
                self.assertEqual(output['fields']['people']['value'], 4)
                self.assertEqual(len(budget.receipts), 2)
                self.assertEqual(budget.receipts[0]['error_class'], 'ValueError')
                retry = json.loads(send.call_args_list[1].args[0].data)
                self.assertLess(len(retry['messages'][0]['content']), len(intake.SYSTEM))
                self.assertGreaterEqual(retry['max_tokens'], 6000)
                self.assertNotIn('chat_template_kwargs', retry)

    def test_pre_location_optional_call_cannot_spend_location_minimum(self):
        class Client:
            def call(self, role, system, payload, deadline):
                self.end = deadline
                return {}, dict(role=role)
        client = Client()
        budget, end = self.budget(client, 40)
        budget.call('critic', '', '', end)
        self.assertLessEqual(client.end, budget.deadline-budget.reserve-budget.MEDIANS['location'])

    def test_protected_location_minimum_covers_recorded_lf5_median(self):
        self.assertGreaterEqual(StageBudget.MEDIANS['location'], 15.25)

    def test_long_intake_skips_critic_visibly(self):
        class Client:
            def call(self, role, *args): return {}, dict(role=role)
        budget, end = self.budget(Client())
        with patch.object(StageBudget, 'LONG_INTAKE_SECONDS', 0):
            budget.call('intake', '', '', end)
            with self.assertRaises(TimeoutError): budget.call('critic', '', '', end)
        self.assertEqual(budget.records[-1]['reason'], 'long_intake')
        self.assertEqual(budget.records[-1]['role'], 'critic')

    def test_skipped_advisory_critic_preserves_validated_rule_decision(self):
        class Client:
            def call(self, role, *args):
                if role == 'intake':
                    return dict(people='4 pessoas', street='Rua das Flores', number='20',
                                municipality='Porto Alegre', confidence='low'), dict(role=role)
                return dict(objections=[], brief_pt=''), dict(role=role)
        with patch.object(StageBudget, 'LONG_INTAKE_SECONDS', 0):
            case = self.case(Client())
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertFalse(case['review_degraded'])
        self.assertTrue(case['agent_warnings'])

    def test_no_location_model_budget_keeps_deterministic_address_send(self):
        class Client:
            def call(self, role, *args):
                if role == 'intake':
                    return dict(people='4 pessoas', street='Rua das Flores', number='20',
                                municipality='Porto Alegre'), dict(role=role)
                raise AssertionError('Optional model must yield')
        # Remove location/advisory model allowance without making the real
        # deterministic work race a sub-second Windows scheduling deadline.
        with patch.dict(StageBudget.MEDIANS, location=120., hazard=120.):
            case = self.case(Client())
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertEqual(case['location_precision'], 'exact')

    def test_no_location_budget_uses_code_fallback_without_timeout(self):
        class Client:
            def call(self, role, *args):
                if role == 'intake':
                    return dict(people='4 pessoas', municipality='Porto Alegre'), dict(role=role)
                raise AssertionError('No model budget')
        with patch.dict(StageBudget.MEDIANS, location=120., hazard=120.):
            case = self.case(Client(), text='4 pessoas perto do lugar desconhecido em Porto Alegre.')
        self.assertNotEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertNotIn('error', case['agents']['location'])
        self.assertTrue(any(r.get('reason') == 'insufficient_budget' and r['stage'] == 'location'
                            for r in case['latency_budget']['stages']))

    def test_refusal_and_queue_attempts_have_safe_diagnostics(self):
        class Client:
            def call(self, *args): raise ProviderRefused(503)
        budget, end = self.budget(Client())
        with self.assertRaises(ProviderRefused): budget.call('intake', '', '', end)
        self.assertEqual(budget.receipts[0]['failure_kind'], 'provider_refused')
        self.assertEqual(budget.receipts[0]['error_class'], 'ProviderRefused')

    def test_usage_counts_recorded_without_completion_text(self):
        data = {'choices':[{'message':{'content':'{}'}}],
                'usage':dict(prompt_tokens=180, completion_tokens=90, total_tokens=270,
                             completion_tokens_details=dict(reasoning_tokens=60))}
        with Scratch() as folder, patch.dict('os.environ', {'NIGHTSHIFT_API_KEY':'TEST-ONLY'}), \
             patch('urllib.request.urlopen', return_value=Response(json.dumps(data).encode())), \
             contextlib.redirect_stdout(io.StringIO()):
            client = Nightshift(Path(folder)/'trace.jsonl')
            client.start_message('usage-test')
            _, meta = client.call('intake', '', '', time.monotonic()+10)
        self.assertEqual(meta['usage'], data['usage'])
        self.assertNotIn('content', meta)

    def test_location_prompt_has_one_copy_of_json_instruction(self):
        class Client:
            remaining_budget_allocator = True
            def call(self, role, system, payload, deadline):
                self.system = system
                return dict(answer=dict(candidate_id=None, precision='area', evidence=[])), dict(role=role)
        client = Client()
        from app.agents.location_tools import LocationTools
        location.run(client, 'Lugar desconhecido', '', time.monotonic()+10,
                     tools=LocationTools(ROWS, [], 'Lugar desconhecido', TIME))
        self.assertEqual(client.system, location.SYSTEM)

    def test_hazard_schema_failure_is_in_stage_journal(self):
        from app.agents import hazard_critic
        class Client:
            def call(self, *args): return {}, {}
        budget, end = self.budget(Client())
        budget.location_complete = True
        case = dict(text='Teste sintético', fields={}, result={}, agents={})
        with patch('app.agents.hazard_critic.compact_input', return_value=dict(facts=[])):
            hazard_critic.attach(case, budget, end)
        self.assertTrue(any(r['stage'] == 'hazard' and r['error_class'] == 'ValueError' for r in budget.records))

    def test_credibility_validation_retry_is_in_stage_journal(self):
        from app.credibility import reviewer
        class Client:
            def call(self, *args): return {}, {}
        budget, end = self.budget(Client())
        budget.location_complete = True
        signals = [dict(id='s1', family='test', strength='weak', label_pt='Teste', quote='teste', detail='teste')]
        reviewer.review(budget, signals, end)
        self.assertTrue(any(r['stage'] == 'credibility' and r['error_class'] == 'ValueError' for r in budget.records))

    def test_arbiter_validation_failure_is_in_stage_journal(self):
        from app.agents import arbiter
        class Client:
            def call(self, *args): return {}, {}
        budget, end = self.budget(Client())
        budget.location_complete = True
        conflict = dict(claims=[dict(id='a')])
        with patch('app.agents.arbiter._valid_claims', return_value=True), \
             patch('app.agents.arbiter._rule', return_value=(None, None)):
            event = arbiter.resolve(conflict, budget, end)
        self.assertEqual(event['verdict'], 'ESCALATE')
        self.assertTrue(any(r['stage'] == 'arbiter' and r['error_class'] == 'ValueError' for r in budget.records))

    def test_outer_worker_failure_preserves_intake_receipt(self):
        class Client:
            def call(self, role, *args):
                return dict(people='4 pessoas', street='Rua das Flores', number='20',
                            municipality='Porto Alegre'), dict(role=role)
        with patch('app.pipeline.attach', side_effect=ValueError('PRIVATE worker failure')):
            case = self.case(Client())
        self.assertTrue(any(c['role'] == 'intake' for c in case['calls']))
        self.assertTrue(any(r['stage'] == 'message_worker' and r['error_class'] == 'ValueError'
                            for r in case['latency_budget']['stages']))
        self.assertNotIn('PRIVATE', json.dumps(case))
        self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')

    def test_persistent_bad_json_uses_only_one_retry_and_never_logs_prefix(self):
        with Scratch() as folder, patch.dict('os.environ', {'NIGHTSHIFT_API_KEY':'TEST-ONLY'}), \
             patch('app.llm.nightshift.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
            responses = [Response(b'{"choices":[{"message":{"content":"PRIVATE malformed"}}]}') for _ in range(2)]
            with patch('urllib.request.urlopen', side_effect=responses) as send:
                budget, end = self.budget(Nightshift(Path(folder)/'trace.jsonl'))
                with self.assertRaises(RuntimeError): intake.run(budget, 'Teste', end)
            self.assertEqual(send.call_count, 2)
            self.assertEqual(len(budget.receipts), 2)
            self.assertNotIn('PRIVATE', json.dumps(budget.receipts))
            self.assertNotIn('PRIVATE', (Path(folder)/'trace.jsonl').read_text(encoding='utf-8'))

    def test_stream_usage_allowlist_excludes_provider_text(self):
        from app.llm.nightshift import read_stream
        stream = Response(b'data: {"usage":{"prompt_tokens":12,"completion_tokens":6,"private":"PRIVATE"}}\n\n'
                          b'data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n')
        answer, metadata = read_stream(stream)
        self.assertEqual(answer, '{}')
        self.assertEqual(metadata['usage'], dict(prompt_tokens=12, completion_tokens=6))

    def test_hazard_deadline_before_transport_is_recorded(self):
        from app.agents import hazard_critic
        class Client:
            def call(self, *args): raise AssertionError('No transport should start')
        budget, _ = self.budget(Client())
        case = dict(text='Teste sintético', fields={}, result={}, agents={})
        hazard_critic.attach(case, budget, time.monotonic()-1)
        self.assertTrue(any(r['stage'] == 'hazard' and r['error_class'] == 'TimeoutError'
                            for r in budget.records))
