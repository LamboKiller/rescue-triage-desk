"""Gate/replay fixtures only: these tests never execute an eval or pipeline."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from tests.support import Scratch

from tools import gate, replay_live


@contextlib.contextmanager
def fixture_directory():
    scratch = Scratch()
    try:
        yield scratch.name
    finally:
        scratch.cleanup()


class GateTests(unittest.TestCase):
    def parse(self, name, data, **kwargs):
        return gate.parse_check(name, json.dumps(data), **kwargs)

    def adversarial(self, **changes):
        value = dict(messages=24, decision_accuracy=1, route_accuracy=1,
                     crashes=0, unsafe_send=0, failures=[])
        value.update(changes)
        return value

    def test_json_logs_and_callback_trailing_rows(self):
        data = dict(cases=12, errors=[], invented_facts_in_questions=0, unmapped_questions=0,
                    decision_correct_before=12, decision_correct_after=12)
        output = 'loading\n' + json.dumps(data, indent=2) + '\ncase1 CALLBACK -> SEND_CANDIDATE'
        self.assertTrue(gate.parse_check('callback', output)['pass'])

    def test_adversarial_requires_all_24_decisions(self):
        self.assertTrue(self.parse('adversarial', self.adversarial())['pass'])
        for change in ({'messages': 23}, {'decision_accuracy': 23/24},
                       {'crashes': 1}, {'failures': ['miss']}, {'unsafe_send': 1}):
            with self.subTest(change=change):
                self.assertFalse(self.parse('adversarial', self.adversarial(**change))['pass'])

    def test_route_mismatch_warns_but_decisions_safety_and_crashes_fail(self):
        value = self.adversarial(route_accuracy=23/24, failures=[
            dict(message_id='synthetic-route', decision='CALLBACK', route='rescue')])
        result = self.parse('adversarial', value)
        self.assertTrue(result['pass'])
        self.assertTrue(result['warnings'])
        self.assertEqual(result['value'], value)
        for change in ({'decision_accuracy': 23/24}, {'unsafe_send': 1}, {'crashes': 1},
                       {'failures': [{'error': 'RuntimeError'}]}, {'route_accuracy': None},
                       {'route_accuracy': 2}):
            self.assertFalse(self.parse('adversarial', dict(value, **change))['pass'])
        self.assertFalse(self.parse('adversarial', value, returncode=1)['pass'])

    def dialogue(self, **changes):
        value = dict(dialogues=10, crashes=0, final_decision_accuracy=1,
                     contradictions_flagged_accuracy=1, version_count_accuracy=1,
                     failures=[dict(dialogue_id='synthetic-field', decision='CALLBACK',
                                    fields={'location': {'actual': 'near bridge', 'expected': 'bridge'}})])
        value.update(changes)
        return value

    def test_dialogue_field_only_exit_one_warns(self):
        for code in (0, 1):
            result = self.parse('dialogues', self.dialogue(), returncode=code)
            self.assertTrue(result['pass'])
            self.assertTrue(result['warnings'])
            self.assertEqual(result['returncode'], code)

    def test_dialogue_warnings_never_hide_hard_failures(self):
        for change in ({'final_decision_accuracy': .9}, {'crashes': 1},
                       {'contradictions_flagged_accuracy': .9}, {'version_count_accuracy': .9},
                       {'unsafe_sends': 1}, {'failures': [{'error': 'RuntimeError'}]},
                       {'failures': [dict(dialogue_id='x', decision='CALLBACK', fields={})]},
                       {'failures': ['FIELD mismatch']}):
            self.assertFalse(self.parse('dialogues', self.dialogue(**change), returncode=1)['pass'])
        self.assertFalse(self.parse('dialogues', self.dialogue(), returncode=2)['pass'])
        self.assertFalse(self.parse('dialogues', self.dialogue(failures=[]), returncode=1)['pass'])

    def test_accuracy_only_label_mismatches_warn(self):
        self.assertTrue(self.parse('adversarial', self.adversarial(route_accuracy=.9))['warnings'])
        result = self.parse('adversarial', self.adversarial(key_field_accuracy=.9))
        self.assertTrue(result['pass'])
        self.assertTrue(result['warnings'])
        result = self.parse('dialogues', self.dialogue(failures=[], merge_accuracy_per_field={
            'location': {'correct': 9, 'total': 10, 'accuracy': .9}}))
        self.assertTrue(result['pass'])
        self.assertTrue(result['warnings'])

    def test_redteam_requires_exact_count_and_100_percent(self):
        for summary, expected in [('n=42 pass=42 rate=1.0 unsafe_send=0', True),
                                  ('n=42 pass=41 rate=0.976 unsafe_send=0', False),
                                  ('n=42 pass=42 rate=1 unsafe_send=1', False),
                                  ('n=0 pass=0 rate=1 unsafe_send=0', False)]:
            self.assertEqual(gate.parse_check('redteam', 'mode=offline ' + summary)['pass'], expected)

    def test_suite_requires_success_and_nonempty_run(self):
        self.assertTrue(gate.parse_check('suite', '', 'Ran 3 tests in 0.1s\n\nOK (skipped=1)')['pass'])
        for output, code in [('Ran 3 tests\nFAILED (failures=1)', 1), ('', 0),
                             ('Ran 0 tests\nOK', 0), ('Ran 3 tests\nOK', 1)]:
            self.assertFalse(gate.parse_check('suite', '', output, code)['pass'])

    def test_realdev_floor_count_safety_and_errors(self):
        def output(n=124, total=150, unsafe=0, errors=0, timeouts=0):
            return (f'decision accuracy: {n}/{total}\n'
                    f'unsafe sends: {unsafe}; errors: {errors}; timeouts: {timeouts}\n')
        self.assertTrue(gate.parse_check('realdev', output())['pass'])
        for change in ({'n': 123}, {'total': 149}, {'unsafe': 1}, {'errors': 1}, {'timeouts': 1}):
            self.assertFalse(gate.parse_check('realdev', output(**change))['pass'])
        self.assertFalse(gate.parse_check('realdev', output(), floor={'correct': 125, 'total': 150})['pass'])

    def test_nested_unsafe_anywhere_including_extra_json_and_stderr(self):
        good = self.adversarial()
        for suffix in ('\n{"diagnostics":[{"unsafe_sends":1}]}', '\nunsafe sends: 1'):
            self.assertFalse(gate.parse_check('adversarial', json.dumps(good), suffix)['pass'])
        good['diagnostics'] = [{'unsafe_send': True}]
        self.assertFalse(self.parse('adversarial', good)['pass'])

    def test_malformed_missing_and_invalid_counters_fail_closed(self):
        for output in ('', '{}', '{broken', '{"messages":24}'):
            self.assertFalse(gate.parse_check('adversarial', output)['pass'])
        for counter in ('0', None, -1, float('nan')):
            self.assertFalse(self.parse('adversarial', self.adversarial(unsafe_send=counter))['pass'])

    def test_other_checks_parse_and_fail(self):
        fixtures = {
            'credibility': dict(cases=4, acceptable=4, likely_fake_on_genuine=0),
            'hydro': dict(cases=5, passed=5, wrong_city=0),
            'callback': dict(cases=4, errors=[], invented_facts_in_questions=0, unmapped_questions=0,
                             decision_correct_before=4, decision_correct_after=4),
            'dialogues': dict(dialogues=3, crashes=0, failures=[], final_decision_accuracy=1,
                              contradictions_flagged_accuracy=1, version_count_accuracy=1),
        }
        bad = {'credibility': {'acceptable': 3}, 'hydro': {'wrong_city': 1},
               'callback': {'unmapped_questions': 1}, 'dialogues': {'version_count_accuracy': .5}}
        for name, value in fixtures.items():
            with self.subTest(name=name):
                self.assertTrue(self.parse(name, value)['pass'])
                self.assertFalse(self.parse(name, dict(value, **bad[name]))['pass'])
                self.assertFalse(self.parse(name, value, returncode=1)['pass'])

    def test_callback_full_artifact_detects_unsafe_sends_before_and_after(self):
        summary = dict(cases=1, errors=[], invented_facts_in_questions=0, unmapped_questions=0)
        row = dict(decision_before='CALLBACK', decision_after='CALLBACK',
                   expect=dict(decision_before='CALLBACK', decision_after='CALLBACK'))
        self.assertTrue(self.parse('callback', dict(summary=summary, cases=[row]))['pass'])
        for stage in ('before', 'after'):
            unsafe = dict(row, **{'decision_' + stage: 'SEND_CANDIDATE'})
            self.assertFalse(self.parse('callback', dict(summary=summary, cases=[unsafe]))['pass'])
        self.assertFalse(self.parse('callback', dict(summary=summary, cases=[]))['pass'])
        self.assertFalse(self.parse('callback', dict(summary=summary, cases=['bad row']))['pass'])

    def test_floor_created_once_never_overwritten_and_invalid_rejected(self):
        with fixture_directory() as folder:
            path = Path(folder)/'floor.json'
            self.assertEqual(gate.load_floor(path), {'correct': 124, 'total': 150})
            path.write_text('{"correct":130,"total":150}', encoding='utf-8')
            self.assertEqual(gate.load_floor(path)['correct'], 130)
            for value in ({'correct': 151, 'total': 150}, {'correct': True, 'total': 150}, {}, []):
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(ValueError):
                    gate.load_floor(path)

    def test_subprocess_timeout_and_failure(self):
        with patch.object(gate.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 1)):
            self.assertFalse(gate.run_check('suite', [], gate.ROOT, gate.DEFAULT_FLOOR)['pass'])
        with patch.object(gate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
            self.assertFalse(gate.run_check('suite', [], gate.ROOT, gate.DEFAULT_FLOOR)['pass'])
            self.assertEqual(run.call_args.kwargs['timeout'], 1500)
        with patch.object(gate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')) as run:
            gate.run_check('redteam', [], gate.ROOT, gate.DEFAULT_FLOOR)
            self.assertEqual(run.call_args.kwargs['timeout'], 300)
            gate.run_check('suite', [], gate.ROOT, gate.DEFAULT_FLOOR, timeout=7)
            self.assertEqual(run.call_args.kwargs['timeout'], 7)

    def test_callback_subprocess_uses_fresh_artifact_and_removes_it(self):
        with fixture_directory() as folder:
            root = Path(folder)
            saved = []
            def respond(command, **kwargs):
                path = Path(command[command.index('--out') + 1])
                saved.append(path)
                path.write_text(json.dumps({'summary': dict(cases=1, errors=[],
                    invented_facts_in_questions=0, unmapped_questions=0), 'cases': [
                    dict(decision_before='CALLBACK', decision_after='SEND_CANDIDATE',
                         expect=dict(decision_before='CALLBACK', decision_after='CALLBACK'))]}), encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, 'log only', '')
            with patch.object(gate, 'ROOT', root), patch.object(gate.subprocess, 'run', side_effect=respond):
                result = gate.run_check('callback', ['fixture.py'], root, gate.DEFAULT_FLOOR)
            self.assertFalse(result['pass'])
            self.assertEqual(result['value']['unsafe_sends'], 1)
            self.assertFalse(saved[0].exists())

    def test_fast_still_runs_all_evals_and_realdev_in_planning_folder(self):
        normal, fast = gate.commands(), gate.commands(True)
        self.assertEqual(normal[1:], fast[1:])
        self.assertEqual(normal[-1][2], gate.PLANNING)
        self.assertEqual(normal[-1][1][-2:], ['--dir', 'review/realdev'])
        self.assertIn('--offline', normal[-1][1])

    def test_main_writes_report_and_propagates_failure_without_real_runs(self):
        for passed in (True, False):
            with self.subTest(passed=passed), fixture_directory() as folder:
                root = Path(folder)
                (root/'eval').mkdir()
                result = {'value': 3, 'pass': passed, 'reasons': [], 'warnings': ['fixture label mismatch']}
                output = io.StringIO()
                with patch.object(gate, 'ROOT', root), patch.object(gate, 'commands', return_value=[('suite', [], root)]), \
                        patch.object(gate, 'run_check', return_value=result), \
                        patch.object(gate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'abc123\n', '')), \
                        contextlib.redirect_stdout(output):
                    self.assertEqual(gate.main([]), 0 if passed else 1)
                report = json.loads((root/'eval/gate_last.json').read_text(encoding='utf-8'))
                self.assertEqual(report['pass'], passed)
                self.assertEqual(report['commit'], 'abc123')
                self.assertIn('date', report)
                self.assertEqual(report['checks']['suite']['warnings'], result['warnings'])
                self.assertIn('WARNING: fixture label mismatch', output.getvalue())

    def test_invalid_stored_floor_fails_main_even_when_commands_pass(self):
        with fixture_directory() as folder:
            root = Path(folder)
            (root/'eval').mkdir()
            (root/'eval/gate_floor.json').write_text('{}', encoding='utf-8')
            with patch.object(gate, 'ROOT', root), patch.object(gate, 'commands', return_value=[]), \
                    patch.object(gate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'abc\n', '')), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(gate.main([]), 1)
            report = json.loads((root/'eval/gate_last.json').read_text(encoding='utf-8'))
            self.assertFalse(report['checks']['floor']['pass'])
            self.assertIn('floor          FAIL', output.getvalue())


class ReplayDumpTests(unittest.TestCase):
    def test_metadata_and_derived_fields_do_not_substitute_for_raw_outputs(self):
        dump = {'decision': 'REVIEW_REQUIRED', 'intake_fields': {'people': {'value': 3}},
                'location': {'answer': {}}, 'calls': [{'role': 'intake', 'status': 'ok'}]}
        missing = replay_live.missing_fields(dump)
        self.assertIn('calls[0].raw_output', missing)
        self.assertTrue(any('request' in value for value in missing))

    def test_per_case_then_now_unavailable_and_nonzero_exit(self):
        with fixture_directory() as folder:
            (Path(folder)/'1.json').write_text(json.dumps({'decision': 'CALLBACK', 'calls': []}), encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(replay_live.main(['--dump', folder]), 2)
            self.assertIn('then=CALLBACK now=UNAVAILABLE', output.getvalue())
            self.assertIn('Missing:', output.getvalue())

    def test_empty_corrupt_and_non_object_dumps(self):
        with fixture_directory() as folder:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(replay_live.main(['--dump', folder]), 2)
            path = Path(folder)/'bad.json'
            for contents in ('{broken', '[]'):
                path.write_text(contents, encoding='utf-8')
                self.assertTrue(replay_live.inspect_dump(path)['missing'])


if __name__ == '__main__':
    unittest.main()
