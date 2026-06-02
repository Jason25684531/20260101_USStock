from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd
from sqlalchemy import text


ERROR_NO_PRICE_DATA = "no_price_data"
ERROR_JSON_PARSE = "json_parse_error"
ERROR_TIMEOUT = "timeout"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_HTTP = "http_error"
ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERROR_UNKNOWN = "unknown_error"

STATUS_LIVE_SUCCESS = "live_success"
STATUS_FALLBACK_SUCCESS = "fallback_success"

DATA_MODE_LIVE = "live"
DATA_MODE_FALLBACK = "fallback"
DATA_MODE_STALE = "stale"
DATA_MODE_FAILED = "failed"
DATA_MODE_UNKNOWN = "unknown"

HEALTH_STATUS_HEALTHY = "healthy"
HEALTH_STATUS_DEGRADED = "degraded"
HEALTH_STATUS_STALE = "stale"
HEALTH_STATUS_FAILED = "failed"
HEALTH_STATUS_CRITICAL = "critical"
HEALTH_STATUS_UNKNOWN = "unknown"

ERROR_STALE_FALLBACK_TOO_OLD = "stale_fallback_too_old"
ERROR_CRITICAL_STALE_FALLBACK = "critical_stale_fallback"


def _json_safe(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _row_get(row: Dict[str, Any], key: str, default=None):
    if row is None:
        return default
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _as_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value):
    parsed = _json_safe(value, value)
    return parsed if isinstance(parsed, list) else []


def _as_dict(value):
    parsed = _json_safe(value, value)
    return parsed if isinstance(parsed, dict) else {}


def _status_counter(items: list[dict], key: str) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        value = item.get(key) or item.get("status") or item.get("error_type")
        if value:
            counter[str(value)] += 1
    return dict(counter)


def _bounded_counter_summary(counter: Dict[str, int], limit: int = 4) -> str:
    items = sorted((counter or {}).items(), key=lambda item: (-int(item[1] or 0), item[0]))[:limit]
    return ",".join(f"{key}:{value}" for key, value in items) or "none"


def _bounded_attempt_summary(counter: Dict[str, int], limit: int = 4) -> str:
    items = sorted((counter or {}).items(), key=lambda item: (-int(item[1] or 0), item[0]))[:limit]
    return " > ".join(f"{key} x{value}" for key, value in items) or "none"


def _effective_provider(provider_counts: dict, provider_attempts: list[dict], explicit=None):
    if explicit:
        return explicit
    for attempt in reversed(provider_attempts or []):
        if isinstance(attempt, dict) and attempt.get("success") and attempt.get("provider"):
            return attempt.get("provider")
    if provider_counts:
        return max(provider_counts.items(), key=lambda item: item[1])[0]
    return None


def empty_provider_health() -> Dict[str, Any]:
    payload = {
        "provider_health_available": False,
        "status": HEALTH_STATUS_UNKNOWN,
        "current_run_status": HEALTH_STATUS_UNKNOWN,
        "current_data_mode": DATA_MODE_UNKNOWN,
        "provider_coverage_ratio": None,
        "coverage": None,
        "minimum_coverage_ratio": None,
        "live_successes": 0,
        "fallback_successes": 0,
        "failed_symbols": 0,
        "skipped_symbols": 0,
        "effective_provider": None,
        "is_stale": False,
        "stale_age_days": None,
        "last_successful_provider": None,
        "last_successful_at": None,
        "last_successful_run_at": None,
        "provider_attempts": [],
        "fallback_attempts": [],
        "skip_reasons": {},
        "top_error_types": {},
        "recommendation_source": "unknown",
        "is_using_last_valid_snapshot": False,
        "last_valid_recommendation_at": None,
        "last_valid_recommendation_time": None,
        "recommendations_written": False,
    }
    payload["diagnostics"] = build_provider_health_diagnostics(payload)
    return payload


