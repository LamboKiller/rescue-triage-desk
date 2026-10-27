"""Offline hero evidence checks; no model or external service is used."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import demo_hero as hero


class EvidenceChecks(unittest.TestCase):
    def test_rejected_gps_fix_is_a_failed_action(self):
        class Desk:
            base = 'offline'
            def health(self):
                return {'mode': 'sample_offline'}
            def call(self, *args):
                return 200, {'status': 'rejected'}
        runner = hero.HeroRunner(Desk(), {'meta': {'replay_day': '2024-05-06'}, 'steps': []},
                                 sleep=lambda s: None, say=lambda s: None)
        runner.state['steps']['1'] = {'unit_id': 'boat', 'gps_bound': True,
                                      'gps_points': [[-51.2, -30.0]], 'log': []}
        runner.op_gps_replay(1, {'t': '12:14'}, {'at': '12:14', 'fixes': 1})
        self.assertEqual(runner.state['steps']['1']['gps']['accepted'], 0)
        self.assertFalse(runner.state['steps']['1']['log'][-1]['ok'])

    def test_synthetic_shift_resource_validates_with_replay_date(self):
        from app.resources import validate
        unit = validate(json.loads((ROOT / 'data/demo/hero_boat.json').read_text(encoding='utf-8')))
        self.assertTrue(unit['synthetic'])
        self.assertTrue(unit['stretcher'])
        self.assertGreaterEqual(unit['capacity_people'], 5)
        self.assertEqual(unit['observed_date'], '2024-05-06')
        self.assertIn('[SIMULADO]', unit['source'])

    def test_stretcher_is_checked_against_registered_inventory(self):
        class Desk:
            def get(self, path):
                if path == '/api/resources':
                    return 200, {'typed_resources': [{'id': 'demo-boat', 'stretcher': True}]}
                return 200, {'case_id': 'c', 'fields': {}}
        state = {'steps': {'1': {'case_id': 'c', 'unit_id': 'demo-boat', 'log': []}}}
        step = {'step': 1, 'expect': {'stretcher_unit': True}}
        good, fails, _ = hero.HeroCheck(Desk(), {'meta': {'replay_day': '2024-05-06'}, 'steps': [step]}, state).step(step)
        self.assertTrue(good, fails)

    def test_missing_land_leg_fails(self):
        class Desk:
            def get(self, path):
                return 200, {}
        state = {'steps': {'1': {'log': [], 'route': {'water_leg': True, 'land': False}}}}
        step = {'step': 1, 'expect': {'route_land_leg': True}}
        good, fails, _ = hero.HeroCheck(Desk(), {'meta': {'replay_day': '2024-05-06'}, 'steps': [step]}, state).step(step)
        self.assertFalse(good, fails)

    def test_timing_and_pacing_do_not_mutate_scenario(self):
        class Desk:
            base = 'offline'
            def health(self):
                return {'mode': 'sample_offline'}
        scenario = {'meta': {'replay_day': '2024-05-06'}, 'steps': [
            {'step': 1, 't': '12:00', 'title': 'timing', 'message': {'text': 'x'},
             'actions': [{'op': 'request_callback', 'delay_s': 4}], 'expect': {'callback_question': True}}]}
        before = copy.deepcopy(scenario)
        runner = hero.HeroRunner(Desk(), scenario, speed=2, sleep=lambda s: None, say=lambda s: None)
        runner.run_step = lambda step: runner.state['steps'].setdefault('1', {'log': []})
        runner.run()
        self.assertEqual(scenario, before)
        self.assertGreaterEqual(runner.state['steps']['1']['wall_seconds'], 0)


class OfflineHero(unittest.TestCase):
    def test_fresh_offline_eight_steps(self):
        # Explicit mkdir avoids restrictive TemporaryDirectory ACLs in Windows sandboxes.
        import uuid
        workdir = ROOT / 'runtime' / ('hero-test-' + uuid.uuid4().hex)
        result = subprocess.run([
            sys.executable, '-u', str(ROOT / 'tools/demo_hero.py'), '--offline',
            '--port', '0', '--workdir', str(workdir)], cwd=ROOT,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, capture_output=True,
            text=True, encoding='utf-8', timeout=240)
        self.assertEqual(result.returncode, 0, result.stdout[-6000:] + result.stderr[-2000:])
        self.assertIn('8/8 PASS', result.stdout)
        self.assertEqual(result.stdout.count('TEMPO passo '), 8)
        state = json.loads((workdir / 'runtime/hero_state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['steps']['1']['unit_id'], 'sim-barco-01')
        self.assertTrue(state['steps']['1']['route']['land'])
        self.assertGreaterEqual(state['steps']['1']['gps']['accepted'], 6)
        self.assertFalse(state['steps']['7']['reroute_snapshot']['auto_applied'])
        self.assertEqual(len(state['supervisor']['no_signal']['alerts']), 1)


if __name__ == '__main__':
    unittest.main()
