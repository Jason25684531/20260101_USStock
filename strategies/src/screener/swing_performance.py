"""Deterministic swing ranking performance evaluation helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import json
from statistics import median
from typing import Any, Iterable, Mapping

import pandas as pd
from sqlalchemy import text

from screener.presentation_utils import safe_float as _shared_safe_float
from screener.swing_ranking import normalize_swing_ranking_metadata


HORIZONS = (5, 10, 20)
INVALID_FRESH_PROVIDER_STATUSES = {"failed", "critical"}
SCORE_BUCKETS = (">=80", "70-80", "60-70", "<60")
DEFAULT_SETUP_TYPES = (
    "breakout",
    "pullback_reclaim",
    "trend_continuation",
    "volatility_expansion",
    "avoid_overextended",
)


def _safe_float(value: Any) -> float | None:
    return _shared_safe_float(value)


def _round(value: Any, digits: int = 4) -> float | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return round(numeric, digits)


def _date_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).split(" ")[0]


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _market_frame(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        frame = rows.copy()
    else:
        frame = pd.DataFrame(list(rows or []))
    if frame.empty:
        return frame

    rename = {
        "Timestamp": "timestamp",
        "Date": "timestamp",
        "date": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    for source, target in rename.items():
        if source in frame.columns and target not in frame.columns:
            frame[target] = frame[source]
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.sort_values("timestamp")
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.reset_index(drop=True)


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, list) else []
        except Exception:
            return []
    return []


def _hit(value: float | None) -> bool | None:
    if value is None:
        return None
    return value > 0


def _future_window(frame: pd.DataFrame, scan_date: str) -> tuple[pd.Series | None, pd.DataFrame, str]:
    if frame.empty or "close" not in frame.columns:
        return None, pd.DataFrame(), "missing_market_data"

    if "timestamp" in frame.columns:
        date_values = frame["timestamp"].dt.date.astype(str)
        exact_matches = frame.loc[date_values == scan_date]
        if not exact_matches.empty:
            entry_index = int(exact_matches.index[-1])
            return frame.loc[entry_index], frame.loc[entry_index + 1 : entry_index + 20].copy(), "complete"
        future = frame.loc[date_values > scan_date].copy()
        return None, future.head(20), "entry_price_fallback"

    return frame.iloc[0], frame.iloc[1:21].copy(), "complete"


def evaluate_recommendation_performance(
    recommendation: Mapping[str, Any],
    market_rows: Iterable[Mapping[str, Any]] | pd.DataFrame,
) -> dict[str, Any]:
    """Evaluate one persisted recommendation against local future OHLCV rows."""
    frame = _market_frame(market_rows)
    recommendation_date = _date_string(
        _row_get(recommendation, "recommendation_date")
        or _row_get(recommendation, "scan_date")
    )
    entry_row, future, status = _future_window(frame, recommendation_date or "")
    fallback_entry = _safe_float(_row_get(recommendation, "entry_close")) or _safe_float(_row_get(recommendation, "current_price"))
    entry_close = _safe_float(entry_row.get("close")) if entry_row is not None else fallback_entry
    if entry_close is None or entry_close == 0:
        status = "missing_entry_price"

    metadata = normalize_swing_ranking_metadata(
        _row_get(recommendation, "strategy_details"),
        fallback_score=_safe_float(_row_get(recommendation, "score")) or _safe_float(_row_get(recommendation, "total_score")),
        rank=int(_row_get(recommendation, "rank") or _row_get(recommendation, "rank_position") or 0) or None,
    )
    provider_status = (
        _row_get(recommendation, "provider_health_status")
        or _row_get(recommendation, "current_run_status")
        or _row_get(recommendation, "status")
        or "unknown"
    )
    source = _row_get(recommendation, "recommendation_source") or "unknown"

    result = {
        "recommendation_date": recommendation_date,
        "symbol": str(_row_get(recommendation, "symbol") or "").upper(),
        "rank": metadata.get("rank"),
        "score": _round(metadata.get("score"), 2),
        "setup_type": metadata.get("setup_type"),
        "provider_health_status": provider_status,
        "recommendation_source": source,
        "entry_close": _round(entry_close, 4),
        "close_5d": None,
        "close_10d": None,
        "close_20d": None,
        "forward_return_5d": None,
        "forward_return_10d": None,
        "forward_return_20d": None,
        "hit_5d": None,
        "hit_10d": None,
        "hit_20d": None,
        "max_drawdown_20d": None,
        "max_favorable_excursion_20d": None,
        "risk_flags": list(metadata.get("risk_flags") or []),
        "reasons": list(metadata.get("reasons") or []),
        "evaluation_status": status,
    }

    if entry_close is None or entry_close == 0:
        return result

    for horizon in HORIZONS:
        if len(future) >= horizon:
            close_value = _safe_float(future.iloc[horizon - 1].get("close"))
            result[f"close_{horizon}d"] = _round(close_value, 4)
            if close_value is not None:
                forward_return = (close_value - entry_close) / entry_close
                result[f"forward_return_{horizon}d"] = _round(forward_return, 4)
                result[f"hit_{horizon}d"] = _hit(forward_return)
        else:
            result["evaluation_status"] = "partial" if result["evaluation_status"] == "complete" else result["evaluation_status"]

    if not future.empty:
        risk_window = future.head(20)
        low_source = risk_window["low"] if "low" in risk_window.columns and risk_window["low"].notna().any() else risk_window["close"]
        high_source = risk_window["high"] if "high" in risk_window.columns and risk_window["high"].notna().any() else risk_window["close"]
        low_values = pd.concat([low_source, risk_window["close"]]).dropna()
        high_values = pd.concat([high_source, risk_window["close"]]).dropna()
        if not low_values.empty:
            result["max_drawdown_20d"] = _round((float(low_values.min()) - entry_close) / entry_close, 4)
        if not high_values.empty:
            result["max_favorable_excursion_20d"] = _round((float(high_values.max()) - entry_close) / entry_close, 4)

    return result


def score_bucket(score: float | None) -> str:
    numeric = _safe_float(score)
    if numeric is None:
        return "unknown"
    if numeric >= 80:
        return ">=80"
    if numeric >= 70:
        return "70-80"
    if numeric >= 60:
        return "60-70"
    return "<60"


def _metric_values(rows: list[Mapping[str, Any]], key: str) -> list[float]:
    return [value for value in (_safe_float(_row_get(row, key)) for row in rows) if value is not None]


def _avg(rows: list[Mapping[str, Any]], key: str) -> float | None:
    values = _metric_values(rows, key)
    if not values:
        return None
    return _round(sum(values) / len(values), 4)


def _hit_rate(rows: list[Mapping[str, Any]], key: str) -> float | None:
    values = [_row_get(row, key) for row in rows if _row_get(row, key) is not None]
    if not values:
        return None
    return _round(sum(1 for value in values if bool(value)) / len(values), 4)


def _profit_factor_like(rows: list[Mapping[str, Any]]) -> float | None:
    values = _metric_values(rows, "forward_return_20d")
    positives = sum(value for value in values if value > 0)
    negatives = abs(sum(value for value in values if value < 0))
    if negatives == 0:
        return None
    return _round(positives / negatives, 4)


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    row_list = list(rows or [])
    returns_20d = _metric_values(row_list, "forward_return_20d")
    return {
        "sample_size": len(row_list),
        "avg_forward_return_5d": _avg(row_list, "forward_return_5d"),
        "avg_forward_return_10d": _avg(row_list, "forward_return_10d"),
        "avg_forward_return_20d": _avg(row_list, "forward_return_20d"),
        "median_forward_return_20d": _round(median(returns_20d), 4) if returns_20d else None,
        "hit_rate_5d": _hit_rate(row_list, "hit_5d"),
        "hit_rate_10d": _hit_rate(row_list, "hit_10d"),
        "hit_rate_20d": _hit_rate(row_list, "hit_20d"),
        "avg_max_drawdown_20d": _avg(row_list, "max_drawdown_20d"),
        "avg_mfe_20d": _avg(row_list, "max_favorable_excursion_20d"),
        "profit_factor_like_20d": _profit_factor_like(row_list),
    }


def _fresh_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        row for row in rows
        if (_row_get(row, "recommendation_source") or "unknown") == "current_run"
        and (_row_get(row, "provider_health_status") or "unknown") not in INVALID_FRESH_PROVIDER_STATUSES
    ]


def _group_rows(rows: list[Mapping[str, Any]], key_func) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(key_func(row) or "unknown")].append(row)
    return grouped


def aggregate_performance(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    row_list = list(rows or [])
    fresh = _fresh_rows(row_list)
    rank_groups = [
        {"group": "top5", **summarize_rows([row for row in fresh if (_row_get(row, "rank") or 999) <= 5])},
        {"group": "top10", **summarize_rows([row for row in fresh if (_row_get(row, "rank") or 999) <= 10])},
    ]

    score_buckets = []
    by_bucket = _group_rows(row_list, lambda row: score_bucket(_row_get(row, "score")))
    for bucket in SCORE_BUCKETS:
        score_buckets.append({"bucket": bucket, **summarize_rows(by_bucket.get(bucket, []))})
    if "unknown" in by_bucket:
        score_buckets.append({"bucket": "unknown", **summarize_rows(by_bucket["unknown"])})

    setup_order = list(DEFAULT_SETUP_TYPES)
    for setup in sorted(_group_rows(row_list, lambda row: _row_get(row, "setup_type")).keys()):
        if setup not in setup_order and setup != "unknown":
            setup_order.append(setup)
    setup_types = [
        {"setup_type": setup, **summarize_rows(_group_rows(row_list, lambda row: _row_get(row, "setup_type")).get(setup, []))}
        for setup in setup_order
    ]

    no_risk = [row for row in row_list if not _json_list(_row_get(row, "risk_flags"))]
    any_risk = [row for row in row_list if _json_list(_row_get(row, "risk_flags"))]
    risk_flags = [
        {"group": "no_risk_flag", **summarize_rows(no_risk)},
        {"group": "any_risk_flag", **summarize_rows(any_risk)},
    ]
    specific: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in row_list:
        for flag in _json_list(_row_get(row, "risk_flags")):
            specific[str(flag)].append(row)
    for flag, grouped_rows in sorted(specific.items()):
        risk_flags.append({"group": flag, **summarize_rows(grouped_rows)})

    provider_health_segments = [
        {"provider_health_status": status, **summarize_rows(grouped)}
        for status, grouped in sorted(_group_rows(row_list, lambda row: _row_get(row, "provider_health_status")).items())
    ]
    recommendation_source_segments = [
        {"recommendation_source": source, **summarize_rows(grouped)}
        for source, grouped in sorted(_group_rows(row_list, lambda row: _row_get(row, "recommendation_source")).items())
    ]

    return {
        "summary": summarize_rows(fresh),
        "rank_groups": rank_groups,
        "score_buckets": score_buckets,
        "setup_types": setup_types,
        "risk_flags": risk_flags,
        "provider_health_segments": provider_health_segments,
        "recommendation_source_segments": recommendation_source_segments,
        "fresh_filter": {
            "recommendation_source": "current_run",
            "excluded_statuses": sorted(INVALID_FRESH_PROVIDER_STATUSES, reverse=True),
        },
    }


def build_performance_payload(rows: Iterable[Mapping[str, Any]], recent_limit: int = 50) -> dict[str, Any]:
    row_list = [dict(row) for row in rows or []]
    if not row_list:
        return {
            "summary": summarize_rows([]),
            "rank_groups": [],
            "score_buckets": [],
            "setup_types": [],
            "risk_flags": [],
            "provider_health_segments": [],
            "recommendation_source_segments": [],
            "fresh_filter": {
                "recommendation_source": "current_run",
                "excluded_statuses": sorted(INVALID_FRESH_PROVIDER_STATUSES, reverse=True),
            },
            "recent_evaluations": [],
        }
    payload = aggregate_performance(row_list)
    payload["recent_evaluations"] = row_list[: max(int(recent_limit or 50), 0)]
    return payload


def _decode_json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, list) else []
        except Exception:
            return []
    return []


def _performance_row_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "recommendation_date": _date_string(_row_get(row, "recommendation_date")),
        "symbol": _row_get(row, "symbol"),
        "rank": _row_get(row, "rank") or _row_get(row, "rank_position"),
        "score": _round(_row_get(row, "score"), 4),
        "setup_type": _row_get(row, "setup_type"),
        "provider_health_status": _row_get(row, "provider_health_status") or "unknown",
        "recommendation_source": _row_get(row, "recommendation_source") or "unknown",
        "entry_close": _round(_row_get(row, "entry_close"), 4),
        "close_5d": _round(_row_get(row, "close_5d"), 4),
        "close_10d": _round(_row_get(row, "close_10d"), 4),
        "close_20d": _round(_row_get(row, "close_20d"), 4),
        "forward_return_5d": _round(_row_get(row, "forward_return_5d"), 6),
        "forward_return_10d": _round(_row_get(row, "forward_return_10d"), 6),
        "forward_return_20d": _round(_row_get(row, "forward_return_20d"), 6),
        "hit_5d": None if _row_get(row, "hit_5d") is None else bool(_row_get(row, "hit_5d")),
        "hit_10d": None if _row_get(row, "hit_10d") is None else bool(_row_get(row, "hit_10d")),
        "hit_20d": None if _row_get(row, "hit_20d") is None else bool(_row_get(row, "hit_20d")),
        "max_drawdown_20d": _round(_row_get(row, "max_drawdown_20d"), 6),
        "max_favorable_excursion_20d": _round(_row_get(row, "max_favorable_excursion_20d"), 6),
        "evaluation_status": _row_get(row, "evaluation_status") or "unknown",
        "risk_flags": _decode_json_list(_row_get(row, "risk_flags_json") or _row_get(row, "risk_flags")),
        "reasons": _decode_json_list(_row_get(row, "reasons_json") or _row_get(row, "reasons")),
    }


def load_swing_performance_rows(conn, limit: int = 500) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 500), 1), 5000)
    rows = conn.execute(text(f"""
        SELECT recommendation_date, symbol, rank_position, score, setup_type,
               provider_health_status, recommendation_source, entry_close,
               close_5d, close_10d, close_20d,
               forward_return_5d, forward_return_10d, forward_return_20d,
               hit_5d, hit_10d, hit_20d,
               max_drawdown_20d, max_favorable_excursion_20d,
               evaluation_status, risk_flags_json, reasons_json
        FROM swing_ranking_performance
        ORDER BY recommendation_date DESC, rank_position ASC, symbol ASC
        LIMIT {safe_limit}
    """)).mappings()
    return [_performance_row_mapping(row) for row in rows]


def ensure_swing_performance_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS swing_ranking_performance (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            recommendation_date DATE NOT NULL,
            symbol VARCHAR(10) NOT NULL,
            rank_position INT NULL,
            score DECIMAL(8, 4) NULL,
            setup_type VARCHAR(64) NULL,
            provider_health_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
            recommendation_source VARCHAR(32) NOT NULL DEFAULT 'unknown',
            entry_close DECIMAL(12, 4) NULL,
            close_5d DECIMAL(12, 4) NULL,
            close_10d DECIMAL(12, 4) NULL,
            close_20d DECIMAL(12, 4) NULL,
            forward_return_5d DECIMAL(12, 6) NULL,
            forward_return_10d DECIMAL(12, 6) NULL,
            forward_return_20d DECIMAL(12, 6) NULL,
            hit_5d TINYINT(1) NULL,
            hit_10d TINYINT(1) NULL,
            hit_20d TINYINT(1) NULL,
            max_drawdown_20d DECIMAL(12, 6) NULL,
            max_favorable_excursion_20d DECIMAL(12, 6) NULL,
            evaluation_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
            risk_flags_json JSON NULL,
            reasons_json JSON NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_swing_perf_recommendation (recommendation_date, symbol),
            INDEX idx_swing_perf_date (recommendation_date),
            INDEX idx_swing_perf_setup (setup_type),
            INDEX idx_swing_perf_provider (provider_health_status, recommendation_source)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))


def persist_performance_rows(conn, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    statement = text("""
        INSERT INTO swing_ranking_performance (
            recommendation_date, symbol, rank_position, score, setup_type,
            provider_health_status, recommendation_source, entry_close,
            close_5d, close_10d, close_20d,
            forward_return_5d, forward_return_10d, forward_return_20d,
            hit_5d, hit_10d, hit_20d,
            max_drawdown_20d, max_favorable_excursion_20d,
            evaluation_status, risk_flags_json, reasons_json
        ) VALUES (
            :recommendation_date, :symbol, :rank_position, :score, :setup_type,
            :provider_health_status, :recommendation_source, :entry_close,
            :close_5d, :close_10d, :close_20d,
            :forward_return_5d, :forward_return_10d, :forward_return_20d,
            :hit_5d, :hit_10d, :hit_20d,
            :max_drawdown_20d, :max_favorable_excursion_20d,
            :evaluation_status, :risk_flags_json, :reasons_json
        )
        ON DUPLICATE KEY UPDATE
            rank_position = VALUES(rank_position),
            score = VALUES(score),
            setup_type = VALUES(setup_type),
            provider_health_status = VALUES(provider_health_status),
            recommendation_source = VALUES(recommendation_source),
            entry_close = VALUES(entry_close),
            close_5d = VALUES(close_5d),
            close_10d = VALUES(close_10d),
            close_20d = VALUES(close_20d),
            forward_return_5d = VALUES(forward_return_5d),
            forward_return_10d = VALUES(forward_return_10d),
            forward_return_20d = VALUES(forward_return_20d),
            hit_5d = VALUES(hit_5d),
            hit_10d = VALUES(hit_10d),
            hit_20d = VALUES(hit_20d),
            max_drawdown_20d = VALUES(max_drawdown_20d),
            max_favorable_excursion_20d = VALUES(max_favorable_excursion_20d),
            evaluation_status = VALUES(evaluation_status),
            risk_flags_json = VALUES(risk_flags_json),
            reasons_json = VALUES(reasons_json),
            updated_at = CURRENT_TIMESTAMP
    """)
    for row in rows or []:
        params = {
            "recommendation_date": _row_get(row, "recommendation_date"),
            "symbol": _row_get(row, "symbol"),
            "rank_position": _row_get(row, "rank"),
            "score": _row_get(row, "score"),
            "setup_type": _row_get(row, "setup_type"),
            "provider_health_status": _row_get(row, "provider_health_status") or "unknown",
            "recommendation_source": _row_get(row, "recommendation_source") or "unknown",
            "entry_close": _row_get(row, "entry_close"),
            "close_5d": _row_get(row, "close_5d"),
            "close_10d": _row_get(row, "close_10d"),
            "close_20d": _row_get(row, "close_20d"),
            "forward_return_5d": _row_get(row, "forward_return_5d"),
            "forward_return_10d": _row_get(row, "forward_return_10d"),
            "forward_return_20d": _row_get(row, "forward_return_20d"),
            "hit_5d": _row_get(row, "hit_5d"),
            "hit_10d": _row_get(row, "hit_10d"),
            "hit_20d": _row_get(row, "hit_20d"),
            "max_drawdown_20d": _row_get(row, "max_drawdown_20d"),
            "max_favorable_excursion_20d": _row_get(row, "max_favorable_excursion_20d"),
            "evaluation_status": _row_get(row, "evaluation_status") or "unknown",
            "risk_flags_json": json.dumps(_json_list(_row_get(row, "risk_flags")), ensure_ascii=False),
            "reasons_json": json.dumps(_json_list(_row_get(row, "reasons")), ensure_ascii=False),
        }
        conn.execute(statement, params)
        count += 1
    return count


def load_recommendations_for_evaluation(conn, limit: int = 500) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 500), 1), 5000)
    rows = conn.execute(text(f"""
        SELECT d.scan_date, d.symbol, d.rank_position, d.total_score, d.current_price,
               d.strategy_details,
               COALESCE((
                   SELECT p.current_data_mode
                   FROM provider_health_log p
                   WHERE DATE(p.run_at) <= d.scan_date
                   ORDER BY p.run_at DESC, p.id DESC
                   LIMIT 1
               ), 'unknown') AS provider_health_status,
               CASE
                   WHEN COALESCE((
                       SELECT p.recommendations_written
                       FROM provider_health_log p
                       WHERE DATE(p.run_at) <= d.scan_date
                       ORDER BY p.run_at DESC, p.id DESC
                       LIMIT 1
                   ), 1) = 1 THEN 'current_run'
                   ELSE 'last_valid_snapshot'
               END AS recommendation_source
        FROM daily_recommendations d
        ORDER BY d.scan_date DESC, d.rank_position ASC
        LIMIT {safe_limit}
    """)).mappings()
    return [dict(row) for row in rows]


def load_market_rows_for_symbol(conn, symbol: str, recommendation_date: str, max_rows: int = 30) -> list[dict[str, Any]]:
    safe_limit = min(max(int(max_rows or 30), 1), 120)
    result = conn.execute(text(f"""
        SELECT timestamp, open, high, low, close, volume
        FROM market_data
        WHERE symbol = :symbol
          AND DATE(timestamp) >= :recommendation_date
        ORDER BY timestamp ASC
        LIMIT {safe_limit}
    """), {"symbol": symbol, "recommendation_date": recommendation_date}).mappings()
    return [dict(row) for row in result]


def evaluate_and_persist_from_db(conn, limit: int = 500) -> dict[str, Any]:
    ensure_swing_performance_table(conn)
    recommendations = load_recommendations_for_evaluation(conn, limit=limit)
    evaluated = []
    for recommendation in recommendations:
        recommendation_date = _date_string(_row_get(recommendation, "scan_date"))
        symbol = str(_row_get(recommendation, "symbol") or "").upper()
        if not recommendation_date or not symbol:
            continue
        market_rows = load_market_rows_for_symbol(conn, symbol, recommendation_date)
        evaluated.append(evaluate_recommendation_performance(recommendation, market_rows))
    persist_performance_rows(conn, evaluated)
    return build_performance_payload(evaluated)
