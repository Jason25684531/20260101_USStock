c

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

if __name__ == "__main__":
    print("🚀 啟動 OpenBB Data Feeder...")
    for ticker in UNIVERSE_TICKERS:
        fetch_and_store_price(ticker)
        time.sleep(1) # 避免密集請求觸發 Rate Limit
    print("🎉 所有資料更新完畢！")