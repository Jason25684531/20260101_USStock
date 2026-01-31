"""
動量策略 (Momentum Strategy)
基於價格突破 200 日高點的趨勢跟隨策略
"""
import pandas as pd
import numpy as np
import vectorbt as vbt


def run_momentum_strategy(
    data: pd.DataFrame,
    lookback_period: int = 200,
    initial_cash: float = 10000.0
) -> vbt.Portfolio:
    """
    執行動量策略回測
    
    策略邏輯：
    - 入場：當收盤價 > 過去 N 天的最高價時買入
    - 出場：當收盤價 < 過去 N 天的最高價時賣出
    
    Args:
        data: 市場數據 DataFrame (必須包含 'Close' 列)
        lookback_period: 回看週期 (預設 200 天)
        initial_cash: 初始資金 (預設 10000)
        
    Returns:
        VectorBT Portfolio 對象
    """
    print(f"\n{'='*60}")
    print(f"執行動量策略回測")
    print(f"{'='*60}")
    print(f"回看週期: {lookback_period} 天")
    print(f"初始資金: ${initial_cash:,.2f}")
    print(f"數據範圍: {data.index[0]} 到 {data.index[-1]}")
    print(f"總交易日: {len(data)} 天\n")
    
    # 確保使用正確的列名
    if 'Close' not in data.columns:
        raise ValueError("數據必須包含 'Close' 列")
    
    close = data['Close']
    
    # 計算 N 日滾動最高價（向量化操作）
    rolling_high = close.rolling(window=lookback_period, min_periods=lookback_period).max()
    
    # 生成交易信號（向量化操作）
    # 買入信號：收盤價 > N 日最高價
    entries = close > rolling_high.shift(1)
    
    # 賣出信號：收盤價 < N 日最高價
    exits = close < rolling_high.shift(1)
    
    # 打印信號統計
    total_entries = entries.sum()
    total_exits = exits.sum()
    print(f"📊 信號統計:")
    print(f"   買入信號: {total_entries} 次")
    print(f"   賣出信號: {total_exits} 次")
    
    # 使用 VectorBT 進行回測
    portfolio = vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        init_cash=initial_cash,
        fees=0.001,  # 0.1% 手續費
        slippage=0.001  # 0.1% 滑點
    )
    
    # 打印績效摘要
    print(f"\n📈 績效摘要:")
    stats = portfolio.stats()
    print(f"   總回報: {stats['Total Return [%]']:.2f}%")
    print(f"   夏普比率: {stats['Sharpe Ratio']:.2f}")
    print(f"   最大回撤: {stats['Max Drawdown [%]']:.2f}%")
    print(f"   勝率: {stats.get('Win Rate [%]', 0):.2f}%")
    print(f"   總交易次數: {stats['Total Trades']}")
    print(f"{'='*60}\n")
    
    return portfolio


def run_multi_symbol_momentum(
    data_dict: dict,
    lookback_period: int = 200,
    initial_cash: float = 10000.0
) -> dict:
    """
    對多個股票執行動量策略
    
    Args:
        data_dict: 股票代碼到數據 DataFrame 的字典
        lookback_period: 回看週期
        initial_cash: 每個股票的初始資金
        
    Returns:
        股票代碼到 Portfolio 對象的字典
    """
    results = {}
    
    for symbol, data in data_dict.items():
        print(f"\n處理股票: {symbol}")
        try:
            portfolio = run_momentum_strategy(data, lookback_period, initial_cash)
            results[symbol] = portfolio
        except Exception as e:
            print(f"❌ {symbol} 策略執行失敗: {str(e)}")
    
    return results
