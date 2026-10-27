"""dev2 set + runner checks (no network, no model calls)."""
import json
import re
import unittest
from pathlib import Path

from eval.dev2 import check
from eval import run_dev2

ROOT = Path(__file__).resolve().parents[1]
REALDEV_DIR = ROOT.parent / 'open-agent-hackathon-2026' / 'review' / 'realdev'


def grams(text, n=8):
    words = re.findall(r'\w+', text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def reference_texts():
    """Texts we must not copy. Only ids are ever reported, never the texts."""
    out = []
    path = ROOT / 'eval/realistic_dev.jsonl'
    if path.exists():
        out += [json.loads(l)['text'] for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    holdout = REALDEV_DIR / 'holdout_20.txt'
    if holdout.exists():
        out += [l for l in holdout.read_text(encoding='utf-8-sig').splitlines() if l.strip()]
    return out


def row(**kw):
    base = {'id': 'x', 'class': 'c', 'bucket': 'targeted', 'ambiguous': False, 'expected_decision': 'SEND',
            'expected_people': 2, 'expected_route': 'street', 'got_decision': 'SEND', 'got_people': 2,
            'got_route': 'street', 'got_precision': 'exact', 'seconds': 1.0, 'failure': None}
    base.update(kw)
    item = {'id': base['id'], 'class': base['class'], 'bucket': base['bucket'], 'ambiguous': base['ambiguous'],
            'expected_decision': base['expected_decision'], 'expected_people': base['expected_people'],
            'expected_route': base['expected_route']}
    obs = {k: base[k] for k in ('got_decision', 'got_people', 'got_route', 'got_precision', 'seconds', 'failure')}
    return run_dev2.judge(item, obs)


class Dev2Set(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = check.load()

    def test_size_and_mix(self):
        n = len(self.rows)
        self.assertGreaterEqual(n, 170)
        share = {b: sum(r['bucket'] == b for r in self.rows) / n for b in ('targeted', 'regression', 'adversarial')}
        self.assertGreater(share['targeted'], .6)
        self.assertTrue(.15 < share['regression'] < .25, share)
        self.assertTrue(.08 < share['adversarial'] < .2, share)

    def test_schema(self):
        self.assertEqual(check.schema_errors(self.rows), [])

    def test_unique_texts(self):
        texts = [r['text'] for r in self.rows]
        self.assertEqual(len(texts), len(set(texts)))

    def test_streets_bairros_landmarks_exist(self):
        self.assertEqual(check.data_errors(self.rows), [])

    def test_derived_count_labels_are_consistent(self):
        for r in self.rows:
            if r['count_basis'] == 'derived':
                self.assertIsInstance(r['expected_people'], int, r['id'])

    def test_no_phone_numbers_other_than_placeholder(self):
        for r in self.rows:
            for m in re.findall(r'\d{4,5}-\d{4}', r['text']):
                self.assertEqual(m[-4:], '0000', r['id'])

    def test_covers_requested_classes(self):
        need = {'derived_count', 'city_lookalike', 'already_rescued', 'ambiguous_street', 'street_no_number', 'landmark_only',
                'multi_vulnerable', 'animals_alone', 'info_request', 'volunteer_offer', 'injection', 'repost',
                'slang_typos', 'long_rambling', 'two_requests', 'out_of_area'}
        self.assertLessEqual(need, {r['class'] for r in self.rows})

    def test_no_8gram_overlap_with_realdev(self):
        refs = set()
        for t in reference_texts():
            refs |= grams(t)
        hits = [r['id'] for r in self.rows if grams(r['text']) & refs]
        self.assertEqual(hits, [])  # ids only; texts are never printed


class Dev2Runner(unittest.TestCase):
    def test_family_and_strict(self):
        r = row(expected_decision='SEND_APPROX', got_decision='SEND')
        self.assertTrue(r['decision_ok']); self.assertFalse(r['strict_ok']); self.assertFalse(r['unsafe'])

    def test_unsafe_and_missed(self):
        self.assertTrue(row(expected_decision='REVIEW', got_decision='SEND_APPROX')['unsafe'])
        r = row(expected_decision='SEND', got_decision='CALLBACK')
        self.assertTrue(r['missed_send']); self.assertFalse(r['unsafe'])

    def test_people_and_route_none_not_scored(self):
        r = row(expected_people=None, expected_route=None)
        self.assertIsNone(r['people_ok']); self.assertIsNone(r['route_ok'])
        self.assertTrue(row(expected_people=None, got_people=4)['invented_count'])

    def test_summarize_math_and_ambiguous_split(self):
        rows = [row(id='a', **{'class': 'k'}), row(id='b', got_decision='CALLBACK', **{'class': 'k'}),
                row(id='c', ambiguous=True, got_decision='CALLBACK', **{'class': 'k'}),
                row(id='d', expected_decision='REVIEW', got_decision='SEND', **{'class': 'z'})]
        s = run_dev2.summarize(rows)
        self.assertEqual(s['overall']['n'], 3)
        self.assertEqual(s['overall']['decision'], (1, 3))
        self.assertEqual(s['by_class']['k']['decision'], (1, 2))
        self.assertEqual(s['ambiguous']['n'], 1)
        self.assertEqual(s['overall']['unsafe'], 1)
        self.assertEqual(s['unsafe_ids'], ['d'])

    def test_failure_kinds_counted(self):
        s = run_dev2.summarize([row(failure='TIMEOUT'), row(id='y', failure='TIMEOUT'), row(id='z')])
        self.assertEqual(s['failure_kinds'], {'TIMEOUT': 2})

    def test_pack_keeps_street_unique_and_one_date(self):
        items = [{'id': 'i%d' % i, 'replay_date': '2024-05-06' if i < 15 else '2024-05-08',
                  'key_fields': {'municipality': 'Canoas', 'street': 'Rua X' if i % 2 else 'Rua %d' % i}} for i in range(20)]
        batches = run_dev2.pack(items)
        self.assertEqual(sum(len(b) for b in batches), 20)
        for b in batches:
            self.assertEqual(len({i['replay_date'] for i in b}), 1)
            keys = [i['key_fields']['street'] for i in b]
            self.assertEqual(len(keys), len(set(keys)))

    def test_load_items_filters(self):
        self.assertTrue(all(r['class'].startswith('reg_') for r in run_dev2.load_items(only='reg_')))
        self.assertEqual(len(run_dev2.load_items(sample=10, seed=1)), 10)
        self.assertEqual(run_dev2.load_items(sample=10, seed=1), run_dev2.load_items(sample=10, seed=1))

    def test_offline_smoke_two_items(self):
        items = run_dev2.load_items(only='d2-129,d2-156')
        rows, _ = run_dev2.run(items, offline=True, jobs=1)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not r['got_decision'].startswith('ERROR') for r in rows))


if __name__ == '__main__':
    unittest.main()
