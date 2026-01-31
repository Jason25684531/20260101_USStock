"""
Market Data Adapter for the US Stock Trading System.

This module provides functions to fetch market data from various sources,
primarily using yfinance for historical OHLCV data and fundamental data.

Author: Quant System
Created: 2025-12-31
Updated: 2026-01-31 - Added fundamental data (PE/PB) and database integration
"""

from typing import List, Optional
import pandas as pd
import yfinance as yf
from .database import DatabaseAdapter


def fetch_data(
    symbol: str,
    period: str = "1y",
    interval: str = "1d"
) -> pd.DataFrame:
    """
    Fetch historical OHLCV data for a given symbol.
    
    Uses yfinance to download market data. Returns a DataFrame with columns:
    Open, High, Low, Close, Volume, and optionally Adj Close.
    
    Args:
        symbol: Stock ticker symbol (e.g., 'SPY', 'AAPL').
        period: Data period to download. Valid periods:
                1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
        interval: Data granularity. Valid intervals:
                  1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
                  
    Returns:
        DataFrame with OHLCV data indexed by datetime.
        
    Raises:
        ValueError: If the symbol is invalid or no data is returned.
        
    Example:
        >>> df = fetch_data("SPY", period="1y", interval="1d")
        >>> print(df.head())
    """
    print(f"📊 正在下載 {symbol} 數據 (period={period}, interval={interval})...")
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            raise ValueError(f"無法獲取數據: {symbol}")
        
        # 清理數據
        df = df.dropna()
        
        print(f"✅ 成功下載 {symbol}: {len(df)} 行數據")
        print(f"   日期範圍: {df.index[0]} 到 {df.index[-1]}")
        
        return df
        
    except Exception as e:
        raise ValueError(f"下載 {symbol} 失敗: {e}") from e


def fetch_fundamentals(symbol: str) -> dict:
    """
    獲取基本面數據 (PE/PB/PEG/成長率/機構持股等)
    
    Args:
        symbol: 股票代碼
        
    Returns:
        包含基本面數據的字典，包括：
        - pe_ratio: 市盈率
        - pb_ratio: 市淨率
        - peg_ratio: PEG比率
        - forward_pe: 預期市盈率
        - revenue_growth_yoy: 年度營收增長率
        - inst_ownership_pct: 機構持股百分比
        - inst_holders_count: 機構持有者數量
        - market_cap: 市值
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # 獲取機構持股數據
        inst_ownership_pct = None
        inst_holders_count = None
        try:
            institutional_holders = ticker.institutional_holders
            if institutional_holders is not None and not institutional_holders.empty:
                # 計算前十大機構持股百分比的總和作為參考
                inst_ownership_pct = info.get('heldPercentInstitutions', None)
                inst_holders_count = len(institutional_holders)
        except Exception as e:
            print(f"   機構持股數據獲取失敗: {e}")
        
        # 計算營收增長率
        revenue_growth_yoy = info.get('revenueGrowth', None)
        
        return {
            'pe_ratio': info.get('trailingPE', None),
            'pb_ratio': info.get('priceToBook', None),
            'forward_pe': info.get('forwardPE', None),
            'peg_ratio': info.get('pegRatio', None),
            'revenue_growth_yoy': revenue_growth_yoy,
            'earnings_growth_yoy': info.get('earningsGrowth', None),
            'inst_ownership_pct': inst_ownership_pct,
            'inst_holders_count': inst_holders_count,
            'market_cap': info.get('marketCap', None)
        }
    except Exception as e:
        print(f"⚠️  無法獲取 {symbol} 基本面數據: {e}")
        return {}


def download_and_save(
    symbols: List[str] = None,
    period: str = "2y",
    interval: str = "1d"
) -> dict:
    """
    下載市場數據和基本面數據並保存到數據庫
    
    Args:
        symbols: 股票代碼列表，默認為 ['SPY', 'QQQ', 'AAPL', 'NVDA']
        period: 數據週期
        interval: 數據粒度
        
    Returns:
        下載結果統計字典
    """
    if symbols is None:
        symbols = ['SPY', 'QQQ', 'AAPL', 'NVDA']
    
    db = DatabaseAdapter()
    results = {
        'success': [],
        'failed': [],
        'total_rows': 0
    }
    
    print(f"\n{'='*60}")
    print(f"開始下載 {len(symbols)} 個股票的數據...")
    print(f"{'='*60}\n")
    
    for symbol in symbols:
        try:
            # 下載 OHLCV 數據
            df = fetch_data(symbol, period=period, interval=interval)
            
            # 獲取基本面數據
            print(f"   正在獲取 {symbol} 基本面數據...")
            fundamentals = fetch_fundamentals(symbol)
            
            # 保存基本面數據到數據庫
            if fundamentals:
                from datetime import date
                db.save_fundamentals(fundamentals, symbol, date.today().isoformat())
            
            # 將部分基本面數據添加到市場數據（可選）
            if fundamentals.get('pe_ratio'):
                df['pe_ratio'] = fundamentals['pe_ratio']
            if fundamentals.get('pb_ratio'):
                df['pb_ratio'] = fundamentals['pb_ratio']
            
            # 保存市場數據到數據庫
            rows_saved = db.save_market_data(df, symbol)
            
            results['success'].append(symbol)
            results['total_rows'] += rows_saved
            
        except Exception as e:
            print(f"❌ {symbol} 處理失敗: {str(e)}")
            results['failed'].append(symbol)
    
    db.close()
    
    # 打印摘要
    print(f"\n{'='*60}")
    print(f"下載完成摘要:")
    print(f"  成功: {len(results['success'])} 個股票")
    print(f"  失敗: {len(results['failed'])} 個股票")
    print(f"  總行數: {results['total_rows']}")
    print(f"{'='*60}\n")
    
    return results


def fetch_multiple(
    symbols: list[str],
    period: str = "1y",
    interval: str = "1d"
) -> dict[str, pd.DataFrame]:
    """
    Fetch historical data for multiple symbols.
    
    Args:
        symbols: List of stock ticker symbols.
        period: Data period to download.
        interval: Data granularity.
        
    Returns:
        Dictionary mapping symbol to DataFrame.
        
    Example:
        >>> data = fetch_multiple(["SPY", "QQQ", "IWM"], period="1y")
        >>> print(data["SPY"].head())
    """
    results = {}
    
    for symbol in symbols:
        try:
            results[symbol] = fetch_data(symbol, period=period, interval=interval)
        except ValueError as e:
            print(f"⚠️ Warning: {e}")
            continue
            
    return results


def get_latest_price(symbol: str) -> Optional[float]:
    """
    Get the latest closing price for a symbol.
    
    Args:
        symbol: Stock ticker symbol.
        
    Returns:
        Latest closing price, or None if unavailable.
    """
    try:
        df = fetch_data(symbol, period="1d", interval="1m")
        return float(df["Close"].iloc[-1])
    except (ValueError, IndexError):
        return None
