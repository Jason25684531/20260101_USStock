"""
Main entry point for the US Stock Trading Strategy Engine.

This script orchestrates the entire backtesting pipeline:
1. Download market data from yfinance
2. Save data to MySQL database
3. Run Momentum and Value strategies
4. Save backtest results to database
5. Send notifications via Line Bot

Supports both one-time execution and scheduled operation.

Author: Quant System
Created: 2025-12-31
Updated: 2026-01-31 - Added APScheduler and Line Bot notifications
"""

import sys
import os
from datetime import datetime
import pytz

# APScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from adapters.market_data import download_and_save, fetch_data
from adapters.database import DatabaseAdapter
from adapters.notifier import send_signal, get_notifier
from strategies import run_momentum_strategy, run_value_strategy


# 交易標的列表
SYMBOLS = ['SPY', 'QQQ', 'AAPL', 'NVDA']

# 美東時區
US_EASTERN = pytz.timezone('US/Eastern')


def job():
    """
    主執行任務 - 可被調度器調用
    
    執行完整的策略流程：
    1. 下載市場數據
    2. 執行策略
    3. 保存結果
    4. 發送通知
    """
    print(f"\n{'#'*60}")
    print(f"# 美股交易策略引擎 - 自動執行")
    print(f"# 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}\n")
    
    notifier = get_notifier()
    signals_generated = []
    
    try:
        # 步驟 1: 下載並保存市場數據
        print("【步驟 1/3】 下載市場數據")
        download_results = download_and_save(
            symbols=SYMBOLS,
            period='2y',
            interval='1d'
        )
        
        if not download_results['success']:
            error_msg = "沒有成功下載任何數據"
            print(f"❌ {error_msg}")
            notifier.send_error_alert("數據下載失敗", error_msg)
            return
        
        # 步驟 2: 執行動量策略
        print("\n【步驟 2/3】 執行動量策略")
        db = DatabaseAdapter()
        momentum_results = {}
        
        for symbol in download_results['success']:
            try:
                data = db.get_market_data(symbol)
                
                if data.empty:
                    print(f"⚠️  {symbol}: 數據庫中無數據，跳過")
                    continue
                
                portfolio = run_momentum_strategy(data, lookback_period=200)
                
                # 檢查是否有新信號
                if hasattr(portfolio, 'trades') and portfolio.trades.count() > 0:
                    last_trade = portfolio.trades.records_readable.iloc[-1]
                    if last_trade['Exit Timestamp'] is None:  # 持倉中
                        signals_generated.append({
                            'symbol': symbol,
                            'action': 'BUY',
                            'price': float(data['Close'].iloc[-1]),
                            'strategy': 'Momentum'
                        })
                
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
                data = db.get_market_data(symbol)
                
                if data.empty:
                    continue
                
                portfolio = run_value_strategy(data, pe_threshold=15, pb_threshold=1.5)
                
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
        
        # 發送交易信號通知
        for signal in signals_generated:
            send_signal(
                symbol=signal['symbol'],
                action=signal['action'],
                price=signal['price'],
                reason="動量突破信號",
                strategy=signal['strategy']
            )
        
        # 發送每日摘要
        if notifier.is_enabled:
            notifier.send_daily_summary(
                total_trades=len(signals_generated),
                pnl=0.0,  # 需要實際計算
                win_rate=0.0,
                top_performers=list(download_results['success'][:3])
            )
        
        # 打印最終摘要
        print(f"\n{'#'*60}")
        print(f"# 執行完成摘要")
        print(f"{'#'*60}")
        print(f"數據下載: {len(download_results['success'])} 成功, {len(download_results['failed'])} 失敗")
        print(f"動量策略: {len(momentum_results)} 個回測已保存")
        print(f"價值策略: {len(value_results)} 個回測已保存")
        print(f"信號發送: {len(signals_generated)} 個")
        print(f"{'#'*60}\n")
        
        print("✅ 任務完成！")
        
    except Exception as e:
        error_msg = f"策略執行異常: {str(e)}"
        print(f"❌ {error_msg}")
        notifier.send_error_alert("系統異常", error_msg)
        raise


def run_scheduler():
    """
    啟動定時調度器
    
    每個交易日美東時間 16:15（收盤後15分鐘）執行策略
    """
    print("\n" + "="*60)
    print("🕐 啟動定時調度器")
    print("="*60)
    print(f"調度時間: 每個交易日 16:15 EST (美東時間)")
    print(f"當前時間: {datetime.now(US_EASTERN).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("="*60 + "\n")
    
    scheduler = BlockingScheduler(timezone=US_EASTERN)
    
    # 每個交易日（週一到週五）16:15 執行
    scheduler.add_job(
        job,
        CronTrigger(
            day_of_week='mon-fri',
            hour=16,
            minute=15,
            timezone=US_EASTERN
        ),
        id='daily_strategy_job',
        name='每日策略執行',
        replace_existing=True
    )
    
    # 添加一個立即執行的測試任務（可選，用於驗證）
    # scheduler.add_job(job, 'date', run_date=datetime.now(US_EASTERN))
    
    print("📅 已添加定時任務:")
    for job_info in scheduler.get_jobs():
        print(f"   - {job_info.name}: {job_info.trigger}")
    
    print("\n🚀 調度器開始運行，按 Ctrl+C 停止...\n")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n⚠️  調度器已停止")
        scheduler.shutdown()


def main():
    """主入口函數"""
    # 檢查是否使用調度器模式
    use_scheduler = os.getenv('USE_SCHEDULER', 'false').lower() == 'true'
    
    if use_scheduler:
        run_scheduler()
    else:
        # 單次執行模式
        job()


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
