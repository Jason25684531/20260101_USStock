import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.modules.setdefault("yfinance", SimpleNamespace())

from screener.engine import DailyScreener
from screener.market_data_resilience import (
    DATA_MODE_FAILED,
    DATA_MODE_FALLBACK,
    DATA_MODE_LIVE,
    DATA_MODE_STALE,
    build_provider_health_summary,
    classify_provider_error,
    persist_provider_health,
)
from adapters.market_data_provider import ProviderResult


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


class _FakeBeginEngine(_FakeEngine):
    def __init__(self):
        super().__init__()
        self.begin_connections = []

    def begin(self):
        conn = _FakeConnection()
        self.begin_connections.append(conn)
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

    def _fake_live_fetch(_symbol, *_args):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return ProviderResult.failure("AAPL", "openbb", "timeout", "request timed out")
        return ProviderResult.success_result(
            symbol="AAPL",
            provider_name="openbb",
            df=_price_frame(),
            data_mode=DATA_MODE_LIVE,
            info={"trailingEps": 8.5},
        )

    screener._market_data_providers = [
        SimpleNamespace(provider_name="openbb", fetch_daily_ohlcv=_fake_live_fetch)
    ]
    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "live_success"
    assert result.attempts == 3


def test_fetch_stock_data_uses_fresh_db_fallback_when_live_fetch_fails():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    fresh_df = _price_frame(latest="2026-05-18")
    screener._market_data_providers = [
        SimpleNamespace(
            provider_name="openbb",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.failure(symbol, "openbb", "no_price_data", "No price data found"),
        ),
        SimpleNamespace(
            provider_name="market_data",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.success_result(
                symbol=symbol,
                provider_name="market_data",
                df=fresh_df,
                data_mode=DATA_MODE_FALLBACK,
                cache_age_days=1,
            ),
        ),
    ]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "fallback_success"
    assert result.used_fallback is True
    assert result.cache_age_days == 1
    assert result.df is not None


def test_fetch_stock_data_uses_stale_db_fallback_when_live_fetch_fails(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "30")
    monkeypatch.setenv("SCREENER_CRITICAL_STALE_DAYS", "40")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    stale_df = _price_frame(latest="2026-05-01")
    screener._market_data_providers = [
        SimpleNamespace(
            provider_name="openbb",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.failure(symbol, "openbb", "no_price_data", "No price data found"),
        ),
        SimpleNamespace(
            provider_name="market_data",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.success_result(
                symbol=symbol,
                provider_name="market_data",
                df=stale_df,
                data_mode=DATA_MODE_STALE,
                cache_age_days=18,
            ),
        ),
    ]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "fallback_success"
    assert result.used_fallback is True
    assert result.data_mode == DATA_MODE_STALE
    assert result.cache_age_days == 18


def test_fetch_stock_data_uses_provider_chain_openbb_then_yfinance():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    openbb = SimpleNamespace(
        provider_name="openbb",
        fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.failure(
            symbol="AAPL",
            provider_name="openbb",
            error_type="timeout",
            message="timeout",
        ),
    )
    yfinance = SimpleNamespace(
        provider_name="yfinance",
        fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.success_result(
            symbol="AAPL",
            provider_name="yfinance",
            df=_price_frame(),
            data_mode=DATA_MODE_FALLBACK,
            info={"trailingEps": 8.5},
        ),
    )
    screener._market_data_providers = [openbb, yfinance]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "fallback_success"
    assert result.provider == "yfinance"
    assert result.provider_attempts[0]["provider"] == "openbb"
    assert result.provider_attempts[0]["error_type"] == "timeout"
    assert result.provider_attempts[-1]["provider"] == "yfinance"


