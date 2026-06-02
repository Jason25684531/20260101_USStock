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
from typing import Dict
import pytz
import traceback

# APScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from adapters.market_data import download_and_save, fetch_data
from adapters.database import DatabaseAdapter
from adapters.notifier import send_signal, get_notifier
from adapters.broker import AlpacaBroker, MockBroker
from strategies import run_momentum_strategy, run_value_strategy
from config import DEFAULT_SYMBOLS
from screener.market_data_resilience import should_alert_degraded_data


# 向後相容：傳統模式只用 4 支, screener 模式用全部
SYMBOLS = os.getenv('SYMBOLS', 'SPY,QQQ,AAPL,NVDA').split(',')

# 美東時區
US_EASTERN = pytz.timezone('US/Eastern')

# 交易模式：'backtest'（回測）, 'paper'（Alpaca模擬）, 'simulation'（本地模擬）
TRADING_MODE = os.getenv('TRADING_MODE', 'backtest').lower()

# 策略類型：'traditional'（動量+價值）, 'ml'（機器學習策略）, 'screener'（每日選股推薦）
STRATEGY_TYPE = os.getenv('STRATEGY_TYPE', 'traditional').lower()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _optional_env_flag(name: str):
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def execute_trades(
    broker,
    target_positions: Dict[str, int],
    db: DatabaseAdapter,
    strategy_label: str = 'Paper Trading',
):
    """
    執行交易 - 計算目標倉位與實際倉位的差異並執行訂單
    
    Args:
        broker: Broker 適配器 (AlpacaBroker 或 MockBroker)
        target_positions: 策略目標倉位 {symbol: target_qty}
        db: 數據庫適配器
    
    Returns:
        List of executed trades
    """
    executed_trades = []
    
    # 獲取當前實際倉位
    try:
        current_positions = broker.get_positions()
    except Exception as e:
        print(f"❌ 無法獲取當前倉位: {e}")
        return executed_trades
    
    # 計算需要執行的交易
    all_symbols = set(target_positions.keys()) | set(current_positions.keys())
    
    for symbol in all_symbols:
        target_qty = target_positions.get(symbol, 0)
        current_qty = current_positions.get(symbol, 0)
        diff = target_qty - current_qty
        
        if diff == 0:
            continue
        
        # 執行訂單
        try:
            side = 'buy' if diff > 0 else 'sell'
            qty = abs(diff)
            
            print(f"\n📊 {symbol}: 目標={target_qty}, 當前={current_qty}, 差異={diff:+d}")
            
            order = broker.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                order_type='market'
            )
            
            executed_trades.append({
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'order_id': order['order_id'],
                'status': order['status']
            })
            
            # 記錄已由 Broker 自動完成（MockBroker._log_to_database）
            
            # 發送通知
            send_signal(
                symbol=symbol,
                action=side.upper(),
                price=broker.get_current_price(symbol),
                reason=f"策略調倉: {current_qty} -> {target_qty}",
                strategy=strategy_label
            )
            
        except Exception as e:
            print(f"❌ {symbol} 訂單執行失敗: {e}")
            get_notifier().send_error_alert(
                f"{symbol} 交易失敗",
                f"無法執行 {side} {qty} 股: {str(e)}"
            )
    
    return executed_trades


