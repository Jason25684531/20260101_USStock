from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yfinance as yf


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config import evaluate_stock_rules_v2


def run(symbols: list[str]) -> int:
    print("Manual check: live screening\n")
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y")
            info = ticker.info

            result = evaluate_stock_rules_v2(df, info)
            print(f"Symbol: {symbol}")
            print(f"  Rule score: {result['rule_score']:.2f} / {result['total_strategies']}")
            print(f"  Passes: {result['passes']} (min {result.get('min_passes', '-')})")
            print(f"  Pass rate: {result['passes']/result['total_strategies']*100:.1f}%")

            passed = [name for name, res in result["all_results"].items() if res["pass"]]
            if passed:
                preview = ", ".join(passed[:5])
                suffix = "..." if len(passed) > 5 else ""
                print(f"  Passed: {preview}{suffix}")
            print("")
        except Exception as exc:
            print(f"Symbol: {symbol} failed: {exc}\n")
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual live screening check using yfinance.")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["AAPL", "MSFT", "NVDA"],
        help="Symbols to evaluate (default: AAPL MSFT NVDA).",
    )
    args = parser.parse_args()
    return run(args.symbols)


if __name__ == "__main__":
    raise SystemExit(main())
