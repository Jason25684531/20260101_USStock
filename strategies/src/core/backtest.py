"""
Backtesting Engine using VectorBT for the US Stock Trading System.

This module implements vectorized backtesting strategies using VectorBT.
All operations must be vectorized (no for loops for data iteration).
Includes ATR-based trailing stop loss functionality.

Author: Quant System
Created: 2025-12-31
Updated: 2026-01-31 - Added ATR trailing stop functionality
"""
from __future__ import annotations

from typing import Tuple, Optional
import pandas as pd
import numpy as np

from config import calc_atr

try:
    import vectorbt as vbt
    _HAS_VBT = True
except ImportError:
    vbt = None  # type: ignore
    _HAS_VBT = False


def run_sma_strategy(
    data: pd.DataFrame,
    fast_window: int = 20,
    slow_window: int = 50,
    initial_cash: float = 10000.0,
    fees: float = 0.001
) -> Tuple[vbt.Portfolio, pd.DataFrame]:
    """
    Run a Simple Moving Average (SMA) crossover strategy using VectorBT.
    
    Strategy Logic:
    - BUY signal: Fast SMA crosses ABOVE Slow SMA
    - SELL signal: Fast SMA crosses BELOW Slow SMA
    
    Args:
        data: DataFrame with OHLCV data (must have 'Close' column).
        fast_window: Window size for fast SMA (default: 20).
        slow_window: Window size for slow SMA (default: 50).
        initial_cash: Starting capital (default: 10000).
        fees: Trading fees as a fraction (default: 0.001 = 0.1%).
        
    Returns:
        Tuple of (Portfolio object, signals DataFrame).
        
    Example:
        >>> portfolio, signals = run_sma_strategy(data, fast_window=20, slow_window=50)
        >>> print(portfolio.stats())
    """
    print(f"\n🚀 Running SMA Strategy (Fast={fast_window}, Slow={slow_window})...")
    
    # Validate data
    if "Close" not in data.columns:
        raise ValueError("Data must contain 'Close' column")
    
    close = data["Close"]
    
    # Calculate SMAs using VectorBT
    fast_sma = vbt.MA.run(close, window=fast_window, short_name=f"SMA{fast_window}")
    slow_sma = vbt.MA.run(close, window=slow_window, short_name=f"SMA{slow_window}")
    
    # Generate signals (vectorized)
    # Buy when fast crosses above slow, Sell when fast crosses below slow
    entries = fast_sma.ma_crossed_above(slow_sma)
    exits = fast_sma.ma_crossed_below(slow_sma)
    
    # Create signals DataFrame for inspection
    signals = pd.DataFrame({
        "Close": close,
        f"SMA_{fast_window}": fast_sma.ma.values,
        f"SMA_{slow_window}": slow_sma.ma.values,
        "Entry": entries.values,
        "Exit": exits.values
    }, index=data.index)
    
    # Run backtest using VectorBT Portfolio
    portfolio = vbt.Portfolio.from_signals(
        close=close,
        entries=entries,
        exits=exits,
        init_cash=initial_cash,
        fees=fees,
        freq="1D"  # Daily frequency
    )
    
    print(f"✅ Backtest completed!")
    print(f"   Total trades: {portfolio.trades.count()}")
    
    return portfolio, signals


def print_performance_report(portfolio: vbt.Portfolio, symbol: str = ""):
    """
    Print a comprehensive performance report for a VectorBT portfolio.
    
    Args:
        portfolio: VectorBT Portfolio object.
        symbol: Optional symbol name for display.
    """
    stats = portfolio.stats()
    
    print("\n" + "="*60)
    print(f"📊 BACKTEST PERFORMANCE REPORT {f'- {symbol}' if symbol else ''}")
    print("="*60)
    
    # Key metrics
    print(f"\n💰 Financial Metrics:")
    print(f"   Start Value:      ${stats['Start Value']:,.2f}")
    print(f"   End Value:        ${stats['End Value']:,.2f}")
    print(f"   Total Return:     {stats['Total Return [%]']:.2f}%")
    print(f"   Max Drawdown:     {stats['Max Drawdown [%]']:.2f}%")
    
    print(f"\n📈 Performance Ratios:")
    print(f"   Sharpe Ratio:     {stats.get('Sharpe Ratio', 'N/A')}")
    print(f"   Calmar Ratio:     {stats.get('Calmar Ratio', 'N/A')}")
    print(f"   Win Rate:         {stats.get('Win Rate [%]', 'N/A')}%")
    
    print(f"\n📊 Trade Statistics:")
    print(f"   Total Trades:     {stats['Total Trades']}")
    print(f"   Win Trades:       {stats.get('Total Winning Trades', 'N/A')}")
    print(f"   Lose Trades:      {stats.get('Total Losing Trades', 'N/A')}")
    print(f"   Avg Win:          {stats.get('Avg Winning Trade [%]', 'N/A')}")
    print(f"   Avg Loss:         {stats.get('Avg Losing Trade [%]', 'N/A')}")
    
    print("\n" + "="*60 + "\n")


