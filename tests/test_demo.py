"""Scripted demo: scenario schema, reset safety, offline 8/8 run."""
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import demo_lib as lib  # noqa: E402
import reset_demo  # noqa: E402


class ScenarioSchema(unittest.TestCase):
    def test_loads_eight_steps_with_synthetic_flag(self):
        sc = lib.load()
        self.assertEqual([s['step'] for s in sc['steps']], list(range(1, 9)))
        self.assertTrue(sc['meta']['synthetic'])
        self.assertEqual(sc['meta']['replay_day'], '2024-05-06')

    def test_no_real_phone_numbers(self):
        for s in lib.load()['steps']:
            for m in lib.PHONE.findall(s['message']['text']):
                self.assertTrue(m.replace(' ', '').endswith('-0000'), m)

    def test_unknown_expect_key_rejected(self):
        rows = [dict(r) for r in map(copy.deepcopy, _rows())]
        rows[1]['expect'] = {'bogus': 1}
        with self.assertRaises(lib.ScenarioError):
            lib.validate(rows)


def _rows():
    import json
    return [json.loads(l) for l in lib.SCENARIO.read_text(encoding='utf-8-sig').splitlines() if l.strip()]


class ResetSafety(unittest.TestCase):
    def test_only_runtime_artifacts_moved_and_nothing_deleted(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as tmp:
            rt = Path(tmp)
            (rt / 'events.jsonl').write_text('x')
            (rt / 'keep.txt').write_text('keep')
            out = reset_demo.reset_demo(runtime=rt)
            self.assertEqual(out['moved'], ['events.jsonl'])
            self.assertTrue((rt / 'keep.txt').exists())
            self.assertFalse((rt / 'events.jsonl').exists())
            self.assertEqual(len(list((rt / 'demo_backup').rglob('events.jsonl'))), 1)

    def test_dry_run_moves_nothing_and_outside_repo_refused(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as tmp:
            rt = Path(tmp)
            (rt / 'events.jsonl').write_text('x')
            reset_demo.reset_demo(runtime=rt, dry_run=True)
            self.assertTrue((rt / 'events.jsonl').exists())
        with self.assertRaises(ValueError):
            reset_demo.reset_demo(runtime=Path(tempfile.gettempdir()) / 'nope')

    def test_artifact_list_excludes_committed_dirs(self):
        for bad in ('data', 'examples', 'eval', 'review', 'app'):
            self.assertNotIn(bad, reset_demo.DEMO_ARTIFACTS)


class OfflineRun(unittest.TestCase):
    def test_offline_8_of_8(self):
        r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'demo_run.py'), '--offline'], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=280)
        self.assertEqual(r.returncode, 0, r.stdout[-2500:])
        self.assertIn('8/8 PASS', r.stdout)


if __name__ == '__main__':
    unittest.main()