def test_fetch_stock_data_falls_back_to_yfinance_after_openbb_json_parse_error():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    openbb = SimpleNamespace(
        provider_name="openbb",
        fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.failure(
            symbol="AAPL",
            provider_name="openbb",
            error_type="json_parse_error",
            message="OpenBB returned HTML instead of JSON",
            raw_metadata={"http_status": 200, "content_type": "text/html", "body_preview": "<html>"},
        ),
    )
    yfinance = SimpleNamespace(
        provider_name="yfinance",
        fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.success_result(
            symbol="AAPL",
            provider_name="yfinance",
            df=_price_frame(),
            data_mode=DATA_MODE_FALLBACK,
        ),
    )
    screener._market_data_providers = [openbb, yfinance]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "fallback_success"
    assert result.provider == "yfinance"
    assert result.used_fallback is True
    assert result.provider_attempts[0]["error_type"] == "json_parse_error"
    assert result.provider_attempts[0]["raw_metadata"]["content_type"] == "text/html"
    assert result.provider_attempts[0]["raw_metadata"]["body_preview"] == "<html>"
    assert result.provider_attempts[-1]["provider"] == "yfinance"


def test_fetch_stock_data_falls_back_to_local_db_after_openbb_schema_and_yfinance_failures(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    openbb = SimpleNamespace(
        provider_name="openbb",
        fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.failure(
            symbol="AAPL",
            provider_name="openbb",
            error_type="schema_mismatch",
            message="OpenBB changed envelope",
        ),
    )
    yfinance = SimpleNamespace(
        provider_name="yfinance",
        fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.failure(
            symbol="AAPL",
            provider_name="yfinance",
            error_type="rate_limited",
            message="429",
        ),
    )
    local_db = SimpleNamespace(
        provider_name="market_data",
        fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.success_result(
            symbol="AAPL",
            provider_name="market_data",
            df=_price_frame(),
            data_mode=DATA_MODE_FALLBACK,
            cache_age_days=1,
        ),
    )
    screener._market_data_providers = [openbb, yfinance, local_db]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "fallback_success"
    assert result.provider == "market_data"
    assert result.cache_age_days == 1
    attempted_providers = [attempt["provider"] for attempt in result.provider_attempts]
    assert attempted_providers[:3] == ["openbb", "openbb", "openbb"]
    assert "yfinance" in attempted_providers
    assert attempted_providers[-1] == "market_data"


def test_fetch_stock_data_all_providers_fail_keeps_critical_snapshot_metadata():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        SimpleNamespace(
            provider_name="openbb",
            fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.failure("AAPL", "openbb", "empty_response", "empty"),
        ),
        SimpleNamespace(
            provider_name="yfinance",
            fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.failure("AAPL", "yfinance", "provider_unavailable", "down"),
        ),
        SimpleNamespace(
            provider_name="market_data",
            fetch_daily_ohlcv=lambda *args, **kwargs: ProviderResult.failure("AAPL", "market_data", "no_price_data", "none"),
        ),
    ]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.data_mode == DATA_MODE_FAILED
    assert result.skip_reason == "provider_data_unavailable"
    assert result.provider_attempts[0]["error_type"] == "empty_response"
    assert result.provider_attempts[-1]["provider"] == "market_data"


def test_scan_all_records_skip_reasons_and_failed_mode_for_all_skipped_symbols():
    screener = DailyScreener(symbols=["AAPL", "MSFT"], use_ml=False)
    failed_result = ProviderResult.failure(
        symbol="AAPL",
        provider_name="openbb",
        error_type="json_parse_error",
        message="schema changed",
    )
    failing_provider = SimpleNamespace(
        provider_name="openbb",
        fetch_daily_ohlcv=lambda symbol, *args, **kwargs: ProviderResult.failure(
            symbol=symbol,
            provider_name="openbb",
            error_type=failed_result.error_type,
            message=failed_result.message,
        ),
    )
    screener._market_data_providers = [failing_provider]

    df = screener.scan_all()

    assert df.empty
    assert screener.last_run_summary["current_data_mode"] == DATA_MODE_FAILED
    assert screener.last_run_summary["top_error_types"]["json_parse_error"] == 2
    assert screener.last_run_summary["skipped_symbols"][0]["skip_reason"] == "provider_data_unavailable"


