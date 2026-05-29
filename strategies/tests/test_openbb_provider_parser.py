from types import SimpleNamespace

import pandas as pd

from adapters.market_data_provider import (
    ERROR_EMPTY_RESPONSE,
    ERROR_HTTP,
    ERROR_JSON_PARSE,
    ERROR_PROVIDER_MAINTENANCE,
    ERROR_RATE_LIMITED,
    ERROR_SCHEMA_MISMATCH,
    OpenBBHistoricalProvider,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        content_type="application/json",
        text="",
        json_payload=None,
        json_error=None,
    ):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.text = text
        self.content = text.encode("utf-8")
        self._json_payload = json_payload
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._json_payload


def _provider_for(response):
    return OpenBBHistoricalProvider(
        api_url="http://openbb.local",
        request_get=lambda *_args, **_kwargs: response,
    )


def _valid_payload():
    dates = pd.date_range(end="2026-05-28", periods=3, freq="D")
    return {
        "results": [
            {
                "date": str(day.date()),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 1000,
            }
            for day in dates
        ]
    }


def test_openbb_html_response_is_json_parse_error_with_safe_metadata():
    html = "<html><body>OpenBB token=SECRET_TOKEN authorization Bearer hidden</body></html>"
    response = FakeResponse(content_type="text/html", text=html)

    result = _provider_for(response).fetch_daily_ohlcv("AAPL")

    assert result.success is False
    assert result.error_type == ERROR_JSON_PARSE
    assert result.raw_metadata["http_status"] == 200
    assert result.raw_metadata["content_type"] == "text/html"
    assert result.raw_metadata["response_length"] == len(html)
    assert "SECRET_TOKEN" not in result.raw_metadata["body_preview"]
    assert len(result.raw_metadata["body_preview"]) <= 240


def test_openbb_empty_response_is_empty_response():
    response = FakeResponse(content_type="application/json", text="")

    result = _provider_for(response).fetch_daily_ohlcv("MSFT")

    assert result.success is False
    assert result.error_type == ERROR_EMPTY_RESPONSE
    assert result.raw_metadata["response_length"] == 0


def test_openbb_schema_mismatch_is_classified():
    response = FakeResponse(
        content_type="application/json",
        text='{"unexpected": {"items": []}}',
        json_payload={"unexpected": {"items": []}},
    )

    result = _provider_for(response).fetch_daily_ohlcv("NVDA")

    assert result.success is False
    assert result.error_type == ERROR_SCHEMA_MISMATCH
    assert result.raw_metadata["schema_keys"] == ["unexpected"]


def test_openbb_http_error_is_classified_with_metadata():
    response = FakeResponse(status_code=500, content_type="application/json", text='{"error":"boom"}')

    result = _provider_for(response).fetch_daily_ohlcv("AAPL")

    assert result.success is False
    assert result.error_type == ERROR_HTTP
    assert result.raw_metadata["http_status"] == 500


def test_openbb_rate_limit_payload_is_classified():
    response = FakeResponse(
        status_code=429,
        content_type="application/json",
        text='{"detail":"Too many requests"}',
    )

    result = _provider_for(response).fetch_daily_ohlcv("AAPL")

    assert result.success is False
    assert result.error_type == ERROR_RATE_LIMITED
    assert result.raw_metadata["http_status"] == 429


def test_openbb_maintenance_payload_is_classified():
    response = FakeResponse(
        status_code=503,
        content_type="application/json",
        text='{"detail":"provider maintenance"}',
    )

    result = _provider_for(response).fetch_daily_ohlcv("AAPL")

    assert result.success is False
    assert result.error_type == ERROR_PROVIDER_MAINTENANCE
    assert result.raw_metadata["http_status"] == 503


def test_openbb_valid_payload_still_succeeds():
    response = FakeResponse(
        content_type="application/json",
        text='{"results":[]}',
        json_payload=_valid_payload(),
    )

    result = _provider_for(response).fetch_daily_ohlcv("AAPL")

    assert result.success is True
    assert result.df is not None
    assert len(result.df) == 3
