import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy.exc import OperationalError


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ["WEB_DISABLE_AUTH"] = "true"
sys.modules.setdefault("yfinance", SimpleNamespace())

from bot import handler as linebot_handler


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConnection:
    def __init__(self, execute_results):
        self._execute_results = list(execute_results)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *args, **kwargs):
        result = self._execute_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class _FakeEngine:
    def __init__(self, connections):
        self._connections = list(connections)
        self.dispose_count = 0

    def connect(self):
        return self._connections.pop(0)

    def dispose(self):
        self.dispose_count += 1


def _stale_mysql_error():
    return OperationalError(
        "SELECT MAX(scan_date) FROM daily_recommendations",
        {},
        Exception("MySQL Connection not available."),
    )


def _top5_row():
    return {
        "symbol": "NVDA",
        "rank_position": 1,
        "signal_type": "BUY",
        "total_score": 86.4,
        "current_price": 123.0,
        "target_price": 140.0,
        "ml_confidence": 0.91,
        "institutional_ownership": 0.72,
        "insider_sentiment": "NEUTRAL",
        "institutional_pass": 1,
        "money_flow_pass": 1,
        "valuation_status": "FAIR",
        "buy_price": 118.0,
        "sell_price": 150.0,
        "reason_summary": "Daily morning setup",
        "support_1": 118.0,
        "resistance_1": 150.0,
        "breakout_pass": 1,
        "acceleration_pass": 1,
        "peg_pass": 1,
        "dupont_pass": 1,
        "strategy_details": '{"swing_ranking":{"score":86.4,"setup_type":"breakout","reasons":["Close broke above the 20-day high"],"risk_flags":["Close is extended above MA20"]}}',
    }


