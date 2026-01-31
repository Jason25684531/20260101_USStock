"""
Chips + Momentum Strategy (Smart Money)

基於機構持股（Chips）和動量指標的策略
買入信號：股價 > SMA(50) AND 機構持股 > 60%

Author: Quant System
Created: 2026-01-31
"""

import pandas as pd
from typing import Tuple, Optional


def calculate_signals(
    df: pd.DataFrame,
    inst_ownership_pct: Optional[float] = None,
    sma_period: int = 50,
    min_inst_ownership: float = 0.60
) -> pd.DataFrame:
    """
    計算 Chips + Momentum 策略信號
    
    買入條件：
    1. 價格 > SMA(50) - 動量指標
    2. 機構持股 > 60% - Smart Money 追蹤
    
    Args:
        df: 包含 OHLCV 數據的 DataFrame
        inst_ownership_pct: 機構持股百分比（0-1之間）
        sma_period: 簡單移動平均線週期
        min_inst_ownership: 最低機構持股要求（默認60%）
        
    Returns:
        添加了信號列的 DataFrame
    """
    df = df.copy()
    
    # 計算 SMA
    df['SMA'] = df['Close'].rolling(window=sma_period).mean()
    
    # 動量信號：價格 > SMA
    df['momentum_signal'] = df['Close'] > df['SMA']
    
    # Chips 信號：機構持股 > 閾值
    if inst_ownership_pct is not None:
        chips_signal = inst_ownership_pct >= min_inst_ownership
        df['chips_signal'] = chips_signal
    else:
        # 如果沒有機構持股數據，假設不滿足條件
        df['chips_signal'] = False
        print("⚠️  警告：沒有機構持股數據，Chips 信號設為 False")
    
    # 綜合信號：兩個條件都滿足
    df['signal'] = df['momentum_signal'] & df['chips_signal']
    
    # 持倉標記：當信號為 True 時持有
    df['position'] = df['signal'].astype(int)
    
    return df


def generate_report(
    df: pd.DataFrame,
    symbol: str,
    inst_ownership_pct: Optional[float] = None
) -> dict:
    """
    生成策略報告
    
    Args:
        df: 包含策略信號的 DataFrame
        symbol: 股票代碼
        inst_ownership_pct: 機構持股百分比
        
    Returns:
        策略報告字典
    """
    total_signals = df['signal'].sum()
    
    # 計算基本統計
    report = {
        'strategy_name': 'Chips + Momentum',
        'symbol': symbol,
        'total_bars': len(df),
        'total_signals': int(total_signals),
        'signal_rate': total_signals / len(df) if len(df) > 0 else 0,
        'inst_ownership_pct': inst_ownership_pct,
        'meets_chips_criteria': inst_ownership_pct >= 0.60 if inst_ownership_pct else False
    }
    
    # 如果有信號，計算收益
    if total_signals > 0:
        # 計算策略收益：只在信號期間持有
        df['strategy_returns'] = df['Close'].pct_change() * df['position'].shift(1)
        
        # 計算累積收益
        cumulative_return = (1 + df['strategy_returns']).prod() - 1
        
        # 計算年化收益（假設252個交易日）
        years = len(df) / 252
        annualized_return = (1 + cumulative_return) ** (1 / years) - 1 if years > 0 else 0
        
        report.update({
            'cumulative_return': cumulative_return,
            'annualized_return': annualized_return,
            'avg_signal_return': df.loc[df['position'] == 1, 'strategy_returns'].mean()
        })
    
    return report


def run_strategy(
    df: pd.DataFrame,
    symbol: str,
    inst_ownership_pct: Optional[float] = None,
    sma_period: int = 50,
    min_inst_ownership: float = 0.60
) -> Tuple[pd.DataFrame, dict]:
    """
    運行 Chips + Momentum 策略
    
    Args:
        df: 包含 OHLCV 數據的 DataFrame
        symbol: 股票代碼
        inst_ownership_pct: 機構持股百分比
        sma_period: SMA 週期
        min_inst_ownership: 最低機構持股要求
        
    Returns:
        (包含信號的 DataFrame, 策略報告字典)
    """
    print(f"\n{'='*60}")
    print(f"運行 Chips + Momentum 策略: {symbol}")
    print(f"{'='*60}")
    print(f"  數據期間: {df.index[0]} 到 {df.index[-1]}")
    print(f"  機構持股: {inst_ownership_pct*100:.2f}%" if inst_ownership_pct else "  機構持股: N/A")
    print(f"  SMA 週期: {sma_period}")
    print(f"  最低機構持股要求: {min_inst_ownership*100:.0f}%")
    
    # 計算信號
    df_signals = calculate_signals(
        df,
        inst_ownership_pct=inst_ownership_pct,
        sma_period=sma_period,
        min_inst_ownership=min_inst_ownership
    )
    
    # 生成報告
    report = generate_report(df_signals, symbol, inst_ownership_pct)
    
    # 打印結果
    print(f"\n策略結果:")
    print(f"  總信號數: {report['total_signals']}")
    print(f"  信號率: {report['signal_rate']*100:.2f}%")
    print(f"  滿足 Chips 條件: {'是' if report['meets_chips_criteria'] else '否'}")
    
    if report.get('cumulative_return'):
        print(f"  累積收益: {report['cumulative_return']*100:.2f}%")
        print(f"  年化收益: {report['annualized_return']*100:.2f}%")
    
    print(f"{'='*60}\n")
    
    return df_signals, report
