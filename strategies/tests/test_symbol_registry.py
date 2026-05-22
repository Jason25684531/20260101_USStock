from __future__ import annotations

from sqlalchemy import create_engine, text


def _bootstrap_registry_schema(engine) -> None:
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
            CREATE TABLE universe_memberships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol VARCHAR(20) NOT NULL,
                universe_code VARCHAR(50) NOT NULL,
                membership_type VARCHAR(20) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1
            )
        """))


def test_registry_enrichment_columns_are_added_without_losing_rows():
    from symbol_registry import ensure_registry_enrichment_columns

    engine = create_engine("sqlite+pysqlite:///:memory:")
    _bootstrap_registry_schema(engine)

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO symbols_registry(symbol, asset_type, sector, is_active, is_benchmark)
                VALUES ('AAPL', 'EQUITY', 'Technology', 1, 0)
            """)
        )
        ensure_registry_enrichment_columns(conn)

        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(symbols_registry)")).all()
        }
        row = conn.execute(
            text("SELECT symbol, is_active FROM symbols_registry WHERE symbol = 'AAPL'")
        ).one()

    assert {
        "whale_held_pct",
        "inst_count",
        "institutional_net_buy",
        "sentiment_score",
    }.issubset(columns)
    assert row.symbol == "AAPL"
    assert row.is_active == 1


def test_upsert_symbol_enrichment_sanitizes_partial_payload():
    from symbol_registry import ensure_registry_enrichment_columns, upsert_symbol_enrichment

    engine = create_engine("sqlite+pysqlite:///:memory:")
    _bootstrap_registry_schema(engine)

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO symbols_registry(symbol, asset_type, sector, is_active, is_benchmark)
                VALUES ('NVDA', 'EQUITY', 'Technology', 1, 0)
            """)
        )
        ensure_registry_enrichment_columns(conn)
        upsert_symbol_enrichment(
            conn,
            "NVDA",
            {
                "whale_held_pct": "nan",
                "inst_count": "42",
                "institutional_net_buy": "-1234.7",
                "sentiment_score": "3.5",
            },
        )
        row = conn.execute(
            text("""
                SELECT whale_held_pct, inst_count, institutional_net_buy, sentiment_score
                FROM symbols_registry
                WHERE symbol = 'NVDA'
            """)
        ).one()

    assert row.whale_held_pct is None
    assert row.inst_count == 42
    assert row.institutional_net_buy == -1234.7
    assert row.sentiment_score == 1.0


def test_load_active_symbols_prefers_registry_entries():
    from symbol_registry import load_active_symbols

    engine = create_engine("sqlite+pysqlite:///:memory:")
    _bootstrap_registry_schema(engine)

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO symbols_registry(symbol, asset_type, sector, is_active, is_benchmark)
                VALUES
                ('AAPL', 'EQUITY', 'Technology', 1, 0),
                ('MSFT', 'EQUITY', 'Technology', 1, 0),
                ('SPY', 'ETF', 'ETF', 1, 1),
                ('TSLA', 'EQUITY', 'Consumer Cyclical', 0, 0)
            """)
        )

    symbols = load_active_symbols(engine)

    assert symbols == ["AAPL", "MSFT"]


def test_load_active_symbols_falls_back_when_registry_missing():
    from symbol_registry import load_active_symbols

    engine = create_engine("sqlite+pysqlite:///:memory:")

    symbols = load_active_symbols(engine, fallback_symbols=["NVDA", "SPY"])

    assert symbols == ["NVDA", "SPY"]
