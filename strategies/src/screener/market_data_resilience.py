from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd


ERROR_NO_PRICE_DATA = "no_price_data"
ERROR_JSON_PARSE = "json_parse_error"
ERROR_TIMEOUT = "timeout"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_HTTP = "http_error"
ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERROR_UNKNOWN = "unknown_error"

STATUS_LIVE_SUCCESS = "live_success"
STATUS_FALLBACK_SUCCESS = "fallback_success"


@dataclass
class MarketDataFetchResult:
    symbol: str
    provider: str = "yfinance"
    status: str = ERROR_UNKNOWN
    message: str = ""
    df: Optional[pd.DataFrame] = None
    info: Dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    used_fallback: bool = False
    cache_age_days: Optional[int] = None


def classify_provider_error(error: Exception) -> str:
    message = str(error or "").lower()
    error_name = type(error).__name__.lower()

    if "no price data found" in message or "possibly delisted" in message or "no data found" in message:
        return ERROR_NO_PRICE_DATA

    if "expecting value" in message or "json" in message or "decode" in message:
        return ERROR_JSON_PARSE

    if isinstance(error, TimeoutError) or "timeout" in message or "timed out" in message:
        return ERROR_TIMEOUT

    if "429" in message or "rate limit" in message or "too many requests" in message:
        return ERROR_RATE_LIMITED

    if "503" in message or "502" in message or "504" in message or "service unavailable" in message:
        return ERROR_PROVIDER_UNAVAILABLE

    if "http" in message or "httperror" in error_name:
        return ERROR_HTTP

    return ERROR_UNKNOWN


def is_retryable_status(status: str) -> bool:
    return status in {
        ERROR_JSON_PARSE,
        ERROR_TIMEOUT,
        ERROR_RATE_LIMITED,
        ERROR_HTTP,
        ERROR_PROVIDER_UNAVAILABLE,
    }


def build_provider_health_summary(summary: Dict[str, Any]) -> str:
    failed_symbols = summary.get("failed_symbols") or []
    skipped_symbols = summary.get("skipped_symbols") or []
    return (
        "provider_health_summary "
        f"total_symbols={summary.get('total_symbols', 0)} "
        f"live_successes={summary.get('live_successes', 0)} "
        f"fallback_successes={summary.get('fallback_successes', 0)} "
        f"failed_symbols={len(failed_symbols)} "
        f"skipped_symbols={len(skipped_symbols)} "
        f"coverage_ratio={float(summary.get('coverage_ratio', 0.0)):.2f} "
        f"minimum_coverage_ratio={float(summary.get('minimum_coverage_ratio', 0.0)):.2f} "
        f"recommendations_written={bool(summary.get('recommendations_written', False))}"
    )


def should_alert_degraded_data(summary: Dict[str, Any]) -> bool:
    total_symbols = int(summary.get("total_symbols", 0) or 0)
    failed_count = len(summary.get("failed_symbols") or [])
    coverage_ratio = float(summary.get("coverage_ratio", 0.0) or 0.0)
    minimum_coverage_ratio = float(summary.get("minimum_coverage_ratio", 0.0) or 0.0)
    if total_symbols <= 0:
        return False
    failure_ratio = failed_count / total_symbols
    return coverage_ratio < minimum_coverage_ratio or failure_ratio >= 0.5
