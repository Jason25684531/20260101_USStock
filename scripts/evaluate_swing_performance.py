from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_SRC = ROOT / "strategies" / "src"
if str(STRATEGIES_SRC) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_SRC))

from adapters.database import DatabaseAdapter
from screener.swing_performance import evaluate_and_persist_from_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate persisted swing ranking recommendations with local market_data.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum recommendation rows to evaluate.")
    args = parser.parse_args()

    db = DatabaseAdapter()
    try:
        with db.engine.begin() as conn:
            payload = evaluate_and_persist_from_db(conn, limit=args.limit)
        summary = payload.get("summary") or {}
        print("Swing ranking performance evaluation complete")
        print(f"sample_size={summary.get('sample_size', 0)}")
        print(f"avg_forward_return_20d={summary.get('avg_forward_return_20d')}")
        print(f"hit_rate_20d={summary.get('hit_rate_20d')}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
