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

    def test_process_command_prefers_db_top5_for_recommend_keyword(self):
        expected_messages = [{"type": "flex", "altText": "top5", "contents": {"type": "carousel", "contents": []}}]

        with patch.object(linebot_handler, "_cmd_top5", return_value=expected_messages) as top5_cmd, \
             patch.object(linebot_handler, "_cmd_top5_realtime", return_value=[{"type": "text", "text": "realtime"}]) as realtime_cmd:
            messages = linebot_handler.process_command("推薦", user_id="user-123")

        self.assertEqual(messages, expected_messages)
        top5_cmd.assert_called_once_with()
        realtime_cmd.assert_not_called()

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
