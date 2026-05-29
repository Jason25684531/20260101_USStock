from datetime import date
from types import SimpleNamespace

import pandas as pd

from adapters.market_data_provider import (
    DATA_MODE_FALLBACK,
    DATA_MODE_LIVE,
    DATA_MODE_STALE,
    ERROR_NO_PRICE_DATA,
    OpenBBHistoricalProvider,
    ProviderResult,
    YFinanceProvider,
    LocalDatabaseProvider,
    normalize_ohlcv_frame,
)


def _raw_price_frame(latest="2026-05-19", days=80):
    dates = pd.date_range(end=pd.Timestamp(latest), periods=days, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * days,
            "high": [101.0] * days,
            "low": [99.0] * days,
            "close": [100.5] * days,
            "volume": [1000] * days,
            "adj_close": [100.4] * days,
        }
    )


def test_normalize_ohlcv_frame_accepts_openbb_lowercase_schema():
    normalized = normalize_ohlcv_frame(_raw_price_frame())

    assert list(normalized.columns) == ["Open", "High", "Low", "Close", "Volume", "Adj Close"]
    assert isinstance(normalized.index, pd.DatetimeIndex)
    assert normalized.index.tz is None
    assert float(normalized["Close"].iloc[-1]) == 100.5


def test_openbb_provider_fetches_daily_history_through_configured_api():
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"results": _raw_price_frame().to_dict("records")},
        )

    provider = OpenBBHistoricalProvider(api_url="http://openbb.local", request_get=fake_get)

    result = provider.fetch_daily_ohlcv("AAPL", "2026-01-01", "2026-05-20")

    assert result.success is True
    assert result.provider_name == "openbb"
    assert result.data_mode == DATA_MODE_LIVE
    assert len(result.df) == 80
    assert calls[0][0] == "http://openbb.local/api/v1/equity/price/historical"
    assert calls[0][1]["symbol"] == "AAPL"


def test_provider_result_classifies_empty_data_as_non_retryable_no_price_data():
    result = ProviderResult.failure(
        symbol="AAPL",
        provider_name="openbb",
        error_type=ERROR_NO_PRICE_DATA,
        message="empty response",
    )

    assert result.success is False
    assert result.is_retriable is False


def test_yfinance_provider_normalizes_history_and_quote():
    history = _raw_price_frame().set_index("date").rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "adj_close": "Adj Close",
        }
    )
    ticker = SimpleNamespace(
        history=lambda **kwargs: history,
        info={"regularMarketPrice": 123.45},
    )
    provider = YFinanceProvider(ticker_factory=lambda symbol: ticker)

    history_result = provider.fetch_daily_ohlcv("MSFT", "2026-01-01", "2026-05-20")
    quote_result = provider.fetch_latest_quote("MSFT")

    assert history_result.success is True
    assert history_result.provider_name == "yfinance"
    assert history_result.data_mode == DATA_MODE_FALLBACK
    assert float(history_result.df["Close"].iloc[-1]) == 100.5
    assert quote_result.success is True
    assert quote_result.quote == 123.45


def test_local_database_provider_returns_stale_mode_when_cache_is_old():
    frame = _raw_price_frame(latest="2026-05-01").set_index("date")
    fake_db = SimpleNamespace(get_market_data=lambda symbol: frame)
    provider = LocalDatabaseProvider(
        db_factory=lambda: fake_db,
        today_factory=lambda: date(2026, 5, 20),
        max_fresh_age_days=3,
    )

    result = provider.fetch_daily_ohlcv("NVDA", "2026-01-01", "2026-05-20")

    assert result.success is True
    assert result.provider_name == "market_data"
    assert result.data_mode == DATA_MODE_STALE
    assert result.cache_age_days == 19
