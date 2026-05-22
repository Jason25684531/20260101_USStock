#!/usr/bin/env python3
"""
Train the strategy model from the local database only.

The training path is deliberately offline: after ingestion has populated
`market_data` and `symbols_registry`, this script does not import or call live
market data providers.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


PROJECT_ROOT = Path(__file__).parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "strategies" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from adapters.database import DatabaseAdapter
from ml import features as features_module
from ml.features import make_features, prepare_train_test_split
from ml.model import StrategyModel


ENRICHMENT_COLUMNS = [
    "whale_held_pct",
    "inst_count",
    "sentiment_score",
    "institutional_net_buy",
]


def _engine_from(db_or_engine: Any | None) -> tuple[Engine, DatabaseAdapter | None]:
    if db_or_engine is None:
        adapter = DatabaseAdapter()
        return adapter.engine, adapter
    if isinstance(db_or_engine, DatabaseAdapter):
        return db_or_engine.engine, None
    if hasattr(db_or_engine, "engine"):
        return db_or_engine.engine, None
    return db_or_engine, None


def _column_names(engine: Engine, table_name: str) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _select_or_null(columns: set[str], column_name: str, alias: str | None = None) -> str:
    target = alias or column_name
    if column_name in columns:
        return f"r.{column_name} AS {target}"
    return f"CAST(NULL AS FLOAT) AS {target}"


def load_training_matrix_from_local_db(
    db_or_engine: Any | None = None,
    lookback_years: int = 5,
) -> pd.DataFrame:
    """Load the active-symbol training matrix from local SQL storage."""
    engine, owned_adapter = _engine_from(db_or_engine)
    start_date = (datetime.now() - timedelta(days=365 * lookback_years)).date().isoformat()

    try:
        market_columns = _column_names(engine, "market_data")
        registry_columns = _column_names(engine, "symbols_registry")
        if not market_columns or not registry_columns:
            raise RuntimeError(
                "Local market_data or symbols_registry table is missing; "
                "run the ingestion workflow before training."
            )

        market_symbol_col = "symbol" if "symbol" in market_columns else "ticker"
        market_date_col = "timestamp" if "timestamp" in market_columns else "date"
        registry_symbol_col = "symbol" if "symbol" in registry_columns else "ticker"
        active_clause = "COALESCE(r.is_active, 0) = 1" if "is_active" in registry_columns else "1 = 1"

        select_enrichment = ",\n                ".join(
            _select_or_null(registry_columns, column)
            for column in ENRICHMENT_COLUMNS
        )
        query = text(f"""
            SELECT
                m.{market_symbol_col} AS symbol,
                m.{market_date_col} AS date,
                m.open AS open,
                m.high AS high,
                m.low AS low,
                m.close AS close,
                m.volume AS volume,
                {select_enrichment}
            FROM market_data m
            INNER JOIN symbols_registry r
                ON m.{market_symbol_col} = r.{registry_symbol_col}
            WHERE m.{market_date_col} >= :start_date
              AND {active_clause}
            ORDER BY m.{market_symbol_col} ASC, m.{market_date_col} ASC
        """)
        df = pd.read_sql(query, engine, params={"start_date": start_date})
    finally:
        if owned_adapter is not None:
            owned_adapter.close()

    if df.empty:
        raise RuntimeError(
            "Local market_data returned no active training rows. "
            "Run the upgraded ingestion workflow before training."
        )

    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["date"] = pd.to_datetime(df["date"])
    for column in ["open", "high", "low", "close", "volume", *ENRICHMENT_COLUMNS]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    print(f"Loaded {len(df)} local DB training rows across {df['symbol'].nunique()} symbols.")
    return df


def _to_price_frame(symbol_frame: pd.DataFrame) -> pd.DataFrame:
    price_frame = symbol_frame.copy().sort_values("date")
    price_frame = price_frame.set_index("date")
    price_frame.index = pd.to_datetime(price_frame.index).tz_localize(None)
    price_frame = price_frame.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    return price_frame


def build_offline_feature_matrix(
    training_matrix: pd.DataFrame,
    min_history_rows: int = 300,
) -> pd.DataFrame:
    """Build per-symbol features without any external provider calls."""
    if training_matrix.empty:
        raise RuntimeError("Local training matrix is empty; run ingestion before training.")

    all_features: list[pd.DataFrame] = []
    original_spy_loader = features_module._fetch_spy_close
    features_module._fetch_spy_close = lambda index: None
    try:
        for symbol, symbol_frame in training_matrix.groupby("symbol", sort=True):
            if len(symbol_frame) < min_history_rows:
                print(f"Skipping {symbol}: only {len(symbol_frame)} local rows")
                continue

            price_frame = _to_price_frame(symbol_frame)
            features = make_features(price_frame)
            if features.empty:
                print(f"Skipping {symbol}: feature extraction returned no rows")
                continue
            features["symbol"] = symbol
            all_features.append(features)
            print(f"{symbol}: built {len(features)} offline feature rows")
    finally:
        features_module._fetch_spy_close = original_spy_loader

    if not all_features:
        raise RuntimeError(
            "No usable feature rows were generated from local market_data. "
            "Check that each active symbol has enough history."
        )

    df_all = pd.concat(all_features, axis=0).sort_index()
    print(f"Built {len(df_all)} total offline feature rows.")
    return df_all


def train_model_from_features(df_all: pd.DataFrame) -> StrategyModel:
    df_all = df_all.copy()
    df_all.replace([np.inf, -np.inf], np.nan, inplace=True)

    X_train, y_train, X_test, y_test = prepare_train_test_split(
        df_all,
        train_end_date="2024-12-31",
        test_start_date="2025-01-01",
    )

    model = StrategyModel(
        model_type="xgboost",
        n_estimators=300,
        max_depth=3,
        learning_rate=0.01,
        random_state=42,
        reg_lambda=5.0,
        gamma=0.1,
    )
    model.train(X_train, y_train, X_test, y_test)
    model.save()
    return model


def main() -> int:
    print("Local DB-driven ML model training")
    try:
        matrix = load_training_matrix_from_local_db()
        features = build_offline_feature_matrix(matrix)
        model = train_model_from_features(features)
        print(model.generate_report())
        print("Training complete: data/model.pkl updated.")
        return 0
    except Exception as exc:
        print(f"Training failed: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
