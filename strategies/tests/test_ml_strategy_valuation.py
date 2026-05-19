from __future__ import annotations

import importlib
import sys
import types

import pandas as pd
import sqlalchemy


def test_evaluate_symbol_uses_growth_aware_policy_for_high_growth(monkeypatch):
    fake_agents = types.ModuleType("agents")

    class DummySentimentAgent:
        def analyze_sentiment(self, symbol: str) -> dict:
            return {"score": 0.5, "reason": "stub"}

    fake_agents.SentimentAgent = DummySentimentAgent
    monkeypatch.setitem(sys.modules, "agents", fake_agents)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: object())

    ml_strategy = importlib.import_module("strategies.ml_strategy")

    raw_df = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "open": [114.0],
            "high": [116.0],
            "low": [113.5],
            "close": [115.0],
            "volume": [1_000_000],
        }
    )
    features_df = pd.DataFrame({"close": [115.0]}, index=pd.to_datetime(["2024-01-02"]))

    monkeypatch.setattr(ml_strategy, "load_data_from_db", lambda symbol: raw_df.copy())
    monkeypatch.setattr(ml_strategy, "calculate_v30_features", lambda df: features_df.copy())
    monkeypatch.setattr(ml_strategy, "run_xgboost_inference", lambda features_df, symbol: 0.91)
    monkeypatch.setattr(
        ml_strategy,
        "calculate_position_size",
        lambda total_equity, is_bear_market: {"max_position_value": 10_000.0, "allocation_pct": 0.1},
    )

    result = ml_strategy.evaluate_symbol(
        "NVDA",
        fundamentals_lookup={
            "NVDA": {
                "pe_ratio": 23.0,
                "forward_pe": 22.0,
                "revenue_growth_yoy": 0.6,
            }
        },
        market_regime="BULL_MARKET",
    )

    assert result is not None
    assert result["valuation_status"] == "PREMIUM_GROWTH"
    assert result["fair_price"] == 101.25
    assert result["buy_price"] == 91.125
    assert result["sell_price"] == 121.5
