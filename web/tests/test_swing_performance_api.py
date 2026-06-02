import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ["WEB_DISABLE_AUTH"] = "true"
sys.modules.setdefault("yfinance", SimpleNamespace())

import app as web_app_module
from bot import handler as linebot_handler


class SwingPerformanceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        web_app_module.app.config["TESTING"] = True
        web_app_module.WEB_DISABLE_AUTH = True

    def setUp(self):
        self.client = web_app_module.app.test_client()

    def test_swing_performance_endpoint_returns_sectioned_payload(self):
        payload = {
            "summary": {"sample_size": 12, "avg_forward_return_20d": 0.038, "hit_rate_20d": 0.64},
            "rank_groups": [{"group": "top5", "sample_size": 5}],
            "score_buckets": [{"bucket": ">=80", "sample_size": 4}],
            "setup_types": [{"setup_type": "breakout", "sample_size": 3}],
            "risk_flags": [{"group": "any_risk_flag", "sample_size": 2}],
            "provider_health_segments": [{"provider_health_status": "healthy", "sample_size": 10}],
            "calibration": {"status": "active", "active_profile_version": "cal-test", "source_sample_size": 120},
            "recent_evaluations": [{"symbol": "NVDA", "recommendation_source": "current_run"}],
        }

        with patch.object(web_app_module, "_load_swing_performance_payload", return_value=payload):
            response = self.client.get("/api/swing-performance")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["summary"]["sample_size"], 12)
        self.assertEqual(body["rank_groups"][0]["group"], "top5")
        self.assertEqual(body["calibration"]["active_profile_version"], "cal-test")
        self.assertEqual(body["recent_evaluations"][0]["recommendation_source"], "current_run")

    def test_swing_performance_endpoint_returns_empty_safe_payload(self):
        with patch.object(web_app_module, "_load_swing_performance_payload", return_value=web_app_module._empty_swing_performance_payload()):
            response = self.client.get("/api/swing-performance")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["summary"]["sample_size"], 0)
        self.assertIsNone(body["summary"]["avg_forward_return_20d"])
        self.assertEqual(body["score_buckets"], [])
        self.assertEqual(body["calibration"]["status"], "inactive")
        self.assertFalse(body["calibration"]["active"])
        self.assertEqual(body["recent_evaluations"], [])

    def test_dashboard_template_has_swing_performance_section_targets(self):
        template = (WEB_DIR / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn("swingPerformanceSection", template)
        self.assertIn("swingPerformanceSummary", template)
        self.assertIn("swingCalibrationStatus", template)
        self.assertIn("swingCalibrationDriftStatus", template)
        self.assertIn("loadSwingCalibrationDrift", template)
        self.assertIn("loadSwingPerformance", template)

    def test_calibration_drift_endpoint_returns_stable_payload(self):
        payload = {
            "active_profile_version": "cal-test",
            "active": True,
            "drift_status": "warning",
            "score_bucket_status": "drifted",
            "top_rank_status": "warning",
            "risk_flag_status": "insufficient_data",
            "calibration_impact_status": "neutral",
            "messages": ["High score bucket underperformed lower buckets by 1.2%"],
            "recent_audit_events": [],
            "rollback_available": False,
        }

        with patch.object(web_app_module, "_load_calibration_drift_payload", return_value=payload):
            response = self.client.get("/api/swing-calibration/drift")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["active_profile_version"], "cal-test")
        self.assertEqual(body["drift_status"], "warning")
        self.assertEqual(body["score_bucket_status"], "drifted")
        self.assertEqual(body["recent_audit_events"], [])


