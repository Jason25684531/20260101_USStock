import sys
from types import SimpleNamespace

import pandas as pd

sys.modules.setdefault("yfinance", SimpleNamespace())

from adapters.market_data_provider import ProviderResult
from screener.engine import DailyScreener
from screener.market_data_resilience import DATA_MODE_FAILED, DATA_MODE_STALE


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


def test_local_db_fallback_within_max_stale_age_is_usable(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    monkeypatch.setenv("SCREENER_CRITICAL_STALE_DAYS", "10")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        SimpleNamespace(
            provider_name="openbb",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.failure(symbol, "openbb", "timeout", "timeout"),
        ),
        SimpleNamespace(
            provider_name="market_data",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.success_result(
                symbol=symbol,
                provider_name="market_data",
                df=_price_frame(),
                data_mode=DATA_MODE_STALE,
                cache_age_days=5,
            ),
        ),
    ]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "fallback_success"
    assert result.data_mode == DATA_MODE_STALE
    assert result.cache_age_days == 5


def test_local_db_fallback_exceeding_max_stale_age_is_rejected(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    monkeypatch.setenv("SCREENER_CRITICAL_STALE_DAYS", "10")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        SimpleNamespace(
            provider_name="openbb",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.failure(symbol, "openbb", "timeout", "timeout"),
        ),
        SimpleNamespace(
            provider_name="market_data",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.success_result(
                symbol=symbol,
                provider_name="market_data",
                df=_price_frame(),
                data_mode=DATA_MODE_STALE,
                cache_age_days=6,
            ),
        ),
    ]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "stale_fallback_too_old"
    assert result.data_mode == DATA_MODE_FAILED
    assert result.skip_reason == "stale_fallback_too_old"


def test_local_db_fallback_exceeding_critical_stale_age_sets_critical_metadata(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    monkeypatch.setenv("SCREENER_CRITICAL_STALE_DAYS", "10")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener._market_data_providers = [
        SimpleNamespace(
            provider_name="market_data",
            fetch_daily_ohlcv=lambda symbol, *_args: ProviderResult.success_result(
                symbol=symbol,
                provider_name="market_data",
                df=_price_frame(),
                data_mode=DATA_MODE_STALE,
                cache_age_days=11,
            ),
        ),
    ]

    result = screener.fetch_stock_data_result("AAPL")

    assert result.status == "critical_stale_fallback"
    assert result.data_mode == DATA_MODE_FAILED
    assert result.cache_age_days == 11


def test_critical_coverage_with_stale_fallback_preserves_last_valid_recommendations(monkeypatch):
    monkeypatch.setenv("SCREENER_MAX_STALE_FALLBACK_DAYS", "5")
    monkeypatch.setenv("SCREENER_CRITICAL_STALE_DAYS", "10")
    screener = DailyScreener(symbols=["AAPL"], use_ml=False)
    screener.last_run_summary = {
        "total_symbols": 1,
        "coverage_ratio": 0.0,
        "minimum_coverage_ratio": 0.6,
        "critical_coverage_ratio": 0.2,
        "current_data_mode": DATA_MODE_FAILED,
        "stale_data_used": True,
        "max_stale_age_exceeded": True,
        "stale_age_days": 11,
    }

    can_write, reason = screener._can_write_recommendations([{"symbol": "AAPL"}])

    assert can_write is False
    assert "preserving previous recommendations" in reason
