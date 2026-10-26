"""Arbiter judges intake/critic conflicts on the post-revision fields."""
import time
import unittest

from app.agents import arbiter

TEXT = 'Estamos em tres pessoas no telhado, a agua subiu muito.'
PHRASE = 'tres pessoas no telhado'


class Counter:
    def __init__(self):
        self.roles = []

    def call(self, role, system, payload, deadline):
        self.roles.append(role)
        return {'choice': 'ESCALATE'}, dict(receipt='T', model='m')


def case(current, reason='missed', quote=PHRASE, field='people'):
    initial = {}
    return dict(text=TEXT, initial_fields=initial, fields=current, result=dict(decision='SEND_CANDIDATE'),
                agents=dict(intake=dict(fields=initial),
                            critic=dict(objections=[dict(field=field, reason=reason, quote=quote)])))


class RevisionAwareConflicts(unittest.TestCase):
    def run_case(self, c):
        client = Counter()
        arbiter.attach(c, client, time.monotonic()+5)
        return client, c

    def test_revision_that_adds_the_missed_phrase_needs_no_arbiter(self):
        c = case(dict(people=dict(value=3, quote='tres pessoas no telhado')))
        client, c = self.run_case(c)
        self.assertEqual(client.roles, [])
        self.assertEqual(c['result']['decision'], 'SEND_CANDIDATE')
        self.assertEqual(c['arbitration'][0]['rule'], 'validated_missing_phrase')

    def test_partial_overlap_of_quote_counts_as_supported(self):
        c = case(dict(people=dict(value=3, quote='em tres pessoas no telhado')))
        client, c = self.run_case(c)
        self.assertEqual(client.roles, [])
        self.assertEqual(c['result']['decision'], 'SEND_CANDIDATE')

    def test_failed_revision_keeps_conflict(self):
        client, c = self.run_case(case({}))
        self.assertEqual(len(c['arbitration']), 1)
        self.assertEqual(c['result']['decision'], 'REVIEW_REQUIRED')

    def test_revision_contradicting_quote_keeps_conflict_and_never_sends_via_model(self):
        c = case(dict(people=dict(value=1, quote='a agua subiu muito')))
        client, c = self.run_case(c)
        self.assertEqual(client.roles, ['arbiter'])
        self.assertEqual(c['result']['decision'], 'REVIEW_REQUIRED')


if __name__ == '__main__':
    unittest.main()
