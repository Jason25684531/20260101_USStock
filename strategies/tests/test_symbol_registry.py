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
