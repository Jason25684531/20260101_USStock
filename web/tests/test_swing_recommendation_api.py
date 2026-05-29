import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ["WEB_DISABLE_AUTH"] = "true"

import app as web_app_module


class SwingRecommendationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web_app_module.app.config["TESTING"] = True
        web_app_module.WEB_DISABLE_AUTH = True

    def setUp(self):
        self.client = web_app_module.app.test_client()

    def _fake_conn(self, strategy_details):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.side_effect = [
            Mock(scalar=Mock(return_value="2026-05-20")),
            [
                {
                    "scan_date": "2026-05-20",
                    "symbol": "MSFT",
                    "rank_position": 2,
                    "signal_type": "BUY",
                    "total_score": 82.0,
                    "breakout_pass": 1,
                    "acceleration_pass": 1,
                    "peg_pass": 0,
                    "dupont_pass": 1,
                    "institutional_pass": None,
                    "volume_structure_pass": None,
                    "money_flow_pass": None,
                    "multi_tf_momentum_pass": None,
                    "relative_strength_pass": None,
                    "earnings_quality_pass": None,
                    "sector_rotation_pass": None,
                    "ml_confidence": None,
                    "current_price": 310.0,
                    "support_1": None,
                    "support_2": None,
                    "resistance_1": None,
                    "resistance_2": None,
                    "pe_ratio": None,
                    "peg_ratio": None,
                    "pb_ratio": None,
                    "roe": None,
                    "strategy_details": strategy_details,
                    "created_at": None,
                }
            ],
        ]
        return fake_conn

    def test_recommendations_endpoint_returns_swing_ranking_metadata(self):
        fake_engine = Mock()
        fake_engine.connect.return_value = self._fake_conn(
            '{"swing_ranking":{"score":82,"setup_type":"pullback_reclaim","trend_score":21,"momentum_score":18,"setup_score":18,"volatility_score":8,"risk_score":9,"liquidity_score":8,"reasons":["Pullback reclaimed MA20/EMA20"],"risk_flags":[],"stop_loss_price":298.5,"risk_percent":3.7}}'
        )

        with patch.object(web_app_module, "engine", fake_engine), \
             patch.object(web_app_module, "_table_exists", return_value=True), \
             patch.object(web_app_module, "_column_exists", return_value=False), \
             patch.object(web_app_module, "_load_latest_provider_health", return_value={
                 "status": "healthy",
                 "current_data_mode": "live",
                 "coverage": 1.0,
                 "provider_coverage_ratio": 1.0,
                 "recommendation_source": "current_run",
                 "is_using_last_valid_snapshot": False,
             }):
            response = self.client.get("/api/recommendations?limit=5")

        payload = response.get_json()
        rec = payload["recommendations"][0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(rec["setup_type"], "pullback_reclaim")
        self.assertEqual(rec["score"], 82.0)
        self.assertEqual(rec["reasons"], ["Pullback reclaimed MA20/EMA20"])
        self.assertEqual(rec["risk_flags"], [])
        self.assertEqual(payload["recommendation_source"], "current_run")
        self.assertEqual(payload["provider_health"]["status"], "healthy")

    def test_recommendations_endpoint_defaults_missing_swing_metadata_safely(self):
        fake_engine = Mock()
        fake_engine.connect.return_value = self._fake_conn("{}")

        with patch.object(web_app_module, "engine", fake_engine), \
             patch.object(web_app_module, "_table_exists", return_value=True), \
             patch.object(web_app_module, "_column_exists", return_value=False), \
             patch.object(web_app_module, "_load_latest_provider_health", return_value={
                 "status": "critical",
                 "current_data_mode": "failed",
                 "coverage": 0.0,
                 "provider_coverage_ratio": 0.0,
                 "recommendation_source": "last_valid_snapshot",
                 "is_using_last_valid_snapshot": True,
             }):
            response = self.client.get("/api/recommendations?limit=5")

        rec = response.get_json()["recommendations"][0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(rec["score"], 82.0)
        self.assertIsNone(rec["setup_type"])
        self.assertEqual(rec["reasons"], [])
        self.assertEqual(rec["risk_flags"], [])
        self.assertTrue(response.get_json()["is_using_last_valid_snapshot"])


if __name__ == "__main__":
    unittest.main()
