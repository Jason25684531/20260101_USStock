from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_SRC = ROOT / "strategies" / "src"
for path in (ROOT, STRATEGIES_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from adapters.database import DatabaseAdapter  # noqa: E402
from screener.engine import DailyScreener  # noqa: E402
from screener.ops_runtime import build_pull_log_record, record_market_data_pull  # noqa: E402


def _symbols(value: str) -> list[str]:
    return [symbol.strip().upper() for symbol in (value or "").split(",") if symbol.strip()]


def pull_market_data(symbols: list[str], *, dry_run: bool = False) -> dict:
    started_at = datetime.utcnow().replace(microsecond=0).isoformat()
    screener = DailyScreener(symbols=symbols, use_ml=False)
    db = None if dry_run else DatabaseAdapter()
    rows_updated = 0
    symbols_updated = 0
    failures = []

    for symbol in symbols:
        result = screener.fetch_stock_data_result(symbol)
        if result.df is not None and not result.df.empty:
            if not dry_run:
                if db is None:
                    db = DatabaseAdapter()
                rows_updated += int(db.save_market_data(result.df, symbol) or 0)
            else:
                rows_updated += len(result.df)
            symbols_updated += 1
        else:
            failures.append({"symbol": symbol, "status": result.status, "message": result.message})

    coverage = symbols_updated / len(symbols) if symbols else 0.0
    status = "success" if not failures else "degraded" if symbols_updated else "failed"
    record = build_pull_log_record(
        job_name="manual_market_data_pull",
        status=status,
        started_at=started_at,
        finished_at=datetime.utcnow().replace(microsecond=0).isoformat(),
        provider_status=screener.last_run_summary.get("current_data_mode") if getattr(screener, "last_run_summary", None) else None,
        coverage=coverage,
        symbols_requested=len(symbols),
        symbols_updated=symbols_updated,
        rows_updated=rows_updated,
        error_type=failures[0]["status"] if failures else None,
        error_message=failures[0]["message"] if failures else None,
    )
    if not dry_run:
        if db is None:
            db = DatabaseAdapter()
        record_market_data_pull(db.engine, record)
    record["dry_run"] = dry_run
    record["failures"] = failures[:10]
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull market data through the screener provider chain and record pull status.")
    parser.add_argument("--symbols", default="AAPL,MSFT,NVDA", help="Comma-separated symbols to pull.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report without writing market_data or pull log.")
    args = parser.parse_args(argv)

    report = pull_market_data(_symbols(args.symbols), dry_run=args.dry_run)
    for key in ("job_name", "status", "coverage", "symbols_requested", "symbols_updated", "rows_updated", "dry_run"):
        print(f"{key}={report.get(key)}")
    if report.get("error_type"):
        print(f"error_type={report.get('error_type')}")
        print(f"error_message={report.get('error_message')}")
    return 0 if report.get("status") in {"success", "degraded"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
