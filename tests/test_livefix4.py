"""Offline provider contention, admission and callback regressions; never live calls."""
import concurrent.futures
import contextlib
import io
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.llm import nightshift
from app.pipeline import Pipeline, StageBudget
from app.engines.world_model.registry import Registry
from app.callback.service import CallbackService
from app.redteam import harness
from tools.scratch import scratch as Scratch
from test_core import ROWS, TIME


class ProviderTests(unittest.TestCase):
    def test_fifo_waiters_cannot_be_overtaken_and_timeout_is_removed(self):
        slots = nightshift.FairSlots(1)
        self.assertTrue(slots.acquire())
        order = []
        def wait(i, timeout=2):
            if slots.acquire(timeout=timeout):
                order.append(i)
                slots.release()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            tasks = []
            for i in range(3):
                tasks.append(pool.submit(wait, i, .08 if i == 1 else 2))
                end = time.monotonic()+1
                while slots.waiting < i+1 and time.monotonic() < end:
                    time.sleep(.001)
            tasks[1].result()
            self.assertFalse(slots.acquire(blocking=False))
            slots.release()
            for task in tasks:
                task.result()
        self.assertEqual(order, [0, 2])
        self.assertEqual(slots.waiting, 0)

    def test_queue_wait_is_recorded_and_expired_admission_never_starts_transport(self):
        with Scratch() as folder:
            client = nightshift.Nightshift(Path(folder)/'trace.jsonl')
            started = []
            def transport(*args):
                started.append(True)
                return {}, {}
            slots = nightshift.FairSlots(1)
            slots.acquire()
            deadline = time.monotonic()+.6
            budget = StageBudget(client, deadline, .6)
            with patch.object(nightshift, 'CALL_SLOTS', slots), \
                 patch.object(StageBudget, 'MEDIANS', dict(intake=.3, critic=.3)), \
                 patch.object(client, '_call', side_effect=transport), \
                 concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(budget.call, 'intake', '', '', deadline)
                time.sleep(.25)
                slots.release()
                with self.assertRaises(TimeoutError):
                    future.result()
            self.assertEqual(started, [])
            queued = [r for r in budget.records if r.get('queue_seconds', 0) > .08]
            self.assertTrue(queued, budget.records)
            self.assertTrue(any(r.get('availability') == 'stage_unavailable' for r in queued))

    def test_intake_does_not_retry_when_remaining_time_is_below_median(self):
        from test_providers import Response
        requests = []
        def invalid(req, timeout):
            requests.append(req)
            time.sleep(.06)
            return Response(b'{"choices":[{"message":{"content":"invalid"}}]}')
        with Scratch() as folder, \
             patch.dict('os.environ', {'NIGHTSHIFT_API_KEY':'TEST-ONLY'}), \
             patch('urllib.request.urlopen', side_effect=invalid), \
             contextlib.redirect_stdout(io.StringIO()):
            client = nightshift.Nightshift(Path(folder)/'trace.jsonl')
            client.start_message('retry')
            client.local.minimum_seconds = .16
            with self.assertRaises((RuntimeError, TimeoutError)):
                client.call('intake', '', '', time.monotonic()+.2)
            self.assertEqual(len(requests), 1)
            self.assertEqual(client.message_calls()[-1].get('retry_skipped'), 'insufficient_budget')

    def test_defaults_limit_active_messages_before_their_budgets_start(self):
        with Scratch() as folder:
            pipe = Pipeline(Registry(Path(folder)/'events.jsonl'), sample=True)
            self.assertLessEqual(pipe.max_workers, 2)


