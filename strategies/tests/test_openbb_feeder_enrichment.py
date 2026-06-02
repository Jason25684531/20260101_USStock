from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


def _load_feeder_module():
    feeder_path = Path(__file__).resolve().parents[1] / "scripts" / "openbb_feeder.py"
    spec = importlib.util.spec_from_file_location("openbb_feeder_under_test", feeder_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bootstrap_registry(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE symbols_registry (
                symbol VARCHAR(20) PRIMARY KEY,
                asset_type VARCHAR(20),
                sector VARCHAR(100),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                is_benchmark BOOLEAN NOT NULL DEFAULT 0
            )
        """))
        conn.execute(text("""
            INSERT INTO symbols_registry(symbol, asset_type, sector, is_active, is_benchmark)
            VALUES ('MSFT', 'EQUITY', 'Technology', 1, 0)
        """))


def test_feeder_builds_registry_enrichment_from_partial_holder_and_news_data():
    feeder = _load_feeder_module()
    snapshot = {
        "institution_holders_count": "27",
        "institution_avg_pct_change": "2.5",
        "mutualfund_avg_pct_change": "-0.5",
    }
    news_df = pd.DataFrame(
        {
            "title": ["MSFT beats expectations", "MSFT faces risk"],
            "summary": ["upgrade growth profit", "supply risk"],
        }
    )

    enrichment = feeder.build_registry_enrichment(snapshot, news_df)

    assert enrichment["inst_count"] == 27
    assert enrichment["institutional_net_buy"] == 2.0
    assert 0 < enrichment["sentiment_score"] <= 1.0
    assert enrichment["whale_held_pct"] is None


def test_feeder_registry_upsert_survives_invalid_sentiment_values():
    feeder = _load_feeder_module()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _bootstrap_registry(engine)

    with engine.begin() as conn:
        feeder.upsert_registry_enrichment(
            conn,
            "MSFT",
            {
                "whale_held_pct": float("inf"),
                "inst_count": "9.9",
                "institutional_net_buy": "bad",
                "sentiment_score": float("-inf"),
            },
        )
        row = conn.execute(
            text("""
                SELECT whale_held_pct, inst_count, institutional_net_buy, sentiment_score
                FROM symbols_registry
                WHERE symbol = 'MSFT'
            """)
        ).one()

    assert row.whale_held_pct is None
    assert row.inst_count == 10
    assert row.institutional_net_buy is None
    assert row.sentiment_score == 0.0
