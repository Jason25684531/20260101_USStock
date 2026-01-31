"""
Growth (PEG) Strategy

基於 PEG 比率和營收增長的成長型策略
買入信號：PEG < 1.5 AND 營收增長率 > 20%

Author: Quant System
Created: 2026-01-31
"""

import pandas as pd
from typing import Tuple, Optional


def calculate_signals(
    df: pd.DataFrame,
    peg_ratio: Optional[float] = None,
    revenue_growth_yoy: Optional[float] = None,
    max_peg: float = 1.5,
    min_revenue_growth: float = 0.20
) -> pd.DataFrame:
    """
    計算 Growth (PEG) 策略信號
    
    買入條件：
    1. PEG < 1.5 - 合理估值的成長股
    2. 營收增長率 > 20% - 高成長性
    
    Args:
        df: 包含 OHLCV 數據的 DataFrame
        peg_ratio: PEG 比率
        revenue_growth_yoy: 年度營收增長率（0-1之間，例如 0.25 表示 25%）
        max_peg: PEG 上限（默認1.5）
        min_revenue_growth: 最低營收增長率（默認20%）
        
    Returns:
        添加了信號列的 DataFrame
    """
    df = df.copy()
    
    # PEG 信號：PEG < 閾值
    peg_signal = False
    if peg_ratio is not None and peg_ratio > 0:
        peg_signal = peg_ratio <= max_peg
        df['peg_signal'] = peg_signal
        df['peg_ratio'] = peg_ratio
    else:
        df['peg_signal'] = False
        df['peg_ratio'] = None
        print("⚠️  警告：沒有有效的 PEG 數據")
    
    # 營收增長信號：增長率 > 閾值
    growth_signal = False
    if revenue_growth_yoy is not None:
        growth_signal = revenue_growth_yoy >= min_revenue_growth
        df['growth_signal'] = growth_signal
        df['revenue_growth'] = revenue_growth_yoy
    else:
        df['growth_signal'] = False
        df['revenue_growth'] = None
        print("⚠️  警告：沒有營收增長數據")
    
    # 綜合信號：兩個條件都滿足
    df['signal'] = df['peg_signal'] & df['growth_signal']
    
    # 持倉標記：當信號為 True 時持有
    df['position'] = df['signal'].astype(int)
    
    return df


def generate_report(
    df: pd.DataFrame,
    symbol: str,
    peg_ratio: Optional[float] = None,
    revenue_growth_yoy: Optional[float] = None
) -> dict:
    """
    生成策略報告
    
    Args:
        df: 包含策略信號的 DataFrame
        symbol: 股票代碼
        peg_ratio: PEG 比率
        revenue_growth_yoy: 營收增長率
        
    Returns:
        策略報告字典
    """
    total_signals = df['signal'].sum()
    
    # 計算基本統計
    report = {
        'strategy_name': 'Growth (PEG)',
        'symbol': symbol,
        'total_bars': len(df),
        'total_signals': int(total_signals),
        'signal_rate': total_signals / len(df) if len(df) > 0 else 0,
        'peg_ratio': peg_ratio,
        'revenue_growth_yoy': revenue_growth_yoy,
        'meets_peg_criteria': peg_ratio <= 1.5 if peg_ratio else False,
        'meets_growth_criteria': revenue_growth_yoy >= 0.20 if revenue_growth_yoy else False
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
        
        # 計算夏普比率
        sharpe_ratio = 0
        if df['strategy_returns'].std() > 0:
            sharpe_ratio = (df['strategy_returns'].mean() / df['strategy_returns'].std()) * (252 ** 0.5)
        
        report.update({
            'cumulative_return': cumulative_return,
            'annualized_return': annualized_return,
            'sharpe_ratio': sharpe_ratio,
            'avg_signal_return': df.loc[df['position'] == 1, 'strategy_returns'].mean()
        })
    
    return report


def run_strategy(
    df: pd.DataFrame,
    symbol: str,
    peg_ratio: Optional[float] = None,
    revenue_growth_yoy: Optional[float] = None,
    max_peg: float = 1.5,
    min_revenue_growth: float = 0.20
) -> Tuple[pd.DataFrame, dict]:
    """
    運行 Growth (PEG) 策略
    
    Args:
        df: 包含 OHLCV 數據的 DataFrame
        symbol: 股票代碼
        peg_ratio: PEG 比率
        revenue_growth_yoy: 年度營收增長率
        max_peg: PEG 上限
        min_revenue_growth: 最低營收增長率
        
    Returns:
        (包含信號的 DataFrame, 策略報告字典)
    """
    print(f"\n{'='*60}")
    print(f"運行 Growth (PEG) 策略: {symbol}")
    print(f"{'='*60}")
    print(f"  數據期間: {df.index[0]} 到 {df.index[-1]}")
    print(f"  PEG 比率: {peg_ratio:.2f}" if peg_ratio else "  PEG 比率: N/A")
    print(f"  營收增長率: {revenue_growth_yoy*100:.2f}%" if revenue_growth_yoy else "  營收增長率: N/A")
    print(f"  PEG 上限: {max_peg}")
    print(f"  最低營收增長率: {min_revenue_growth*100:.0f}%")
    
    # 計算信號
    df_signals = calculate_signals(
        df,
        peg_ratio=peg_ratio,
        revenue_growth_yoy=revenue_growth_yoy,
        max_peg=max_peg,
        min_revenue_growth=min_revenue_growth
    )
    
    # 生成報告
    report = generate_report(df_signals, symbol, peg_ratio, revenue_growth_yoy)
    
    # 打印結果
    print(f"\n策略結果:")
    print(f"  總信號數: {report['total_signals']}")
    print(f"  信號率: {report['signal_rate']*100:.2f}%")
    print(f"  滿足 PEG 條件: {'是' if report['meets_peg_criteria'] else '否'}")
    print(f"  滿足成長條件: {'是' if report['meets_growth_criteria'] else '否'}")
    
    if report.get('cumulative_return'):
        print(f"  累積收益: {report['cumulative_return']*100:.2f}%")
        print(f"  年化收益: {report['annualized_return']*100:.2f}%")
        print(f"  夏普比率: {report['sharpe_ratio']:.2f}")
    
    print(f"{'='*60}\n")
    
    return df_signals, report