class CallbackTests(unittest.TestCase):
    def test_failed_reply_exposes_its_own_budget_without_losing_previous_evidence(self):
        class Source:
            def streets(self, **kwargs): return ROWS
        class Client:
            failing = False
            def call(self, role, system, payload, deadline):
                if self.failing and role == 'intake':
                    raise TimeoutError('synthetic intake tail')
                if role == 'intake':
                    return dict(people='4 pessoas', street='Rua das Flores', number='20',
                                municipality='Porto Alegre'), dict(role=role)
                return dict(objections=[], brief_pt=''), dict(role=role)
        with Scratch() as folder, contextlib.redirect_stdout(io.StringIO()):
            client = Client()
            pipe = Pipeline(Registry(Path(folder)/'events.jsonl'), source=Source(), client=client)
            first = pipe.run(dict(replay_time=TIME, messages=[dict(message_id='callback-tail',
                text='4 pessoas na Rua das Flores 20 em Porto Alegre.')]))['cases'][0]
            client.failing = True
            out = CallbackService(pipe.registry, pipe).reply(first['case_id'], dict(text='Ainda aqui.'))
        self.assertEqual(out['case']['fields'], first['fields'])
        self.assertEqual(out['diff']['decision']['after'], 'REVIEW_REQUIRED')
        self.assertTrue(out['diff']['analysis']['errors'])
        self.assertTrue(out['diff']['analysis']['latency_budget']['stages'])

    def test_offline_pipeline_finishes_its_advisory_readers_before_scratch_cleanup(self):
        from app.contradictions import service
        original = service.ContradictionService.finish
        def slow_reader(instance, *args, **kwargs):
            time.sleep(.1)  # emulate a filesystem reader that outlives ingestion
            return original(instance, *args, **kwargs)
        with Scratch() as folder, contextlib.redirect_stdout(io.StringIO()), \
             patch.object(service.ContradictionService, 'finish', slow_reader):
            pipe = Pipeline(Registry(Path(folder)/'events.jsonl'), sample=True)
            pipe.run(dict(replay_time=TIME, messages=[dict(message_id='reader-%d' % n,
                text='%d pessoas na Rua das Flores 20 em Porto Alegre.' % n) for n in (4, 7)]))
            unfinished = any(t.is_alive() for t in service.PENDING)
            service.wait_all()  # Always drain before the test's own scratch cleanup.
        self.assertFalse(unfinished, 'offline pipeline returned while its registry was still in use')


