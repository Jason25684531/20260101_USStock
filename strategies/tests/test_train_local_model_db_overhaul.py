from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


def _load_train_module(monkeypatch=None, block_yfinance: bool = False):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "train_local_model.py"
    spec = importlib.util.spec_from_file_location("train_local_model_under_test", script_path)
    assert spec and spec.loader

    if monkeypatch is not None and block_yfinance:
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "yfinance" or name.startswith("yfinance."):
                raise AssertionError("train_local_model.py must not import yfinance")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bootstrap_training_db(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE symbols_registry (
                symbol VARCHAR(20) PRIMARY KEY,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                is_benchmark BOOLEAN NOT NULL DEFAULT 0,
                whale_held_pct DECIMAL(10,4),
                inst_count INTEGER,
                institutional_net_buy DECIMAL(18,4),
                sentiment_score DECIMAL(8,4)
            )
        """))
        conn.execute(text("""
            CREATE TABLE market_data (
                symbol VARCHAR(20) NOT NULL,
                timestamp DATETIME NOT NULL,
                open FLOAT,
                high FLOAT,
                low FLOAT,
                close FLOAT,
                volume FLOAT,
                adj_close FLOAT
            )
        """))
        conn.execute(text("""
            INSERT INTO symbols_registry(
                symbol, is_active, is_benchmark, whale_held_pct, inst_count,
                institutional_net_buy, sentiment_score
            )
            VALUES
                ('AAPL', 1, 0, 72.5, 1500, 25.0, 0.6),
                ('TSLA', 0, 0, 12.0, 20, -5.0, -0.1)
        """))
        conn.execute(text("""
            INSERT INTO market_data(symbol, timestamp, open, high, low, close, volume, adj_close)
            VALUES
                ('AAPL', '2024-01-02', 100, 102, 99, 101, 1000000, 101),
                ('AAPL', '2024-01-03', 101, 103, 100, 102, 1000001, 102),
                ('TSLA', '2024-01-02', 200, 202, 199, 201, 2000000, 201)
        """))


def test_training_module_imports_without_yfinance_and_loads_local_sql(monkeypatch):
    train_local_model = _load_train_module(monkeypatch, block_yfinance=True)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _bootstrap_training_db(engine)

    df = train_local_model.load_training_matrix_from_local_db(engine)

    assert list(df["symbol"].unique()) == ["AAPL"]
    assert {
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "whale_held_pct",
        "inst_count",
        "sentiment_score",
        "institutional_net_buy",
    }.issubset(df.columns)


def test_training_matrix_empty_raises_actionable_error(monkeypatch):
    train_local_model = _load_train_module(monkeypatch, block_yfinance=True)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE symbols_registry (
                symbol VARCHAR(20) PRIMARY KEY,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                is_benchmark BOOLEAN NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE market_data (
                symbol VARCHAR(20) NOT NULL,
                timestamp DATETIME NOT NULL,
                open FLOAT,
                high FLOAT,
                low FLOAT,
                close FLOAT,
                volume FLOAT
            )
        """))

    try:
        train_local_model.load_training_matrix_from_local_db(engine)
    except RuntimeError as exc:
        assert "market_data" in str(exc)
        assert "ingestion" in str(exc).lower()
    else:
        raise AssertionError("expected empty local training matrix to fail")


def test_build_offline_feature_matrix_preserves_enrichment_features(monkeypatch):
    train_local_model = _load_train_module(monkeypatch, block_yfinance=True)
    dates = pd.date_range("2024-01-01", periods=260, freq="D")
    matrix = pd.DataFrame(
        {
            "symbol": ["AAPL"] * len(dates),
            "date": dates,
            "open": range(100, 360),
            "high": range(101, 361),
            "low": range(99, 359),
            "close": range(100, 360),
            "volume": [1_000_000 + index for index in range(len(dates))],
            "whale_held_pct": [72.5] * len(dates),
            "inst_count": [1500] * len(dates),
            "institutional_net_buy": [25.0] * len(dates),
            "sentiment_score": [1.8] * len(dates),
        }
    )

    features = train_local_model.build_offline_feature_matrix(matrix, min_history_rows=200)
    latest = features.iloc[-1]

    assert latest["whale_concentration"] == 0.725
    assert 0.0 < latest["inst_trust_score"] <= 1.0
    assert latest["news_sentiment"] == 1.0
    assert latest["institutional_net_buy_score"] == 0.25
    assert latest["inst_net_intensity"] == 0.25


def test_train_model_from_features_replaces_inf_before_training(monkeypatch):
    train_local_model = _load_train_module(monkeypatch, block_yfinance=False)

    X_train = pd.DataFrame({"feature_a": [1.0, np.nan], "feature_b": [2.0, 3.0]})
    y_train = pd.Series([0, 1])
    X_test = pd.DataFrame({"feature_a": [np.nan], "feature_b": [4.0]})
    y_test = pd.Series([1])

    def fake_prepare_train_test_split(df_all, train_end_date, test_start_date):
        assert not np.isinf(df_all.to_numpy(dtype=float)).any()
        assert pd.isna(df_all.iloc[0]["feature_a"])
        assert pd.isna(df_all.iloc[1]["feature_b"])
        return X_train, y_train, X_test, y_test

    monkeypatch.setattr(train_local_model, "prepare_train_test_split", fake_prepare_train_test_split)

    class FakeStrategyModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def train(self, X_train_arg, y_train_arg, X_test_arg, y_test_arg):
            assert not np.isinf(X_train_arg.to_numpy(dtype=float)).any()
            assert not np.isinf(X_test_arg.to_numpy(dtype=float)).any()
            assert pd.isna(X_train_arg.iloc[1, 0])
            assert pd.isna(X_test_arg.iloc[0, 0])
            return {}

        def save(self):
            return None

    monkeypatch.setattr(train_local_model, "StrategyModel", FakeStrategyModel)

    model = train_local_model.train_model_from_features(
        pd.DataFrame(
            {
                "feature_a": [np.inf, 5.0],
                "feature_b": [1.0, -np.inf],
                "Target": [0, 1],
            }
        )
    )

    assert isinstance(model, FakeStrategyModel)


def test_train_model_from_features_includes_enrichment_features_in_x_train(monkeypatch):
    train_local_model = _load_train_module(monkeypatch, block_yfinance=False)
    dates = pd.date_range("2024-01-01", periods=420, freq="D")
    matrix = pd.DataFrame(
        {
            "symbol": ["AAPL"] * len(dates),
            "date": dates,
            "open": range(100, 520),
            "high": range(101, 521),
            "low": range(99, 519),
            "close": range(100, 520),
            "volume": [1_000_000 + index for index in range(len(dates))],
            "whale_held_pct": [72.5] * len(dates),
            "inst_count": [1500] * len(dates),
            "institutional_net_buy": [25.0] * len(dates),
            "sentiment_score": [0.6] * len(dates),
        }
    )
    features = train_local_model.build_offline_feature_matrix(matrix, min_history_rows=200)

    required_columns = {
        "whale_concentration",
        "inst_trust_score",
        "news_sentiment",
        "inst_net_intensity",
    }

    class FakeStrategyModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def train(self, X_train_arg, y_train_arg, X_test_arg, y_test_arg):
            assert required_columns.issubset(set(X_train_arg.columns))
            assert len(X_train_arg.columns) > 30
            return {}

        def save(self):
            return None

    monkeypatch.setattr(train_local_model, "StrategyModel", FakeStrategyModel)

    model = train_local_model.train_model_from_features(features)

    assert isinstance(model, FakeStrategyModel)