class LineBotHandlerTests(unittest.TestCase):
    def test_process_command_routes_bare_ticker_to_stock(self):
        expected_messages = [{"type": "text", "text": "ok"}]

        with patch.object(linebot_handler, "_cmd_stock", return_value=expected_messages) as stock_cmd:
            messages = linebot_handler.process_command("AAPL", user_id="user-123")

        self.assertEqual(messages, expected_messages)
        stock_cmd.assert_called_once_with("AAPL")

    def test_process_command_routes_exact_recommend_to_default_strategy(self):
        expected_messages = [{"type": "flex", "altText": "default", "contents": {"type": "carousel", "contents": []}}]

        with patch.object(linebot_handler, "_cmd_default_recommendations", return_value=expected_messages, create=True) as default_cmd, \
             patch.object(linebot_handler, "_cmd_momentum_recommendations", return_value=[{"type": "text", "text": "momentum"}], create=True) as momentum_cmd, \
             patch.object(linebot_handler, "_cmd_institutional_recommendations", return_value=[{"type": "text", "text": "institutional"}], create=True) as institutional_cmd, \
             patch.object(linebot_handler, "_cmd_top5_realtime", return_value=[{"type": "text", "text": "realtime"}]) as realtime_cmd:
            messages = linebot_handler.process_command("推薦", user_id="user-123")

        self.assertEqual(messages, expected_messages)
        default_cmd.assert_called_once_with()
        momentum_cmd.assert_not_called()
        institutional_cmd.assert_not_called()
        realtime_cmd.assert_not_called()

    def test_handle_message_event_calibration_replies_once_and_logs_success(self):
        event = {
            "replyToken": "reply-token",
            "source": {"userId": "user-123"},
            "message": {"type": "text", "text": "  /CaLiBrAtIoN  "},
        }
        sent = []
        logs = []

        with patch.object(linebot_handler, "_cmd_calibration", return_value=[{"type": "text", "text": "Calibration Drift"}]) as calibration_cmd, \
             patch.object(linebot_handler, "http_requests") as http_requests, \
             patch.object(linebot_handler, "CHANNEL_TOKEN", "token"), \
             patch.object(linebot_handler, "_log_linebot", side_effect=logs.append):
            http_requests.post.return_value = Mock(status_code=200, text="OK")
            linebot_handler.handle_message_event(event)
            sent.append(http_requests.post.call_args.kwargs["json"])

        calibration_cmd.assert_called_once_with()
        self.assertEqual(http_requests.post.call_count, 1)
        self.assertEqual(len(sent[0]["messages"]), 1)
        self.assertEqual(sent[0]["messages"][0]["text"], "Calibration Drift")
        self.assertIn("LineBot command=/calibration started", logs)
        self.assertIn("LineBot command=/calibration build succeeded", logs)
        self.assertIn("LineBot command=/calibration reply sent successfully", logs)

    def test_process_command_routes_momentum_recommendation(self):
        expected_messages = [{"type": "flex", "altText": "momentum", "contents": {"type": "carousel", "contents": []}}]

        with patch.object(linebot_handler, "_cmd_momentum_recommendations", return_value=expected_messages, create=True) as momentum_cmd:
            messages = linebot_handler.process_command("推薦 動量", user_id="user-123")

        self.assertEqual(messages, expected_messages)
        momentum_cmd.assert_called_once_with()

    def test_process_command_routes_institutional_recommendation_aliases(self):
        expected_messages = [{"type": "flex", "altText": "institutional", "contents": {"type": "carousel", "contents": []}}]

        for command in ("推薦 機構", "推薦 籌碼"):
            with self.subTest(command=command), \
                 patch.object(linebot_handler, "_cmd_institutional_recommendations", return_value=expected_messages, create=True) as institutional_cmd:
                messages = linebot_handler.process_command(command, user_id="user-123")

            self.assertEqual(messages, expected_messages)
            institutional_cmd.assert_called_once_with()

    def test_process_command_returns_supported_strategy_hint_for_unknown_recommendation(self):
        messages = linebot_handler.process_command("推薦 亂碼", user_id="user-123")

        self.assertEqual(messages[0]["type"], "text")
        self.assertIn("推薦", messages[0]["text"])
        self.assertIn("動量", messages[0]["text"])
        self.assertIn("機構", messages[0]["text"])

    def test_status_reports_degraded_provider_health(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.side_effect = [
            Mock(),
            Mock(first=Mock(return_value=("2026-05-20", 5))),
        ]
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(linebot_handler, "_get_db_engine", return_value=fake_engine), \
             patch.object(linebot_handler, "_load_latest_provider_health", return_value={
                 "status": "critical",
                 "current_data_mode": "failed",
                 "provider_coverage_ratio": 0.0,
                 "coverage": 0.0,
                 "effective_provider": "provider_chain",
                 "is_stale": False,
                 "live_successes": 0,
                 "fallback_successes": 0,
                 "failed_symbols": 503,
                 "skipped_symbols": 503,
                 "top_error_types": {"timeout": 503},
                 "recommendation_source": "last_valid_snapshot",
                 "is_using_last_valid_snapshot": True,
                 "last_successful_run_at": None,
             }):
            messages = linebot_handler._cmd_status()

        text = messages[0]["text"]
        self.assertIn("data_health=critical", text)
        self.assertIn("failed", text)
        self.assertIn("coverage=0.00", text)
        self.assertIn("effective_provider=provider_chain", text)
        self.assertIn("recommendation_source=last_valid_snapshot", text)
        self.assertIn("top_errors=timeout:503", text)
        self.assertNotIn("系統運行正常", text)

    def test_status_reports_parse_error_with_chinese_remediation(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.side_effect = [
            Mock(),
            Mock(first=Mock(return_value=("2026-05-28", 5))),
        ]
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn
        provider_health = linebot_handler.normalize_provider_health({
            "coverage_ratio": 0.0,
            "critical_coverage_ratio": 0.2,
            "current_data_mode": "failed",
            "recommendations_written": False,
            "last_valid_recommendation_time": "2026-05-28 00:00:00",
            "provider_attempts": [
                {"provider": "openbb", "success": False, "error_type": "openbbjson_parse_error"},
                {"provider": "openbb", "success": False, "error_type": "openbbjson_parse_error"},
            ],
            "top_error_types": {"json_parse_error": 2},
            "skip_reasons": {"provider_data_unavailable": 2},
        })

        with patch.object(linebot_handler, "_get_db_engine", return_value=fake_engine), \
             patch.object(linebot_handler, "_load_latest_provider_health", return_value=provider_health):
            messages = linebot_handler._cmd_status()

        text = messages[0]["text"]
        self.assertIn("data_health=critical", text)
        self.assertIn("root_cause=openbb_json_parse_error", text)
        self.assertIn("修復方式", text)
        self.assertIn("OpenBB", text)
        self.assertIn("前次有效推薦", text)

    def test_background_top5_critical_failure_preserves_previous_recommendations(self):
        class CriticalScreener:
            def __init__(self, use_ml):
                self.last_run_summary = {}

            def scan_all(self):
                self.last_run_summary = {
                    "coverage_ratio": 0.0,
                    "current_data_mode": "failed",
                    "provider_health_summary": "provider_health_summary coverage_ratio=0.00",
                }
                return []

            def get_top_recommendations(self, df_all, n=5):
                return []

            def save_to_db(self, recommendations):
                raise AssertionError("critical provider failure must not save empty recommendations")

        pushed = []
        with patch.object(linebot_handler, "_get_daily_screener_class", return_value=CriticalScreener), \
             patch.object(linebot_handler, "push_message", side_effect=lambda user_id, messages: pushed.append(messages)):
            linebot_handler._run_screener_and_push("user-123")

        self.assertIn("資料供應", pushed[0][0]["text"])
        self.assertIn("保留上一輪", pushed[0][0]["text"])

    def test_background_top5_degraded_scan_marks_pushed_message(self):
        class DegradedScreener:
            def __init__(self, use_ml):
                self.last_run_summary = {}

            def scan_all(self):
                self.last_run_summary = {
                    "coverage_ratio": 0.4,
                    "current_data_mode": "fallback",
                    "degraded": True,
                    "live_successes": 0,
                    "fallback_successes": 2,
                    "failed_symbols": [{"symbol": "AAPL"}],
                    "skipped_symbols": [{"symbol": "AAPL"}],
                }
                return ["dummy"]

            def get_top_recommendations(self, df_all, n=5):
                return [{"symbol": "MSFT"}]

            def save_to_db(self, recommendations):
                return True

        pushed = []
        with patch.object(linebot_handler, "_get_daily_screener_class", return_value=DegradedScreener), \
             patch.object(linebot_handler, "_build_top5_flex", return_value={"type": "flex", "altText": "top5"}), \
             patch.object(linebot_handler, "push_message", side_effect=lambda user_id, messages: pushed.append(messages)):
            linebot_handler._run_screener_and_push("user-123")

        self.assertEqual(len(pushed[0]), 2)
        self.assertIn("data_provider_mode=fallback", pushed[0][0]["text"])
        self.assertIn("coverage=0.40", pushed[0][0]["text"])
        self.assertIn("recommendation_source=current_run", pushed[0][0]["text"])

    def test_default_recommendations_marks_stale_provider_health(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_result = Mock()
        fake_result.mappings.return_value = [{"symbol": "MSFT"}]
        fake_conn.execute.return_value = fake_result
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(linebot_handler, "_get_db_engine", return_value=fake_engine), \
             patch.object(linebot_handler, "_latest_recommendation_date", return_value="2026-05-20"), \
             patch.object(linebot_handler, "_daily_recommendation_select_columns", return_value="symbol"), \
             patch.object(linebot_handler, "_row_to_recommendation", return_value={"symbol": "MSFT"}), \
             patch.object(linebot_handler, "_build_top5_flex", return_value={"type": "flex", "altText": "default"}), \
             patch.object(linebot_handler, "_recommendation_quick_reply", return_value={"items": []}), \
             patch.object(linebot_handler, "_load_latest_provider_health", return_value={
                 "provider_health_available": True,
                 "status": "stale",
                 "current_data_mode": "stale",
                 "provider_coverage_ratio": 0.35,
                 "minimum_coverage_ratio": 0.6,
                 "effective_provider": "market_data",
                 "is_stale": True,
                 "stale_age_days": 4,
                 "live_successes": 0,
                 "fallback_successes": 5,
                 "failed_symbols": 10,
                 "skipped_symbols": 10,
                 "recommendation_source": "last_valid_snapshot",
                 "is_using_last_valid_snapshot": True,
                 "last_valid_recommendation_at": "2026-05-20",
             }):
            messages = linebot_handler._cmd_default_recommendations()

        self.assertEqual(messages[0]["type"], "text")
        self.assertIn("data_health=stale", messages[0]["text"])
        self.assertIn("data_provider_mode=stale", messages[0]["text"])
        self.assertIn("recommendation_source=last_valid_snapshot", messages[0]["text"])
        self.assertIn("last_valid_recommendation_at=2026-05-20", messages[0]["text"])
        self.assertEqual(messages[1]["type"], "flex")

    def test_top5_retries_stale_mysql_connection_and_returns_recommendations(self):
        fake_engine = _FakeEngine(
            [
                _FakeConnection([_stale_mysql_error()]),
                _FakeConnection([_FakeScalarResult("2026-05-28"), _FakeResult([_top5_row()])]),
            ]
        )

        with patch.object(linebot_handler, "_get_db_engine", return_value=fake_engine), \
             patch.object(linebot_handler, "_daily_recommendation_select_columns", return_value="symbol"), \
             patch.object(linebot_handler, "_build_today_flow_snapshot", return_value=None):
            messages = linebot_handler._cmd_top5()

        self.assertEqual(fake_engine.dispose_count, 1)
        self.assertEqual(messages[0]["type"], "flex")
        self.assertIn("NVDA", str(messages[0]))

    def test_history_retries_stale_mysql_connection_and_returns_rows(self):
        fake_engine = _FakeEngine(
            [
                _FakeConnection([_stale_mysql_error()]),
                _FakeConnection([_FakeResult([("NVDA", 1, "BUY", 86.4, 0.91)])]),
            ]
        )

        with patch.object(linebot_handler, "_get_db_engine", return_value=fake_engine):
            messages = linebot_handler._cmd_history("0528")

        self.assertEqual(fake_engine.dispose_count, 1)
        self.assertEqual(messages[0]["type"], "flex")
        self.assertIn("NVDA", str(messages[0]))

    def test_top5_persistent_database_outage_uses_safe_message(self):
        fake_engine = _FakeEngine(
            [
                _FakeConnection([_stale_mysql_error()]),
                _FakeConnection([_stale_mysql_error()]),
            ]
        )

        with patch.object(linebot_handler, "_get_db_engine", return_value=fake_engine):
            messages = linebot_handler._cmd_top5()

        self.assertEqual(messages[0]["type"], "text")
        self.assertIn("資料庫暫時無法連線", messages[0]["text"])
        self.assertNotIn("SELECT", messages[0]["text"])
        self.assertNotIn("sqlalche.me", messages[0]["text"])

    def test_top5_flex_uses_daily_morning_canonical_card_labels(self):
        flex = linebot_handler._build_top5_flex(
            [
                {
                    "symbol": "NVDA",
                    "rank": 1,
                    "total_score": 86.4,
                    "score": 86.4,
                    "setup_type": "breakout",
                    "reasons": ["Close broke above the 20-day high"],
                    "risk_flags": ["Close is extended above MA20"],
                    "valuation_status": "FAIR",
                    "buy_price": 118.0,
                    "suggested_allocation_pct": 7.5,
                    "reason_summary": "Daily morning setup",
                }
            ],
            "2026-05-28",
        )

        rendered = str(flex)
        self.assertIn("Decision", rendered)
        self.assertIn("Price / Target", rendered)
        self.assertIn("Buy Below", rendered)
        self.assertIn("Smart Money / AI", rendered)
        self.assertIn("Reason", rendered)
        self.assertIn("breakout", rendered)
        self.assertNotIn("AI Score", rendered)

    def test_calibration_active_payload_replies(self):
        payload = {
            "active": True,
            "active_profile_version": "cal-active",
            "drift_status": "healthy",
            "score_bucket_status": "healthy",
            "top_rank_status": "warning",
            "risk_flag_status": "insufficient_data",
            "calibration_impact_status": "neutral",
            "messages": ["Score buckets are stable"],
        }

        with patch.object(linebot_handler, "_load_calibration_drift_for_linebot", return_value=payload), \
             patch.object(linebot_handler, "_provider_incident_note_for_linebot", return_value=None):
            messages = linebot_handler._cmd_calibration()

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["type"], "text")
        self.assertIn("Calibration Drift", messages[0]["text"])
        self.assertIn("Active: cal-active", messages[0]["text"])
        self.assertIn("Status: healthy", messages[0]["text"])

    def test_calibration_insufficient_data_payload_replies(self):
        payload = {
            "active": False,
            "drift_status": "insufficient_data",
            "sample_size": 2,
        }

        with patch.object(linebot_handler, "_load_calibration_drift_for_linebot", return_value=payload), \
             patch.object(linebot_handler, "_provider_incident_note_for_linebot", return_value=None):
            messages = linebot_handler._cmd_calibration()

        self.assertEqual(len(messages), 1)
        self.assertIn("Calibration Drift", messages[0]["text"])
        self.assertIn("insufficient data", messages[0]["text"].lower())
        self.assertIn("Sample: 2", messages[0]["text"])

    def test_calibration_unavailable_data_replies_with_fallback(self):
        with patch.object(linebot_handler, "_load_calibration_drift_for_linebot", side_effect=RuntimeError("db unavailable")):
            messages = linebot_handler._cmd_calibration()

        self.assertEqual(messages, [
            {"type": "text", "text": "Calibration 狀態暫時無法取得，請稍後再試。"}
        ])

    def test_calibration_build_failure_falls_back_to_text(self):
        with patch.object(linebot_handler, "_build_calibration_reply_messages", side_effect=ValueError("bad flex")):
            messages = linebot_handler._cmd_calibration()

        self.assertEqual(messages, [
            {"type": "text", "text": "Calibration 狀態暫時無法取得，請稍後再試。"}
        ])

    def test_row_to_recommendation_extracts_swing_ranking_metadata(self):
        row = {
            "symbol": "NVDA",
            "rank_position": 1,
            "signal_type": "BUY",
            "total_score": 86.4,
            "current_price": 123.0,
            "reason_summary": "legacy reason",
            "strategy_details": '{"swing_ranking":{"score":86.4,"setup_type":"breakout","trend_score":22,"momentum_score":20,"setup_score":18,"volatility_score":8,"risk_score":8,"liquidity_score":10,"reasons":["Close broke above the 20-day high"],"risk_flags":["Close is extended above MA20"],"stop_loss_price":118.5,"risk_percent":3.7}}',
        }

        with patch.object(linebot_handler, "_build_today_flow_snapshot", return_value=None):
            rec = linebot_handler._row_to_recommendation(Mock(), row)

        self.assertEqual(rec["score"], 86.4)
        self.assertEqual(rec["setup_type"], "breakout")
        self.assertEqual(rec["reasons"], ["Close broke above the 20-day high"])
        self.assertEqual(rec["risk_flags"], ["Close is extended above MA20"])

    def test_top5_flex_includes_swing_score_setup_reason_and_risk_flag(self):
        flex = linebot_handler._build_top5_flex(
            [
                {
                    "symbol": "NVDA",
                    "total_score": 86.4,
                    "score": 86.4,
                    "setup_type": "breakout",
                    "reasons": ["Close broke above the 20-day high"],
                    "risk_flags": ["Close is extended above MA20"],
                    "current_price": 123.0,
                }
            ],
            "2026-05-20",
        )

        rendered = str(flex)
        self.assertIn("Score 86", rendered)
        self.assertIn("breakout", rendered)
        self.assertIn("20-day high", rendered)
        self.assertIn("extended above MA20", rendered)

    def test_build_stock_analysis_message_surfaces_growth_aware_valuation(self):
        payload = {
            "symbol": "NVDA",
            "scan_date": "2026-05-15",
            "signal": "BUY",
            "total_score": 4.7,
            "current_price": 115.0,
            "support_1": 91.125,
            "resistance_1": 121.5,
            "macro_regime": "BULL_MARKET",
            "ml_confidence": 0.92,
            "fundamentals": {
                "eps_ttm": 5.0,
                "pe_ratio": 23.0,
                "peg_ratio": 1.05,
                "pb_ratio": 12.3,
                "roe": 0.28,
                "profit_margin": 0.31,
                "revenue_growth_yoy": 0.60,
                "sector": "Technology",
            },
            "strategies_passed": ["Breakout", "PEG", "Institutional"],
            "strategies_failed": ["DuPont"],
        }

        message = linebot_handler._build_stock_analysis_message(payload)

        self.assertIn("PREMIUM_GROWTH", message)
        self.assertIn("Buy Below: $91.12", message)
        self.assertIn("Fair Price: $101.25", message)
        self.assertIn("Sell Above: $121.50", message)


if __name__ == "__main__":
    unittest.main()
