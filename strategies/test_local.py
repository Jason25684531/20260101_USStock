"""
測試腳本：在本地生成測試數據並插入數據庫
用於驗證系統功能（當 Docker 容器無法訪問外部網絡時）
"""
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 添加 src 目錄到路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from adapters.database import DatabaseAdapter
from strategies import run_momentum_strategy, run_value_strategy


def generate_mock_data(symbol: str, days: int = 504) -> pd.DataFrame:
    """生成模擬的市場數據"""
    print(f"📊 生成 {symbol} 的模擬數據 ({days} 天)...")
    
    # 生成日期範圍
    end_date = datetime.now()
    dates = pd.date_range(end=end_date, periods=days, freq='D')
    
    # 生成價格數據（帶有趨勢和波動）
    np.random.seed(42 + hash(symbol) % 100)
    
    # 不同股票的基礎價格
    base_prices = {'SPY': 400, 'QQQ': 350, 'AAPL': 150, 'NVDA': 400}
    base_price = base_prices.get(symbol, 100)
    
    # 生成帶有趨勢的收益率
    trend = np.linspace(0, 0.3, days)  # 30% 的總增長趨勢
    volatility = 0.02
    daily_returns = np.random.normal(trend / days, volatility, days)
    prices = base_price * np.exp(np.cumsum(daily_returns))
    
    # 生成 OHLCV 數據
    df = pd.DataFrame({
        'Open': prices * (1 + np.random.uniform(-0.01, 0.01, days)),
        'High': prices * (1 + np.random.uniform(0.005, 0.02, days)),
        'Low': prices * (1 + np.random.uniform(-0.02, -0.005, days)),
        'Close': prices,
        'Volume': np.random.randint(50000000, 150000000, days),
        'Adj Close': prices
    }, index=dates)
    
    # 添加基本面數據（模擬）
    df['pe_ratio'] = np.random.uniform(12, 18, days)
    df['pb_ratio'] = np.random.uniform(1.0, 2.0, days)
    
    print(f"✅ 已生成 {len(df)} 行數據")
    return df


def main():
    """主測試函數"""
    print("\n" + "="*60)
    print("本地測試腳本 - 生成模擬數據並測試策略")
    print("="*60 + "\n")
    
    # 設置環境變量連接到本地 Docker 數據庫
    os.environ['DB_HOST'] = 'localhost'
    os.environ['DB_PORT'] = '3308'
    os.environ['DB_USER'] = 'root'
    os.environ['DB_PASSWORD'] = 'rootpassword'
    os.environ['DB_NAME'] = 'usstock'
    
    symbols = ['SPY', 'QQQ', 'AAPL', 'NVDA']
    db = DatabaseAdapter()
    
    # 步驟 1: 生成並保存市場數據
    print("\n【步驟 1/3】生成並保存市場數據")
    for symbol in symbols:
        df = generate_mock_data(symbol, days=504)  # 2 年數據
        db.save_market_data(df, symbol)
    
    # 步驟 2: 執行動量策略
    print("\n【步驟 2/3】執行動量策略")
    for symbol in symbols:
        try:
            data = db.get_market_data(symbol)
            if data.empty:
                print(f"⚠️  {symbol}: 無數據")
                continue
            
            portfolio = run_momentum_strategy(data, lookback_period=200)
            run_id = db.save_backtest_run(
                portfolio,
                strategy_name=f'Momentum-{symbol}',
                start_date=str(data.index[0].date()),
                end_date=str(data.index[-1].date())
            )
            print(f"✅ {symbol}: Momentum 策略已保存 (run_id={run_id})")
        except Exception as e:
            print(f"❌ {symbol}: 失敗 - {str(e)}")
    
    # 步驟 3: 執行價值策略
    print("\n【步驟 3/3】執行價值策略")
    for symbol in symbols:
        try:
            data = db.get_market_data(symbol)
            if data.empty:
                print(f"⚠️  {symbol}: 無數據")
                continue
            
            portfolio = run_value_strategy(data, pe_threshold=15, pb_threshold=1.5)
            run_id = db.save_backtest_run(
                portfolio,
                strategy_name=f'Value-{symbol}',
                start_date=str(data.index[0].date()),
                end_date=str(data.index[-1].date())
            )
            print(f"✅ {symbol}: Value 策略已保存 (run_id={run_id})")
        except Exception as e:
            print(f"❌ {symbol}: 失敗 - {str(e)}")
    
    db.close()
    
    print("\n" + "="*60)
    print("✅ 測試完成！")
    print("請訪問 http://localhost:5000 查看儀表板")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
