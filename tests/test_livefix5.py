"""Offline admission-pressure replays; no provider or source network."""
import contextlib
import io
import json
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from app.llm import nightshift
from app.pipeline import Pipeline, StageBudget
from app.engines.world_model.registry import Registry
from tools.scratch import scratch as Scratch
from test_core import ROWS, TIME
from test_providers import Response


class AdmissionTests(unittest.TestCase):
    def transport(self, replies, seconds=10, role='intake'):
        with Scratch() as folder, patch.dict('os.environ', {'NIGHTSHIFT_API_KEY':'TEST-ONLY'}), \
             patch('urllib.request.urlopen', side_effect=replies) as send, \
             patch('app.llm.nightshift.time.sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            client = nightshift.Nightshift(Path(folder)/'trace.jsonl')
            client.start_message('admission')
            value = error = None
            try:
                value = client.call(role, '', '', time.monotonic()+seconds)
            except Exception as exc:
                error = exc
            return value, error, client.message_calls(), send.call_count, sleep.call_args_list

    def refusal(self, status=503, detail='admission_refused: Pause memory pressure'):
        return urllib.error.HTTPError('http://fake', status, 'pressure', {},
            io.BytesIO(json.dumps({'error':{'meterless_detail':detail}}).encode()))

    def answer(self):
        return Response(b'{"choices":[{"message":{"content":"{}"}}]}')

    def test_refusal_backoff_success_and_receipt(self):
        value, error, events, sent, sleeps = self.transport([self.refusal(), self.answer()])
        self.assertIsNone(error)
        self.assertEqual(value[0], {})
        self.assertEqual(sent, 2)
        self.assertEqual(events[0].get('failure_kind'), 'provider_refused')
        self.assertGreater(events[0].get('backoff_seconds', 0), 0)
        self.assertTrue(sleeps)

    def test_429_is_retried(self):
        value, error, events, sent, _ = self.transport([self.refusal(429), self.answer()])
        self.assertIsNone(error)
        self.assertEqual(sent, 2)
        self.assertEqual(events[0].get('http_status'), 429)

    def test_connection_reset_is_distinct_and_retried(self):
        value, error, events, _, _ = self.transport([
            urllib.error.URLError(ConnectionResetError('synthetic reset')), self.answer()])
        self.assertIsNone(error)
        self.assertEqual(events[0].get('failure_kind'), 'connection_reset')

    def test_nonretryable_401_and_side_effect_role_are_not_retried(self):
        for role, status in [('intake', 401), ('dispatch_mission', 503)]:
            with self.subTest(role=role):
                _, error, _, sent, _ = self.transport([self.refusal(status), self.answer()], role=role)
                self.assertIsNotNone(error)
                self.assertEqual(sent, 1)

    def test_backoff_cannot_consume_remaining_budget(self):
        _, error, events, sent, sleeps = self.transport([self.refusal()], seconds=.01)
        self.assertIsNotNone(error)
        self.assertEqual(sent, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(events[-1].get('retry_skipped'), 'insufficient_budget')

    def test_error_body_never_enters_receipt(self):
        _, _, events, _, _ = self.transport([self.refusal(401, 'PRIVATE BODY')])
        self.assertNotIn('PRIVATE BODY', json.dumps(events))

    def test_streamed_admission_error_is_retried(self):
        refused = Response(b'data: {"error":{"code":"admission_refused"}}\n\n')
        value, error, events, sent, _ = self.transport([refused, self.answer()])
        self.assertIsNone(error)
        self.assertEqual(sent, 2)
        self.assertEqual(events[0]['failure_kind'], 'provider_refused')

    def test_budget_journal_carries_retry_queue_and_backoff(self):
        with Scratch() as folder, patch.dict('os.environ', {'NIGHTSHIFT_API_KEY':'TEST-ONLY'}), \
             patch('urllib.request.urlopen', side_effect=[self.refusal(), self.answer()]), \
             patch('app.llm.nightshift.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
            client = nightshift.Nightshift(Path(folder)/'trace.jsonl')
            deadline = time.monotonic()+60
            budget = StageBudget(client, deadline, 60)
            budget.call('intake', '', '', deadline)
            with self.assertRaises(TimeoutError):
                budget.call('hazard_critic', '', '', deadline)
        self.assertTrue(any(r['status'] == 'provider_queue' for r in budget.records))
        self.assertTrue(any(r.get('backoff_seconds', 0) > 0 for r in budget.records))
        self.assertEqual(len(budget.receipts), 2)
        self.assertEqual(budget.records[-1]['reason'], 'provider_pressure')

    def test_persistent_runtime_refusal_uses_bounded_attempts(self):
        _, error, events, sent, sleeps = self.transport([self.refusal() for _ in range(3)])
        self.assertIsInstance(error, nightshift.ProviderRefused)
        self.assertEqual(sent, 3)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(events[-1]['backoff_seconds'], 0)

    def test_recovered_intake_pressure_skips_advice_without_promoting_uncertain_intake(self):
        class Source:
            def streets(self, **kwargs): return ROWS
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain):
                raw = dict(people='4 pessoas', street='Rua das Flores', number='20', municipality='Porto Alegre')
                if uncertain: raw['confidence'] = 'low'
                response = Response(json.dumps({'choices':[{'message':{'content':json.dumps(raw)}}]}).encode())
                with Scratch() as folder, patch.dict('os.environ', {'NIGHTSHIFT_API_KEY':'TEST-ONLY'}), \
                     patch('urllib.request.urlopen', side_effect=[self.refusal(), response]) as send, \
                     patch('app.llm.nightshift.time.sleep'), patch('app.contradictions.hook.after_decision'), \
                     contextlib.redirect_stdout(io.StringIO()):
                    client = nightshift.Nightshift(Path(folder)/'trace.jsonl')
                    pipe = Pipeline(Registry(Path(folder)/'events.jsonl'), source=Source(), client=client)
                    case = pipe.run(dict(replay_time=TIME, messages=[dict(message_id='recovered-pressure',
                        text='4 pessoas na Rua das Flores 20 em Porto Alegre.')]))['cases'][0]
                self.assertEqual(send.call_count, 2)
                self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
                self.assertEqual(case['failure_kind'], 'provider_refused')
                self.assertEqual(case['hazard_check'], 'deterministic_only')
                self.assertTrue(case['latency_budget']['provider_pressure'])
                self.assertIn('perigo não revisado', ' '.join(case['agent_warnings']))


class MinimalPathTests(unittest.TestCase):
    def run_case(self, fail_role=None, uncertain=False, missing_location=False, failure='refused'):
        class Source:
            def streets(self, **kwargs): return ROWS
        class Client:
            def __init__(self): self.roles = []
            def call(self, role, system, payload, deadline):
                self.roles.append(role)
                if role == fail_role:
                    if failure == 'refused':
                        raise nightshift.ProviderRefused(503)
                    raise TimeoutError('synthetic slow response')
                if role == 'intake':
                    raw = dict(people='4 pessoas', street='Rua das Flores', number='20', municipality='Porto Alegre')
                    if missing_location:
                        raw.pop('street'); raw.pop('number')
                    if uncertain: raw['confidence'] = 'low'
                    return raw, dict(role=role)
                return dict(objections=[], brief_pt=''), dict(role=role)
        with Scratch() as folder, contextlib.redirect_stdout(io.StringIO()), \
             patch('app.contradictions.hook.after_decision'):
            client = Client()
            pipe = Pipeline(Registry(Path(folder)/'events.jsonl'), source=Source(), client=client)
            case = pipe.run(dict(replay_time=TIME, messages=[dict(message_id='pressure-test',
                text='4 pessoas na Rua das Flores 20 em Porto Alegre.')]))['cases'][0]
            return case, client.roles

    def test_persistent_intake_refusal_finishes_safe_minimal_path(self):
        case, roles = self.run_case('intake')
        self.assertEqual(roles, ['intake'])
        self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')
        self.assertEqual(case.get('failure_kind'), 'provider_refused')
        self.assertTrue(case.get('minimal_path'))
        self.assertEqual(case['hazard_check'], 'deterministic_only')
        self.assertIn('credibility', case)

    def test_validated_intake_keeps_rule_decision_after_advisory_refusal(self):
        case, roles = self.run_case('critic', uncertain=True)
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertEqual(roles, ['intake', 'critic'])
        self.assertFalse(case['review_degraded'])
        self.assertTrue(case['agent_warnings'])

    def test_descriptive_hazard_gap_preserves_send_and_is_visible(self):
        with patch('app.geo.hydro.hydro_conflict', return_value={'reason':'synthetic conflict'}):
            case, roles = self.run_case('hazard_critic')
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertIn('etapa pulada: provedor sob pressão', ' '.join(case['agent_warnings']))
        self.assertIn('hazard', case['stage_unavailable'])
        self.assertNotIn('critic', roles)  # certain intake already supplies copied fields

    def test_dump_shape_intake_cut_stops_later_calls(self):
        # Dumps 20/30/50/130: no intake receipt, then needless hazard calls.
        case, roles = self.run_case('intake', failure='timeout')
        self.assertEqual(roles, ['intake'])
        self.assertEqual(case['result']['decision'], 'CALLBACK')
        self.assertTrue(case['intake_degraded'])

    def test_dump_shape_post_intake_critic_cut_is_conservative(self):
        # Dumps 5/75/145: intake present, later review failure without receipt.
        case, roles = self.run_case('critic', uncertain=True, failure='timeout')
        self.assertEqual(case['result']['decision'], 'SEND_CANDIDATE')
        self.assertTrue(case['agent_warnings'])
        self.assertNotIn('hazard_critic', roles)

    def test_dump_shape_location_turn_cut_remains_unresolved(self):
        # Dumps 25/35/150: successful tool turns followed by TimeoutError.
        class Tail:
            def call(self, *args): raise TimeoutError('synthetic next location turn')
        deadline = time.monotonic()+60
        budget = StageBudget(Tail(), deadline, 60)
        with self.assertRaises(TimeoutError): budget.call('location_agent', '', '', deadline)
        with self.assertRaises(TimeoutError): budget.call('hazard_critic', '', '', deadline)
        self.assertEqual(budget.records[-1]['status'], 'skipped')
        self.assertEqual(budget.records[-1]['reason'], 'provider_pressure')

    def test_slow_fake_never_exceeds_message_deadline(self):
        class Tail:
            def call(self, *args):
                time.sleep(.25)
                return {}, {}
        deadline = time.monotonic()+.16
        budget = StageBudget(Tail(), deadline, .16)
        with self.assertRaises(TimeoutError): budget.call('intake', '', '', deadline)
        self.assertLess(time.monotonic(), deadline)
        time.sleep(.25)  # drain the deliberately uncooperative fake

    def test_eval_distinguishes_failure_causes_from_decisions(self):
        from eval.failures import failure_counts
        refused, _ = self.run_case('intake')
        timeout, _ = self.run_case('intake', failure='timeout')
        healthy, _ = self.run_case()
        invalid = dict(healthy, complete=False, errors=['agent_step_failed:ValueError'])
        self.assertEqual(failure_counts([refused, timeout, healthy, invalid]),
                         dict(TIMEOUT=1, provider_refused=1, agent_failure=1))


if __name__ == '__main__': unittest.main()
