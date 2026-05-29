import json
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

from bot import handler as linebot_handler
from bot import flex_messages


def _text_values(payload):
    values = []

    def visit(value):
        if isinstance(value, dict):
            if "text" in value:
                values.append(value["text"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return values


def _rendered(payload):
    return json.dumps(payload, ensure_ascii=False)


class ReadOnlyFlexBuilderTests(unittest.TestCase):
    def test_stock_check_bubble_shows_warning_fields_and_serializes(self):
        payload = {
            "symbol": "AAPL",
            "scan_date": "2026-05-29",
            "signal": "BUY",
            "total_score": 4.8,
            "current_price": 190.25,
            "support_1": 180.0,
            "resistance_1": 205.0,
            "macro_regime": "RISK_ON",
            "ml_confidence": 0.32,
            "source": "daily_recommendations",
            "valuation": {
                "valuation_status": "OVERVALUED",
                "buy_price": 165.0,
                "fair_price": 178.0,
                "sell_price": 210.0,
            },
        }

        message = flex_messages.build_stock_check_message(payload)

        self.assertEqual(message["type"], "flex")
        self.assertEqual(message["contents"]["type"], "bubble")
        rendered = _rendered(message)
        self.assertIn("AAPL", rendered)
        self.assertIn("BUY", rendered)
        self.assertIn("OVERVALUED", rendered)
        self.assertIn("ML confidence is low", rendered)
        self.assertIn("valuation risk", rendered)
        json.dumps(message, ensure_ascii=False)

    def test_recommendations_carousel_marks_degraded_data(self):
        message = flex_messages.build_recommendations_carousel(
            [
                {
                    "symbol": "MSFT",
                    "signal": "WATCH",
                    "total_score": 4.2,
                    "current_price": 430.0,
                    "valuation_status": "FAIR",
                    "ml_confidence": 0.77,
                    "reason_summary": "Strong quality setup",
                }
            ],
            title="Latest recommendations",
            degraded=True,
        )

        self.assertEqual(message["type"], "flex")
        self.assertEqual(message["contents"]["type"], "carousel")
        rendered = _rendered(message)
        self.assertIn("DATA DEGRADED", rendered)
        self.assertIn("MSFT", rendered)
        self.assertIn("Strong quality setup", rendered)

    def test_market_regime_bubble_uses_expected_colors(self):
        expected = {
            "RISK_ON": "#00C853",
            "NEUTRAL": "#FFA000",
            "RISK_OFF": "#FF1744",
        }

        for regime, color in expected.items():
            with self.subTest(regime=regime):
                message = flex_messages.build_market_regime_message(
                    {
                        "regime": regime,
                        "vix": 18.2,
                        "yield_curve": 0.35,
                        "unemployment": 3.9,
                        "fed_rate": 5.25,
                        "description": "Macro regime explanation",
                    }
                )

                self.assertEqual(message["contents"]["header"]["backgroundColor"], color)
                self.assertIn(regime, _rendered(message))

    def test_sector_ranking_bubble_marks_anomalies(self):
        message = flex_messages.build_sector_ranking_message(
            [
                {"sector": "Technology", "etf": "XLK", "rank": 1, "return_20d": 0.12, "return_63d": 0.24},
                {"sector": "Energy", "etf": "XLE", "rank": 2, "return_20d": 11.5, "return_63d": None},
            ]
        )

        rendered = _rendered(message)
        self.assertIn("Technology", rendered)
        self.assertIn("XLK", rendered)
        self.assertIn("DATA ANOMALY", rendered)

    def test_history_recommendation_bubble_shows_top_rows(self):
        message = flex_messages.build_history_recommendation_message(
            "2026-02-14",
            [
                {"symbol": "NVDA", "rank": 1, "signal": "BUY", "total_score": 4.9, "ml_confidence": 0.91},
                {"symbol": "AAPL", "rank": 2, "signal": "WATCH", "total_score": 4.1, "ml_confidence": None},
            ],
        )

        rendered = _rendered(message)
        self.assertIn("2026-02-14", rendered)
        self.assertIn("NVDA", rendered)
        self.assertIn("91%", rendered)

    def test_ml_prediction_bubble_shows_prediction_fields(self):
        message = flex_messages.build_ml_prediction_message(
            {
                "symbol": "AAPL",
                "date": "2026-05-29",
                "price": 190.25,
                "score": 4.7,
                "signal": "BUY",
                "ml_confidence": 0.88,
                "support": 181.0,
                "resistance": 205.0,
            }
        )

        rendered = _rendered(message)
        self.assertIn("AAPL", rendered)
        self.assertIn("88%", rendered)
        self.assertIn("$181.00", rendered)

    def test_builders_tolerate_missing_optional_fields(self):
        messages = [
            flex_messages.build_stock_check_message({"symbol": "AAPL"}),
            flex_messages.build_recommendations_carousel([{"symbol": "AAPL"}]),
            flex_messages.build_market_regime_message({}),
            flex_messages.build_sector_ranking_message([{}]),
            flex_messages.build_history_recommendation_message("2026-02-14", [{}]),
            flex_messages.build_ml_prediction_message({"symbol": "AAPL"}),
        ]

        for message in messages:
            with self.subTest(alt_text=message.get("altText")):
                self.assertEqual(message["type"], "flex")
                json.dumps(message, ensure_ascii=False)
                self.assertTrue(all(isinstance(value, str) and value.strip() for value in _text_values(message)))


class ReadOnlyFlexHandlerIntegrationTests(unittest.TestCase):
    def test_stock_command_returns_flex_and_falls_back_to_text_on_builder_failure(self):
        payload = {
            "symbol": "AAPL",
            "signal": "BUY",
            "total_score": 4.8,
            "current_price": 190.25,
            "valuation": {"valuation_status": "FAIR"},
        }

        with patch.object(linebot_handler, "_get_db_engine") as db_engine, \
             patch.object(linebot_handler, "_load_stock_analysis_payload", return_value=payload), \
             patch.object(linebot_handler, "_build_stock_analysis_message", return_value="TEXT FALLBACK"):
            db_engine.return_value.connect.return_value.__enter__.return_value = Mock()
            messages = linebot_handler._cmd_stock("AAPL")

        self.assertEqual(messages[0]["type"], "flex")
        self.assertIn("AAPL", _rendered(messages[0]))

        with patch.object(linebot_handler, "_get_db_engine") as db_engine, \
             patch.object(linebot_handler, "_load_stock_analysis_payload", return_value=payload), \
             patch.object(linebot_handler, "_build_stock_analysis_message", return_value="TEXT FALLBACK"), \
             patch.object(linebot_handler.flex_messages, "build_stock_check_message", side_effect=ValueError("bad flex")):
            db_engine.return_value.connect.return_value.__enter__.return_value = Mock()
            fallback = linebot_handler._cmd_stock("AAPL")

        self.assertEqual(fallback, [{"type": "text", "text": "TEXT FALLBACK"}])

    def test_reply_messages_uses_fallback_text_when_flex_send_fails(self):
        fallback = [{"type": "text", "text": "TEXT FALLBACK"}]
        flex = {"type": "flex", "altText": "bad", "contents": {"type": "bubble"}}

        with patch.object(linebot_handler, "CHANNEL_TOKEN", "token"), \
             patch.object(linebot_handler, "_sanitize_line_message", side_effect=lambda message: message), \
             patch.object(linebot_handler, "_validate_line_messages_for_reply", return_value=True), \
             patch.object(linebot_handler, "http_requests") as http_requests:
            http_requests.post.side_effect = [
                Mock(status_code=400, text="bad flex"),
                Mock(status_code=200, text="OK"),
            ]
            ok = linebot_handler.reply_messages("reply-token", [flex], fallback_messages=fallback)

        self.assertTrue(ok)
        self.assertEqual(http_requests.post.call_count, 2)
        self.assertEqual(http_requests.post.call_args.kwargs["json"]["messages"], fallback)

    def test_ml_missing_ticker_suggests_nvda_for_nvdi(self):
        fake_conn = Mock()
        fake_conn.__enter__ = Mock(return_value=fake_conn)
        fake_conn.__exit__ = Mock(return_value=False)
        fake_conn.execute.return_value.first.return_value = None
        fake_engine = Mock()
        fake_engine.connect.return_value = fake_conn

        with patch.object(linebot_handler, "_get_db_engine", return_value=fake_engine), \
             patch.object(linebot_handler, "_table_exists", return_value=False):
            messages = linebot_handler._cmd_ml("NVDI")

        self.assertEqual(messages[0]["type"], "text")
        self.assertIn("NVDA", messages[0]["text"])

    def test_process_command_routing_for_readonly_commands_is_unchanged(self):
        with patch.object(linebot_handler, "_cmd_default_recommendations", return_value=[{"type": "flex"}]) as rec_cmd, \
             patch.object(linebot_handler, "_cmd_stock", return_value=[{"type": "flex"}]) as stock_cmd, \
             patch.object(linebot_handler, "_cmd_market", return_value=[{"type": "flex"}]) as market_cmd, \
             patch.object(linebot_handler, "_cmd_sector", return_value=[{"type": "flex"}]) as sector_cmd, \
             patch.object(linebot_handler, "_cmd_history", return_value=[{"type": "flex"}]) as history_cmd, \
             patch.object(linebot_handler, "_cmd_ml", return_value=[{"type": "flex"}]) as ml_cmd:
            self.assertEqual(linebot_handler.process_command("/recommendations"), [{"type": "flex"}])
            self.assertEqual(linebot_handler.process_command("/stock AAPL"), [{"type": "flex"}])
            self.assertEqual(linebot_handler.process_command("/market"), [{"type": "flex"}])
            self.assertEqual(linebot_handler.process_command("/sector"), [{"type": "flex"}])
            self.assertEqual(linebot_handler.process_command("/history 0214"), [{"type": "flex"}])
            self.assertEqual(linebot_handler.process_command("ML AAPL"), [{"type": "flex"}])

        rec_cmd.assert_called_once_with()
        stock_cmd.assert_called_once_with("AAPL")
        market_cmd.assert_called_once_with()
        sector_cmd.assert_called_once_with()
        history_cmd.assert_called_once_with("0214")
        ml_cmd.assert_called_once_with("AAPL")


if __name__ == "__main__":
    unittest.main()