class LineBotSwingPerformanceTests(unittest.TestCase):
    def test_process_command_routes_performance_summary(self):
        expected = [{"type": "text", "text": "Swing Ranking Performance"}]

        with patch.object(linebot_handler, "_cmd_performance", return_value=expected) as perf_cmd:
            messages = linebot_handler.process_command("/performance", user_id="user-123")

        self.assertEqual(messages, expected)
        perf_cmd.assert_called_once_with()

    def test_process_command_routes_calibration_summary(self):
        expected = [{"type": "text", "text": "Calibration Drift"}]

        with patch.object(linebot_handler, "_cmd_calibration", return_value=expected) as calibration_cmd:
            messages = linebot_handler.process_command("/calibration", user_id="user-123")

        self.assertEqual(messages, expected)
        calibration_cmd.assert_called_once_with()

    def test_calibration_command_returns_active_drift_summary(self):
        payload = {
            "active_profile_version": "cal-test",
            "active": True,
            "drift_status": "warning",
            "score_bucket_status": "drifted",
            "top_rank_status": "warning",
            "risk_flag_status": "insufficient_data",
            "calibration_impact_status": "neutral",
            "messages": ["High score bucket underperformed lower buckets by 1.2%"],
            "sample_size": 120,
        }

        with patch.object(linebot_handler, "_load_calibration_drift_for_linebot", return_value=payload):
            messages = linebot_handler._cmd_calibration()

        text = messages[0]["text"]
        self.assertIn("Calibration Drift", text)
        self.assertIn("Active: cal-test", text)
        self.assertIn("Status: warning", text)
        self.assertIn("Score bucket: drifted", text)
        self.assertIn("Risk flags: insufficient data", text)
        self.assertIn("High score bucket", text)

    def test_performance_command_returns_summary_when_data_exists(self):
        payload = {
            "summary": {"sample_size": 120, "avg_forward_return_20d": 0.038, "hit_rate_20d": 0.64},
            "score_buckets": [
                {"bucket": ">=80", "sample_size": 32, "avg_forward_return_20d": 0.061}
            ],
            "setup_types": [
                {"setup_type": "pullback_reclaim", "sample_size": 44, "avg_forward_return_20d": 0.051}
            ],
            "risk_flags": [
                {"group": "any_risk_flag", "sample_size": 20, "avg_forward_return_20d": 0.012}
            ],
            "calibration": {
                "status": "active",
                "active_profile_version": "cal-test",
                "source_sample_size": 120,
            },
        }

        with patch.object(linebot_handler, "_load_performance_payload_for_linebot", return_value=payload):
            messages = linebot_handler._cmd_performance()

        text = messages[0]["text"]
        self.assertIn("Swing Ranking Performance", text)
        self.assertIn("Sample: 120", text)
        self.assertIn("20D avg return: +3.8%", text)
        self.assertIn("20D hit rate: 64.0%", text)
        self.assertIn("Best setup: pullback_reclaim +5.1%", text)
        self.assertIn("Best score bucket: >=80 +6.1%", text)
        self.assertIn("Risk-flagged avg return: +1.2%", text)
        self.assertIn("Calibration: active cal-test n=120", text)

    def test_performance_command_returns_no_data_message(self):
        with patch.object(linebot_handler, "_load_performance_payload_for_linebot", return_value={"summary": {"sample_size": 0}}):
            messages = linebot_handler._cmd_performance()

        self.assertIn("performance data is not available yet", messages[0]["text"])

    def test_performance_command_reports_inactive_calibration_without_overstating_tuning(self):
        payload = {
            "summary": {"sample_size": 10, "avg_forward_return_20d": 0.01, "hit_rate_20d": 0.5},
            "score_buckets": [],
            "setup_types": [],
            "risk_flags": [],
            "calibration": {"status": "inactive", "active": False, "source_sample_size": 0},
        }

        with patch.object(linebot_handler, "_load_performance_payload_for_linebot", return_value=payload):
            messages = linebot_handler._cmd_performance()

        text = messages[0]["text"]
        self.assertIn("Calibration: inactive/default profile", text)
        self.assertNotIn("calibrated performance guarantee", text)

    def test_performance_command_keeps_provider_incident_separate(self):
        payload = {
            "summary": {"sample_size": 10, "avg_forward_return_20d": 0.01, "hit_rate_20d": 0.5},
            "score_buckets": [],
            "setup_types": [],
            "risk_flags": [],
            "calibration": {"status": "active", "active_profile_version": "cal-test", "source_sample_size": 10},
        }
        provider_health = linebot_handler.normalize_provider_health({
            "coverage_ratio": 0.0,
            "critical_coverage_ratio": 0.2,
            "current_data_mode": "failed",
            "recommendations_written": False,
            "last_valid_recommendation_time": "2026-05-28 00:00:00",
            "provider_attempts": [
                {"provider": "openbb", "success": False, "error_type": "openbbjson_parse_error"},
            ],
            "top_error_types": {"json_parse_error": 1},
        })

        with patch.object(linebot_handler, "_load_performance_payload_for_linebot", return_value=payload), \
             patch.object(linebot_handler, "_load_latest_provider_health_for_linebot", return_value=provider_health):
            messages = linebot_handler._cmd_performance()

        text = messages[0]["text"]
        self.assertIn("Swing Ranking Performance", text)
        self.assertIn("Calibration: active cal-test n=10", text)
        self.assertIn("Provider incident: critical", text)
        self.assertIn("root_cause=openbb_json_parse_error", text)
        self.assertNotIn("current provider run is healthy", text)

    def test_calibration_command_keeps_provider_incident_separate(self):
        payload = {
            "active_profile_version": "cal-test",
            "active": True,
            "drift_status": "warning",
            "score_bucket_status": "healthy",
            "top_rank_status": "warning",
            "risk_flag_status": "insufficient_data",
            "calibration_impact_status": "neutral",
            "messages": [],
        }
        provider_health = linebot_handler.normalize_provider_health({
            "coverage_ratio": 0.0,
            "critical_coverage_ratio": 0.2,
            "current_data_mode": "failed",
            "recommendations_written": False,
            "top_error_types": {"json_parse_error": 1},
        })

        with patch.object(linebot_handler, "_load_calibration_drift_for_linebot", return_value=payload), \
             patch.object(linebot_handler, "_load_latest_provider_health_for_linebot", return_value=provider_health):
            messages = linebot_handler._cmd_calibration()

        text = messages[0]["text"]
        self.assertIn("Calibration Drift", text)
        self.assertIn("Provider incident: critical", text)
        self.assertIn("provider health separate from calibration quality", text)


if __name__ == "__main__":
    unittest.main()
