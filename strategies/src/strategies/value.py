"""
價值策略 (Value Strategy)
基於基本面指標 (PE/PB) 的價值投資策略
"""
import pandas as pd
import numpy as np


def run_value_strategy(
    data: pd.DataFrame,
    pe_threshold: float = 15.0,
    pb_threshold: float = 1.5,
    initial_cash: float = 10000.0,
    rebalance_freq: str = '1M'
):
    """
    執行價值策略回測
    
    策略邏輯：
    - 入場：當 PE < 15 且 PB < 1.5 時買入
    - 出場：當 PE >= 15 或 PB >= 1.5 時賣出
    - 定期重新平衡（預設每月）
    
    Args:
        data: 市場數據 DataFrame (必須包含 'Close', 'pe_ratio', 'pb_ratio' 列)
        pe_threshold: PE 比率閾值 (預設 15)
        pb_threshold: PB 比率閾值 (預設 1.5)
        initial_cash: 初始資金 (預設 10000)
        rebalance_freq: 重新平衡頻率 (預設 '1M' = 每月)
        
    Returns:
        VectorBT Portfolio 對象
    """
    print(f"\n{'='*60}")
    print(f"執行價值策略回測")
    print(f"{'='*60}")
    print(f"PE 閾值: {pe_threshold}")
    print(f"PB 閾值: {pb_threshold}")
    print(f"初始資金: ${initial_cash:,.2f}")
    print(f"數據範圍: {data.index[0]} 到 {data.index[-1]}")
    print(f"總交易日: {len(data)} 天\n")
    
    # 確保使用正確的列名
    required_columns = ['Close']
    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"數據必須包含 '{col}' 列")
    
    close = data['Close']
    
    # 如果沒有 PE/PB 數據，跳過（不再使用隨機模擬）
    if 'pe_ratio' not in data.columns or 'pb_ratio' not in data.columns:
        print("⚠️  警告: 未找到基本面數據 (pe_ratio/pb_ratio)，策略將不會產生任何買入信號")
        pe_ratio = pd.Series(999.0, index=data.index)
        pb_ratio = pd.Series(999.0, index=data.index)
    else:
        pe_ratio = data['pe_ratio'].fillna(999)  # 填充缺失值為高值
        pb_ratio = data['pb_ratio'].fillna(999)
    
    # 生成交易信號（向量化操作）
    # 買入信號：PE < threshold AND PB < threshold
    value_signal = (pe_ratio < pe_threshold) & (pb_ratio < pb_threshold)
    
    # 為了避免頻繁交易，使用重新平衡邏輯
    # 在每個重新平衡週期開始時檢查信號
    rebalance_mask = pd.Series(False, index=data.index)
    
    # 使用 resample 來標記重新平衡點
    if rebalance_freq:
        resampled = close.resample(rebalance_freq).first()
        for date in resampled.index:
            # 找到最接近的交易日
            closest_date = close.index[close.index >= date][0] if any(close.index >= date) else close.index[-1]
            rebalance_mask[closest_date] = True
    else:
        # 如果不重新平衡，每天都檢查
        rebalance_mask[:] = True
    
    # 只在重新平衡日檢查信號
    entries = value_signal & rebalance_mask
    exits = ~value_signal & rebalance_mask
    
    # 打印信號統計
    total_entries = entries.sum()
    total_exits = exits.sum()
    signal_days = value_signal.sum()
    print(f"📊 信號統計:")
    print(f"   符合價值條件的天數: {signal_days} 天 ({signal_days/len(data)*100:.1f}%)")
    print(f"   買入信號: {total_entries} 次")
    print(f"   賣出信號: {total_exits} 次")
    
    import vectorbt as vbt  # lazy import — 僅回測時需要

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


def run_multi_symbol_value(
    data_dict: dict,
    pe_threshold: float = 15.0,
    pb_threshold: float = 1.5,
    initial_cash: float = 10000.0
) -> dict:
    """
    對多個股票執行價值策略
    
    Args:
        data_dict: 股票代碼到數據 DataFrame 的字典
        pe_threshold: PE 比率閾值
        pb_threshold: PB 比率閾值
        initial_cash: 每個股票的初始資金
        
    Returns:
        股票代碼到 Portfolio 對象的字典
    """
    results = {}
    
    for symbol, data in data_dict.items():
        print(f"\n處理股票: {symbol}")
        try:
            portfolio = run_value_strategy(
                data, 
                pe_threshold, 
                pb_threshold, 
                initial_cash
            )
            results[symbol] = portfolio
        except Exception as e:
            print(f"❌ {symbol} 策略執行失敗: {str(e)}")
    
    return results