def calculate_metrics(portfolio: vbt.Portfolio) -> dict:
    """
    Extract key metrics from a VectorBT portfolio.
    
    Args:
        portfolio: VectorBT Portfolio object.
        
    Returns:
        Dictionary of performance metrics.
    """
    stats = portfolio.stats()
    
    return {
        "total_return": stats.get("Total Return [%]", 0.0),
        "sharpe_ratio": stats.get("Sharpe Ratio", 0.0),
        "max_drawdown": stats.get("Max Drawdown [%]", 0.0),
        "win_rate": stats.get("Win Rate [%]", 0.0),
        "total_trades": stats.get("Total Trades", 0),
        "start_value": stats.get("Start Value", 0.0),
        "end_value": stats.get("End Value", 0.0)
    }


def apply_atr_stop(
    entry_price: float,
    current_price: float,
    atr_value: float,
    multiplier: float = 2.0
) -> bool:
    """
    判斷是否觸發 ATR 追蹤止損
    
    止損邏輯：
    - 當前價格低於（入場價格 - ATR * 倍數）時觸發止損
    
    Args:
        entry_price: 入場價格
        current_price: 當前價格
        atr_value: ATR 值
        multiplier: ATR 倍數（默認2.0）
        
    Returns:
        是否觸發止損（True=觸發，False=未觸發）
    """
    if atr_value is None or np.isnan(atr_value):
        return False
    
    stop_loss_price = entry_price - (atr_value * multiplier)
    
    return current_price <= stop_loss_price


def calculate_atr_stop_levels(
    data: pd.DataFrame,
    entries: pd.Series,
    atr_period: int = 14,
    atr_multiplier: float = 2.0
) -> Tuple[pd.Series, pd.Series]:
    """
    計算基於 ATR 的止損位（向量化）
    
    Args:
        data: 包含 OHLC 數據的 DataFrame
        entries: 入場信號（布爾值 Series）
        atr_period: ATR 計算週期
        atr_multiplier: ATR 倍數
        
    Returns:
        (止損價格 Series, ATR 值 Series)
    """
    # 計算 ATR
    atr = calc_atr(data, period=atr_period)
    
    # 獲取入場價格
    entry_prices = data['Close'].where(entries).ffill()
    
    # 計算止損價格
    stop_prices = entry_prices - (atr * atr_multiplier)
    
    return stop_prices, atr


def run_strategy_with_atr_stop(
    data: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    initial_cash: float = 10000.0,
    fees: float = 0.001,
    atr_period: int = 14,
    atr_multiplier: float = 2.0
) -> Tuple[vbt.Portfolio, pd.DataFrame]:
    """
    運行帶有 ATR 追蹤止損的策略
    
    Args:
        data: 包含 OHLCV 數據的 DataFrame
        entries: 入場信號
        exits: 出場信號
        initial_cash: 初始資金
        fees: 交易費用
        atr_period: ATR 週期
        atr_multiplier: ATR 倍數
        
    Returns:
        (Portfolio 對象, 包含止損信息的 DataFrame)
    """
    close = data['Close']
    
    # 計算 ATR 止損位
    stop_prices, atr = calculate_atr_stop_levels(
        data, entries, atr_period, atr_multiplier
    )
    
    # 檢測 ATR 止損觸發
    atr_stops = close <= stop_prices
    
    # 合併原始出場信號和 ATR 止損
    combined_exits = exits | atr_stops
    
    # 運行回測
    portfolio = vbt.Portfolio.from_signals(
        close=close,
        entries=entries,
        exits=combined_exits,
        init_cash=initial_cash,
        fees=fees,
        freq="1D"
    )
    
    # 創建報告 DataFrame
    report_df = pd.DataFrame({
        'Close': close,
        'Entry': entries,
        'Original_Exit': exits,
        'ATR': atr,
        'Stop_Price': stop_prices,
        'ATR_Stop': atr_stops,
        'Final_Exit': combined_exits
    }, index=data.index)
    
    print(f"\n✅ ATR 止損統計:")
    print(f"   ATR 週期: {atr_period}")
    print(f"   ATR 倍數: {atr_multiplier}")
    print(f"   觸發 ATR 止損次數: {atr_stops.sum()}")
    print(f"   原始出場信號次數: {exits.sum()}")
    print(f"   總出場次數: {combined_exits.sum()}")
    
    return portfolio, report_df
