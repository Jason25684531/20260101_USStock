import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy.exc import OperationalError


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / 'web'

if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ['WEB_DISABLE_AUTH'] = 'true'
sys.modules.setdefault("yfinance", SimpleNamespace())

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

    def test_health_includes_provider_health_when_log_exists(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.side_effect = [
            Mock(),
            Mock(mappings=Mock(return_value=Mock(first=Mock(return_value={
                'run_at': '2026-05-20 21:00:00',
                'total_symbols': 503,
                'live_successes': 0,
                'fallback_successes': 120,
                'failed_symbols': 383,
                'skipped_symbols': 383,
                'coverage_ratio': 0.2386,
                'minimum_coverage_ratio': 0.6,
                'current_data_mode': 'stale',
                'stale_data_used': 1,
                'recommendations_written': 1,
                'top_error_types': '{"json_parse_error": 383}',
                'last_successful_run_at': '2026-05-20 21:00:00',
                'last_valid_recommendation_time': '2026-05-20',
            }))))
        ]
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(web_app_module, 'engine', fake_engine), \
             patch.object(web_app_module, '_table_exists', return_value=True):
            response = self.client.get('/health')

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['provider_health']['current_data_mode'], 'stale')
        self.assertEqual(payload['provider_health']['fallback_successes'], 120)
        self.assertAlmostEqual(payload['provider_health']['provider_coverage_ratio'], 0.2386)

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

    def test_recommendations_include_provider_health_metadata(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.side_effect = [
            Mock(scalar=Mock(return_value='2026-05-20')),
            [
                {
                    'scan_date': '2026-05-20',
                    'symbol': 'AAPL',
                    'rank_position': 1,
                    'signal_type': 'BUY',
                    'total_score': 4.5,
                    'breakout_pass': 1,
                    'acceleration_pass': 1,
                    'peg_pass': 0,
                    'dupont_pass': 1,
                    'institutional_pass': None,
                    'volume_structure_pass': None,
                    'money_flow_pass': None,
                    'multi_tf_momentum_pass': None,
                    'relative_strength_pass': None,
                    'earnings_quality_pass': None,
                    'sector_rotation_pass': None,
                    'ml_confidence': 0.7,
                    'current_price': 123.0,
                    'support_1': None,
                    'support_2': None,
                    'resistance_1': None,
                    'resistance_2': None,
                    'pe_ratio': None,
                    'peg_ratio': None,
                    'pb_ratio': None,
                    'roe': None,
                    'strategy_details': '{}',
                    'created_at': None,
                }
            ],
        ]
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(web_app_module, 'engine', fake_engine), \
             patch.object(web_app_module, '_table_exists', return_value=True), \
             patch.object(web_app_module, '_column_exists', return_value=False), \
             patch.object(web_app_module, '_load_latest_provider_health', return_value={
                 'status': 'critical',
                 'current_data_mode': 'failed',
                 'provider_coverage_ratio': 0.0,
                 'coverage': 0.0,
                 'last_valid_recommendation_time': '2026-05-20',
                 'last_valid_recommendation_at': '2026-05-20',
                 'recommendation_source': 'last_valid_snapshot',
                 'is_using_last_valid_snapshot': True,
             }):
            response = self.client.get('/api/recommendations?limit=5')

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['recommendations'][0]['symbol'], 'AAPL')
        self.assertEqual(payload['provider_health']['current_data_mode'], 'failed')
        self.assertTrue(payload['stale_or_degraded'])
        self.assertEqual(payload['recommendation_source'], 'last_valid_snapshot')
        self.assertTrue(payload['is_using_last_valid_snapshot'])
        self.assertEqual(payload['last_valid_recommendation_at'], '2026-05-20')
        self.assertEqual(payload['current_run_status'], 'critical')
        self.assertEqual(payload['current_run_coverage'], 0.0)

    def test_recommendations_empty_state_includes_provider_diagnostics(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn
        provider_health = web_app_module.normalize_provider_health({
            'status': 'critical',
            'current_data_mode': 'failed',
            'coverage_ratio': 0.0,
            'critical_coverage_ratio': 0.2,
            'recommendations_written': False,
            'last_valid_recommendation_time': '2026-05-28 00:00:00',
            'provider_attempts': [
                {'provider': 'openbb', 'success': False, 'error_type': 'openbbjson_parse_error'},
                {'provider': 'openbb', 'success': False, 'error_type': 'openbbjson_parse_error'},
            ],
            'top_error_types': {'json_parse_error': 2},
            'skip_reasons': {'provider_data_unavailable': 2},
        })

        with patch.object(web_app_module, 'engine', fake_engine), \
             patch.object(web_app_module, '_table_exists', return_value=False), \
             patch.object(web_app_module, '_load_latest_provider_health', return_value=provider_health):
            response = self.client.get('/api/recommendations?limit=5')

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['recommendations'], [])
        self.assertEqual(payload['provider_diagnostics']['root_cause'], 'openbb_json_parse_error')
        self.assertTrue(payload['provider_diagnostics']['snapshot_preserved'])
        self.assertIn('前次有效推薦', payload['provider_diagnostics']['display_message'])

    def test_recommendations_include_swing_ranking_metadata_from_strategy_details(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.side_effect = [
            Mock(scalar=Mock(return_value='2026-05-20')),
            [
                {
                    'scan_date': '2026-05-20',
                    'symbol': 'NVDA',
                    'rank_position': 1,
                    'signal_type': 'BUY',
                    'total_score': 86.4,
                    'breakout_pass': 1,
                    'acceleration_pass': 1,
                    'peg_pass': 0,
                    'dupont_pass': 1,
                    'institutional_pass': None,
                    'volume_structure_pass': None,
                    'money_flow_pass': None,
                    'multi_tf_momentum_pass': None,
                    'relative_strength_pass': None,
                    'earnings_quality_pass': None,
                    'sector_rotation_pass': None,
                    'ml_confidence': 0.7,
                    'current_price': 123.0,
                    'support_1': None,
                    'support_2': None,
                    'resistance_1': None,
                    'resistance_2': None,
                    'pe_ratio': None,
                    'peg_ratio': None,
                    'pb_ratio': None,
                    'roe': None,
                    'strategy_details': '{"swing_ranking":{"score":86.4,"setup_type":"breakout","trend_score":22,"momentum_score":20,"setup_score":18,"volatility_score":8,"risk_score":8,"liquidity_score":10,"reasons":["Close broke above the 20-day high"],"risk_flags":["Close is extended above MA20"],"stop_loss_price":118.5,"risk_percent":3.7}}',
                    'created_at': None,
                }
            ],
        ]
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(web_app_module, 'engine', fake_engine), \
             patch.object(web_app_module, '_table_exists', return_value=True), \
             patch.object(web_app_module, '_column_exists', return_value=False), \
             patch.object(web_app_module, '_load_latest_provider_health', return_value={
                 'status': 'healthy',
                 'current_data_mode': 'live',
                 'provider_coverage_ratio': 1.0,
                 'coverage': 1.0,
                 'recommendation_source': 'current_run',
                 'is_using_last_valid_snapshot': False,
             }):
            response = self.client.get('/api/recommendations?limit=5')

        rec = response.get_json()['recommendations'][0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(rec['score'], 86.4)
        self.assertEqual(rec['setup_type'], 'breakout')
        self.assertEqual(rec['trend_score'], 22)
        self.assertEqual(rec['momentum_score'], 20)
        self.assertEqual(rec['risk_score'], 8)
        self.assertEqual(rec['reasons'], ['Close broke above the 20-day high'])
        self.assertEqual(rec['risk_flags'], ['Close is extended above MA20'])
        self.assertEqual(rec['stop_loss_price'], 118.5)
        self.assertEqual(rec['risk_percent'], 3.7)

    def test_dashboard_template_has_swing_ranking_fields(self):
        template = (ROOT / 'web' / 'templates' / 'index.html').read_text(encoding='utf-8')

        self.assertIn('setup_type', template)
        self.assertIn('risk_flags', template)

    def test_provider_health_latest_endpoint_returns_normalized_contract(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn
        provider_health = {
            'provider_health_available': True,
            'status': 'stale',
            'coverage': 0.35,
            'provider_coverage_ratio': 0.35,
            'effective_provider': 'market_data',
            'is_stale': True,
            'stale_age_days': 4,
            'last_successful_provider': 'market_data',
            'last_successful_at': '2026-05-20 21:00:00',
            'provider_attempts': [{'provider': 'openbb', 'success': False}],
            'fallback_attempts': [{'provider': 'market_data', 'success': True}],
            'skip_reasons': {'timeout': 3},
            'top_error_types': {'timeout': 3},
            'current_run_status': 'stale',
            'recommendation_source': 'last_valid_snapshot',
            'is_using_last_valid_snapshot': True,
        }

        with patch.object(web_app_module, 'engine', fake_engine), \
             patch.object(web_app_module, '_load_latest_provider_health', return_value=provider_health):
            response = self.client.get('/api/provider-health/latest')

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'stale')
        self.assertEqual(payload['effective_provider'], 'market_data')
        self.assertTrue(payload['is_stale'])
        self.assertEqual(payload['stale_age_days'], 4)
        self.assertEqual(payload['recommendation_source'], 'last_valid_snapshot')

    def test_provider_health_history_endpoint_returns_newest_first_rows(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(web_app_module, 'engine', fake_engine), \
             patch.object(web_app_module, '_load_provider_health_history', return_value=[
                 {'run_at': '2026-05-21 21:00:00', 'status': 'healthy'},
                 {'run_at': '2026-05-20 21:00:00', 'status': 'stale'},
             ], create=True):
            response = self.client.get('/api/provider-health/history?limit=2')

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['limit'], 2)
        self.assertEqual([row['status'] for row in payload['rows']], ['healthy', 'stale'])

    def test_dashboard_template_has_provider_health_detail_panel_target(self):
        template = (ROOT / 'web' / 'templates' / 'index.html').read_text(encoding='utf-8')

        self.assertIn('sysDataHealthDetail', template)
        self.assertIn('/api/provider-health/latest', template)

    def test_dashboard_template_has_provider_incident_render_targets(self):
        template = (ROOT / 'web' / 'templates' / 'index.html').read_text(encoding='utf-8')

        self.assertIn('providerHealthIncidentMessage', template)
        self.assertIn('providerHealthOperatorActions', template)
        self.assertIn('目前資料供應異常', template)
        self.assertIn('前次有效推薦', template)

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
