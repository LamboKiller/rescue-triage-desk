import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from app.operator_boundary import operator_allowed


def remote(path):
    # Docker bridge client: not loopback, so only the explicit container opt-in can open /run.
    return NS(server=NS(server_address=('0.0.0.0', 8000)), client_address=('172.17.0.1', 50123),
              headers={'Host': 'localhost:8000'}, path=path)


class ContainerRunGateTest(unittest.TestCase):
    def test_remote_run_closed_by_default(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(operator_allowed(remote('/run')))

    def test_opt_in_opens_only_run(self):
        with patch.dict('os.environ', {'RESCUE_OPEN_RUN': 'true'}, clear=True):
            self.assertTrue(operator_allowed(remote('/run')))
            self.assertFalse(operator_allowed(remote('/api/cases/c1/actions')))
            self.assertFalse(operator_allowed(remote('/api/telemetry/osmand'), device=True))

    def test_operator_token_overrides_opt_in(self):
        with patch.dict('os.environ', {'RESCUE_OPEN_RUN': 'true', 'RESCUE_OPERATOR_TOKEN': 'synthetic-test-token'}, clear=True):
            self.assertFalse(operator_allowed(remote('/run')))
            h = remote('/run'); h.headers['Authorization'] = 'Bearer synthetic-test-token'
            self.assertTrue(operator_allowed(h))

    def test_cross_origin_still_rejected(self):
        with patch.dict('os.environ', {'RESCUE_OPEN_RUN': 'true'}, clear=True):
            h = remote('/run'); h.headers['Origin'] = 'http://evil.example'
            self.assertFalse(operator_allowed(h))


if __name__ == '__main__':
    unittest.main()
