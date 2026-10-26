"""Animal rescue routing and literal landmark evidence regressions."""
import contextlib
import io
from pathlib import Path
import time
import unittest

from app.agents import location
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline
from support import Scratch
from test_l1 import place, street, REPLAY


class EvidenceTests(unittest.TestCase):
    def test_animal_rescue_keeps_lookup_and_human_review(self):
        class Source:
            def streets(self, **kwargs):
                return [street('Rua Boreal')]
        scratch = Scratch()
        self.addCleanup(scratch.cleanup)
        with contextlib.redirect_stdout(io.StringIO()):
            case = Pipeline(Registry(Path(scratch.name)/'events.jsonl'), sample=True, source=Source()).run(
                dict(replay_time=REPLAY, messages=[dict(message_id='animal-rescue',
                     text='Resgatar 3 gatos presos na Rua Boreal, número 17, Canoas. Nenhuma pessoa no local.')]))['cases'][0]
        self.assertEqual(case['result']['decision'], 'REVIEW_REQUIRED')
        self.assertEqual(case['route']['id'], 'incomplete')
        self.assertTrue(case['checks']['found'])
        self.assertNotEqual(case['agents']['location']['location_path'], 'not_required')
        self.assertEqual(case['fields']['pets']['value'], 3)

    def test_catalogue_alias_retains_callers_landmark_phrase(self):
        phrase = 'perto da Escola Lunar'
        fields = dict(landmark=dict(value=phrase, quote=phrase),
                      municipality=dict(value='Canoas', quote='Canoas'))
        row = place('Escola Municipal Lunar')
        row['alt_names'] = 'Escola Lunar'
        out = location.locate([], [row], fields, '3 pessoas '+phrase+' em Canoas.',
                              REPLAY, None, time.monotonic()+10)
        self.assertEqual(fields['landmark'], dict(value=phrase, quote=phrase))
        self.assertEqual(out[2]['matched']['name'], row['name'])
        self.assertEqual(out[2]['status'], 'resolved')


if __name__ == '__main__':
    unittest.main()
