from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
STRATEGIES_SRC = PROJECT_ROOT / "strategies" / "src"
WEB_ROOT = PROJECT_ROOT / "web"

if str(STRATEGIES_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_SRC))

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def check_flex_structure() -> bool:
    from adapters.notifier import LineNotifier

    notifier = LineNotifier()

    mock_recs = [
        {
            "rank": 1,
            "symbol": "VZ",
            "signal": "BUY",
            "total_score": 3.50,
            "current_price": 42.15,
            "ml_confidence": 0.65,
            "breakout_pass": True,
            "acceleration_pass": True,
            "peg_pass": False,
            "dupont_pass": True,
            "support_1": 40.50,
            "resistance_1": 44.20,
        },
        {
            "rank": 2,
            "symbol": "XOM",
            "signal": "BUY",
            "total_score": 3.20,
            "current_price": 108.30,
            "ml_confidence": 0.58,
            "breakout_pass": True,
            "acceleration_pass": False,
            "peg_pass": True,
            "dupont_pass": True,
            "support_1": 105.00,
            "resistance_1": 112.00,
        },
    ]

    bubble = notifier._build_stock_bubble(mock_recs[0])
    assert bubble["type"] == "bubble"
    assert bubble["header"]["backgroundColor"] == "#00C853"

    kv = LineNotifier._flex_kv("Score", "3.5/5")
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

    preview = json.dumps(flex_msg["contents"], indent=2, ensure_ascii=False)[:500]
    print("Flex JSON preview:\n", preview, "...\n")
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
    from adapters.notifier import get_notifier

    notifier = get_notifier()
    if not notifier.is_enabled:
        print("Line token/user id not configured. Skip sending.")
        return False

    return notifier.send_text("Manual check: Line push")


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
