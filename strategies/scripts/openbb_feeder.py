from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine

try:
    import yfinance as yf
except ImportError:
    yf = None

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies.src.config import DB_URI, NEWS_LIMIT, NEWS_PROVIDER, OPENBB_API_URL, UNIVERSE_TICKERS

engine = create_engine(DB_URI)
DEFAULT_FEED_SYMBOLS = tuple(sorted({symbol.upper() for symbol in UNIVERSE_TICKERS} | {"SPY"}))


def _extract_results(payload):
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            return payload["results"]
        if isinstance(payload.get("data"), list):
            return payload["data"]
    if isinstance(payload, list):
        return payload
    return []


def _clean_news_records(symbol: str, records: list[dict], provider: str) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["symbol", "date", "title", "summary", "url", "provider"])

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["symbol", "date", "title", "summary", "url", "provider"])

    date_col = next((column for column in ["date", "published", "published_date", "publishedDate", "datetime"] if column in df.columns), None)
    title_col = next((column for column in ["title", "headline", "name"] if column in df.columns), None)
    summary_col = next((column for column in ["summary", "text", "description", "body"] if column in df.columns), None)
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

def fetch_and_store_price(symbol: str):
    print(f"🔄 正在向 OpenBB 請求 {symbol} 的歷史量價資料...")

    try:
        raw_df = _fetch_price_dataframe_from_openbb(symbol)
        source = "OpenBB"
    except Exception as error:
        print(f"⚠️ {symbol}: OpenBB 抓取失敗，改用 yfinance fallback: {error}")
        raw_df = _fetch_price_dataframe_from_yfinance(symbol)
        source = "yfinance"

    prepared_df = _prepare_price_dataframe(raw_df, symbol)
    if prepared_df.empty:
        print(f"⚠️ {symbol}: 無可寫入的歷史量價資料。")
        return 0

    try:
        row_count = _replace_price_rows(symbol, prepared_df)
        print(f"✅ {symbol}: 使用 {source} 成功將 {row_count} 筆 K 線寫入 MySQL！")
        return row_count
    except Exception as error:
        print(f"❌ 寫入失敗 ({symbol}): {error}")
        return 0


def fetch_and_store_news(symbol: str, provider: str = NEWS_PROVIDER, limit: int = NEWS_LIMIT):
    print(f"📰 正在向 OpenBB 請求 {symbol} 的新聞資料...")
    endpoint = f"{OPENBB_API_URL}/api/v1/news/company"
    params = {"symbol": symbol, "provider": provider, "limit": limit}

    try:
        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()
        records = _extract_results(response.json())
        news_df = _clean_news_records(symbol, records, provider)

        if news_df.empty:
            print(f"⚠️ {symbol}: 新聞 API 回傳成功，但無可寫入資料。")
            return news_df

        news_df.to_sql("news_cache", con=engine, if_exists="append", index=False)
        print(f"✅ {symbol}: 成功將 {len(news_df)} 筆新聞寫入 MySQL！")
        return news_df
    except Exception as e:
        print(f"❌ 新聞抓取失敗 ({symbol}): {e}")
        return pd.DataFrame()

def main() -> int:
    parser = argparse.ArgumentParser(description="OpenBB / yfinance data feeder")
    parser.add_argument("--symbols", type=str, default=None, help="逗號分隔股票代碼；未指定則使用 UNIVERSE + SPY")
    parser.add_argument("--skip-news", action="store_true", help="只更新價格，不抓新聞")
    parser.add_argument("--sleep", type=float, default=1.0, help="每檔之間等待秒數")
    args = parser.parse_args()

    if args.symbols:
        symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    else:
        symbols = list(DEFAULT_FEED_SYMBOLS)

    if "SPY" not in symbols:
        symbols.append("SPY")

    print("🚀 啟動 OpenBB Data Feeder...")
    print(f"   股票池: {len(symbols)} 檔 (含 SPY)")

    for index, ticker in enumerate(symbols):
        fetch_and_store_price(ticker)
        if not args.skip_news:
            fetch_and_store_news(ticker)
        if index < len(symbols) - 1 and args.sleep > 0:
            time.sleep(args.sleep)

    print("🎉 所有資料更新完畢！")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())