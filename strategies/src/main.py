"""
Main entry point for the US Stock Trading Strategy Engine.

This script orchestrates the entire backtesting pipeline:
1. Fetch market data
2. Run VectorBT strategy
3. Print performance report

Author: Quant System
Created: 2025-12-31
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from adapters import fetch_data
from core import run_sma_strategy, print_performance_report
from utils import is_production


def generate_mock_data(symbol: str, days: int = 252) -> pd.DataFrame:
    """
    Generate mock OHLCV data for testing when network is unavailable.
    
    Args:
        symbol: Stock ticker symbol (for reference)
        days: Number of trading days to generate
        
    Returns:
        DataFrame with mock OHLCV data
    """
    print(f"⚠️  Using mock data generation (network unavailable)")
    
    # Generate dates
    end_date = datetime.now()
    dates = pd.date_range(end=end_date, periods=days, freq='B')
    
    # Generate realistic price data with trend
    np.random.seed(42)
    base_price = 400.0
    returns = np.random.normal(0.001, 0.02, days)
    prices = base_price * (1 + returns).cumprod()
    
    # Generate OHLCV
    data = pd.DataFrame({
        'Open': prices * (1 + np.random.uniform(-0.01, 0.01, days)),
        'High': prices * (1 + np.random.uniform(0.005, 0.02, days)),
        'Low': prices * (1 + np.random.uniform(-0.02, -0.005, days)),
        'Close': prices,
        'Volume': np.random.randint(50000000, 150000000, days)
    }, index=dates)
    
    return data


def main():
    """
    Main execution function for the strategy engine.
    """
    print("="*60)
    print("🚀 US Stock Trading System - Strategy Engine")
    print("="*60)
    print(f"Environment: {'Production (Docker)' if is_production() else 'Local Development'}")
    print()
    
    # Configuration
    SYMBOL = "SPY"
    PERIOD = "1y"
    FAST_WINDOW = 20
    SLOW_WINDOW = 50
    INITIAL_CASH = 10000.0
    
    try:
        # Step 1: Fetch market data
        print(f"📊 Step 1: Fetching market data for {SYMBOL}...")
        
        try:
            data = fetch_data(symbol=SYMBOL, period=PERIOD, interval="1d")
        except Exception as e:
            print(f"⚠️  Network fetch failed: {e}")
            print(f"   Switching to mock data generation...")
            data = generate_mock_data(SYMBOL, days=252)
        
        if data.empty:
            print("❌ Error: No data available. Exiting.")
            sys.exit(1)
        
        # Step 2: Run SMA strategy
        print(f"\n📈 Step 2: Running SMA Strategy...")
        portfolio, signals = run_sma_strategy(
            data=data,
            fast_window=FAST_WINDOW,
            slow_window=SLOW_WINDOW,
            initial_cash=INITIAL_CASH,
            fees=0.001  # 0.1% trading fees
        )
        
        # Step 3: Print performance report
        print(f"\n📊 Step 3: Generating Performance Report...")
        print_performance_report(portfolio, symbol=SYMBOL)
        
        # Optional: Show first few signals
        signal_entries = signals[signals["Entry"] | signals["Exit"]]
        if not signal_entries.empty:
            print("\n📋 Sample Signals (First 5 Entries):")
            print(signal_entries.head())
        
        print("\n✅ Strategy execution completed successfully!")
        print("="*60)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error during strategy execution: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
