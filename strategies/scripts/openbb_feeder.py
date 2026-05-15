from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine, text

try:
    import yfinance as yf
except ImportError:
    yf = None

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies.src.adapters.institutional_activity import fetch_and_store_institutional_activity
from strategies.src.config import DB_URI, NEWS_LIMIT, NEWS_PROVIDER, OPENBB_API_URL, UNIVERSE_TICKERS
from strategies.src.symbol_registry import (
    DEFAULT_BENCHMARK_SYMBOLS,
    deactivate_missing_memberships,
    dedupe_symbols,
    load_active_symbols,
    normalize_symbol,
    refresh_registry_activity,
    seed_benchmark_memberships,
    upsert_membership,
    upsert_symbol,
)

engine = create_engine(DB_URI)
DEFAULT_FEED_SYMBOLS = tuple(sorted({symbol.upper() for symbol in UNIVERSE_TICKERS} | {"SPY"}))
INDEX_SYNC_MAP = {
    "SP500": {"provider_symbol": "sp500", "provider": "fmp", "membership_type": "index"},
}


def _extract_results(payload):
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            return payload["results"]
        if isinstance(payload.get("data"), list):
            return payload["data"]
    if isinstance(payload, list):
        return payload
    return []


def _chunked(records: list[dict], batch_size: int) -> list[list[dict]]:
    size = max(int(batch_size), 1)
    return [records[index:index + size] for index in range(0, len(records), size)]


def _clean_news_records(symbol: str, records: list[dict], provider: str) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["symbol", "date", "title", "summary", "url", "provider"])

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["symbol", "date", "title", "summary", "url", "provider"])

    date_col = next(
        (
            column
            for column in ["date", "published", "published_date", "publishedDate", "datetime"]
            if column in df.columns
        ),
        None,
    )
    title_col = next((column for column in ["title", "headline", "name"] if column in df.columns), None)
    summary_col = next(
        (column for column in ["summary", "text", "description", "body"] if column in df.columns),
        None,
    )
    url_col = next((column for column in ["url", "link", "article_url"] if column in df.columns), None)

    cleaned = pd.DataFrame(index=df.index)
    cleaned["date"] = pd.to_datetime(df[date_col], errors="coerce") if date_col else pd.NaT
    cleaned["title"] = df[title_col].astype(str).str.strip() if title_col else ""
    cleaned["summary"] = df[summary_col].astype(str).str.strip() if summary_col else ""
    cleaned["url"] = df[url_col].astype(str).str.strip() if url_col else ""
    cleaned["symbol"] = symbol.upper()
    cleaned["provider"] = provider

    cleaned = cleaned.dropna(subset=["date"])
    cleaned = cleaned[cleaned["title"].astype(bool)]
    cleaned["summary"] = cleaned["summary"].replace({"nan": "", "None": ""}).fillna("")
    cleaned["url"] = cleaned["url"].replace({"nan": "", "None": ""}).fillna("")
    cleaned = cleaned.drop_duplicates(subset=["symbol", "date", "title", "url"])
    return cleaned.reset_index(drop=True)


def _fetch_price_dataframe_from_openbb(symbol: str) -> pd.DataFrame:
    endpoint = f"{OPENBB_API_URL}/api/v1/equity/price/historical"
    params = {"symbol": symbol, "provider": "yfinance"}
    response = requests.get(endpoint, params=params, timeout=45)
    response.raise_for_status()
    data = response.json()
    if "results" not in data or not data["results"]:
        return pd.DataFrame()
    return pd.DataFrame(data["results"])


def _fetch_price_dataframe_from_yfinance(symbol: str) -> pd.DataFrame:
    if yf is None:
        return pd.DataFrame()

    history = yf.Ticker(symbol).history(period="2y", interval="1d", auto_adjust=False)
    if history.empty:
        return pd.DataFrame()

    history = history.reset_index()
    history.columns = [str(column).lower() for column in history.columns]
    return history