class LoadReplayTests(unittest.TestCase):
    def test_holdout_success_status_matches_its_scoring_protocol(self):
        from test_l4 import runner_module
        worker = runner_module()
        row = worker.extract_case(dict(complete=True, errors=[], fields={},
            result={'decision': 'SEND_CANDIDATE'}, route={'id': 'street'}))
        self.assertEqual(row['status'], 'result')
        self.assertEqual(row['got_decision'], 'SEND')

    def test_redteam_24_and_holdout_30_share_concurrency_and_low_failure_rate(self):
        # The transport alone is fake: real StageBudget, queue, Pipeline, registry,
        # red-team runner and holdout worker/protocol all execute. No source network.
        import random
        from test_l4 import runner_module
        measured = dict(intake=(7.4, 29.), critic=(17., 24.3), revision=(8.2, 28.1),
                        location=(8.1, 32.), hazard=(5.1, 13.5))
        scale = .02
        stats = dict(active=0, peak=0, calls=0)
        lock = threading.Lock()
        rng = random.Random(41)
        samples = {k: [rng.uniform(.6*v[0], v[0]) for _ in range(30)]+[.97*v[1]]
                   for k, v in measured.items()}
        class Source:
            def streets(self, **kwargs): return ROWS
            def landmarks(self, **kwargs): return []
        class ReplayPipeline(Pipeline):
            def __init__(self, registry, **kwargs):
                kwargs.update(source=Source(), budget_seconds=60*scale)
                super().__init__(registry, **kwargs)
        def transport(client, role, system, payload, deadline):
            stage = {'hazard_critic':'hazard', 'location_agent':'location'}.get(role, role)
            with lock:
                stats['active'] += 1
                stats['peak'] = max(stats['peak'], stats['active'])
                index = stats['calls']
                stats['calls'] += 1
                latency = samples.get(stage, samples['critic'])[index % 31]*scale
            try:
                time.sleep(latency)
                if role in ('intake', 'revision'):
                    # Vary the quoted count to avoid inventing extra duplicate work.
                    import re
                    count = re.search(r'\d+ pessoas', payload)[0]
                    output = dict(people=count, street='Rua das Flores', number='20',
                                  municipality='Porto Alegre', confidence='low')
                elif role == 'critic':
                    output = dict(objections=[dict(field='pets', reason='missed', quote='um cachorro')])
                else:
                    output = dict(objections=[], brief_pt='')
                return output, dict(role=role, receipt='SYNTHETIC-LOAD')
            finally:
                with lock:
                    stats['active'] -= 1
        def messages(n):
            return [dict(message_id='load-%d' % i, received_at=TIME,
                         text='%d pessoas na Rua das Flores 20 em Porto Alegre, um cachorro.' % (i+2))
                    for i in range(n)]
        metrics = []
        with patch('app.pipeline.Pipeline', ReplayPipeline), \
             patch.object(StageBudget, 'RESERVE_SECONDS', 2*scale), \
             patch.object(StageBudget, 'MEDIANS', {k:v*scale for k,v in StageBudget.MEDIANS.items()}), \
             patch.object(StageBudget, 'CEILINGS', {k:v*scale for k,v in StageBudget.CEILINGS.items()}), \
             patch.object(nightshift, 'CALL_SLOTS', nightshift.FairSlots(2)), \
             patch.object(nightshift.Nightshift, '_call', transport), \
             patch('app.contradictions.hook.after_decision'), \
             patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
             patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
             patch('app.config.load_env', side_effect=AssertionError('must not read .env')), \
             contextlib.redirect_stdout(io.StringIO()), Scratch() as folder:
            cases = harness.make_runner(False, nightshift.Nightshift(Path(folder)/'redteam.jsonl'))(messages(24))
            failures = sum(c['route']['id'] == 'agent_failure' for c in cases)
            self.assertEqual(len(cases), 24)
            self.assertLessEqual(failures/24, .1)
            metrics.append(dict(path='redteam', total=24, failures=failures, peak=stats['peak']))
            self.assertEqual(stats['active'], 0)
            stats.update(peak=0, calls=0)
            worker = runner_module()
            protocol = io.StringIO()
            inputs = ''.join(json.dumps(dict(messages=messages(30)[i:i+15]))+'\n' for i in (0, 15))
            # Worker live setup is replaced only at its settings boundary. No dotenv,
            # credentials or HTTP request is used by this replay.
            with patch('sys.stdout', protocol), patch('sys.stderr', io.StringIO()), \
                 patch('sys.stdin', io.StringIO(inputs)), patch('app.pipeline.ROOT', Path(folder)), \
                 patch('app.config.load_env'), \
                 patch.dict('os.environ', {'NIGHTSHIFT_API_KEY':'SYNTHETIC', 'ZETARIS_API_KEY':'SYNTHETIC'}):
                try:
                    self.assertEqual(worker.worker(Path('.'), False, jobs=2), 0)
                finally:
                    worker.sys.stdout.close()
            batches = [json.loads(l) for l in protocol.getvalue().splitlines() if '"results"' in l]
            rows = [r for b in batches for r in b['results']]
            self.assertEqual(len(rows), 30, protocol.getvalue()[-1000:])
            # The holdout wire/scoring protocol calls a completed case "result";
            # "ok" is a provider receipt status, never a worker result status.
            self.assertTrue(all(r.get('status') in ('result', 'error', 'timeout') for r in rows))
            failures = sum(r.get('status') != 'result' or
                           r.get('diagnostic', {}).get('route') == 'agent_failure' for r in rows)
            self.assertLessEqual(failures/30, .1)
            metrics.append(dict(path='holdout', total=30, failures=failures, peak=stats['peak']))
        self.assertEqual([m['peak'] for m in metrics], [2, 2])
        self.assertEqual(stats['active'], 0)
        print('LIVEFIX4 replay '+json.dumps(metrics))


if __name__ == '__main__':
    unittest.main()
