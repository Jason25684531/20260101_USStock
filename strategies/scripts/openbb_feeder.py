from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategies.src.config import DB_URI, NEWS_LIMIT, NEWS_PROVIDER, OPENBB_API_URL, UNIVERSE_TICKERS

engine = create_engine(DB_URI)


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

def fetch_and_store_price(symbol: str):
    print(f"🔄 正在向 OpenBB 請求 {symbol} 的歷史量價資料...")
    endpoint = f"{OPENBB_API_URL}/api/v1/equity/price/historical"
    # 使用 yfinance 確保穩定抓取歷史股價
    params = {"symbol": symbol, "provider": "yfinance"}
    
    try:
        response = requests.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        
        if "results" in data and len(data["results"]) > 0:
            df = pd.DataFrame(data["results"])
            
            # 欄位標準化
            columns_to_keep = ['date', 'open', 'high', 'low', 'close', 'volume']
            df = df[[col for col in columns_to_keep if col in df.columns]]
            df['symbol'] = symbol
            
            # 寫入 MySQL (取代舊有的 yfinance 直接塞給模型)
            df.to_sql('price_data_v2', con=engine, if_exists='append', index=False)
            print(f"✅ {symbol}: 成功將 {len(df)} 筆 K 線寫入 MySQL！")
        else:
            print(f"⚠️ {symbol}: API 回傳成功，但無數據。")
            
    except Exception as e:
        print(f"❌ 抓取失敗 ({symbol}): {e}")


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

if __name__ == "__main__":
    print("🚀 啟動 OpenBB Data Feeder...")
    for ticker in UNIVERSE_TICKERS:
        fetch_and_store_price(ticker)
        fetch_and_store_news(ticker)
        time.sleep(1) # 避免密集請求觸發 Rate Limit
    print("🎉 所有資料更新完畢！")