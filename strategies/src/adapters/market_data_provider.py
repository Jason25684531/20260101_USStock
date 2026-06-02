from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

import pandas as pd
import requests

ERROR_NO_PRICE_DATA = "no_price_data"
ERROR_JSON_PARSE = "json_parse_error"
ERROR_SCHEMA_MISMATCH = "schema_mismatch"
ERROR_EMPTY_RESPONSE = "empty_response"
ERROR_TIMEOUT = "timeout"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_HTTP = "http_error"
ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERROR_PROVIDER_MAINTENANCE = "provider_maintenance"
ERROR_UNKNOWN = "unknown_error"

DATA_MODE_LIVE = "live"
DATA_MODE_FALLBACK = "fallback"
DATA_MODE_STALE = "stale"
DATA_MODE_FAILED = "failed"


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
    if "http" in message or "httperror" in error_name or "connection" in message:
        return ERROR_HTTP
    return ERROR_UNKNOWN


def is_retryable_status(status: str) -> bool:
    return status in {
        ERROR_JSON_PARSE,
        ERROR_SCHEMA_MISMATCH,
        ERROR_EMPTY_RESPONSE,
        ERROR_TIMEOUT,
        ERROR_RATE_LIMITED,
        ERROR_HTTP,
        ERROR_PROVIDER_UNAVAILABLE,
        ERROR_PROVIDER_MAINTENANCE,
    }


OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
OPTIONAL_OHLCV_COLUMNS = ["Adj Close"]
MAX_RESPONSE_PREVIEW_CHARS = 240


def _sanitize_response_preview(text: Any, max_chars: int = MAX_RESPONSE_PREVIEW_CHARS) -> str:
    preview = "" if text is None else str(text)
    replacements = (
        ("authorization", "authorization"),
        ("bearer", "bearer"),
        ("token", "token"),
        ("api_key", "api_key"),
        ("apikey", "apikey"),
        ("secret", "secret"),
        ("cookie", "cookie"),
    )
    for marker, replacement in replacements:
        lower = preview.lower()
        start = lower.find(marker)
        while start >= 0:
            end = start
            while end < len(preview) and preview[end] not in {" ", "\n", "\r", "\t", "&", ",", ";", '"', "'"}:
                end += 1
            preview = preview[:start] + f"{replacement}=[redacted]" + preview[end:]
            lower = preview.lower()
            start = lower.find(marker, start + len(replacement) + 10)
    preview = " ".join(preview.split())
    return preview[:max_chars]


