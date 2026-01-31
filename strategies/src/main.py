"""
Main entry point for the US Stock Trading Strategy Engine.

This script orchestrates the entire backtesting pipeline:
1. Download market data from yfinance
2. Save data to MySQL database
3. Run Momentum and Value strategies
4. Save backtest results to database

Author: Quant System
Created: 2025-12-31
Updated: 2026-01-31 - Added MVP strategies implementation
"""

import sys
import os
from datetime import datetime
from adapters.market_data import download_and_save, fetch_data
from adapters.database import DatabaseAdapter
from strategies import run_momentum_strategy, run_value_strategy


# 交易標的列表
SYMBOLS = ['SPY', 'QQQ', 'AAPL', 'NVDA']


def main():
    """主執行函數"""
    print(f"\n{'#'*60}")
    print(f"# 美股交易策略引擎 - MVP 版本")
    print(f"# 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}\n")
    
    # 步驟 1: 下載並保存市場數據
    print("【步驟 1/3】 下載市場數據")
    download_results = download_and_save(
        symbols=SYMBOLS,
        period='2y',  # 下載 2 年數據以確保有足夠的回看期
        interval='1d'
    )
    
    if not download_results['success']:
        print("❌ 沒有成功下載任何數據，退出程序")
        sys.exit(1)
    
    # 步驟 2: 執行動量策略
    print("【步驟 2/3】 執行動量策略")
    db = DatabaseAdapter()
    momentum_results = {}
    
    for symbol in download_results['success']:
        try:
            # 從數據庫讀取數據
            data = db.get_market_data(symbol)
            
            if data.empty:
                print(f"⚠️  {symbol}: 數據庫中無數據，跳過")
                continue
            
            # 執行策略
            portfolio = run_momentum_strategy(data, lookback_period=200)
            
            # 保存結果
            run_id = db.save_backtest_run(
                portfolio,
                strategy_name=f'Momentum-{symbol}',
                start_date=str(data.index[0].date()),
                end_date=str(data.index[-1].date())
            )
            
            momentum_results[symbol] = run_id
            print(f"✅ {symbol}: 動量策略結果已保存 (run_id={run_id})")
            
        except Exception as e:
            print(f"❌ {symbol}: 動量策略執行失敗 - {str(e)}")
    
    # 步驟 3: 執行價值策略
    print("\n【步驟 3/3】 執行價值策略")
    value_results = {}
    
    for symbol in download_results['success']:
        try:
            # 從數據庫讀取數據
            data = db.get_market_data(symbol)
            
            if data.empty:
                print(f"⚠️  {symbol}: 數據庫中無數據，跳過")
                continue
            
            # 執行策略
            portfolio = run_value_strategy(data, pe_threshold=15, pb_threshold=1.5)
            
            # 保存結果
            run_id = db.save_backtest_run(
                portfolio,
                strategy_name=f'Value-{symbol}',
                start_date=str(data.index[0].date()),
                end_date=str(data.index[-1].date())
            )
            
            value_results[symbol] = run_id
            print(f"✅ {symbol}: 價值策略結果已保存 (run_id={run_id})")
            
        except Exception as e:
            print(f"❌ {symbol}: 價值策略執行失敗 - {str(e)}")
    
    db.close()
    
    # 打印最終摘要
    print(f"\n{'#'*60}")
    print(f"# 執行完成摘要")
    print(f"{'#'*60}")
    print(f"數據下載: {len(download_results['success'])} 成功, {len(download_results['failed'])} 失敗")
    print(f"動量策略: {len(momentum_results)} 個回測已保存")
    print(f"價值策略: {len(value_results)} 個回測已保存")
    print(f"{'#'*60}\n")
    
    print("✅ 所有任務完成！請訪問 http://localhost:5000 查看儀表板\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  程序被用戶中斷")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 程序執行失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
