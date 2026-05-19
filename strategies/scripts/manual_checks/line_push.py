from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
STRATEGIES_SRC = PROJECT_ROOT / "strategies" / "src"
WEB_ROOT = PROJECT_ROOT / "web"

if str(STRATEGIES_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_SRC))

from utils.line_flex import flex_kv

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def check_flex_structure() -> bool:
    notifier_path = STRATEGIES_SRC / "adapters" / "notifier.py"
    spec = importlib.util.spec_from_file_location("line_notifier_manual_check", notifier_path)
    assert spec and spec.loader
    notifier_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notifier_module)
    LineNotifier = notifier_module.LineNotifier

    notifier = LineNotifier()

    mock_recs = [
        {
            "rank": 1,
            "symbol": "VZ",
            "signal": "BUY",
            "total_score": 3.50,
            "current_price": 42.15,
            "target_price": 48.00,
            "buy_price": 40.50,
            "sell_price": 49.25,
            "valuation_status": "UNDERVALUED",
            "institutional_ownership": 0.71,
            "insider_sentiment": "BUYING",
            "ml_confidence": 0.65,
            "reason_summary": "技術面突破 | 法人籌碼支持 | 🔥內部人買進",
        },
        {
            "rank": 2,
            "symbol": "NVDA",
            "signal": "BUY",
            "total_score": 3.20,
            "current_price": 128.30,
            "target_price": 145.80,
            "buy_price": None,
            "sell_price": 156.50,
            "valuation_status": "PREMIUM_GROWTH",
            "institutional_ownership": 0.64,
            "insider_sentiment": "NEUTRAL",
            "ml_confidence": 0.58,
            "reason_summary": "高成長估值溢價已納入，Flex 仍需維持 FAIR 風格",
        },
    ]

    bubble = notifier._build_stock_bubble(mock_recs[0])
    assert bubble["type"] == "bubble"
    assert bubble["header"]["backgroundColor"] == "#00C853"
    assert bubble["footer"]["contents"][0]["type"] == "separator"
    assert bubble["footer"]["contents"][1]["text"] == "Reason"

    kv = flex_kv("Score", "3.5/5")
    assert kv["type"] == "box"
    assert kv["layout"] == "horizontal"
    assert len(kv["contents"]) == 2

    bubbles = [notifier._build_stock_bubble(r) for r in mock_recs]
    flex_msg = {
        "type": "flex",
        "altText": "manual check",
        "contents": {"type": "carousel", "contents": bubbles},
    }
    assert flex_msg["contents"]["type"] == "carousel"
    assert len(flex_msg["contents"]["contents"]) == len(mock_recs)
    assert flex_msg["contents"]["contents"][1]["header"]["backgroundColor"] == "#FFA000"
    assert "FAIR" in flex_msg["contents"]["contents"][1]["header"]["contents"][1]["text"]

    preview = json.dumps(flex_msg["contents"], indent=2, ensure_ascii=False)[:500]
    print("Flex JSON preview:\n", preview, "...\n")

    daily_df = pd.DataFrame([
        {
            "symbol": "RTX",
            "latest_date": "2026-04-26",
            "xgboost_score": 0.68,
            "valuation_status": "UNDERVALUED",
            "buy_price": 160.0,
            "sell_price": 192.0,
            "suggested_allocation_pct": 20.0,
            "ai_reason": "軍工訂單強，估值仍未擴張過度",
        },
        {
            "symbol": "NVDA",
            "latest_date": "2026-04-26",
            "xgboost_score": 0.61,
            "valuation_status": "PREMIUM_GROWTH",
            "buy_price": None,
            "sell_price": 279.0,
            "suggested_allocation_pct": None,
            "ai_reason": None,
        },
    ])
    daily_flex = notifier.build_daily_screener_flex(daily_df)
    assert daily_flex["contents"]["type"] == "carousel"
    assert len(daily_flex["contents"]["contents"]) == 2
    assert daily_flex["contents"]["contents"][1]["header"]["backgroundColor"] == "#A16207"
    return True


def check_handler_commands() -> bool:
    if str(WEB_ROOT) not in sys.path:
        sys.path.insert(0, str(WEB_ROOT))

    from bot.handler import process_command

    msgs = process_command("/help")
    assert msgs and msgs[0]["type"] == "text"
    assert "Top5" in msgs[0]["text"]

    msgs = process_command("/status")
    assert msgs and msgs[0]["type"] == "text"

    msgs = process_command("/strategies")
    assert msgs and msgs[0]["type"] == "text"

    return True


def check_db_commands() -> bool:
    if str(WEB_ROOT) not in sys.path:
        sys.path.insert(0, str(WEB_ROOT))

    from bot.handler import process_command

    msgs = process_command("Top5")
    assert msgs is not None

    msgs = process_command("ML AAPL")
    assert msgs is not None

    return True


def send_line_message() -> bool:
    notifier_path = STRATEGIES_SRC / "adapters" / "notifier.py"
    spec = importlib.util.spec_from_file_location("line_notifier_manual_send", notifier_path)
    assert spec and spec.loader
    notifier_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notifier_module)
    get_notifier = notifier_module.get_notifier

    notifier = get_notifier()
    if not notifier.is_enabled:
        print("Line token/user id not configured. Skip sending.")
        return False

    premium_growth_df = pd.DataFrame(
        [
            {
                "symbol": "NVDA",
                "latest_date": "2026-05-15",
                "xgboost_score": 0.74,
                "valuation_status": "PREMIUM_GROWTH",
                "buy_price": None,
                "sell_price": 156.5,
                "suggested_allocation_pct": None,
                "ai_reason": "Premium growth fallback check",
            }
        ]
    )
    return notifier.send_daily_screener_flex(premium_growth_df)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual checks for LineBot integration.")
    parser.add_argument("--handler", action="store_true", help="Check handler commands (no DB).")
    parser.add_argument("--db", action="store_true", help="Check Top5/ML commands (requires DB).")
    parser.add_argument("--send", action="store_true", help="Send a Line message (requires tokens).")
    args = parser.parse_args()

    ok = True
    ok = check_flex_structure() and ok

    if args.handler:
        ok = check_handler_commands() and ok
    if args.db:
        ok = check_db_commands() and ok
    if args.send:
        ok = send_line_message() and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