def job():
    """
    主執行任務 - 可被調度器調用
    
    執行完整的策略流程：
    1. 下載市場數據
    2. 執行策略
    3. 計算目標倉位
    4. (Paper Trading 模式) 執行實際交易
    5. 保存結果
    6. 發送通知
    """
    print(f"\n{'#'*60}")
    print(f"# 美股交易策略引擎 - 自動執行")
    print(f"# 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"# 交易模式: {TRADING_MODE.upper()}")
    print(f"# 策略類型: {STRATEGY_TYPE.upper()}")
    print(f"{'#'*60}\n")
    
    notifier = get_notifier()
    signals_generated = []
    broker = None
    db = None
    screener = None
    
    # 初始化 Broker
    if TRADING_MODE == 'paper':
        # Alpaca Paper Trading
        try:
            broker = AlpacaBroker(use_paper=True)
            account = broker.get_account()
            print(f"💰 Alpaca 帳戶資訊:")
            print(f"   現金: ${account['cash']:,.2f}")
            print(f"   購買力: ${account['buying_power']:,.2f}")
            print(f"   總權益: ${account['equity']:,.2f}\n")
        except Exception as e:
            error_msg = f"Alpaca Broker 初始化失敗: {e}"
            print(f"❌ {error_msg}")
            notifier.send_error_alert("Broker 連接失敗", error_msg)
            return
    
    elif TRADING_MODE == 'simulation':
        # 本地模擬交易（使用 MockBroker）
        try:
            broker = MockBroker()
            account = broker.get_account()
            print(f"💰 模擬帳戶資訊:")
            print(f"   現金: ${account['cash']:,.2f}")
            print(f"   購買力: ${account['buying_power']:,.2f}\n")
        except Exception as e:
            error_msg = f"Mock Broker 初始化失敗: {e}"
            print(f"❌ {error_msg}")
            notifier.send_error_alert("Mock Broker 失敗", error_msg)
            return
    
    elif TRADING_MODE != 'backtest':
        print(f"⚠️  不支持的交易模式: {TRADING_MODE}，將使用 backtest 模式")
        # Note: TRADING_MODE 是全局常量，此處不修改
    
    try:
        download_results = {'success': [], 'failed': []}
        if STRATEGY_TYPE == 'screener':
            print("【步驟 1/4】 跳過通用市場數據下載，直接走 DailyScreener 官方排程路徑")
        else:
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
        
        # 步驟 2: 執行策略
        db = DatabaseAdapter()
        momentum_results = {}
        target_positions = {}  # 策略目標倉位
        
        if STRATEGY_TYPE == 'screener':
            # === 每日選股推薦模式 ===
            print("\n【步驟 2/4】 執行每日選股推薦")
            from screener.engine import DailyScreener

            try:
                screener = DailyScreener(
                    symbols=None,
                    use_ml=_optional_env_flag('USE_ML'),
                    top_n=int(os.getenv('SCREENER_TOP_N', '5')),
                )
                df_scan = screener.scan_all()
                recommendations = screener.get_top_recommendations(df_scan)

                # 存入 DB
                wrote_recommendations = screener.save_to_db(recommendations)
                run_summary = getattr(screener, 'last_run_summary', {}) or {}

                # 發送 Flex Message 推薦報告
                if notifier.is_enabled and wrote_recommendations:
                    notifier.send_flex_report(recommendations)
                elif notifier.is_enabled and should_alert_degraded_data(run_summary):
                    notifier.send_error_alert(
                        "Screener data degraded",
                        run_summary.get('provider_health_summary')
                        or run_summary.get('write_blocked_reason')
                        or 'provider degradation detected',
                    )

                if wrote_recommendations:
                    for rec in recommendations:
                        signals_generated.append({
                            'symbol': rec['symbol'],
                            'action': rec['signal'],
                            'price': rec['current_price'],
                            'strategy': 'Screener',
                            'confidence': rec['total_score'] / 5.0,
                        })


            except Exception as e:
                print(f"❌ 選股推薦執行失敗: {str(e)}")
                traceback.print_exc()

        elif STRATEGY_TYPE == 'ml':
            # === ML 策略模式 ===
            print("\n【步驟 2/4】 執行 ML 策略")
            from strategies.ml_strategy import MLStrategy
            
            try:
                ml_strategy = MLStrategy()
                df_signals = ml_strategy.scan_multiple_symbols(
                    list(download_results['success'])
                )
                
                # === Top-N Confidence Ranking ===
                # 只對信心度最高的前 5 檔 BUY 信號下單
                TOP_N = int(os.getenv('ML_TOP_N', '5'))
                buy_signals = df_signals[df_signals['signal'] == 'BUY'].copy()
                if len(buy_signals) > TOP_N:
                    buy_signals = buy_signals.nlargest(TOP_N, 'confidence')
                    print(f"   🏆 Top-{TOP_N} Confidence 篩選: "
                          f"{len(df_signals[df_signals['signal']=='BUY'])} → {len(buy_signals)} 檔")
                
                # === Hysteresis Filter ===
                # 只有新信號 confidence 比既有持倉信號高出 15% 以上才輪換
                # 減少手續費侵蝕 (0.1% per trade)
                HYSTERESIS_THRESHOLD = float(os.getenv('HYSTERESIS_THRESHOLD', '0.15'))
                if broker:
                    current_positions = broker.get_positions()
                    if current_positions:
                        kept_symbols = set()
                        new_buy_list = []
                        for _, row in buy_signals.iterrows():
                            sym = row['symbol']
                            conf = row['confidence']
                            if sym in current_positions:
                                # 已持有 → 直接保留，無需輪換
                                kept_symbols.add(sym)
                                new_buy_list.append(row)
                            else:
                                # 新標的 → 檢查是否 confidence 足夠高
                                # 比較對象：current Top-N 中 confidence 最低者
                                min_held_conf = 0.0
                                for prev_sig in signals_generated:
                                    if prev_sig.get('strategy') == 'ML' and prev_sig['action'] == 'BUY':
                                        if prev_sig['symbol'] in current_positions:
                                            min_held_conf = max(min_held_conf, prev_sig.get('confidence', 0))
                                if min_held_conf == 0 or conf >= min_held_conf + HYSTERESIS_THRESHOLD:
                                    new_buy_list.append(row)
                                else:
                                    print(f"   🔒 Hysteresis: {sym} confidence={conf:.2f} "
                                          f"< 持倉最低 {min_held_conf:.2f}+{HYSTERESIS_THRESHOLD}, 不輪換")
                        if new_buy_list:
                            buy_signals = pd.DataFrame(new_buy_list)
                
                # 合併 SELL（全部保留）+ 篩選後的 BUY
                sell_signals = df_signals[df_signals['signal'] == 'SELL']
                selected_signals = pd.concat([buy_signals, sell_signals], ignore_index=True)
                
                for _, row in selected_signals.iterrows():
                    if row['signal'] == 'BUY':
                        target_positions[row['symbol']] = 10
                        signals_generated.append({
                            'symbol': row['symbol'],
                            'action': 'BUY',
                            'price': row['price'],
                            'strategy': 'ML',
                            'confidence': row['confidence']
                        })
                        print(f"   [ML Strategy] Signal: BUY {row['symbol']} "
                              f"Confidence: {row['confidence']:.2f}")
                    elif row['signal'] == 'SELL':
                        target_positions[row['symbol']] = 0
                        signals_generated.append({
                            'symbol': row['symbol'],
                            'action': 'SELL',
                            'price': row['price'],
                            'strategy': 'ML',
                            'confidence': row['confidence']
                        })
                        print(f"   [ML Strategy] Signal: SELL {row['symbol']} "
                              f"Confidence: {row['confidence']:.2f}")
                
                ml_strategy.close()
                
            except Exception as e:
                print(f"❌ ML 策略執行失敗: {str(e)}")
                traceback.print_exc()
        
        else:
            # === 傳統策略模式 ===
            print("\n【步驟 2/4】 執行動量策略")
        
            for symbol in download_results['success']:
                try:
                    data = db.get_market_data(symbol)
                    
                    if data.empty:
                        print(f"⚠️  {symbol}: 數據庫中無數據，跳過")
                        continue
                    
                    portfolio = run_momentum_strategy(data, lookback_period=200)
                    
                    # 檢查是否有新信號並計算目標倉位
                    if hasattr(portfolio, 'trades') and portfolio.trades.count() > 0:
                        last_trade = portfolio.trades.records_readable.iloc[-1]
                        if last_trade['Exit Timestamp'] is None:  # 持倉中
                            # 簡單策略：有信號則持有 10 股，無信號則 0 股
                            target_positions[symbol] = 10
                            
                            signals_generated.append({
                                'symbol': symbol,
                                'action': 'BUY',
                                'price': float(data['Close'].iloc[-1]),
                                'strategy': 'Momentum'
                            })
                        else:
                            target_positions[symbol] = 0
                    else:
                        target_positions[symbol] = 0
                    
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
        
        # 步驟 3: 執行價值策略 (僅在回測模式且傳統策略)
        value_results = {}
        
        if TRADING_MODE == 'backtest' and STRATEGY_TYPE == 'traditional':
            print(f"\n【步驟 3/4】 執行價值策略")
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
        else:
            print(f"\n【步驟 3/4】 跳過價值策略 (ML/Paper Trading 模式)")
        
        # 步驟 4: 執行交易 (僅在 paper/simulation 模式)
        executed_trades = []
        if TRADING_MODE in ('paper', 'simulation') and broker:
            print(f"\n【步驟 4/4】 執行實際交易")
            strategy_label = 'Simulation Trading' if TRADING_MODE == 'simulation' else 'Paper Trading'
            executed_trades = execute_trades(broker, target_positions, db, strategy_label=strategy_label)
            print(f"✅ 已執行 {len(executed_trades)} 筆交易")
        else:
            print(f"\n【步驟 4/4】 跳過交易執行 (回測模式)")
        
        
        # 發送交易信號通知 (僅在回測模式)
        if TRADING_MODE == 'backtest':
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
            top_performers = list(download_results['success'][:3]) or [
                signal['symbol'] for signal in signals_generated[:3]
            ]
            notifier.send_daily_summary(
                total_trades=len(executed_trades) if TRADING_MODE in ('paper', 'simulation') else len(signals_generated),
                pnl=0.0,  # 需要實際計算
                win_rate=0.0,
                top_performers=top_performers
            )
        
        # 打印最終摘要
        print(f"\n{'#'*60}")
        print(f"# 執行完成摘要")
        print(f"{'#'*60}")
        print(f"交易模式: {TRADING_MODE.upper()}")
        print(f"數據下載: {len(download_results['success'])} 成功, {len(download_results['failed'])} 失敗")
        print(f"動量策略: {len(momentum_results)} 個回測已保存")
        
        if TRADING_MODE == 'backtest':
            print(f"價值策略: {len(value_results)} 個回測已保存")
            print(f"信號發送: {len(signals_generated)} 個")
        else:
            print(f"實際交易: {len(executed_trades)} 筆已執行")
            if broker:
                account = broker.get_account()
                print(f"帳戶權益: ${account['equity']:,.2f}")
        
        print(f"{'#'*60}\n")
        
        print("✅ 任務完成！")
        
    except Exception as e:
        error_msg = f"策略執行異常: {str(e)}"
        print(f"❌ {error_msg}")
        notifier.send_error_alert("系統異常", error_msg)
        traceback.print_exc()
        if _env_flag('USE_SCHEDULER', default=False):
            return
        raise
    finally:
        if screener is not None:
            try:
                screener.close()
            except Exception as close_error:
                print(f"??  DailyScreener close 憭望?: {close_error}")
        if db is not None:
            try:
                db.close()
            except Exception as close_error:
                print(f"??  DatabaseAdapter close 憭望?: {close_error}")


def run_scheduler():
    """
    啟動定時調度器
    
    每個交易日美東時間 16:15（收盤後15分鐘）執行策略
    """
    print("\n" + "="*60)
    print("🕐 啟動定時調度器")
    print("="*60)
    scheduler_hour = int(os.getenv('SCHEDULER_HOUR', '16'))
    scheduler_minute = int(os.getenv('SCHEDULER_MINUTE', '15'))
    print(f"調度時間: 每個交易日 {scheduler_hour:02d}:{scheduler_minute:02d} EST (美東時間)")
    print(f"當前時間: {datetime.now(US_EASTERN).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("="*60 + "\n")

    scheduler = BlockingScheduler(timezone=US_EASTERN)
    
    # 每個交易日（週一到週五）16:15 執行
    scheduler.add_job(
        job,
        CronTrigger(
            day_of_week='mon-fri',
            hour=scheduler_hour,
            minute=scheduler_minute,
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