def _prepare_price_dataframe(raw_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()

    normalized = raw_df.copy()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    columns_to_keep = [column for column in ["date", "open", "high", "low", "close", "volume"] if column in normalized.columns]
    normalized = normalized[columns_to_keep]
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.tz_localize(None)
    for column in ["open", "high", "low", "close", "volume"]:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    normalized = normalized.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    normalized["symbol"] = symbol.upper()
    return normalized.reset_index(drop=True)


def _replace_price_rows(symbol: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM price_data_v2 WHERE symbol = %s", (symbol.upper(),))
        df.to_sql("price_data_v2", con=conn, if_exists="append", index=False)
    return len(df)


def _create_sync_run(conn, universe_code: str, total_symbols: int) -> int:
    conn.execute(text("""
        INSERT INTO universe_sync_runs(universe_code, status, total_symbols, processed_symbols, started_at)
        VALUES (:universe_code, 'running', :total_symbols, 0, CURRENT_TIMESTAMP)
    """), {"universe_code": universe_code, "total_symbols": int(total_symbols)})
    return int(conn.execute(text("SELECT LAST_INSERT_ID()")).scalar())


def _update_sync_run(
    conn,
    run_id: int,
    status: str,
    processed_symbols: int,
    error_message: str | None = None,
) -> None:
    conn.execute(text("""
        UPDATE universe_sync_runs
        SET status = :status,
            processed_symbols = :processed_symbols,
            error_message = :error_message,
            finished_at = CASE
                WHEN :status IN ('completed', 'failed', 'partial_failed')
                THEN CURRENT_TIMESTAMP
                ELSE finished_at
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :run_id
    """), {
        "run_id": int(run_id),
        "status": status,
        "processed_symbols": int(processed_symbols),
        "error_message": error_message,
    })


def _fetch_index_constituents_from_openbb(index_code: str) -> list[dict]:
    config = INDEX_SYNC_MAP.get(index_code.upper())
    if not config:
        raise ValueError(f"Unsupported index code: {index_code}")

    endpoint = f"{OPENBB_API_URL}/api/v1/index/constituents"
    params = {"symbol": config["provider_symbol"], "provider": config["provider"]}
    response = requests.get(endpoint, params=params, timeout=45)
    response.raise_for_status()
    records = _extract_results(response.json())
    if not records:
        raise ValueError(f"No constituents returned for {index_code}")
    return records


def _normalize_constituents(records: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for row in records:
        symbol = normalize_symbol(row.get("symbol"))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append({
            "symbol": symbol,
            "asset_type": str(row.get("asset_type") or "EQUITY").upper(),
            "sector": row.get("sector"),
        })
    return normalized


def sync_from_indices(index_codes: list[str] | None = None, batch_size: int = 20) -> dict[str, dict]:
    summaries: dict[str, dict] = {}
    for index_code in dedupe_symbols(index_codes or ["SP500"]):
        processed = 0
        errors: list[str] = []
        try:
            raw_records = _fetch_index_constituents_from_openbb(index_code)
            constituents = _normalize_constituents(raw_records)
        except Exception as error:
            summaries[index_code] = {
                "status": "failed",
                "processed_symbols": 0,
                "total_symbols": 0,
                "error_message": str(error),
            }
            continue

        with engine.begin() as conn:
            seed_benchmark_memberships(conn, DEFAULT_BENCHMARK_SYMBOLS)
            run_id = _create_sync_run(conn, index_code, len(constituents))

        for batch in _chunked(constituents, batch_size):
            try:
                with engine.begin() as conn:
                    for item in batch:
                        upsert_symbol(
                            conn,
                            item["symbol"],
                            asset_type=item["asset_type"],
                            sector=item.get("sector"),
                            is_active=True,
                            is_benchmark=False,
                        )
                        upsert_membership(
                            conn,
                            item["symbol"],
                            universe_code=index_code,
                            membership_type=INDEX_SYNC_MAP[index_code]["membership_type"],
                            is_active=True,
                        )
                    processed += len(batch)
                    _update_sync_run(conn, run_id, "running", processed)
            except Exception as error:
                errors.append(str(error))

        with engine.begin() as conn:
            deactivate_missing_memberships(conn, index_code, [item["symbol"] for item in constituents])
            refresh_registry_activity(conn)
            final_status = "completed" if not errors else "partial_failed"
            _update_sync_run(conn, run_id, final_status, processed, " | ".join(errors) if errors else None)

        summaries[index_code] = {
            "status": "completed" if not errors else "partial_failed",
            "processed_symbols": processed,
            "total_symbols": len(constituents),
            "error_message": " | ".join(errors) if errors else None,
        }

    return summaries


def fetch_and_store_price(symbol: str):
    print(f"下載 {symbol} 價格資料中...")

    try:
        raw_df = _fetch_price_dataframe_from_openbb(symbol)
        source = "OpenBB"
    except Exception as error:
        print(f"{symbol}: OpenBB 失敗，改用 yfinance fallback: {error}")
        raw_df = _fetch_price_dataframe_from_yfinance(symbol)
        source = "yfinance"

    prepared_df = _prepare_price_dataframe(raw_df, symbol)
    if prepared_df.empty:
        print(f"{symbol}: 無有效價格資料")
        return 0

    try:
        row_count = _replace_price_rows(symbol, prepared_df)
        print(f"{symbol}: 使用 {source} 寫入 {row_count} 筆 K 線")
        return row_count
    except Exception as error:
        print(f"{symbol}: 寫入價格資料失敗: {error}")
        return 0


def fetch_and_store_news(symbol: str, provider: str = NEWS_PROVIDER, limit: int = NEWS_LIMIT):
    print(f"下載 {symbol} 新聞中...")
    endpoint = f"{OPENBB_API_URL}/api/v1/news/company"
    params = {"symbol": symbol, "provider": provider, "limit": limit}

    try:
        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()
        records = _extract_results(response.json())
        news_df = _clean_news_records(symbol, records, provider)

        if news_df.empty:
            print(f"{symbol}: 沒有可寫入的新聞資料")
            return news_df

        news_df.to_sql("news_cache", con=engine, if_exists="append", index=False)
        print(f"{symbol}: 寫入 {len(news_df)} 則新聞")
        return news_df
    except Exception as error:
        print(f"{symbol}: 下載新聞失敗: {error}")
        return pd.DataFrame()


def fetch_and_store_holder_activity(symbol: str):
    print(f"下載 {symbol} 機構與內部人活動中...")
    try:
        snapshot = fetch_and_store_institutional_activity(symbol, db_uri=DB_URI)
        if not snapshot:
            print(f"{symbol}: 沒有可寫入的籌碼快照")
            return {}
        print(
            f"{symbol}: institution={snapshot.get('institution_total_shares')} | "
            f"mutualfund={snapshot.get('mutualfund_total_shares')} | "
            f"insider_6m={snapshot.get('insider_net_shares_6m')}"
        )
        return snapshot
    except Exception as error:
        print(f"{symbol}: 下載籌碼資料失敗: {error}")
        return {}


def _load_symbols_for_default_feed() -> list[str]:
    return load_active_symbols(
        engine,
        fallback_symbols=DEFAULT_FEED_SYMBOLS,
        include_benchmarks=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenBB / yfinance data feeder")
    parser.add_argument("--symbols", type=str, default=None, help="股票代碼，逗號分隔；未指定則使用 registry active pool")
    parser.add_argument("--skip-news", action="store_true", help="略過公司新聞同步")
    parser.add_argument("--skip-institutional", action="store_true", help="略過機構與內部人籌碼同步")
    parser.add_argument("--skip-index-sync", action="store_true", help="略過指數成分股同步")
    parser.add_argument("--sync-indices", type=str, default="SP500", help="要同步的指數代碼，逗號分隔")
    parser.add_argument("--sleep", type=float, default=1.0, help="每檔股票之間的等待秒數")
    args = parser.parse_args()

    if not args.skip_index_sync:
        try:
            sync_codes = [value.strip().upper() for value in str(args.sync_indices or "").split(",") if value.strip()]
            sync_result = sync_from_indices(index_codes=sync_codes or ["SP500"])
            print(f"Universe Registry 同步結果: {sync_result}")
        except Exception as error:
            print(f"Universe Registry 同步失敗，改用 fallback 股票池: {error}")

    if args.symbols:
        symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    else:
        symbols = _load_symbols_for_default_feed()

    if "SPY" not in symbols:
        symbols.append("SPY")

    print("開始執行 OpenBB Data Feeder")
    print(f"股票池共 {len(symbols)} 檔")

    for index, ticker in enumerate(symbols):
        fetch_and_store_price(ticker)
        if not args.skip_news:
            fetch_and_store_news(ticker)
        if not args.skip_institutional:
            fetch_and_store_holder_activity(ticker)
        if index < len(symbols) - 1 and args.sleep > 0:
            time.sleep(args.sleep)

    print("Data Feeder 執行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