def _response_metadata(response: Any, endpoint: str, provider: str, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    headers = getattr(response, "headers", {}) or {}
    content_type = headers.get("Content-Type") or headers.get("content-type") or ""
    body_text = getattr(response, "text", "") or ""
    content = getattr(response, "content", None)
    if content is not None:
        try:
            response_length = len(content)
        except TypeError:
            response_length = len(body_text)
    else:
        response_length = len(body_text)
    metadata = {
        "endpoint": endpoint,
        "provider": provider,
        "http_status": getattr(response, "status_code", None),
        "content_type": str(content_type),
        "response_length": response_length,
        "body_preview": _sanitize_response_preview(body_text),
    }
    if extra:
        metadata.update(extra)
    return metadata


def _classify_openbb_http_response(response: Any) -> Optional[str]:
    status_code = int(getattr(response, "status_code", 200) or 200)
    body_text = str(getattr(response, "text", "") or "").lower()
    if status_code == 429 or "too many requests" in body_text or "rate limit" in body_text:
        return ERROR_RATE_LIMITED
    if status_code in {502, 503, 504} and ("maintenance" in body_text or "temporarily unavailable" in body_text):
        return ERROR_PROVIDER_MAINTENANCE
    if status_code >= 400:
        return ERROR_HTTP
    return None


def _extract_openbb_records(payload: Any) -> tuple[Optional[Any], Optional[str], dict[str, Any]]:
    if isinstance(payload, list):
        return payload, None, {}
    if not isinstance(payload, dict):
        return None, ERROR_SCHEMA_MISMATCH, {"schema_type": type(payload).__name__}
    if "results" in payload:
        return payload.get("results"), None, {}
    for key in ("data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value, None, {"schema_key": key}
        if isinstance(value, dict) and "results" in value:
            return value.get("results"), None, {"schema_key": f"{key}.results"}
    return None, ERROR_SCHEMA_MISMATCH, {"schema_keys": sorted(str(key) for key in payload.keys())}


@dataclass
class ProviderResult:
    symbol: str
    provider_name: str
    success: bool
    df: Optional[pd.DataFrame] = None
    quote: Optional[float] = None
    info: dict[str, Any] = field(default_factory=dict)
    error_type: str = ""
    message: str = ""
    is_retriable: bool = False
    data_mode: str = DATA_MODE_FAILED
    cache_age_days: Optional[int] = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success_result(
        cls,
        symbol: str,
        provider_name: str,
        df: Optional[pd.DataFrame] = None,
        quote: Optional[float] = None,
        info: Optional[dict[str, Any]] = None,
        data_mode: str = DATA_MODE_LIVE,
        cache_age_days: Optional[int] = None,
        raw_metadata: Optional[dict[str, Any]] = None,
    ) -> "ProviderResult":
        return cls(
            symbol=symbol,
            provider_name=provider_name,
            success=True,
            df=df,
            quote=quote,
            info=info or {},
            data_mode=data_mode,
            cache_age_days=cache_age_days,
            raw_metadata=raw_metadata or {},
        )

    @classmethod
    def failure(
        cls,
        symbol: str,
        provider_name: str,
        error_type: str,
        message: str,
        raw_metadata: Optional[dict[str, Any]] = None,
    ) -> "ProviderResult":
        return cls(
            symbol=symbol,
            provider_name=provider_name,
            success=False,
            error_type=error_type or ERROR_UNKNOWN,
            message=message,
            is_retriable=is_retryable_status(error_type),
            data_mode=DATA_MODE_FAILED,
            raw_metadata=raw_metadata or {},
        )


def normalize_ohlcv_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    normalized = df.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    lower_to_original = {column.lower().replace(" ", "_"): column for column in normalized.columns}

    if not isinstance(normalized.index, pd.DatetimeIndex):
        date_column = None
        for candidate in ("date", "datetime", "timestamp"):
            if candidate in lower_to_original:
                date_column = lower_to_original[candidate]
                break
        if date_column:
            normalized.index = pd.to_datetime(normalized[date_column], errors="coerce")
            normalized = normalized.drop(columns=[date_column])
        else:
            normalized.index = pd.to_datetime(normalized.index, errors="coerce")

    normalized = normalized[~normalized.index.isna()]
    normalized.index = pd.DatetimeIndex(normalized.index).tz_localize(None)

    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "adj_close": "Adj Close",
        "adjclose": "Adj Close",
        "adjusted_close": "Adj Close",
    }
    for key, target in rename_map.items():
        source = lower_to_original.get(key)
        if source and target not in normalized.columns:
            normalized[target] = normalized[source]

    missing = [column for column in OHLCV_COLUMNS if column not in normalized.columns]
    if missing:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    for column in OHLCV_COLUMNS + OPTIONAL_OHLCV_COLUMNS:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    columns = OHLCV_COLUMNS + [column for column in OPTIONAL_OHLCV_COLUMNS if column in normalized.columns]
    normalized = normalized[columns].dropna(subset=OHLCV_COLUMNS).sort_index()
    return normalized


class OpenBBHistoricalProvider:
    provider_name = "openbb"

    def __init__(
        self,
        api_url: Optional[str] = None,
        provider: Optional[str] = None,
        request_get: Optional[Callable[..., Any]] = None,
        timeout_seconds: float = 45,
    ):
        self.api_url = (api_url or os.getenv("OPENBB_API_URL") or "http://127.0.0.1:6900").rstrip("/")
        self.provider = provider or os.getenv("OPENBB_PRICE_PROVIDER", "yfinance")
        self.request_get = request_get or requests.get
        self.timeout_seconds = timeout_seconds

    def fetch_daily_ohlcv(self, symbol: str, start_date=None, end_date=None) -> ProviderResult:
        endpoint = f"{self.api_url}/api/v1/equity/price/historical"
        params = {"symbol": symbol, "provider": self.provider}
        if start_date:
            params["start_date"] = str(start_date)
        if end_date:
            params["end_date"] = str(end_date)

        try:
            response = self.request_get(endpoint, params=params, timeout=self.timeout_seconds)
            metadata = _response_metadata(response, endpoint, self.provider)
            http_error_type = _classify_openbb_http_response(response)
            if http_error_type:
                return ProviderResult.failure(
                    symbol,
                    self.provider_name,
                    http_error_type,
                    f"OpenBB HTTP response classified as {http_error_type}",
                    raw_metadata=metadata,
                )
            body_text = getattr(response, "text", "") or ""
            has_body_attrs = hasattr(response, "text") or hasattr(response, "content")
            if has_body_attrs and not body_text and not getattr(response, "content", None):
                return ProviderResult.failure(
                    symbol,
                    self.provider_name,
                    ERROR_EMPTY_RESPONSE,
                    "empty OpenBB daily OHLCV response body",
                    raw_metadata=metadata,
                )
            content_type = str(metadata.get("content_type") or "").lower()
            if content_type and "json" not in content_type:
                return ProviderResult.failure(
                    symbol,
                    self.provider_name,
                    ERROR_JSON_PARSE,
                    "OpenBB daily OHLCV response was not JSON",
                    raw_metadata=metadata,
                )
            try:
                payload = response.json()
            except Exception as exc:
                return ProviderResult.failure(
                    symbol,
                    self.provider_name,
                    ERROR_JSON_PARSE,
                    str(exc),
                    raw_metadata=metadata,
                )
            records, schema_error, schema_metadata = _extract_openbb_records(payload)
            if schema_error:
                metadata.update(schema_metadata)
                return ProviderResult.failure(
                    symbol,
                    self.provider_name,
                    schema_error,
                    "OpenBB daily OHLCV response schema mismatch",
                    raw_metadata=metadata,
                )
            df = normalize_ohlcv_frame(pd.DataFrame(records or []))
            if df.empty:
                return ProviderResult.failure(
                    symbol,
                    self.provider_name,
                    ERROR_NO_PRICE_DATA,
                    "empty OpenBB daily OHLCV response",
                    raw_metadata=metadata,
                )
            return ProviderResult.success_result(
                symbol=symbol,
                provider_name=self.provider_name,
                df=df,
                data_mode=DATA_MODE_LIVE,
                raw_metadata=metadata,
            )
        except Exception as exc:
            return ProviderResult.failure(symbol, self.provider_name, classify_provider_error(exc), str(exc))

    def fetch_latest_quote(self, symbol: str) -> ProviderResult:
        endpoint = f"{self.api_url}/api/v1/equity/price/quote"
        params = {"symbol": symbol, "provider": self.provider}
        try:
            response = self.request_get(endpoint, params=params, timeout=self.timeout_seconds)
            metadata = _response_metadata(response, endpoint, self.provider)
            http_error_type = _classify_openbb_http_response(response)
            if http_error_type:
                return ProviderResult.failure(symbol, self.provider_name, http_error_type, f"OpenBB HTTP response classified as {http_error_type}", raw_metadata=metadata)
            body_text = getattr(response, "text", "") or ""
            has_body_attrs = hasattr(response, "text") or hasattr(response, "content")
            if has_body_attrs and not body_text and not getattr(response, "content", None):
                return ProviderResult.failure(symbol, self.provider_name, ERROR_EMPTY_RESPONSE, "empty OpenBB quote response body", raw_metadata=metadata)
            content_type = str(metadata.get("content_type") or "").lower()
            if content_type and "json" not in content_type:
                return ProviderResult.failure(symbol, self.provider_name, ERROR_JSON_PARSE, "OpenBB quote response was not JSON", raw_metadata=metadata)
            try:
                payload = response.json()
            except Exception as exc:
                return ProviderResult.failure(symbol, self.provider_name, ERROR_JSON_PARSE, str(exc), raw_metadata=metadata)
            records, schema_error, schema_metadata = _extract_openbb_records(payload)
            if schema_error:
                metadata.update(schema_metadata)
                return ProviderResult.failure(symbol, self.provider_name, schema_error, "OpenBB quote response schema mismatch", raw_metadata=metadata)
            first = records[0] if isinstance(records, list) and records else records
            quote = None
            if isinstance(first, dict):
                for key in ("price", "last_price", "lastPrice", "close"):
                    if first.get(key) is not None:
                        quote = float(first[key])
                        break
            if quote is None:
                return ProviderResult.failure(symbol, self.provider_name, ERROR_NO_PRICE_DATA, "empty OpenBB quote response", raw_metadata=metadata)
            return ProviderResult.success_result(symbol, self.provider_name, quote=quote, data_mode=DATA_MODE_LIVE, raw_metadata=metadata)
        except Exception as exc:
            return ProviderResult.failure(symbol, self.provider_name, classify_provider_error(exc), str(exc))


class YFinanceProvider:
    provider_name = "yfinance"

    def __init__(self, ticker_factory: Optional[Callable[[str], Any]] = None):
        if ticker_factory is None:
            import yfinance as yf
            ticker_factory = yf.Ticker
        self.ticker_factory = ticker_factory

    def fetch_daily_ohlcv(self, symbol: str, start_date=None, end_date=None) -> ProviderResult:
        try:
            ticker = self.ticker_factory(symbol)
            kwargs = {"period": "1y", "interval": "1d", "auto_adjust": False}
            if start_date or end_date:
                kwargs = {"start": start_date, "end": end_date, "interval": "1d", "auto_adjust": False}
            df = normalize_ohlcv_frame(ticker.history(**kwargs))
            if df.empty:
                return ProviderResult.failure(symbol, self.provider_name, ERROR_NO_PRICE_DATA, "empty yfinance daily OHLCV response")
            info = {}
            try:
                info = ticker.info or {}
            except Exception as exc:
                info = {"info_warning": str(exc)}
            return ProviderResult.success_result(
                symbol=symbol,
                provider_name=self.provider_name,
                df=df,
                info=info,
                data_mode=DATA_MODE_FALLBACK,
            )
        except Exception as exc:
            return ProviderResult.failure(symbol, self.provider_name, classify_provider_error(exc), str(exc))

    def fetch_latest_quote(self, symbol: str) -> ProviderResult:
        try:
            ticker = self.ticker_factory(symbol)
            info = ticker.info or {}
            quote = info.get("regularMarketPrice") or info.get("currentPrice")
            if quote is None:
                df = normalize_ohlcv_frame(ticker.history(period="5d", interval="1d"))
                if not df.empty:
                    quote = float(df["Close"].iloc[-1])
            if quote is None:
                return ProviderResult.failure(symbol, self.provider_name, ERROR_NO_PRICE_DATA, "empty yfinance quote response")
            return ProviderResult.success_result(symbol, self.provider_name, quote=float(quote), info=info, data_mode=DATA_MODE_FALLBACK)
        except Exception as exc:
            return ProviderResult.failure(symbol, self.provider_name, classify_provider_error(exc), str(exc))


class LocalDatabaseProvider:
    provider_name = "market_data"

    def __init__(
        self,
        db_factory: Callable[[], Any],
        today_factory: Callable[[], date] = date.today,
        max_fresh_age_days: int = 3,
    ):
        self.db_factory = db_factory
        self.today_factory = today_factory
        self.max_fresh_age_days = max_fresh_age_days

    def fetch_daily_ohlcv(self, symbol: str, start_date=None, end_date=None) -> ProviderResult:
        try:
            df = self.db_factory().get_market_data(symbol, start_date=start_date, end_date=end_date)
            normalized = normalize_ohlcv_frame(df)
            if normalized.empty:
                return ProviderResult.failure(symbol, self.provider_name, ERROR_NO_PRICE_DATA, "empty local market_data fallback")
            latest_timestamp = pd.to_datetime(normalized.index.max())
            age_days = max(0, (pd.Timestamp(self.today_factory()) - latest_timestamp.normalize()).days)
            mode = DATA_MODE_FALLBACK if age_days <= self.max_fresh_age_days else DATA_MODE_STALE
            return ProviderResult.success_result(
                symbol=symbol,
                provider_name=self.provider_name,
                df=normalized,
                data_mode=mode,
                cache_age_days=age_days,
            )
        except TypeError:
            try:
                df = self.db_factory().get_market_data(symbol)
                normalized = normalize_ohlcv_frame(df)
                if normalized.empty:
                    return ProviderResult.failure(symbol, self.provider_name, ERROR_NO_PRICE_DATA, "empty local market_data fallback")
                latest_timestamp = pd.to_datetime(normalized.index.max())
                age_days = max(0, (pd.Timestamp(self.today_factory()) - latest_timestamp.normalize()).days)
                mode = DATA_MODE_FALLBACK if age_days <= self.max_fresh_age_days else DATA_MODE_STALE
                return ProviderResult.success_result(symbol, self.provider_name, df=normalized, data_mode=mode, cache_age_days=age_days)
            except Exception as exc:
                return ProviderResult.failure(symbol, self.provider_name, classify_provider_error(exc), str(exc))
        except Exception as exc:
            return ProviderResult.failure(symbol, self.provider_name, classify_provider_error(exc), str(exc))

    def fetch_latest_quote(self, symbol: str) -> ProviderResult:
        result = self.fetch_daily_ohlcv(symbol)
        if result.success and result.df is not None and not result.df.empty:
            return ProviderResult.success_result(
                symbol=symbol,
                provider_name=self.provider_name,
                quote=float(result.df["Close"].iloc[-1]),
                data_mode=result.data_mode,
                cache_age_days=result.cache_age_days,
            )
        return result
