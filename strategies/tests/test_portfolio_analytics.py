from __future__ import annotations

import pandas as pd


def test_correlation_engine_returns_empty_state_for_single_holding():
    from analytics.correlation_engine import build_correlation_payload

    price_history = {
        "AAPL": pd.DataFrame(
            {"close": [100, 101, 102]},
            index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
        )
    }

    payload = build_correlation_payload(["AAPL"], price_history, window_days=60)

    assert payload["symbols"] == []
    assert payload["matrix"] == []
    assert "至少需要 2 檔" in payload["reason"]


def test_correlation_engine_builds_matrix_for_multiple_holdings():
    from analytics.correlation_engine import build_correlation_payload

    dates = pd.bdate_range("2026-01-01", periods=25)
    price_history = {
        "AAPL": pd.DataFrame({"close": range(100, 125)}, index=dates),
        "MSFT": pd.DataFrame({"close": range(200, 225)}, index=dates),
    }

    payload = build_correlation_payload(["AAPL", "MSFT"], price_history, window_days=60)

    assert payload["symbols"] == ["AAPL", "MSFT"]
    assert len(payload["matrix"]) == 2
    assert len(payload["matrix"][0]) == 2
    assert payload["reason"] == ""
