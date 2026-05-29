from __future__ import annotations

from datetime import date

import pandas as pd

from screener.swing_performance import (
    aggregate_performance,
    build_performance_payload,
    evaluate_recommendation_performance,
    ensure_swing_performance_table,
    persist_performance_rows,
    score_bucket,
)


def _market_rows(closes, *, start="2026-05-01", high_spread=0.02, low_spread=0.02):
    rows = []
    for index, close in enumerate(closes):
        close = float(close)
        rows.append({
            "timestamp": pd.Timestamp(start) + pd.Timedelta(days=index),
            "open": close * 0.99,
            "high": close * (1 + high_spread),
            "low": close * (1 - low_spread),
            "close": close,
            "volume": 1_000_000,
        })
    return rows


def _recommendation(**overrides):
    base = {
        "scan_date": date(2026, 5, 1),
        "symbol": "NVDA",
        "rank_position": 1,
        "total_score": 4.8,
        "current_price": 100.0,
        "provider_health_status": "healthy",
        "recommendation_source": "current_run",
        "strategy_details": {
            "swing_ranking": {
                "score": 86.4,
                "setup_type": "breakout",
                "reasons": ["Close broke above the 20-day high"],
                "risk_flags": ["Close is extended above MA20"],
            }
        },
    }
    base.update(overrides)
    return base


def test_evaluate_recommendation_calculates_forward_returns_hits_drawdown_and_mfe():
    closes = [100, 100, 102, 103, 104, 110, 106, 107, 108, 109, 120]
    closes.extend([121, 122, 123, 124, 125, 126, 127, 128, 129, 140])

    row = evaluate_recommendation_performance(
        _recommendation(),
        _market_rows(closes, high_spread=0.05, low_spread=0.03),
    )

    assert row["symbol"] == "NVDA"
    assert row["recommendation_date"] == "2026-05-01"
    assert row["entry_close"] == 100.0
    assert row["close_5d"] == 110.0
    assert row["close_10d"] == 120.0
    assert row["close_20d"] == 140.0
    assert row["forward_return_5d"] == 0.1
    assert row["forward_return_10d"] == 0.2
    assert row["forward_return_20d"] == 0.4
    assert row["hit_5d"] is True
    assert row["hit_10d"] is True
    assert row["hit_20d"] is True
    assert row["max_drawdown_20d"] == -0.03
    assert row["max_favorable_excursion_20d"] == 0.47
    assert row["score"] == 86.4
    assert row["setup_type"] == "breakout"
    assert row["risk_flags"] == ["Close is extended above MA20"]


def test_evaluate_recommendation_handles_missing_future_and_entry_data_safely():
    short_row = evaluate_recommendation_performance(
        _recommendation(),
        _market_rows([100, 101, 102, 103, 104, 105]),
    )
    missing_entry = evaluate_recommendation_performance(
        _recommendation(scan_date=date(2026, 4, 30)),
        _market_rows([100, 101, 102, 103, 104, 105]),
    )

    assert short_row["forward_return_5d"] == 0.05
    assert short_row["forward_return_10d"] is None
    assert short_row["forward_return_20d"] is None
    assert short_row["evaluation_status"] == "partial"
    assert missing_entry["entry_close"] == 100.0
    assert missing_entry["evaluation_status"] == "entry_price_fallback"


def test_close_only_rows_are_used_for_drawdown_and_mfe_when_high_low_missing():
    rows = [{"timestamp": pd.Timestamp("2026-05-01") + pd.Timedelta(days=i), "close": close} for i, close in enumerate([100, 95, 105])]

    row = evaluate_recommendation_performance(_recommendation(), rows)

    assert row["max_drawdown_20d"] == -0.05
    assert row["max_favorable_excursion_20d"] == 0.05


def test_aggregate_performance_groups_rank_score_setup_risk_and_provider_context():
    rows = [
        {
            "rank": 1,
            "score": 86.0,
            "setup_type": "breakout",
            "risk_flags": [],
            "provider_health_status": "healthy",
            "recommendation_source": "current_run",
            "forward_return_5d": 0.02,
            "forward_return_10d": 0.04,
            "forward_return_20d": 0.10,
            "hit_5d": True,
            "hit_10d": True,
            "hit_20d": True,
            "max_drawdown_20d": -0.03,
            "max_favorable_excursion_20d": 0.12,
        },
        {
            "rank": 7,
            "score": 65.0,
            "setup_type": "pullback_reclaim",
            "risk_flags": ["wide stop"],
            "provider_health_status": "critical",
            "recommendation_source": "last_valid_snapshot",
            "forward_return_5d": -0.01,
            "forward_return_10d": -0.02,
            "forward_return_20d": -0.04,
            "hit_5d": False,
            "hit_10d": False,
            "hit_20d": False,
            "max_drawdown_20d": -0.08,
            "max_favorable_excursion_20d": 0.02,
        },
    ]

    payload = aggregate_performance(rows)

    assert payload["summary"]["sample_size"] == 1
    assert payload["summary"]["avg_forward_return_20d"] == 0.1
    assert payload["rank_groups"][0]["group"] == "top5"
    assert payload["score_buckets"][0]["bucket"] == ">=80"
    assert payload["score_buckets"][0]["sample_size"] == 1
    assert any(item["setup_type"] == "breakout" for item in payload["setup_types"])
    assert any(item["group"] == "any_risk_flag" for item in payload["risk_flags"])
    assert any(item["provider_health_status"] == "critical" for item in payload["provider_health_segments"])
    assert payload["fresh_filter"]["excluded_statuses"] == ["failed", "critical"]


def test_score_bucket_and_empty_payload_are_stable():
    assert score_bucket(81) == ">=80"
    assert score_bucket(75) == "70-80"
    assert score_bucket(60) == "60-70"
    assert score_bucket(59) == "<60"
    assert build_performance_payload([])["summary"]["sample_size"] == 0
    assert build_performance_payload([])["summary"]["avg_forward_return_20d"] is None


class RecordingConn:
    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))


def test_persistence_helpers_create_table_and_upsert_by_recommendation_date_symbol():
    conn = RecordingConn()
    ensure_swing_performance_table(conn)
    persist_performance_rows(conn, [{"recommendation_date": "2026-05-01", "symbol": "NVDA"}])

    joined = "\n".join(statement for statement, _ in conn.statements)
    assert "CREATE TABLE IF NOT EXISTS swing_ranking_performance" in joined
    assert "UNIQUE KEY uk_swing_perf_recommendation" in joined
    assert "ON DUPLICATE KEY UPDATE" in joined
