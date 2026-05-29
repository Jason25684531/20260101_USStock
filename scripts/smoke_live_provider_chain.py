from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_SRC = ROOT / "strategies" / "src"
for path in (ROOT, STRATEGIES_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from screener.engine import DailyScreener  # noqa: E402


def _normalize_symbols(symbols: Iterable[str] | str) -> list[str]:
    if isinstance(symbols, str):
        values = symbols.split(",")
    else:
        values = symbols
    return [str(symbol).strip().upper() for symbol in values if str(symbol).strip()]


def _attempts_for(result: Any) -> list[dict[str, Any]]:
    attempts = getattr(result, "provider_attempts", None) or []
    return [attempt for attempt in attempts if isinstance(attempt, dict)]


def _top_counter(counter: Counter[str], limit: int = 5) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _next_operator_action(coverage: float, fallback_attempts: list[dict[str, Any]], top_error_types: dict[str, int]) -> str:
    if coverage >= 0.6 and fallback_attempts:
        return "Fallback recovered coverage; inspect OpenBB response/parser before trusting fresh primary-provider runs."
    if coverage >= 0.6:
        return "Provider chain healthy; no immediate action required."
    if coverage >= 0.2:
        return "Coverage is degraded; verify fallback availability and inspect top provider errors."
    if any("json_parse_error" in key for key in top_error_types):
        return "Critical coverage with OpenBB parse errors; inspect OpenBB response contract, then verify yfinance and local DB fallback."
    return "Critical coverage; verify OpenBB, yfinance, and local market_data fallback availability."


def build_smoke_report(symbols: Iterable[str], results: list[Any]) -> dict[str, Any]:
    normalized_symbols = _normalize_symbols(symbols)
    provider_attempts: list[dict[str, Any]] = []
    fallback_attempts: list[dict[str, Any]] = []
    provider_successes: Counter[str] = Counter()
    top_error_types: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    successes = 0

    for result in results:
        attempts = _attempts_for(result)
        provider_attempts.extend(attempts)
        fallback_attempts.extend(
            attempt for attempt in attempts
            if attempt.get("success") and attempt.get("provider") not in {"openbb", "provider_chain"}
        )
        if getattr(result, "used_fallback", False) and not any(
            attempt.get("success") and attempt.get("provider") == getattr(result, "provider", None)
            for attempt in fallback_attempts
        ):
            fallback_attempts.append({
                "provider": getattr(result, "provider", "fallback"),
                "success": True,
                "data_mode": getattr(result, "data_mode", "fallback"),
            })

        if getattr(result, "df", None) is not None and not result.df.empty:
            successes += 1
            provider_successes[str(getattr(result, "provider", "unknown"))] += 1
        elif not attempts and getattr(result, "status", None):
            top_error_types[str(getattr(result, "status"))] += 1

        for attempt in attempts:
            if not attempt.get("success") and attempt.get("error_type"):
                top_error_types[str(attempt["error_type"])] += 1
        skip_reason = getattr(result, "skip_reason", None)
        if skip_reason:
            skip_reasons[str(skip_reason)] += 1

    coverage = successes / len(normalized_symbols) if normalized_symbols else 0.0
    effective_provider = None
    if provider_successes:
        effective_provider = sorted(provider_successes.items(), key=lambda item: (-item[1], item[0]))[0][0]

    top_errors = _top_counter(top_error_types)
    report = {
        "symbols": normalized_symbols,
        "symbols_requested": len(normalized_symbols),
        "symbols_succeeded": successes,
        "coverage": coverage,
        "effective_provider": effective_provider,
        "provider_attempts": provider_attempts,
        "fallback_attempts": fallback_attempts,
        "top_error_types": top_errors,
        "skip_reasons": _top_counter(skip_reasons),
        "recommendations_written": False,
    }
    report["next_operator_action"] = _next_operator_action(coverage, fallback_attempts, top_errors)
    return report


def run_provider_chain_smoke(
    symbols: Iterable[str] | str,
    *,
    days: int = 90,
    screener_factory: Callable[..., Any] = DailyScreener,
) -> dict[str, Any]:
    normalized_symbols = _normalize_symbols(symbols)
    screener = screener_factory(symbols=normalized_symbols, use_ml=False)
    if hasattr(screener, "_provider_date_window"):
        end_date = date.today()
        start_date = end_date - timedelta(days=max(int(days or 90), 1))
        screener._provider_date_window = lambda: (start_date.isoformat(), end_date.isoformat())
    results = [screener.fetch_stock_data_result(symbol) for symbol in normalized_symbols]
    return build_smoke_report(normalized_symbols, results)


def render_smoke_report(report: dict[str, Any]) -> str:
    def fmt_counter(values: dict[str, int]) -> str:
        return ", ".join(f"{key}:{value}" for key, value in (values or {}).items()) or "none"

    lines = [
        "Provider chain live smoke",
        f"symbols requested: {report.get('symbols_requested', 0)}",
        f"symbols succeeded: {report.get('symbols_succeeded', 0)}",
        f"coverage: {float(report.get('coverage') or 0.0):.2%}",
        f"effective provider: {report.get('effective_provider') or 'N/A'}",
        f"provider attempts: {len(report.get('provider_attempts') or [])}",
        f"fallback attempts: {len(report.get('fallback_attempts') or [])}",
        f"top error types: {fmt_counter(report.get('top_error_types') or {})}",
        f"skip reasons: {fmt_counter(report.get('skip_reasons') or {})}",
        f"recommendations written: {bool(report.get('recommendations_written'))}",
        f"next operator action: {report.get('next_operator_action') or 'N/A'}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the screener live provider chain without writing recommendations.")
    parser.add_argument("--symbols", default="AAPL,MSFT,NVDA", help="Comma-separated symbols to smoke.")
    parser.add_argument("--days", type=int, default=90, help="Lookback days for provider requests.")
    args = parser.parse_args(argv)

    report = run_provider_chain_smoke(args.symbols, days=args.days)
    print(render_smoke_report(report))
    return 0 if report["coverage"] >= 0.2 else 2


if __name__ == "__main__":
    raise SystemExit(main())
