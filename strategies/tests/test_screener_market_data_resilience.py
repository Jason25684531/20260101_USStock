import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.modules.setdefault("yfinance", SimpleNamespace())

from screener.engine import DailyScreener
from screener.market_data_resilience import (
    build_provider_health_summary,
    classify_provider_error,
)


def _price_frame(days=80, close=100.0, latest="2026-05-19"):
    index = pd.date_range(end=pd.Timestamp(latest), periods=days, freq="D")
    return pd.DataFrame(
        {
            "Open": [close] * days,
            "High": [close + 1] * days,
            "Low": [close - 1] * days,
            "Close": [close] * days,
            "Volume": [1000] * days,
        },
        index=index,
    )


def _base_recommendation():
    return {
        "rank": 1,
        "symbol": "AAPL",
        "signal": "BUY",
        "total_score": 4.2,
        "breakout_pass": True,
        "acceleration_pass": True,
        "peg_pass": False,
        "dupont_pass": True,
        "ml_confidence": 0.71,
        "current_price": 100.0,
        "target_price": 120.0,
        "institutional_ownership": 66.5,
        "insider_sentiment": "BUYING",
        "support_1": 95.0,
        "support_2": 92.0,
        "resistance_1": 110.0,
        "resistance_2": 118.0,
        "pe_ratio": 20.0,
        "peg_ratio": 1.5,
        "pb_ratio": 4.1,
        "roe": 0.21,
        "fair_price": 108.0,
        "buy_price": 98.0,
        "sell_price": 116.0,
        "valuation_status": "FAIR",
        "reason_summary": "test summary",
        "strategy_details": {"breakout": {"pass": True}},
    }


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))

        class _ScalarResult:
            def scalar(self_nonlocal):
                return 1

        return _ScalarResult()

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self):
        self.connections = []

    def connect(self):
        conn = _FakeConnection()
        self.connections.append(conn)
        return conn


class _FakeDB:
    def __init__(self):
        self.engine = _FakeEngine()

    def close(self):
        return None


def test_classify_provider_error_json_parse():
    assert classify_provider_error(ValueError("Expecting value: line 1 column 1 (char 0)")) == "json_parse_error"


def test_classify_provider_error_no_price_data():
    assert classify_provider_error(RuntimeError("No price data found")) == "no_price_data"


def test_classify_provider_error_timeout_rate_limit_and_http():
    assert classify_provider_error(TimeoutError("request timed out")) == "timeout"
    assert classify_provider_error(RuntimeError("429 Too Many Requests")) == "rate_limited"
    assert classify_provider_error(RuntimeError("HTTP 500 upstream failure")) == "http_error"


def test_fetch_stock_data_retries_within_limit_before_succeeding():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    attempts = {"count": 0}

    def _fake_live_fetch(_symbol):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("request timed out")
        return _price_frame(), {"trailingEps": 8.5}

    with patch.object(screener, "_fetch_live_stock_data_once", side_effect=_fake_live_fetch):
        result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "live_success"
    assert result.attempts == 3


def test_fetch_stock_data_uses_fresh_db_fallback_when_live_fetch_fails():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    fresh_df = _price_frame(latest="2026-05-18")

    with patch.object(screener, "_fetch_live_stock_data_once", side_effect=ValueError("No price data found")), \
         patch.object(screener, "_load_market_data_fallback", return_value=(fresh_df, 1)):
        result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "fallback_success"
    assert result.used_fallback is True
    assert result.cache_age_days == 1
    assert result.df is not None


def test_fetch_stock_data_rejects_stale_db_fallback():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    stale_df = _price_frame(latest="2026-05-01")

    with patch.object(screener, "_fetch_live_stock_data_once", side_effect=ValueError("No price data found")), \
         patch.object(screener, "_load_market_data_fallback", return_value=(stale_df, 18)):
        result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "no_price_data"
    assert result.used_fallback is False
    assert "stale" in result.message.lower()


def test_save_to_db_skips_write_when_coverage_below_threshold():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener.last_run_summary = {
        "total_symbols": 10,
        "coverage_ratio": 0.4,
        "minimum_coverage_ratio": 0.6,
    }

    with patch("adapters.database.DatabaseAdapter", return_value=_FakeDB()) as db_cls:
        written = screener.save_to_db([_base_recommendation()], scan_date=date(2026, 5, 19))

    assert written is False
    assert screener.last_run_summary["recommendations_written"] is False
    assert db_cls.call_count == 0


def test_save_to_db_allows_write_when_coverage_threshold_met():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener.last_run_summary = {
        "total_symbols": 10,
        "coverage_ratio": 0.8,
        "minimum_coverage_ratio": 0.6,
    }
    fake_db = _FakeDB()

    with patch("adapters.database.DatabaseAdapter", return_value=fake_db):
        written = screener.save_to_db([_base_recommendation()], scan_date=date(2026, 5, 19))

    assert written is True
    assert screener.last_run_summary["recommendations_written"] is True
    assert fake_db.engine.connections


def test_provider_health_summary_includes_live_fallback_failure_counts():
    summary_text = build_provider_health_summary(
        {
            "total_symbols": 10,
            "live_successes": 4,
            "fallback_successes": 3,
            "failed_symbols": [
                {"symbol": "QQQ", "status": "json_parse_error"},
                {"symbol": "SPY", "status": "timeout"},
            ],
            "skipped_symbols": [
                {"symbol": "SPY", "status": "timeout"},
            ],
            "coverage_ratio": 0.7,
            "minimum_coverage_ratio": 0.6,
            "recommendations_written": True,
        }
    )

    assert "live_successes=4" in summary_text
    assert "fallback_successes=3" in summary_text
    assert "failed_symbols=2" in summary_text
    assert "coverage_ratio=0.70" in summary_text