def test_save_to_db_allows_degraded_write_when_coverage_is_partial():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener.last_run_summary = {
        "total_symbols": 10,
        "coverage_ratio": 0.4,
        "minimum_coverage_ratio": 0.6,
        "current_data_mode": "fallback",
    }
    fake_db = _FakeDB()

    with patch("adapters.database.DatabaseAdapter", return_value=fake_db):
        written = screener.save_to_db([_base_recommendation()], scan_date=date(2026, 5, 19))

    assert written is True
    assert screener.last_run_summary["recommendations_written"] is True
    assert screener.last_run_summary["degraded"] is True


def test_save_to_db_blocks_write_when_coverage_is_critical():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener.last_run_summary = {
        "total_symbols": 10,
        "coverage_ratio": 0.1,
        "minimum_coverage_ratio": 0.6,
        "current_data_mode": DATA_MODE_FAILED,
    }

    with patch("adapters.database.DatabaseAdapter", return_value=_FakeDB()) as db_cls:
        written = screener.save_to_db([_base_recommendation()], scan_date=date(2026, 5, 19))

    assert written is False
    assert screener.last_run_summary["recommendations_written"] is False
    assert "critical" in screener.last_run_summary["write_blocked_reason"]
    assert db_cls.call_count == 1


def test_save_to_db_blocks_write_when_provider_mode_is_failed_even_with_rows():
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener.last_run_summary = {
        "total_symbols": 10,
        "coverage_ratio": 0.8,
        "minimum_coverage_ratio": 0.6,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_FAILED,
    }

    with patch("adapters.database.DatabaseAdapter", return_value=_FakeDB()) as db_cls:
        written = screener.save_to_db([_base_recommendation()], scan_date=date(2026, 5, 19))

    assert written is False
    assert screener.last_run_summary["recommendations_written"] is False
    assert "failed provider health" in screener.last_run_summary["write_blocked_reason"]
    assert db_cls.call_count == 1


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
            "current_data_mode": DATA_MODE_FALLBACK,
            "top_error_types": {"timeout": 1},
        }
    )

    assert "live_successes=4" in summary_text
    assert "fallback_successes=3" in summary_text
    assert "failed_symbols=2" in summary_text
    assert "coverage_ratio=0.70" in summary_text
    assert "current_data_mode=fallback" in summary_text
    assert "top_error_types=timeout:1" in summary_text


def test_persist_provider_health_writes_normal_degraded_stale_and_failed_modes():
    for mode, coverage_ratio in [
        (DATA_MODE_LIVE, 0.9),
        (DATA_MODE_FALLBACK, 0.4),
        (DATA_MODE_STALE, 0.3),
        (DATA_MODE_FAILED, 0.0),
    ]:
        engine = _FakeBeginEngine()
        summary = {
            "provider_health_run_key": f"run-{mode}",
            "provider_health_run_at": "2026-05-20T21:00:00",
            "total_symbols": 10,
            "live_successes": 6 if mode == DATA_MODE_LIVE else 0,
            "fallback_successes": 4 if mode in {DATA_MODE_FALLBACK, DATA_MODE_STALE} else 0,
            "failed_symbols": [{"symbol": "AAPL", "status": "timeout"}] if mode == DATA_MODE_FAILED else [],
            "skipped_symbols": [{"symbol": "AAPL", "status": "timeout"}] if mode == DATA_MODE_FAILED else [],
            "coverage_ratio": coverage_ratio,
            "minimum_coverage_ratio": 0.6,
            "current_data_mode": mode,
            "stale_data_used": mode == DATA_MODE_STALE,
            "recommendations_written": mode != DATA_MODE_FAILED,
            "provider_counts": {"openbb": 6},
            "top_error_types": {"timeout": 1} if mode == DATA_MODE_FAILED else {},
        }

        assert persist_provider_health(engine, summary, last_valid_recommendation_time="2026-05-19") is True
        insert_call = engine.begin_connections[0].calls[-1]
        assert "provider_health_log" in insert_call[0]
        assert insert_call[1]["current_data_mode"] == mode
        assert insert_call[1]["last_valid_recommendation_time"] == "2026-05-19"
