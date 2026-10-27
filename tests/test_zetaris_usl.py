"""Offline tests for the Unified Semantic Layer reads (app/data/usl.py).

These exercise the SAMPLE_MODE (LocalSource) path only -- no network, no Zetaris --
and assert against counts independently verified live against Zetaris on 2026-10-27
(see docs/submission/ZETARIS_USL.md). A live-mode counterpart is intentionally not
in the offline suite: the brief forbids network calls from this review.
"""
import unittest
from unittest import mock

from app.data import usl


def _sample_mode():
    """Force the LocalSource (offline CSV) path without mutating process-wide os.environ,
    which would leak into other test modules sharing this unittest process."""
    return mock.patch('app.data.usl.sample_mode', return_value=True)


class IncidentContextTests(unittest.TestCase):
    def setUp(self):
        self._patch = _sample_mode()
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_joins_every_landmark_with_its_municipality_flood_totals(self):
        rows = usl.incident_context()
        self.assertEqual(len(rows), 4201)
        canoas_flooded = [r for r in rows if r['municipality'] == 'Canoas' and r['landmark_in_water_0506'] == '1']
        self.assertEqual(len(canoas_flooded), 252)  # matches live Zetaris landmarks_v4 GROUP BY query
        self.assertEqual(canoas_flooded[0]['municipality_flooded_segments_0506'], 1345.0)

    def test_porto_alegre_flooded_segment_total_matches_live_zetaris(self):
        rows = usl.incident_context()
        poa = next(r for r in rows if r['municipality'] == 'Porto Alegre')
        self.assertEqual(poa['municipality_total_segments'], 19742.0)
        self.assertEqual(poa['municipality_flooded_segments_0506'], 4514.0)

    def test_landmark_with_no_street_matches_still_joins(self):
        rows = usl.incident_context()
        unmatched = [r for r in rows if r['municipality'] not in (None, '')]
        self.assertTrue(all(r['municipality_total_segments'] is not None for r in unmatched
                             if r['municipality'] in ('Porto Alegre', 'Canoas', 'São Leopoldo',
                                                       'Eldorado do Sul', 'Guaíba', 'Novo Hamburgo')))


class AssetAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self._patch = _sample_mode()
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_every_row_has_a_known_pump_and_a_boolean_down_flag(self):
        rows = usl.asset_availability()
        self.assertEqual(len(rows), 988)
        self.assertTrue(all(isinstance(r['is_down'], bool) for r in rows))
        self.assertTrue(any(r['is_down'] for r in rows))

    def test_down_on_0506_count_matches_live_zetaris(self):
        rows = usl.asset_availability()
        down = [r for r in rows if r['status_date'] == '2024-05-06' and r['is_down']]
        self.assertEqual(len(down), 10)


class ShelterCapacityTests(unittest.TestCase):
    def setUp(self):
        self._patch = _sample_mode()
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_occupancy_rate_only_computed_when_both_fields_present(self):
        rows = usl.shelter_capacity()
        self.assertEqual(len(rows), 7574)
        for row in rows:
            if row['capacity'] in (None, '') or row['sheltered_people'] in (None, ''):
                self.assertIsNone(row['occupancy_rate'])

    def test_over_capacity_rule_matches_live_zetaris_dq_check(self):
        rule = usl.shelter_over_capacity_rule()
        self.assertEqual(rule['checked'], 734)
        self.assertEqual(rule['violations'], 62)
        self.assertTrue(all(ex['over_capacity_flag'] for ex in rule['examples']))

    def test_sample_mode_result_is_deterministic(self):
        self.assertEqual(usl.shelter_over_capacity_rule(), usl.shelter_over_capacity_rule())


if __name__ == '__main__':
    unittest.main()
