#!/usr/bin/env python3
"""
快速填充回測績效數據

用途：在數據庫中生成模擬回測記錄，讓前端頁面有數據可顯示
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# 添加專案路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "web"))

from dotenv import load_dotenv
load_dotenv(dotenv_path=project_root / ".env")

from sqlalchemy import text
from db import get_engine


def create_sample_backtest_data(engine):
    """創建示範回測數據"""
    print("\n📊 創建示範回測數據...")
    
    # 策略配置
    strategies = [
        {
            'name': 'Enhanced Multi-Strategy (11 Rules + ML)',
            'total_return': 28.5,
            'sharpe_ratio': 1.85,
            'max_drawdown': -12.3
        },
        {
            'name': 'Breakout + Acceleration',
            'total_return': 22.1,
            'sharpe_ratio': 1.62,
            'max_drawdown': -15.8
        },
        {
            'name': 'PEG + DuPont Quality',
            'total_return': 18.7,
            'sharpe_ratio': 1.45,
            'max_drawdown': -11.2
        },
        {
            'name': 'Multi-TF Momentum',
            'total_return': 25.3,
            'sharpe_ratio': 1.71,
            'max_drawdown': -14.5
        },
    ]
    
    # 回測時間範圍
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=365)  # 一年
    
    with engine.begin() as conn:
        # 先清空舊數據（可選）
        # conn.execute(text("DELETE FROM backtest_runs"))
        # conn.execute(text("DELETE FROM equity_curve"))
        # conn.execute(text("DELETE FROM trade_logs"))
        
        for idx, strat in enumerate(strategies, 1):
            # 插入回測運行記錄
            result = conn.execute(text("""
                INSERT INTO backtest_runs 
                (strategy_name, start_date, end_date, total_return, sharpe_ratio, 
                 max_drawdown, created_at)
                VALUES 
                (:strategy_name, :start_date, :end_date, :total_return, :sharpe_ratio,
                 :max_drawdown, NOW())
            """), {
                'strategy_name': strat['name'],
                'start_date': start_date,
                'end_date': end_date,
                'total_return': strat['total_return'],
                'sharpe_ratio': strat['sharpe_ratio'],
                'max_drawdown': strat['max_drawdown']
            })
            
            run_id = result.lastrowid
            print(f"  ✅ 創建回測 #{run_id}: {strat['name']}")
            
            # 生成權益曲線（每天）
            days = (end_date - start_date).days
            base_equity = 100000.0
            current_equity = base_equity
            
            equity_points = []
            for day in range(0, days + 1, 7):  # 每週一個點
                date = start_date + timedelta(days=day)
                
                # 模擬權益增長（帶波動）
                progress = day / days
                target_equity = base_equity * (1 + strat['total_return'] / 100)
                expected_equity = base_equity + (target_equity - base_equity) * progress
                
                # 添加隨機波動
                import random
                volatility = abs(strat['max_drawdown']) / 100 * base_equity * 0.3
                noise = random.uniform(-volatility, volatility)
                current_equity = expected_equity + noise
                
                # 確保不低於最大回撤
                min_equity = base_equity * (1 + strat['max_drawdown'] / 100)
                current_equity = max(current_equity, min_equity)
                
                equity_points.append({
                    'run_id': run_id,
                    'date': date,
                    'equity_value': round(current_equity, 2)
                })
            
            # 批量插入權益曲線
            if equity_points:
                conn.execute(text("""
                    INSERT INTO equity_curve (run_id, date, equity_value)
                    VALUES (:run_id, :date, :equity_value)
                """), equity_points)
                print(f"     └─ 生成 {len(equity_points)} 個權益點")
            
            # 生成示範交易記錄
            trade_samples = [
                {'symbol': 'AAPL', 'entry': 150.00, 'exit': 165.50, 'shares': 100, 'days': 21},
                {'symbol': 'MSFT', 'entry': 350.00, 'exit': 338.20, 'shares': 50, 'days': 15},
                {'symbol': 'NVDA', 'entry': 480.00, 'exit': 525.00, 'shares': 30, 'days': 28},
                {'symbol': 'GOOGL', 'entry': 140.00, 'exit': 152.80, 'shares': 80, 'days': 18},
                {'symbol': 'META', 'entry': 320.00, 'exit': 348.50, 'shares': 40, 'days': 25},
            ]
            
            trades = []
            current_date = start_date + timedelta(days=30)
            num_trades = 15 + idx * 5  # 每個策略不同的交易數量
            
            for i in range(num_trades):
                sample = trade_samples[i % len(trade_samples)]
                
                entry_date = current_date + timedelta(days=i * 8)
                exit_date = entry_date + timedelta(days=sample['days'])
                
                if exit_date > end_date:
                    break
                
                pnl = (sample['exit'] - sample['entry']) * sample['shares']
                
                trades.append({
                    'run_id': run_id,
                    'symbol': sample['symbol'],
                    'entry_date': entry_date,
                    'entry_price': sample['entry'],
                    'exit_date': exit_date,
                    'exit_price': sample['exit'],
                    'pnl': round(pnl, 2)
                })
            
            if trades:
                conn.execute(text("""
                    INSERT INTO trade_logs 
                    (run_id, symbol, entry_date, entry_price, exit_date, exit_price, pnl)
                    VALUES 
                    (:run_id, :symbol, :entry_date, :entry_price, :exit_date, :exit_price, :pnl)
                """), trades)
                print(f"     └─ 生成 {len(trades)} 筆交易記錄")
    
    print("\n✅ 回測數據創建完成！")


def main():
    print("=" * 60)
    print(" 📊 填充示範回測績效數據")
    print("=" * 60)
    
    engine = get_engine()
    
    try:
        create_sample_backtest_data(engine)
        print("\n🎉 前端回測頁面現在應該有數據可顯示了！")
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
