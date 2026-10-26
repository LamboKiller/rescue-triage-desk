"""N1 S7+A5: declared data-source kinds, no-hindsight gate, Evals view. No network, no model calls."""
import datetime as dt
import json
import re
import unittest
from pathlib import Path

from app import provenance as prov
from app.geo.hazards import get_data
from support import Scratch

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.timezone.utc)


class ProvenanceTable(unittest.TestCase):
    def test_every_layer_has_a_declared_kind(self):
        for key, row in prov.LAYERS.items():
            self.assertIn(row[2], prov.KINDS, key)
        for key in ('flood', 'depth', 'closures', 'pumps', 'shelters', 'events', 'levees', 'buildings', 'cases', 'ring'):
            self.assertIsNotNone(prov.layer_kind(key), key)  # every map layer menu key is labelled
        self.assertEqual(prov.layer_kind('depth'), 'retrospective')
        self.assertEqual(prov.layer_kind('closures'), 'live_equivalent')
        self.assertEqual(prov.layer_kind('streets'), 'pre_event')
        self.assertEqual(prov.layer_kind('citizen_replies'), 'simulated')
        self.assertIsNone(prov.layer_kind('made_up_layer'))

    def test_map_menu_keys_are_all_declared(self):
        js = (ROOT / 'app/web/v2/map.js').read_text(encoding='utf-8')
        keys = re.search(r"const config=\{(.*?)\};", js).group(1)
        for key in re.findall(r"(\w+):'", keys):
            self.assertIsNotNone(prov.layer_kind(key), key)

    def test_message_kind(self):
        self.assertEqual(prov.message_kind({'text': 'água no térreo', 'synthetic': True}), 'simulated')
        self.assertEqual(prov.message_kind({'text': '[SIMULADO] sim, estamos aqui'}), 'simulated')
        self.assertEqual(prov.message_kind({'text': 'água no térreo'}), 'live_equivalent')

    def test_readme_carries_the_generated_table(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8').replace('\r\n', '\n')
        block = readme.split('<!-- provenance-table:start -->')[1].split('<!-- provenance-table:end -->')[0].strip()
        self.assertEqual(block, prov.readme_table())

    def test_ui_wiring(self):
        html = (ROOT / 'app/web/v2/index.html').read_text(encoding='utf-8')
        self.assertIn('/v2/evals.js', html)
        self.assertIn('data-mode="evals"', html)
        self.assertIn('id="evals"', html)
        self.assertIn('/v2/evals.js', (ROOT / 'app/web/routes_v2.py').read_text(encoding='utf-8'))


class NoHindsight(unittest.TestCase):
    def test_usable_at_rules(self):
        self.assertTrue(prov.usable_at('closures', '2024-05-06T08:00:00', '2024-05-08'))
        self.assertTrue(prov.usable_at('closures', '2024-05-08T23:59:00', '2024-05-08'))
        self.assertFalse(prov.usable_at('closures', '2024-05-09T00:01:00', '2024-05-08'))
        self.assertFalse(prov.usable_at('closures', None, '2024-05-08'))      # unknown time is not usable
        self.assertFalse(prov.usable_at('flood', 'sem data', '2024-05-08'))
        self.assertFalse(prov.usable_at('undeclared', '2024-05-01', '2024-05-08'))
        self.assertTrue(prov.usable_at('streets', None, '2024-05-01'))         # pre-event content

    def test_replay_layers_never_contain_later_records(self):
        data = get_data()
        for day in ('2024-05-02', '2024-05-06', '2024-05-08', '2024-05-12'):
            _, layers = data.dated_layers(day)
            for f in layers['closures']:
                self.assertTrue(prov.usable_at('closures', f['properties'].get('source_published_at'), day), (day, f['properties'].get('road')))
            for f in layers['events']:
                p = f['properties']
                self.assertTrue(prov.usable_at('events', p.get('published_at'), day), day)
                self.assertTrue(prov.usable_at('events', p.get('observed_at'), day), day)


class EvalsView(unittest.TestCase):
    def setUp(self):
        self.scratch = Scratch()
        self.root = Path(self.scratch.name)
        (self.root / 'eval').mkdir()

    def tearDown(self):
        self.scratch.cleanup()

    def write_gate(self, date, commit='abc123', value=None):
        report = {'commit': commit, 'date': date, 'fast': True, 'pass': True, 'checks': {
            'redteam': {'value': value if value is not None else {'correct': 42, 'total': 42, 'rate': 1.0}, 'pass': True},
            'hydro': {'value': {'cases': 3}, 'pass': True}}}
        (self.root / 'eval/gate_last.json').write_text(json.dumps(report), encoding='utf-8')

    def rows(self, head='abc123'):
        return {r['id']: r for r in prov.evals_view(self.root, NOW, head)['rows']}

    def test_fresh_same_commit_is_not_stale(self):
        self.write_gate('2026-10-26T06:00:00+00:00')
        row = self.rows()['redteam']
        self.assertFalse(row['stale'])
        self.assertEqual((row['value'], row['of'], row['mode'], row['commit'], row['date']), (1.0, 42, 'offline', 'abc123', '2026-10-26T06:00:00+00:00'))
        self.assertIn('run_redteam.py', row['command'])

    def test_old_run_and_other_commit_are_stale(self):
        self.write_gate('2026-10-24T06:00:00+00:00')
        self.assertTrue(self.rows()['redteam']['stale'])
        self.write_gate('2026-10-26T06:00:00+00:00')
        row = self.rows(head='def456')['redteam']
        self.assertTrue(row['stale'])
        self.assertIn('commit diferente do atual', row['stale_reasons'])

    def test_missing_numbers_stay_missing(self):
        self.write_gate('2026-10-26T06:00:00+00:00', value={'total': 42})
        self.assertIsNone(self.rows()['redteam']['value'])         # headline key absent -> None, not 0 or a guess
        self.assertIsNone(self.rows()['hydro']['value'])           # 'passed' absent
        (self.root / 'eval/gate_last.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(prov.evals_view(self.root, NOW, 'x')['rows'], [])

    def test_result_files_report_their_own_mode_and_numbers(self):
        self.write_gate('2026-10-26T06:00:00+00:00')
        sets = {'generated': {'full': {'n': 30, 'decision_accuracy': 0.9}, 'intake': {'n': 30}}}
        (self.root / 'eval/results_live.json').write_text(json.dumps({'mode': 'live', 'sets': sets}), encoding='utf-8')
        rows = self.rows()
        self.assertEqual(rows['results_live:generated:full']['mode'], 'live')
        self.assertEqual(rows['results_live:generated:full']['value'], 0.9)
        self.assertIsNone(rows['results_live:generated:intake']['value'])
        self.assertTrue(rows['results_live:generated:full']['stale'])  # no commit recorded -> never "current"

    def test_commands_point_at_real_scripts(self):
        for name, cmd in prov.EVAL_COMMANDS.items():
            for script in re.findall(r'(?:eval|tools)/\w+\.py', cmd):
                self.assertTrue((ROOT / script).is_file(), (name, script))

    def test_real_repo_view_has_no_invented_values(self):
        view = prov.evals_view()
        gate = json.loads((ROOT / 'eval/gate_last.json').read_text(encoding='utf-8')) if (ROOT / 'eval/gate_last.json').exists() else None
        if gate:
            self.assertEqual(view['rows'][0]['commit'], gate['commit'])
            self.assertEqual(view['rows'][0]['date'], gate['date'])


if __name__ == '__main__':
    unittest.main()
