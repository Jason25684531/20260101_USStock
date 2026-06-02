from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import create_engine, inspect, text

try:
    from strategies.src.config import DB_URI, DEFAULT_SYMBOLS
except ImportError:
    from config import DB_URI, DEFAULT_SYMBOLS


DEFAULT_BENCHMARK_SYMBOLS = ("SPY", "QQQ", "IWM")
REGISTRY_ENRICHMENT_COLUMNS = {
    "whale_held_pct": "DECIMAL(10,4) NULL",
    "inst_count": "INT NULL",
    "institutional_net_buy": "DECIMAL(18,4) NULL",
    "sentiment_score": "DECIMAL(8,4) NULL",
}


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


def _safe_float(value, *, default=None):
    try:
        if value is None:
            return default
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return default
    return numeric


def _sanitize_enrichment_payload(payload: dict | None) -> dict:
    payload = payload or {}

    whale_held_pct = _safe_float(payload.get("whale_held_pct"))
    if whale_held_pct is not None:
        if whale_held_pct < 0:
            whale_held_pct = None
        elif whale_held_pct <= 1:
            whale_held_pct *= 100
        whale_held_pct = round(whale_held_pct, 4) if whale_held_pct is not None else None

    inst_count_value = _safe_float(payload.get("inst_count"))
    inst_count = None
    if inst_count_value is not None and inst_count_value >= 0:
        inst_count = int(round(inst_count_value))

    institutional_net_buy = _safe_float(payload.get("institutional_net_buy"))
    if institutional_net_buy is not None:
        institutional_net_buy = round(institutional_net_buy, 4)

    sentiment_score = _safe_float(payload.get("sentiment_score"), default=0.0)
    sentiment_score = min(1.0, max(-1.0, sentiment_score))

    return {
        "whale_held_pct": whale_held_pct,
        "inst_count": inst_count,
        "institutional_net_buy": institutional_net_buy,
        "sentiment_score": round(sentiment_score, 4),
    }


def _has_registry_tables(bind) -> bool:
    inspector = inspect(bind)
    return inspector.has_table("symbols_registry") and inspector.has_table("universe_memberships")


def ensure_registry_enrichment_columns(conn) -> None:
    inspector = inspect(conn)
    if not inspector.has_table("symbols_registry"):
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("symbols_registry")
    }
    for column_name, definition_sql in REGISTRY_ENRICHMENT_COLUMNS.items():
        if column_name in existing_columns:
            continue
        conn.execute(text(f"ALTER TABLE symbols_registry ADD COLUMN {column_name} {definition_sql}"))
        existing_columns.add(column_name)


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


def upsert_symbol_enrichment(conn, symbol: str, payload: dict | None) -> None:
    symbol = normalize_symbol(symbol)
    if not symbol:
        return

    ensure_registry_enrichment_columns(conn)
    sanitized = _sanitize_enrichment_payload(payload)
    existing = conn.execute(
        text("SELECT symbol FROM symbols_registry WHERE symbol = :symbol"),
        {"symbol": symbol},
    ).scalar()

    inspector = inspect(conn)
    columns = {column["name"] for column in inspector.get_columns("symbols_registry")}
    updated_at_sql = ", updated_at = CURRENT_TIMESTAMP" if "updated_at" in columns else ""

    if existing:
        conn.execute(
            text(f"""
                UPDATE symbols_registry
                SET whale_held_pct = :whale_held_pct,
                    inst_count = :inst_count,
                    institutional_net_buy = :institutional_net_buy,
                    sentiment_score = :sentiment_score
                    {updated_at_sql}
                WHERE symbol = :symbol
            """),
            {"symbol": symbol, **sanitized},
        )
    else:
        conn.execute(
            text("""
                INSERT INTO symbols_registry(
                    symbol, asset_type, is_active, is_benchmark,
                    whale_held_pct, inst_count, institutional_net_buy, sentiment_score
                )
                VALUES (
                    :symbol, 'EQUITY', 1, 0,
                    :whale_held_pct, :inst_count, :institutional_net_buy, :sentiment_score
                )
            """),
            {"symbol": symbol, **sanitized},
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
