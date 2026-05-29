from types import SimpleNamespace

import pandas as pd

from adapters.market_data_provider import DATA_MODE_FALLBACK, DATA_MODE_LIVE, ProviderResult
from scripts.smoke_live_provider_chain import build_smoke_report, render_smoke_report, run_provider_chain_smoke


def _price_frame(days=80, close=100.0):
    index = pd.date_range(end=pd.Timestamp("2026-05-28"), periods=days, freq="D")
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


class FakeScreener:
    def __init__(self, symbols, use_ml=False):
        self.symbols = symbols
        self.use_ml = use_ml
        self._results = {
            "AAPL": ProviderResult.failure("AAPL", "openbb", "json_parse_error", "html"),
            "MSFT": ProviderResult.success_result("MSFT", "yfinance", df=_price_frame(), data_mode=DATA_MODE_FALLBACK),
            "NVDA": ProviderResult.success_result("NVDA", "openbb", df=_price_frame(), data_mode=DATA_MODE_LIVE),
        }

    def fetch_stock_data_result(self, symbol):
        result = self._results[symbol]
        if result.success:
            return SimpleNamespace(
                symbol=symbol,
                provider=result.provider_name,
                status="live_success" if result.data_mode == DATA_MODE_LIVE else "fallback_success",
                data_mode=result.data_mode,
                df=result.df,
                used_fallback=result.data_mode == DATA_MODE_FALLBACK,
                provider_attempts=[{"provider": result.provider_name, "success": True, "data_mode": result.data_mode}],
                skip_reason=None,
            )
        return SimpleNamespace(
            symbol=symbol,
            provider=result.provider_name,
            status=result.error_type,
            data_mode="failed",
            df=None,
            used_fallback=False,
            provider_attempts=[{"provider": result.provider_name, "success": False, "error_type": result.error_type}],
            skip_reason="provider_data_unavailable",
        )


def test_run_provider_chain_smoke_uses_screener_fetch_path_without_writes():
    report = run_provider_chain_smoke(
        ["AAPL", "MSFT", "NVDA"],
        days=90,
        screener_factory=FakeScreener,
    )

    assert report["symbols_requested"] == 3
    assert report["coverage"] == 2 / 3
    assert report["effective_provider"] == "openbb"
    assert report["fallback_attempts"][0]["provider"] == "yfinance"
    assert report["top_error_types"] == {"json_parse_error": 1}
    assert report["skip_reasons"] == {"provider_data_unavailable": 1}
    assert report["recommendations_written"] is False
    assert "fallback" in report["next_operator_action"].lower()


def test_render_smoke_report_contains_operator_fields():
    report = build_smoke_report(
        symbols=["AAPL"],
        results=[
            SimpleNamespace(
                symbol="AAPL",
                provider="openbb",
                status="json_parse_error",
                data_mode="failed",
                df=None,
                used_fallback=False,
                provider_attempts=[{"provider": "openbb", "success": False, "error_type": "json_parse_error"}],
                skip_reason="provider_data_unavailable",
            )
        ],
    )

    text = render_smoke_report(report)

    assert "provider attempts" in text.lower()
    assert "fallback attempts" in text.lower()
    assert "coverage" in text.lower()
    assert "effective provider" in text.lower()
    assert "top error types" in text.lower()
    assert "next operator action" in text.lower()
