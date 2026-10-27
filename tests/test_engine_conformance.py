"""Conformance test for the Meterless World Model engine (app/engines/world_model/registry.py).

This names, in one place, the six behavioural properties the README and
docs/submission/SPONSOR_EXPLANATION.md claim for our World Model adaptation, so a
reviewer can point at one file instead of locating the claim across tests/test_core.py
and tests/test_pipeline.py. It is a conformance test for OUR behavioural adaptation,
not upstream Meterless SDK certification -- no Meterless SDK is imported anywhere.
"""
import unittest
from pathlib import Path

from support import Scratch
from app.engines.world_model.registry import Registry, Conflict

TIME = '2024-05-06T14:00:00-03:00'


def case(mid='conformance', text='3 pessoas', at=TIME):
    return {'message_id': mid, 'text': text, 'received_at': at, 'synthetic': True,
            'fleet': [{'asset': 'irb', 'label_pt': 'Bote', 'verdict': 'caution',
                       'reasons_pt': ['Verifique a equipe.'], 'rule_ids': ['R004'], 'source_ids': ['POLICY']}],
            'result': {'priority': 1, 'decision': 'SEND_CANDIDATE'}}


class EngineConformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Scratch()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'events.jsonl'
        self.registry = Registry(self.path)

    def test_journal_is_append_only(self):
        """Every mutation adds a line; no prior line is ever rewritten or removed."""
        self.registry.ingest(case())
        after_first = self.path.read_text(encoding='utf-8')
        self.registry.ingest(case(text='4 pessoas'))
        after_second = self.path.read_text(encoding='utf-8')
        self.assertTrue(after_second.startswith(after_first))
        self.assertEqual(len(after_second.splitlines()), len(after_first.splitlines()) + 1)

    def test_state_is_a_pure_replay_of_the_journal(self):
        """A fresh Registry pointed at the same file reconstructs identical state by replay alone."""
        c = self.registry.ingest(case())
        c = self.registry.action(c['case_id'], 'confirm_location', 1, 'demo', human=True)
        replayed = Registry(self.path).read(c['case_id'])
        self.assertEqual(replayed, self.registry.read(c['case_id']))
        self.assertEqual(replayed['version'], 2)

    def test_duplicate_delivery_is_deduplicated(self):
        """Ingesting byte-identical text for the same message is a no-op, not a second event."""
        first = self.registry.ingest(case())
        second = self.registry.ingest(case())
        self.assertEqual(first, second)
        self.assertEqual(len(self.path.read_text(encoding='utf-8').splitlines()), 1)

    def test_conflicting_observations_are_retained_not_overwritten(self):
        """A later, different report about the same case is kept alongside the earlier one."""
        self.registry.ingest(case())
        changed = self.registry.ingest(case(text='4 pessoas'))
        self.assertEqual(len(changed['facts']), 2)
        self.assertEqual({f['text'] for f in changed['facts']}, {'3 pessoas', '4 pessoas'})

    def test_stale_expected_version_is_rejected_as_conflict(self):
        """A command against a version that is no longer current is refused (the 409-equivalent gate)."""
        c = self.registry.ingest(case())
        self.registry.action(c['case_id'], 'confirm_location', c['version'], 'demo', human=True)
        with self.assertRaises(Conflict):
            self.registry.action(c['case_id'], 'confirm_location', c['version'], 'demo', human=True)

    def test_transitions_require_an_explicit_human_flag(self):
        """No model or automated caller can move a case through a state transition."""
        c = self.registry.ingest(case())
        with self.assertRaises(PermissionError):
            self.registry.action(c['case_id'], 'confirm_location', c['version'], 'demo')
        with self.assertRaises(PermissionError):
            self.registry.action(c['case_id'], 'approve_dispatch', c['version'], 'demo', asset='irb')


if __name__ == '__main__':
    unittest.main()
