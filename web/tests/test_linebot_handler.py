import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

os.environ["WEB_DISABLE_AUTH"] = "true"

from bot import handler as linebot_handler


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
