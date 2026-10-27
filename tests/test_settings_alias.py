import os
import unittest
from unittest import mock

from app.config import setting

KEYS = ('NIGHTSHIFT_BASE_URL', 'NIGHTSHIFT_API_KEY', 'METERLESS_BASE_URL', 'METERLESS_RUNTIME_TOKEN')


def env(**values):
    base = {k: v for k, v in os.environ.items() if k not in KEYS}
    base.update(values)
    return mock.patch.dict(os.environ, base, clear=True)


class SettingsAliasTest(unittest.TestCase):
    def test_meterless_names_fill_unset_nightshift_names(self):
        with env(METERLESS_BASE_URL='http://m:1/v1', METERLESS_RUNTIME_TOKEN='tok'):
            self.assertEqual(setting('NIGHTSHIFT_BASE_URL', 'd'), 'http://m:1/v1')
            self.assertEqual(setting('NIGHTSHIFT_API_KEY'), 'tok')

    def test_nightshift_names_win(self):
        with env(NIGHTSHIFT_BASE_URL='http://n:2/v1', METERLESS_BASE_URL='http://m:1/v1'):
            self.assertEqual(setting('NIGHTSHIFT_BASE_URL', 'd'), 'http://n:2/v1')

    def test_default_when_neither_set(self):
        with env():
            self.assertEqual(setting('NIGHTSHIFT_BASE_URL', 'http://127.0.0.1:8088/v1'), 'http://127.0.0.1:8088/v1')
            self.assertEqual(setting('NIGHTSHIFT_API_KEY'), '')
            self.assertEqual(setting('OTHER_NAME', 'x'), 'x')


if __name__ == '__main__':
    unittest.main()
