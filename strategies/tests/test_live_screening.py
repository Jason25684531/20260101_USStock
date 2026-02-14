"""
實時選股測試腳本
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path('strategies/src')))

import yfinance as yf
import pandas as pd
from config import evaluate_stock_rules_v2

# 選擇測試股票
symbols = ['AAPL', 'MSFT', 'NVDA']

print('🔍 正在下載數據並評分...\n')

for symbol in symbols:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period='1y')
        info = ticker.info
        
        result = evaluate_stock_rules_v2(df, info)
        
        print(f'📊 {symbol}:')
        print(f'   綜合評分: {result["rule_score"]:.2f} / {result["total_strategies"]}')
        print(f'   通過策略數: {result["passes"]} (閾值: {result.get("min_passes", "?")})') 
        print(f'   通過率: {result["passes"]/result["total_strategies"]*100:.1f}%')
        
        # 列出通過的策略
        passed = [name for name, res in result['all_results'].items() if res['pass']]
        if passed:
            print(f'   ✓ 通過: {", ".join(passed[:5])}{"..." if len(passed) > 5 else ""}')
        print()
            
    except Exception as e:
        print(f'❌ {symbol}: {str(e)}\n')

print('✅ 測試完成')