def normalize_provider_health(raw: Optional[Dict[str, Any]], critical_stale_days: Optional[int] = None) -> Dict[str, Any]:
    if not raw:
        return empty_provider_health()

    coverage = _as_float(
        _row_get(raw, "coverage", _row_get(raw, "provider_coverage_ratio", _row_get(raw, "coverage_ratio")))
    )
    minimum = _as_float(_row_get(raw, "minimum_coverage_ratio"), 0.6)
    critical_ratio = _as_float(_row_get(raw, "critical_coverage_ratio"), 0.2)
    mode = _row_get(raw, "current_data_mode") or DATA_MODE_UNKNOWN
    provider_counts = _as_dict(_row_get(raw, "provider_counts"))
    top_error_types = _as_dict(_row_get(raw, "top_error_types"))
    failed_items = _as_list(_row_get(raw, "failed_symbols"))
    skipped_items = _as_list(_row_get(raw, "skipped_symbols"))
    provider_attempts = _as_list(_row_get(raw, "provider_attempts"))
    fallback_attempts = _as_list(_row_get(raw, "fallback_attempts"))

    stale_age_days = _row_get(raw, "stale_age_days")
    if stale_age_days is None:
        ages = [
            attempt.get("cache_age_days")
            for attempt in provider_attempts + fallback_attempts
            if isinstance(attempt, dict) and attempt.get("cache_age_days") is not None
        ]
        stale_age_days = max(ages) if ages else None
    stale_age_days = _as_int(stale_age_days, None)

    critical_stale_days = _as_int(
        critical_stale_days if critical_stale_days is not None else _row_get(raw, "critical_stale_days"),
        _as_int(os.getenv("SCREENER_CRITICAL_STALE_DAYS", "10"), 10),
    )
    stale_used = _bool(_row_get(raw, "is_stale", _row_get(raw, "stale_data_used", False))) or mode == DATA_MODE_STALE
    recommendations_written = _bool(_row_get(raw, "recommendations_written", False))

    if stale_age_days is not None and stale_age_days > critical_stale_days:
        status = HEALTH_STATUS_CRITICAL
    elif coverage is not None and coverage < critical_ratio:
        status = HEALTH_STATUS_CRITICAL
    elif mode == DATA_MODE_FAILED:
        status = HEALTH_STATUS_FAILED
    elif stale_used:
        status = HEALTH_STATUS_STALE
    elif mode == DATA_MODE_FALLBACK or (coverage is not None and minimum is not None and coverage < minimum):
        status = HEALTH_STATUS_DEGRADED
    elif mode == DATA_MODE_LIVE:
        status = HEALTH_STATUS_HEALTHY
    else:
        status = _row_get(raw, "status") or HEALTH_STATUS_UNKNOWN

    last_valid = (
        _row_get(raw, "last_valid_recommendation_at")
        or _row_get(raw, "last_valid_recommendation_time")
    )
    recommendation_source = _row_get(raw, "recommendation_source")
    if not recommendation_source:
        if recommendations_written:
            recommendation_source = "current_run"
        elif last_valid and status in {HEALTH_STATUS_CRITICAL, HEALTH_STATUS_FAILED, HEALTH_STATUS_STALE}:
            recommendation_source = "last_valid_snapshot"
        else:
            recommendation_source = "unknown"

    effective_provider = _effective_provider(
        provider_counts,
        provider_attempts,
        explicit=_row_get(raw, "effective_provider"),
    )
    last_successful_provider = (
        _row_get(raw, "last_successful_provider")
        or effective_provider
    )
    last_successful_at = (
        _row_get(raw, "last_successful_at")
        or _row_get(raw, "last_successful_run_at")
    )

    payload = {
        "provider_health_available": _bool(_row_get(raw, "provider_health_available", True)),
        "status": status,
        "current_run_status": _row_get(raw, "current_run_status") or status,
        "run_at": str(_row_get(raw, "run_at")) if _row_get(raw, "run_at") else None,
        "total_symbols": _as_int(_row_get(raw, "total_symbols"), 0),
        "live_successes": _as_int(_row_get(raw, "live_successes"), 0),
        "fallback_successes": _as_int(_row_get(raw, "fallback_successes"), 0),
        "failed_symbols": len(failed_items) if failed_items else _as_int(_row_get(raw, "failed_symbols"), 0),
        "skipped_symbols": len(skipped_items) if skipped_items else _as_int(_row_get(raw, "skipped_symbols"), 0),
        "coverage": coverage,
        "provider_coverage_ratio": coverage,
        "coverage_ratio": coverage,
        "minimum_coverage_ratio": minimum,
        "critical_coverage_ratio": critical_ratio,
        "current_data_mode": mode,
        "stale_data_used": stale_used,
        "is_stale": stale_used,
        "stale_age_days": stale_age_days,
        "critical_stale_days": critical_stale_days,
        "recommendations_written": recommendations_written,
        "write_blocked_reason": _row_get(raw, "write_blocked_reason"),
        "provider_counts": provider_counts,
        "effective_provider": effective_provider,
        "last_successful_provider": last_successful_provider,
        "last_successful_at": str(last_successful_at) if last_successful_at else None,
        "last_successful_run_at": str(_row_get(raw, "last_successful_run_at")) if _row_get(raw, "last_successful_run_at") else None,
        "provider_attempts": provider_attempts,
        "fallback_attempts": fallback_attempts,
        "skip_reasons": _as_dict(_row_get(raw, "skip_reasons")) or _status_counter(skipped_items, "skip_reason"),
        "top_error_types": top_error_types,
        "error_summary": _row_get(raw, "error_summary"),
        "recommendation_source": recommendation_source,
        "is_using_last_valid_snapshot": recommendation_source == "last_valid_snapshot",
        "last_valid_recommendation_at": str(last_valid) if last_valid else None,
        "last_valid_recommendation_time": str(_row_get(raw, "last_valid_recommendation_time")) if _row_get(raw, "last_valid_recommendation_time") else None,
        "current_run_coverage": coverage,
    }
    payload["diagnostics"] = build_provider_health_diagnostics(payload)
    return payload


