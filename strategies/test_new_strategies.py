"""
測試新策略：Chips + Momentum 和 Growth (PEG)

這個腳本測試新實現的策略功能，包括：
1. 基本面數據獲取
2. Chips + Momentum 策略
3. Growth (PEG) 策略
4. ATR 追蹤止損

Author: Quant System
Created: 2026-01-31
"""

import sys
import os
from datetime import datetime

# 添加 src 目錄到路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from adapters.market_data import fetch_data, fetch_fundamentals
from adapters.database import DatabaseAdapter
from strategies.chips_momentum import run_strategy as run_chips_strategy
from strategies.growth_peg import run_strategy as run_peg_strategy
from core.backtest import calculate_atr, calculate_atr_stop_levels


def test_fundamentals():
    """測試基本面數據獲取"""
    print("\n" + "="*80)
    print("測試 1: 基本面數據獲取")
    print("="*80)
    
    symbols = ['NVDA', 'TSLA', 'AAPL']
    
    for symbol in symbols:
        print(f"\n獲取 {symbol} 基本面數據...")
        fundamentals = fetch_fundamentals(symbol)
        
        if fundamentals:
            print(f"  PEG 比率: {fundamentals.get('peg_ratio', 'N/A')}")
            print(f"  PE 比率: {fundamentals.get('pe_ratio', 'N/A')}")
            print(f"  營收增長率: {fundamentals.get('revenue_growth_yoy', 'N/A')}")
            print(f"  機構持股: {fundamentals.get('inst_ownership_pct', 'N/A')}")
            print(f"  市值: ${fundamentals.get('market_cap', 0):,}")


def test_chips_strategy():
    """測試 Chips + Momentum 策略"""
    print("\n" + "="*80)
    print("測試 2: Chips + Momentum 策略")
    print("="*80)
    
    symbol = 'NVDA'
    
    # 獲取市場數據
    print(f"\n下載 {symbol} 市場數據...")
    df = fetch_data(symbol, period='1y')
    
    # 獲取基本面數據
    print(f"獲取 {symbol} 基本面數據...")
    fundamentals = fetch_fundamentals(symbol)
    inst_ownership = fundamentals.get('inst_ownership_pct')
    
    # 運行策略
    df_signals, report = run_chips_strategy(
        df=df,
        symbol=symbol,
        inst_ownership_pct=inst_ownership,
        sma_period=50,
        min_inst_ownership=0.60
    )
    
    print("\n策略報告:")
    for key, value in report.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
    
    return df_signals, report


def test_peg_strategy():
    """測試 Growth (PEG) 策略"""
    print("\n" + "="*80)
    print("測試 3: Growth (PEG) 策略")
    print("="*80)
    
    symbol = 'NVDA'
    
    # 獲取市場數據
    print(f"\n下載 {symbol} 市場數據...")
    df = fetch_data(symbol, period='1y')
    
    # 獲取基本面數據
    print(f"獲取 {symbol} 基本面數據...")
    fundamentals = fetch_fundamentals(symbol)
    peg_ratio = fundamentals.get('peg_ratio')
    revenue_growth = fundamentals.get('revenue_growth_yoy')
    
    # 運行策略
    df_signals, report = run_peg_strategy(
        df=df,
        symbol=symbol,
        peg_ratio=peg_ratio,
        revenue_growth_yoy=revenue_growth,
        max_peg=1.5,
        min_revenue_growth=0.20
    )
    
    print("\n策略報告:")
    for key, value in report.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
    
    return df_signals, report


def test_atr():
    """測試 ATR 計算"""
    print("\n" + "="*80)
    print("測試 4: ATR 追蹤止損")
    print("="*80)
    
    symbol = 'AAPL'
    
    # 獲取市場數據
    print(f"\n下載 {symbol} 市場數據...")
    df = fetch_data(symbol, period='3mo')
    
    # 計算 ATR
    atr = calculate_atr(df, period=14)
    
    print(f"\nATR 統計:")
    print(f"  平均 ATR: ${atr.mean():.2f}")
    print(f"  最小 ATR: ${atr.min():.2f}")
    print(f"  最大 ATR: ${atr.max():.2f}")
    print(f"  最近 ATR: ${atr.iloc[-1]:.2f}")
    
    # 測試止損計算
    latest_price = df['Close'].iloc[-1]
    latest_atr = atr.iloc[-1]
    
    print(f"\n假設在 ${latest_price:.2f} 入場:")
    for multiplier in [1.5, 2.0, 2.5]:
        stop_price = latest_price - (latest_atr * multiplier)
        stop_pct = ((stop_price - latest_price) / latest_price) * 100
        print(f"  {multiplier}x ATR 止損: ${stop_price:.2f} ({stop_pct:.2f}%)")


def main():
    """主測試函數"""
    print("\n" + "="*80)
    print("🚀 開始測試安全增強和策略擴展功能")
    print("="*80)
    print(f"測試時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # 測試 1: 基本面數據
        test_fundamentals()
        
        # 測試 2: Chips 策略
        test_chips_strategy()
        
        # 測試 3: PEG 策略
        test_peg_strategy()
        
        # 測試 4: ATR
        test_atr()
        
        print("\n" + "="*80)
        print("✅ 所有測試完成！")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ 測試失敗: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
