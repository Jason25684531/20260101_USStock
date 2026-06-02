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


def test_institutional_sentiment_features_normalize_high_whale_concentration():
    from ml.features import extract_institutional_and_sentiment_features

    features = extract_institutional_and_sentiment_features(
        {
            "whale_held_pct": 72.5,
            "inst_count": 1500,
            "institutional_net_buy": 25.0,
            "sentiment_score": 1.8,
        }
    )

    assert features["whale_concentration"] == 0.725
    assert 0.0 < features["inst_trust_score"] <= 1.0
    assert features["institutional_net_buy_score"] == 0.25
    assert features["inst_net_intensity"] == 0.25
    assert features["news_sentiment"] == 1.0


def test_institutional_sentiment_features_use_neutral_defaults():
    from ml.features import extract_institutional_and_sentiment_features

    features = extract_institutional_and_sentiment_features({})

    assert features == {
        "whale_concentration": 0.0,
        "inst_trust_score": 0.0,
        "institutional_net_buy_score": 0.0,
        "inst_net_intensity": 0.0,
        "news_sentiment": 0.0,
    }


def test_calculate_v30_features_carries_enriched_columns(monkeypatch):
    fake_agents = types.ModuleType("agents")

    class DummySentimentAgent:
        def analyze_sentiment(self, symbol: str) -> dict:
            return {"score": 0.0, "reason": "stub"}

    fake_agents.SentimentAgent = DummySentimentAgent
    monkeypatch.setitem(sys.modules, "agents", fake_agents)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: object())

    ml_strategy = importlib.import_module("strategies.ml_strategy")
    dates = pd.date_range("2024-01-01", periods=260, freq="D")
    price_df = pd.DataFrame(
        {
            "date": dates,
            "open": range(100, 360),
            "high": range(101, 361),
            "low": range(99, 359),
            "close": range(100, 360),
            "volume": [1_000_000 + index for index in range(260)],
            "whale_held_pct": 72.0,
            "inst_count": 1200,
            "institutional_net_buy": 15.0,
            "sentiment_score": -1.4,
        }
    ).set_index("date")

    monkeypatch.setattr(ml_strategy, "_get_spy_close", lambda index: None)
    features_df = ml_strategy.calculate_v30_features(price_df)

    latest = features_df.iloc[-1]
    assert latest["whale_concentration"] == 0.72
    assert latest["inst_trust_score"] > 0
    assert latest["institutional_net_buy_score"] == 0.15
    assert latest["inst_net_intensity"] == 0.15
    assert latest["news_sentiment"] == -1.0


def test_save_daily_screener_results_persists_enrichment_snapshots(monkeypatch):
    fake_agents = types.ModuleType("agents")

    class DummySentimentAgent:
        def analyze_sentiment(self, symbol: str) -> dict:
            return {"score": 0.0, "reason": "stub"}

    fake_agents.SentimentAgent = DummySentimentAgent
    monkeypatch.setitem(sys.modules, "agents", fake_agents)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: object())

    ml_strategy = importlib.import_module("strategies.ml_strategy")
    executed = []

    class FakeConnection:
        def execute(self, statement, params=None):
            executed.append((str(statement), params))

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(ml_strategy, "ENGINE", FakeEngine())

    count = ml_strategy.save_daily_screener_results(
        pd.DataFrame(
            [
                {
                    "symbol": "NVDA",
                    "latest_date": "2026-05-19",
                    "latest_close": 125.0,
                    "xgboost_score": 0.91,
                    "valuation_status": "PREMIUM_GROWTH",
                    "buy_price": 110.0,
                    "sell_price": 150.0,
                    "suggested_allocation_pct": 10.0,
                    "market_regime": "BULL_MARKET",
                    "pe_ratio": 25.0,
                    "whale_held_pct": 72.0,
                    "inst_count": 1200,
                    "institutional_net_buy": 15.0,
                    "sentiment_score": 0.4,
                }
            ]
        )
    )

    insert_params = [params for _, params in executed if params and params.get("symbol") == "NVDA"][0]
    assert count == 1
    assert insert_params["whale_held_pct"] == 72.0
    assert insert_params["inst_count"] == 1200
    assert insert_params["institutional_net_buy"] == 15.0
    assert insert_params["sentiment_score"] == 0.4