def build_provider_health_diagnostics(provider_health: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = provider_health or {}
    status = _row_get(payload, "status") or HEALTH_STATUS_UNKNOWN
    mode = _row_get(payload, "current_data_mode") or DATA_MODE_UNKNOWN
    coverage = _as_float(_row_get(payload, "coverage", _row_get(payload, "provider_coverage_ratio")))
    provider_attempts = _as_list(_row_get(payload, "provider_attempts"))
    fallback_attempts = _as_list(_row_get(payload, "fallback_attempts"))
    top_error_types = _as_dict(_row_get(payload, "top_error_types"))
    skip_reasons = _as_dict(_row_get(payload, "skip_reasons"))

    attempt_counter: Counter[str] = Counter()
    provider_failure_counter: Counter[str] = Counter()
    for attempt in provider_attempts:
        if not isinstance(attempt, dict) or attempt.get("success"):
            continue
        provider = str(attempt.get("provider") or "provider")
        error_type = str(attempt.get("error_type") or attempt.get("status") or ERROR_UNKNOWN)
        attempt_counter[f"{provider}:{error_type}"] += 1
        provider_failure_counter[provider] += 1

    parse_error_keys = {"json_parse_error", "openbbjson_parse_error"}
    has_parse_error = any(
        key in parse_error_keys or str(key).endswith("json_parse_error")
        for key in top_error_types
    ) or any(
        key.split(":", 1)[-1] in parse_error_keys or key.endswith("json_parse_error")
        for key in attempt_counter
    )
    openbb_parse_error = any(
        key.startswith("openbb:") and (key.endswith("json_parse_error") or key.endswith("openbbjson_parse_error"))
        for key in attempt_counter
    )

    if has_parse_error and not provider_attempts and status in {HEALTH_STATUS_CRITICAL, HEALTH_STATUS_FAILED}:
        root_cause = "provider_unavailable"
    elif openbb_parse_error:
        root_cause = "openbb_json_parse_error"
    elif has_parse_error:
        root_cause = "provider_json_parse_error"
    elif top_error_types:
        root_cause = next(iter(sorted(top_error_types.items(), key=lambda item: (-int(item[1] or 0), item[0]))))[0]
    elif status in {HEALTH_STATUS_CRITICAL, HEALTH_STATUS_FAILED} or mode == DATA_MODE_FAILED:
        root_cause = "provider_unavailable"
    elif status == HEALTH_STATUS_STALE or _bool(_row_get(payload, "is_stale", False)):
        root_cause = "stale_fallback"
    elif status == HEALTH_STATUS_DEGRADED:
        root_cause = "partial_provider_coverage"
    else:
        root_cause = "none" if status == HEALTH_STATUS_HEALTHY else "unknown"

    successful_fallback = next(
        (attempt for attempt in fallback_attempts if isinstance(attempt, dict) and attempt.get("success")),
        None,
    )
    if successful_fallback:
        fallback_outcome = str(successful_fallback.get("provider") or "available")
    elif fallback_attempts or status in {HEALTH_STATUS_CRITICAL, HEALTH_STATUS_FAILED} or coverage == 0:
        fallback_outcome = "unavailable"
    else:
        fallback_outcome = "not_needed"

    snapshot_preserved = bool(_row_get(payload, "is_using_last_valid_snapshot"))
    last_valid = _row_get(payload, "last_valid_recommendation_at") or _row_get(payload, "last_valid_recommendation_time")
    display_status = status if status in {
        HEALTH_STATUS_HEALTHY,
        HEALTH_STATUS_DEGRADED,
        HEALTH_STATUS_STALE,
        HEALTH_STATUS_FAILED,
        HEALTH_STATUS_CRITICAL,
    } else HEALTH_STATUS_UNKNOWN

    if root_cause == "openbb_json_parse_error":
        summary = "OpenBB response parse failed repeatedly"
        message = "資料健康異常：OpenBB 回應解析失敗，這次掃描沒有足夠即時資料。"
        actions = [
            "檢查 OpenBB API 回應格式與 adapter parser contract",
            "確認 yfinance fallback 與本機 market_data 可用性",
        ]
    elif root_cause == "provider_json_parse_error":
        summary = "Provider response parse failed"
        message = "資料健康異常：資料供應商回應解析失敗，請先確認 provider 回應內容。"
        actions = [
            "檢查 provider response 是否為有效 JSON",
            "確認 fallback provider 與本機資料庫狀態",
        ]
    elif root_cause == "stale_fallback":
        summary = "Using stale fallback data"
        message = "資料健康降級：目前使用 stale fallback，請不要視為完整即時行情。"
        actions = ["確認 live provider 恢復狀態", "檢查本機資料 stale age 是否仍在允許範圍"]
    elif root_cause == "partial_provider_coverage":
        summary = "Provider coverage is degraded"
        message = "資料健康降級：本次掃描只有部分標的取得資料。"
        actions = ["檢查失敗標的與 provider 錯誤摘要", "確認 fallback provider 是否可補足覆蓋率"]
    elif root_cause == "none":
        summary = "Provider health is normal"
        message = "資料健康正常：目前建議來自本次有效掃描。"
        actions = []
    else:
        summary = "Provider data unavailable"
        message = "資料健康異常：目前沒有足夠 provider 資料可產生新的有效推薦。"
        actions = [
            "檢查 OpenBB / yfinance / 本機 market_data fallback",
            "確認 provider health log 的 skip reasons 與 top error types",
        ]

    if snapshot_preserved:
        message = f"{message} 系統已保留前次有效推薦快照。"
    elif status in {HEALTH_STATUS_CRITICAL, HEALTH_STATUS_FAILED} and coverage == 0:
        message = f"{message} 目前沒有可用的前次有效推薦快照。"

    diagnostics = {
        "root_cause": root_cause,
        "diagnostic_summary": summary,
        "display_status": display_status,
        "display_message": message,
        "operator_actions": actions,
        "attempt_summary": _bounded_attempt_summary(dict(attempt_counter)),
        "provider_failure_counts": dict(provider_failure_counter),
        "fallback_outcome": fallback_outcome,
        "snapshot_preserved": snapshot_preserved,
        "last_valid_recommendation_at": str(last_valid) if last_valid else None,
        "top_error_summary": _bounded_counter_summary(top_error_types),
        "skip_summary": _bounded_counter_summary(skip_reasons),
    }
    return diagnostics


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
    data_mode: str = DATA_MODE_UNKNOWN
    is_retriable: bool = False
    provider_attempts: list[dict] = field(default_factory=list)
    fallback_attempted: bool = False
    skip_reason: Optional[str] = None


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
    top_error_types = summary.get("top_error_types") or {}
    if isinstance(top_error_types, Counter):
        top_error_types = dict(top_error_types)
    if isinstance(top_error_types, dict):
        error_summary = ",".join(
            f"{key}:{value}" for key, value in sorted(top_error_types.items())
        ) or "none"
    else:
        error_summary = str(top_error_types)

    return (
        "provider_health_summary "
        f"total_symbols={summary.get('total_symbols', 0)} "
        f"live_successes={summary.get('live_successes', 0)} "
        f"fallback_successes={summary.get('fallback_successes', 0)} "
        f"failed_symbols={len(failed_symbols)} "
        f"skipped_symbols={len(skipped_symbols)} "
        f"coverage_ratio={float(summary.get('coverage_ratio', 0.0)):.2f} "
        f"minimum_coverage_ratio={float(summary.get('minimum_coverage_ratio', 0.0)):.2f} "
        f"current_data_mode={summary.get('current_data_mode', DATA_MODE_UNKNOWN)} "
        f"stale_data_used={bool(summary.get('stale_data_used', False))} "
        f"top_error_types={error_summary} "
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


def summarize_error_types(summary: Dict[str, Any]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for item in summary.get("failed_symbols") or []:
        status = item.get("status") or item.get("error_type") or ERROR_UNKNOWN
        counter[str(status)] += 1
    for item in summary.get("skipped_symbols") or []:
        status = item.get("status") or item.get("error_type")
        if status and status not in counter:
            counter[str(status)] += 1
    return dict(counter.most_common(5))


def compute_current_data_mode(summary: Dict[str, Any], critical_coverage_ratio: float = 0.20) -> str:
    coverage_ratio = float(summary.get("coverage_ratio", 0.0) or 0.0)
    if summary.get("critical_stale_fallback") or summary.get("max_stale_age_exceeded"):
        return DATA_MODE_FAILED
    if coverage_ratio < critical_coverage_ratio:
        return DATA_MODE_FAILED
    if int(summary.get("stale_successes", 0) or 0) > 0 or summary.get("stale_data_used"):
        return DATA_MODE_STALE
    if int(summary.get("fallback_successes", 0) or 0) > 0:
        return DATA_MODE_FALLBACK
    if int(summary.get("live_successes", 0) or 0) > 0:
        return DATA_MODE_LIVE
    return DATA_MODE_FAILED


def ensure_provider_health_log(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS provider_health_log (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            run_key VARCHAR(64) NOT NULL,
            run_at DATETIME NOT NULL,
            total_symbols INT NOT NULL DEFAULT 0,
            live_successes INT NOT NULL DEFAULT 0,
            fallback_successes INT NOT NULL DEFAULT 0,
            failed_symbols INT NOT NULL DEFAULT 0,
            skipped_symbols INT NOT NULL DEFAULT 0,
            coverage_ratio DECIMAL(8, 4) NOT NULL DEFAULT 0,
            minimum_coverage_ratio DECIMAL(8, 4) NOT NULL DEFAULT 0,
            current_data_mode VARCHAR(16) NOT NULL DEFAULT 'unknown',
            stale_data_used TINYINT(1) NOT NULL DEFAULT 0,
            recommendations_written TINYINT(1) NOT NULL DEFAULT 0,
            write_blocked_reason TEXT NULL,
            provider_counts JSON NULL,
            effective_provider VARCHAR(64) NULL,
            stale_age_days INT NULL,
            last_successful_provider VARCHAR(64) NULL,
            provider_attempts JSON NULL,
            fallback_attempts JSON NULL,
            skip_reasons JSON NULL,
            top_error_types JSON NULL,
            error_summary TEXT NULL,
            last_successful_run_at DATETIME NULL,
            last_valid_recommendation_time DATETIME NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_provider_health_run_key (run_key),
            INDEX idx_provider_health_run_at (run_at),
            INDEX idx_provider_health_mode (current_data_mode)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))
    optional_columns = {
        "effective_provider": "VARCHAR(64) NULL",
        "stale_age_days": "INT NULL",
        "last_successful_provider": "VARCHAR(64) NULL",
        "provider_attempts": "JSON NULL",
        "fallback_attempts": "JSON NULL",
        "skip_reasons": "JSON NULL",
    }
    for column_name, definition in optional_columns.items():
        try:
            conn.execute(text(f"ALTER TABLE provider_health_log ADD COLUMN {column_name} {definition}"))
        except Exception:
            pass


def persist_provider_health(engine, summary: Dict[str, Any], last_valid_recommendation_time=None) -> bool:
    run_key = summary.setdefault(
        "provider_health_run_key",
        datetime.utcnow().strftime("%Y%m%d%H%M%S%f"),
    )
    run_at = summary.setdefault("provider_health_run_at", datetime.utcnow().replace(microsecond=0).isoformat())
    failed_symbols = summary.get("failed_symbols") or []
    skipped_symbols = summary.get("skipped_symbols") or []
    top_error_types = summary.get("top_error_types") or summarize_error_types(summary)
    provider_counts = summary.get("provider_counts") or {}
    current_data_mode = summary.get("current_data_mode") or compute_current_data_mode(summary)
    normalized = normalize_provider_health({**summary, "current_data_mode": current_data_mode})
    successful_run_at = run_at if current_data_mode != DATA_MODE_FAILED else summary.get("last_successful_run_at")

    try:
        with engine.begin() as conn:
            ensure_provider_health_log(conn)
            conn.execute(text("""
                INSERT INTO provider_health_log (
                    run_key, run_at, total_symbols, live_successes, fallback_successes,
                    failed_symbols, skipped_symbols, coverage_ratio, minimum_coverage_ratio,
                    current_data_mode, stale_data_used, recommendations_written,
                    write_blocked_reason, provider_counts, effective_provider, stale_age_days,
                    last_successful_provider, provider_attempts, fallback_attempts, skip_reasons,
                    top_error_types, error_summary,
                    last_successful_run_at, last_valid_recommendation_time
                ) VALUES (
                    :run_key, :run_at, :total_symbols, :live_successes, :fallback_successes,
                    :failed_symbols, :skipped_symbols, :coverage_ratio, :minimum_coverage_ratio,
                    :current_data_mode, :stale_data_used, :recommendations_written,
                    :write_blocked_reason, :provider_counts, :effective_provider, :stale_age_days,
                    :last_successful_provider, :provider_attempts, :fallback_attempts, :skip_reasons,
                    :top_error_types, :error_summary,
                    :last_successful_run_at, :last_valid_recommendation_time
                )
                ON DUPLICATE KEY UPDATE
                    total_symbols = VALUES(total_symbols),
                    live_successes = VALUES(live_successes),
                    fallback_successes = VALUES(fallback_successes),
                    failed_symbols = VALUES(failed_symbols),
                    skipped_symbols = VALUES(skipped_symbols),
                    coverage_ratio = VALUES(coverage_ratio),
                    minimum_coverage_ratio = VALUES(minimum_coverage_ratio),
                    current_data_mode = VALUES(current_data_mode),
                    stale_data_used = VALUES(stale_data_used),
                    recommendations_written = VALUES(recommendations_written),
                    write_blocked_reason = VALUES(write_blocked_reason),
                    provider_counts = VALUES(provider_counts),
                    effective_provider = VALUES(effective_provider),
                    stale_age_days = VALUES(stale_age_days),
                    last_successful_provider = VALUES(last_successful_provider),
                    provider_attempts = VALUES(provider_attempts),
                    fallback_attempts = VALUES(fallback_attempts),
                    skip_reasons = VALUES(skip_reasons),
                    top_error_types = VALUES(top_error_types),
                    error_summary = VALUES(error_summary),
                    last_successful_run_at = VALUES(last_successful_run_at),
                    last_valid_recommendation_time = VALUES(last_valid_recommendation_time)
            """), {
                "run_key": run_key,
                "run_at": run_at,
                "total_symbols": int(summary.get("total_symbols", 0) or 0),
                "live_successes": int(summary.get("live_successes", 0) or 0),
                "fallback_successes": int(summary.get("fallback_successes", 0) or 0),
                "failed_symbols": len(failed_symbols),
                "skipped_symbols": len(skipped_symbols),
                "coverage_ratio": float(summary.get("coverage_ratio", 0.0) or 0.0),
                "minimum_coverage_ratio": float(summary.get("minimum_coverage_ratio", 0.0) or 0.0),
                "current_data_mode": current_data_mode,
                "stale_data_used": bool(summary.get("stale_data_used", False)),
                "recommendations_written": bool(summary.get("recommendations_written", False)),
                "write_blocked_reason": summary.get("write_blocked_reason"),
                "provider_counts": json.dumps(provider_counts, ensure_ascii=False, default=str),
                "effective_provider": normalized.get("effective_provider"),
                "stale_age_days": normalized.get("stale_age_days"),
                "last_successful_provider": normalized.get("last_successful_provider"),
                "provider_attempts": json.dumps(summary.get("provider_attempts") or [], ensure_ascii=False, default=str),
                "fallback_attempts": json.dumps(summary.get("fallback_attempts") or [], ensure_ascii=False, default=str),
                "skip_reasons": json.dumps(normalized.get("skip_reasons") or {}, ensure_ascii=False, default=str),
                "top_error_types": json.dumps(top_error_types, ensure_ascii=False, default=str),
                "error_summary": summary.get("provider_health_summary") or build_provider_health_summary(summary),
                "last_successful_run_at": successful_run_at,
                "last_valid_recommendation_time": last_valid_recommendation_time,
            })
        return True
    except Exception as exc:
        print(f"[provider-health-log-failed] {exc}")
        return False


def prune_provider_health_log(engine, retention_days: int = 30, now: Optional[datetime] = None) -> int:
    retention_days = max(int(retention_days or 30), 1)
    cutoff = (now or datetime.utcnow()) - timedelta(days=retention_days)
    try:
        with engine.begin() as conn:
            ensure_provider_health_log(conn)
            result = conn.execute(
                text("DELETE FROM provider_health_log WHERE run_at < :cutoff"),
                {"cutoff": cutoff.replace(microsecond=0)},
            )
            return int(getattr(result, "rowcount", 0) or 0)
    except Exception as exc:
        print(f"[provider-health-retention-warning] {exc}")
        return 0
