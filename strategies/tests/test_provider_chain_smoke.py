import sys
from types import SimpleNamespace

import pandas as pd

sys.modules.setdefault("yfinance", SimpleNamespace())

from adapters.market_data_provider import ProviderResult
from screener.engine import DailyScreener
from screener.market_data_resilience import (
    DATA_MODE_FAILED,
    DATA_MODE_FALLBACK,
    DATA_MODE_LIVE,
    DATA_MODE_STALE,
    build_provider_health_diagnostics,
    normalize_provider_health,
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


def _provider(name, result):
    return SimpleNamespace(provider_name=name, fetch_daily_ohlcv=lambda symbol, *_args: result(symbol))


def test_provider_chain_smoke_openbb_success_is_healthy(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        _provider("openbb", lambda symbol: ProviderResult.success_result(symbol, "openbb", df=_price_frame(), data_mode=DATA_MODE_LIVE)),
    ]

    result = screener.fetch_stock_data_result("AAPL")
    health = normalize_provider_health({
        "coverage_ratio": 1.0,
        "minimum_coverage_ratio": 0.6,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": result.data_mode,
        "recommendations_written": True,
        "provider_counts": {result.provider: 1},
        "provider_attempts": result.provider_attempts,
    })

    assert result.provider == "openbb"
    assert result.used_fallback is False
    assert health["status"] == "healthy"


def test_provider_chain_smoke_yfinance_success_after_openbb_failure(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        _provider("openbb", lambda symbol: ProviderResult.failure(symbol, "openbb", "timeout", "timeout")),
        _provider("yfinance", lambda symbol: ProviderResult.success_result(symbol, "yfinance", df=_price_frame(), data_mode=DATA_MODE_FALLBACK)),
    ]

    result = screener.fetch_stock_data_result("AAPL")
    health = normalize_provider_health({
        "coverage_ratio": 1.0,
        "minimum_coverage_ratio": 0.6,
        "current_data_mode": result.data_mode,
        "recommendations_written": True,
        "provider_counts": {result.provider: 1},
        "provider_attempts": result.provider_attempts,
        "fallback_attempts": result.provider_attempts[1:],
    })

    assert result.provider == "yfinance"
    assert result.used_fallback is True
    assert health["status"] == "degraded"
    assert health["effective_provider"] == "yfinance"


def test_provider_chain_smoke_local_db_fallback_is_stale(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        _provider("openbb", lambda symbol: ProviderResult.failure(symbol, "openbb", "timeout", "timeout")),
        _provider("yfinance", lambda symbol: ProviderResult.failure(symbol, "yfinance", "rate_limited", "429")),
        _provider("market_data", lambda symbol: ProviderResult.success_result(symbol, "market_data", df=_price_frame(), data_mode=DATA_MODE_STALE, cache_age_days=4)),
    ]

    result = screener.fetch_stock_data_result("AAPL")
    health = normalize_provider_health({
        "coverage_ratio": 1.0,
        "minimum_coverage_ratio": 0.6,
        "current_data_mode": result.data_mode,
        "stale_data_used": True,
        "stale_age_days": result.cache_age_days,
        "recommendations_written": True,
        "provider_counts": {result.provider: 1},
    })

    assert result.provider == "market_data"
    assert health["status"] == "stale"
    assert health["stale_age_days"] == 4


def test_provider_chain_smoke_critical_coverage_uses_last_valid_snapshot():
    health = normalize_provider_health({
        "coverage_ratio": 0.1,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_FAILED,
        "recommendations_written": False,
        "last_valid_recommendation_time": "2026-05-20",
    })

    assert health["status"] == "critical"
    assert health["recommendation_source"] == "last_valid_snapshot"
    assert health["is_using_last_valid_snapshot"] is True


def test_provider_chain_smoke_rejects_local_db_fallback_beyond_max_stale_days(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    monkeypatch.setenv("SCREENER_CRITICAL_STALE_DAYS", "10")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        _provider("market_data", lambda symbol: ProviderResult.success_result(symbol, "market_data", df=_price_frame(), data_mode=DATA_MODE_STALE, cache_age_days=6)),
    ]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.data_mode == DATA_MODE_FAILED
    assert result.skip_reason == "stale_fallback_too_old"


def test_provider_chain_smoke_parse_error_diagnostics_preserve_snapshot(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        _provider("openbb", lambda symbol: ProviderResult.failure(symbol, "openbb", "openbbjson_parse_error", "invalid json")),
        _provider("yfinance", lambda symbol: ProviderResult.failure(symbol, "yfinance", "provider_unavailable", "unavailable")),
    ]

    result = screener.fetch_stock_data_result("AAPL")
    health = normalize_provider_health({
        "coverage_ratio": 0.0,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": result.data_mode,
        "recommendations_written": False,
        "last_valid_recommendation_time": "2026-05-28 00:00:00",
        "provider_attempts": result.provider_attempts,
        "fallback_attempts": result.provider_attempts[1:],
        "top_error_types": {"openbbjson_parse_error": 1, "provider_unavailable": 1},
        "skip_reasons": {result.skip_reason: 1},
    })
    diagnostics = build_provider_health_diagnostics(health)

    assert result.data_mode == DATA_MODE_FAILED
    assert health["status"] == "critical"
    assert health["recommendation_source"] == "last_valid_snapshot"
    assert diagnostics["root_cause"] == "openbb_json_parse_error"
    assert diagnostics["fallback_outcome"] == "unavailable"
    assert diagnostics["snapshot_preserved"] is True
