#!/usr/bin/env python3
"""
完整數據獲取腳本
從 yfinance 和 FRED API 獲取股票、基本面和宏觀經濟數據並存儲到 MySQL
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd
import yfinance as yf
from fredapi import Fred
from dotenv import load_dotenv

# 加載 .env 文件（從項目根目錄）
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# 添加父目錄到路徑
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from adapters.database import DatabaseAdapter
from utils.security import get_secret


class DataIngestion:
    """數據獲取和存儲管理器"""
    
    def __init__(self):
        """初始化數據獲取器"""
        self.db = DatabaseAdapter()
        
        # 設置 FRED API
        fred_api_key = os.getenv('FRED_API_KEY', 'dummy_key')
        try:
            self.fred = Fred(api_key=fred_api_key)
            # 測試連接
            self.fred.get_series('UNRATE', observation_start='2024-01-01', observation_end='2024-01-31')
            self.fred_available = True
            print("✅ FRED API 連接成功")
        except Exception as e:
            print(f"⚠️  FRED API 不可用: {str(e)}")
            print("   如需使用宏觀數據，請在 .env 中設置 FRED_API_KEY")
            self.fred_available = False
    
    def fetch_yahoo_prices(
        self, 
        symbols: List[str], 
        start_date: str = None,
        end_date: str = None,
        delay: float = 0.5
    ) -> Dict[str, pd.DataFrame]:
        """
        從 Yahoo Finance 獲取股票價格數據
        
        Args:
            symbols: 股票代碼列表
            start_date: 開始日期 (YYYY-MM-DD)，默認為5年前
            end_date: 結束日期 (YYYY-MM-DD)，默認為今天
            delay: 每次請求之間的延遲（秒），避免 API 限制
            
        Returns:
            字典 {symbol: DataFrame}
        """
        # 設置默認日期範圍
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365*5)).strftime('%Y-%m-%d')
        
        print(f"\n📊 開始獲取股票價格數據: {start_date} 到 {end_date}")
        print(f"   股票列表: {', '.join(symbols)}")
        
        results = {}
        
        for i, symbol in enumerate(symbols, 1):
            try:
                print(f"\n[{i}/{len(symbols)}] 獲取 {symbol} 的價格數據...")
                
                # 使用 yfinance 獲取數據
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start_date, end=end_date)
                
                if df.empty:
                    print(f"   ⚠️  {symbol}: 無數據")
                    continue
                
                # 保存到數據庫
                rows = self.db.save_market_data(df, symbol)
                results[symbol] = df
                
                print(f"   ✅ {symbol}: 成功獲取並保存 {len(df)} 條記錄")
                
                # 延遲以避免 API 限制
                if i < len(symbols):
                    time.sleep(delay)
                
            except Exception as e:
                print(f"   ❌ {symbol}: 獲取失敗 - {str(e)}")
                continue
        
        print(f"\n✅ 價格數據獲取完成: {len(results)}/{len(symbols)} 個股票成功")
        return results
    
    def fetch_yahoo_fundamentals(
        self, 
        symbols: List[str],
        delay: float = 1.0
    ) -> Dict[str, Dict]:
        """
        從 Yahoo Finance 獲取基本面數據
        
        Args:
            symbols: 股票代碼列表
            delay: 每次請求之間的延遲（秒）
            
        Returns:
            字典 {symbol: fundamentals_dict}
        """
        print(f"\n📈 開始獲取基本面數據...")
        print(f"   股票列表: {', '.join(symbols)}")
        
        results = {}
        today = datetime.now().strftime('%Y-%m-%d')
        
        for i, symbol in enumerate(symbols, 1):
            try:
                print(f"\n[{i}/{len(symbols)}] 獲取 {symbol} 的基本面數據...")
                
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                # 提取基本面指標
                fundamentals = {
                    'pe_ratio': info.get('trailingPE'),
                    'peg_ratio': info.get('pegRatio'),
                    'pb_ratio': info.get('priceToBook'),
                    'forward_pe': info.get('forwardPE'),
                    'market_cap': info.get('marketCap'),
                    'revenue_growth_yoy': info.get('revenueGrowth'),
                    'earnings_growth_yoy': info.get('earningsGrowth'),
                    'inst_ownership_pct': info.get('heldPercentInstitutions'),
                    'inst_holders_count': info.get('institutionHolders')
                }
                
                # 清理數據：將 None 和 NaN 轉為 None
                fundamentals = {
                    k: (v if v is not None and pd.notna(v) else None)
                    for k, v in fundamentals.items()
                }
                
                # 保存到數據庫
                if any(v is not None for v in fundamentals.values()):
                    self.db.save_fundamentals(fundamentals, symbol, today)
                    results[symbol] = fundamentals
                    print(f"   ✅ {symbol}: 基本面數據已保存")
                else:
                    print(f"   ⚠️  {symbol}: 無有效基本面數據")
                
                # 延遲以避免 API 限制
                if i < len(symbols):
                    time.sleep(delay)
                
            except Exception as e:
                print(f"   ❌ {symbol}: 獲取基本面數據失敗 - {str(e)}")
                continue
        
        print(f"\n✅ 基本面數據獲取完成: {len(results)}/{len(symbols)} 個股票成功")
        return results
    
    def fetch_fred_data(
        self, 
        indicators: List[str] = None,
        start_date: str = None,
        end_date: str = None
    ) -> Dict[str, pd.Series]:
        """
        從 FRED API 獲取宏觀經濟數據
        
        Args:
            indicators: FRED 指標代碼列表
            start_date: 開始日期 (YYYY-MM-DD)，默認為5年前
            end_date: 結束日期 (YYYY-MM-DD)，默認為今天
            
        Returns:
            字典 {indicator: Series}
        """
        if not self.fred_available:
            print("⚠️  跳過 FRED 數據獲取（API 不可用）")
            return {}
        
        # 默認指標
        if indicators is None:
            indicators = [
                'UNRATE',    # 失業率
                'GDP',       # GDP
                'DFF',       # 聯邦基金利率
                'CPIAUCSL',  # 消費者物價指數
                'T10Y2Y'     # 10年期與2年期國債收益率差
            ]
        
        # 設置默認日期範圍
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365*5)).strftime('%Y-%m-%d')
        
        print(f"\n🌐 開始獲取宏觀經濟數據: {start_date} 到 {end_date}")
        print(f"   指標列表: {', '.join(indicators)}")
        
        results = {}
        
        for i, indicator in enumerate(indicators, 1):
            try:
                print(f"\n[{i}/{len(indicators)}] 獲取 {indicator}...")
                
                # 從 FRED 獲取數據
                series = self.fred.get_series(
                    indicator, 
                    observation_start=start_date,
                    observation_end=end_date
                )
                
                if series.empty:
                    print(f"   ⚠️  {indicator}: 無數據")
                    continue
                
                # 保存到數據庫
                self._save_macro_data(indicator, series)
                results[indicator] = series
                
                print(f"   ✅ {indicator}: 成功獲取並保存 {len(series)} 條記錄")
                
                # 稍微延遲
                time.sleep(0.5)
                
            except Exception as e:
                print(f"   ❌ {indicator}: 獲取失敗 - {str(e)}")
                continue
        
        print(f"\n✅ 宏觀數據獲取完成: {len(results)}/{len(indicators)} 個指標成功")
        return results
    
    def _save_macro_data(self, ticker: str, series: pd.Series):
        """
        保存宏觀數據到數據庫
        
        Args:
            ticker: FRED 指標代碼
            series: 時間序列數據
        """
        # 準備數據
        df = pd.DataFrame({
            'date': series.index.date,
            'ticker': ticker,
            'value': series.values
        })
        
        # 使用 UPSERT 邏輯保存
        try:
            from sqlalchemy import text
            
            with self.db.engine.begin() as conn:
                for _, row in df.iterrows():
                    query = text("""
                        INSERT INTO macro_data (date, ticker, value)
                        VALUES (:date, :ticker, :value)
                        ON DUPLICATE KEY UPDATE
                            value = VALUES(value),
                            updated_at = CURRENT_TIMESTAMP
                    """)
                    conn.execute(query, {
                        'date': row['date'],
                        'ticker': row['ticker'],
                        'value': float(row['value']) if pd.notna(row['value']) else None
                    })
        except Exception as e:
            print(f"   ❌ 保存宏觀數據失敗: {str(e)}")
            raise
    
    def close(self):
        """關閉數據庫連接"""
        self.db.close()


def main():
    """主函數：執行完整的數據獲取流程"""
    print("=" * 70)
    print(" 🚀 開始完整數據獲取流程")
    print("=" * 70)
    
    # 初始化
    ingestion = DataIngestion()
    
    # 定義目標股票列表（由 config.DEFAULT_SYMBOLS 統一管理）
    from config import DEFAULT_SYMBOLS
    default_list = ','.join(DEFAULT_SYMBOLS)
    symbols = os.getenv('SYMBOLS', default_list).split(',')
    
    # 設置日期範圍（可以通過環境變量自定義）
    start_date = os.getenv('START_DATE', None)  # 默認為5年前
    end_date = os.getenv('END_DATE', None)      # 默認為今天
    
    try:
        # 1. 獲取股票價格
        print("\n" + "=" * 70)
        print(" 步驟 1: 獲取股票價格數據")
        print("=" * 70)
        prices = ingestion.fetch_yahoo_prices(symbols, start_date, end_date)
        
        # 2. 獲取基本面數據
        print("\n" + "=" * 70)
        print(" 步驟 2: 獲取基本面數據")
        print("=" * 70)
        fundamentals = ingestion.fetch_yahoo_fundamentals(symbols)
        
        # 3. 獲取宏觀數據
        print("\n" + "=" * 70)
        print(" 步驟 3: 獲取宏觀經濟數據")
        print("=" * 70)
        macro_data = ingestion.fetch_fred_data()
        
        # 總結
        print("\n" + "=" * 70)
        print(" 📊 數據獲取總結")
        print("=" * 70)
        print(f"✅ 價格數據: {len(prices)} 個股票")
        print(f"✅ 基本面數據: {len(fundamentals)} 個股票")
        print(f"✅ 宏觀數據: {len(macro_data)} 個指標")
        print("\n✅ 所有數據已成功保存到數據庫！")
        
    except Exception as e:
        print(f"\n❌ 數據獲取過程出錯: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        ingestion.close()
    
    print("\n" + "=" * 70)
    print(" 🎉 數據獲取流程完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
