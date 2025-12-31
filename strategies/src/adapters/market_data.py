"""
Market Data Adapter for the US Stock Trading System.

This module provides functions to fetch market data from various sources,
primarily using yfinance for historical OHLCV data.

Author: Quant System
Created: 2025-12-31
"""

from typing import Optional
import pandas as pd
import yfinance as yf


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
    print(f"📊 Fetching data for {symbol} (period={period}, interval={interval})...")
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            raise ValueError(f"No data returned for symbol: {symbol}")
        
        # Clean up the dataframe
        df = df.dropna()
        
        # Ensure proper column names
        df.columns = [col.replace(" ", "_") for col in df.columns]
        
        print(f"✅ Successfully fetched {len(df)} rows of data for {symbol}")
        print(f"   Date range: {df.index[0]} to {df.index[-1]}")
        
        return df
        
    except Exception as e:
        raise ValueError(f"Failed to fetch data for {symbol}: {e}") from e


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
