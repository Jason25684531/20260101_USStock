"""
Backtesting Engine using VectorBT for the US Stock Trading System.

This module implements vectorized backtesting strategies using VectorBT.
All operations must be vectorized (no for loops for data iteration).

Author: Quant System
Created: 2025-12-31
"""

from typing import Tuple
import pandas as pd
import numpy as np
import vectorbt as vbt


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
