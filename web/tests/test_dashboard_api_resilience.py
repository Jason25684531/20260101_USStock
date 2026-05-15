import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy.exc import OperationalError


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / 'web'

if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ['WEB_DISABLE_AUTH'] = 'true'

import app as web_app_module


class DummyDBError(Exception):
    def __init__(self, errno, message):
        super().__init__(errno, message)
        self.errno = errno


class DashboardApiResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web_app_module.app.config['TESTING'] = True
        web_app_module.WEB_DISABLE_AUTH = True

    def setUp(self):
        self.client = web_app_module.app.test_client()

    def _recoverable_connect_error(self):
        return OperationalError(
            'connect',
            None,
            DummyDBError(2003, "Can't connect to MySQL server on 'localhost:3308' (10061)"),
        )

    def test_recommendations_degrades_when_database_unavailable(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = self._recoverable_connect_error()

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/recommendations?limit=10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['recommendations'], [])
        self.assertTrue(response.get_json()['degraded'])

    def test_portfolio_degrades_when_database_unavailable(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = self._recoverable_connect_error()

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/portfolio')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['holdings'], [])
        self.assertTrue(response.get_json()['degraded'])

    def test_portfolio_state_degrades_when_database_unavailable(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = self._recoverable_connect_error()

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/portfolio/state')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['holdings'], [])
        self.assertEqual(payload['sector_breakdown'], [])
        self.assertEqual(payload['correlation']['symbols'], [])
        self.assertEqual(payload['correlation']['matrix'], [])
        self.assertTrue(payload['degraded'])

    def test_macro_degrades_when_database_unavailable(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = self._recoverable_connect_error()

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/macro')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()['regime'])
        self.assertEqual(response.get_json()['indicators'], {})
        self.assertTrue(response.get_json()['degraded'])

    def test_unrecoverable_error_still_returns_500(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = RuntimeError('boom')

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/recommendations?limit=10')

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()['error'], 'recommendations failed')

    def test_recommendation_dates_degrades_when_database_unavailable(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = self._recoverable_connect_error()

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/recommendations/dates')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['dates'], [])
        self.assertTrue(response.get_json()['degraded'])

    def test_strategies_degrades_when_database_unavailable(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = self._recoverable_connect_error()

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/strategies')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['strategies'], [])
        self.assertTrue(response.get_json()['degraded'])

    def test_sectors_degrades_when_database_unavailable(self):
        failing_engine = Mock()
        failing_engine.connect.side_effect = self._recoverable_connect_error()

        with patch.object(web_app_module, 'engine', failing_engine):
            response = self.client.get('/api/sectors')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['sectors'], [])
        self.assertIsNone(response.get_json()['report_date'])
        self.assertTrue(response.get_json()['degraded'])


if __name__ == '__main__':
    unittest.main()
