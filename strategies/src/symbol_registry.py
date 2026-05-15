from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import create_engine, inspect, text

try:
    from strategies.src.config import DB_URI, DEFAULT_SYMBOLS
except ImportError:
    from config import DB_URI, DEFAULT_SYMBOLS


DEFAULT_BENCHMARK_SYMBOLS = ("SPY", "QQQ", "IWM")


def normalize_symbol(symbol: str | None) -> str:
    value = str(symbol or "").strip().upper().replace(".", "-")
    return value


def dedupe_symbols(symbols: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _has_registry_tables(bind) -> bool:
    inspector = inspect(bind)
    return inspector.has_table("symbols_registry") and inspector.has_table("universe_memberships")


def _fallback_symbols(fallback_symbols: Iterable[str] | None) -> list[str]:
    source = fallback_symbols if fallback_symbols is not None else DEFAULT_SYMBOLS
    return dedupe_symbols(source)


def load_active_symbols(
    bind,
    fallback_symbols: Iterable[str] | None = None,
    include_benchmarks: bool = False,
) -> list[str]:
    fallback = _fallback_symbols(fallback_symbols)
    if bind is None or not _has_registry_tables(bind):
        return fallback

    benchmark_clause = "" if include_benchmarks else "AND COALESCE(is_benchmark, 0) = 0"
    query = text(f"""
        SELECT symbol
        FROM symbols_registry
        WHERE COALESCE(is_active, 0) = 1
          {benchmark_clause}
        ORDER BY COALESCE(is_benchmark, 0) ASC, symbol ASC
    """)

    with bind.connect() as conn:
        rows = conn.execute(query).scalars().all()

    symbols = dedupe_symbols(rows)
    return symbols or fallback


def load_default_active_symbols(
    fallback_symbols: Iterable[str] | None = None,
    include_benchmarks: bool = False,
) -> list[str]:
    try:
        engine = create_engine(DB_URI)
    except Exception:
        return _fallback_symbols(fallback_symbols)

    try:
        return load_active_symbols(
            engine,
            fallback_symbols=fallback_symbols,
            include_benchmarks=include_benchmarks,
        )
    except Exception:
        return _fallback_symbols(fallback_symbols)
    finally:
        engine.dispose()


def upsert_symbol(
    conn,
    symbol: str,
    asset_type: str = "EQUITY",
    sector: str | None = None,
    is_active: bool = True,
    is_benchmark: bool = False,
) -> None:
    symbol = normalize_symbol(symbol)
    existing = conn.execute(
        text("SELECT symbol FROM symbols_registry WHERE symbol = :symbol"),
        {"symbol": symbol},
    ).scalar()

    params = {
        "symbol": symbol,
        "asset_type": asset_type,
        "sector": sector,
        "is_active": 1 if is_active else 0,
        "is_benchmark": 1 if is_benchmark else 0,
    }
    if existing:
        conn.execute(
            text("""
                UPDATE symbols_registry
                SET asset_type = :asset_type,
                    sector = COALESCE(:sector, sector),
                    is_active = :is_active,
                    is_benchmark = :is_benchmark,
                    updated_at = CURRENT_TIMESTAMP
                WHERE symbol = :symbol
            """),
            params,
        )
    else:
        conn.execute(
            text("""
                INSERT INTO symbols_registry(symbol, asset_type, sector, is_active, is_benchmark)
                VALUES (:symbol, :asset_type, :sector, :is_active, :is_benchmark)
            """),
            params,
        )


def upsert_membership(
    conn,
    symbol: str,
    universe_code: str,
    membership_type: str,
    is_active: bool = True,
) -> None:
    symbol = normalize_symbol(symbol)
    existing = conn.execute(
        text("""
            SELECT id
            FROM universe_memberships
            WHERE symbol = :symbol
              AND universe_code = :universe_code
              AND membership_type = :membership_type
        """),
        {
            "symbol": symbol,
            "universe_code": universe_code,
            "membership_type": membership_type,
        },
    ).scalar()

    params = {
        "symbol": symbol,
        "universe_code": universe_code,
        "membership_type": membership_type,
        "is_active": 1 if is_active else 0,
    }
    if existing:
        conn.execute(
            text("""
                UPDATE universe_memberships
                SET is_active = :is_active,
                    last_seen_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {**params, "id": existing},
        )
    else:
        conn.execute(
            text("""
                INSERT INTO universe_memberships(symbol, universe_code, membership_type, is_active)
                VALUES (:symbol, :universe_code, :membership_type, :is_active)
            """),
            params,
        )


def seed_benchmark_memberships(conn, symbols: Iterable[str] = DEFAULT_BENCHMARK_SYMBOLS) -> None:
    for symbol in dedupe_symbols(symbols):
        upsert_symbol(conn, symbol, asset_type="ETF", sector="ETF", is_active=True, is_benchmark=True)
        upsert_membership(conn, symbol, "CORE_BENCHMARK", "benchmark", is_active=True)


def deactivate_missing_memberships(conn, universe_code: str, active_symbols: Iterable[str]) -> None:
    active_list = dedupe_symbols(active_symbols)
    params = {"universe_code": universe_code}
    if active_list:
        placeholders = ", ".join(f":s{index}" for index, _ in enumerate(active_list))
        params.update({f"s{index}": symbol for index, symbol in enumerate(active_list)})
        conn.execute(
            text(f"""
                UPDATE universe_memberships
                SET is_active = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE universe_code = :universe_code
                  AND symbol NOT IN ({placeholders})
            """),
            params,
        )
    else:
        conn.execute(
            text("""
                UPDATE universe_memberships
                SET is_active = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE universe_code = :universe_code
            """),
            params,
        )


def refresh_registry_activity(conn) -> None:
    conn.execute(text("""
        UPDATE symbols_registry sr
        SET is_active = CASE
            WHEN COALESCE(sr.is_benchmark, 0) = 1 THEN 1
            WHEN EXISTS (
                SELECT 1
                FROM universe_memberships um
                WHERE um.symbol = sr.symbol
                  AND COALESCE(um.is_active, 0) = 1
            ) THEN 1
            ELSE 0
        END,
        updated_at = CURRENT_TIMESTAMP
    """))
