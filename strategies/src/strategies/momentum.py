"""
動量策略 (Momentum Strategy)

包含兩個篩選函式（用於每日選股）與一個 VectorBT 回測函式（用於歷史驗證）:
  1. screen_breakout  — 創新高延續動能（200日突破 + RSI + 多頭排列）
  2. screen_acceleration — 加速度指標（均線曲率向上 = 越漲越快）
  3. run_momentum_strategy — VectorBT 回測（向後相容）
"""
import pandas as pd
import numpy as np
from typing import Dict

from config import calc_rsi
from strategies.registry import BaseScreenStrategy


# ============================================================
# 篩選函式 — 用於每日選股推薦
# ============================================================


def screen_breakout(df: pd.DataFrame) -> Dict:
    """
    創新高延續動能策略篩選

    條件:
      1. 收盤價 = 過去 200 日最高價（突破長線壓力）
      2. RSI(14) > 60（強勢但未過熱）
      3. Close > SMA(60) > SMA(120)（多頭排列）

    Args:
        df: 含 Close 欄位, 至少 200 行

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    close_col = 'Close' if 'Close' in df.columns else 'close'
    close = df[close_col]

    if len(close) < 200:
        return {"pass": False, "score": 0.0, "details": "數據不足200日"}

    current = float(close.iloc[-1])
    rolling_high_200 = float(close.rolling(200).max().iloc[-1])
    rsi = float(calc_rsi(close, 14).iloc[-1])
    sma_60 = float(close.rolling(60).mean().iloc[-1])
    sma_120 = float(close.rolling(120).mean().iloc[-1])

    # 判定條件
    is_new_high = current >= rolling_high_200 * 0.99  # 容差 1%
    rsi_ok = rsi > 60
    ma_aligned = current > sma_60 > sma_120

    passed = is_new_high and rsi_ok and ma_aligned

    # 評分: 每個子條件 0.33 分, 滿分 1.0
    score = sum([
        0.34 if is_new_high else 0.0,
        0.33 if rsi_ok else 0.0,
        0.33 if ma_aligned else 0.0,
    ])

    parts = []
    parts.append(f"200日新高:{'✓' if is_new_high else '✗'}({current:.2f} vs {rolling_high_200:.2f})")
    parts.append(f"RSI:{rsi:.1f}{'✓' if rsi_ok else '✗'}")
    parts.append(f"多頭排列:{'✓' if ma_aligned else '✗'}")

    return {"pass": passed, "score": round(score, 2), "details": " | ".join(parts)}


class BreakoutStrategy(BaseScreenStrategy):
    """Registry 版: 創新高延續動能策略"""
    name = "breakout"
    description = "200日突破 + RSI強勢 + 多頭排列"
    category = "momentum"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_breakout(df)


def screen_acceleration(df: pd.DataFrame, n: int = 20) -> Dict:
    """
    加速度指標策略篩選

    公式: (price[t-n] + price[t]) / 2 > price[t - n/2]
    意義: 均線曲率向上 → 股價不只在漲, 而且越漲越快

    額外確認: 最近 n 日收益率 > 0（確保是在漲的）

    Args:
        df: 含 Close 欄位, 至少 n+1 行
        n: 回看天數 (預設 20)

    Returns:
        {"pass": bool, "score": float, "details": str}
    """
    close_col = 'Close' if 'Close' in df.columns else 'close'
    close = df[close_col]

    if len(close) < n + 1:
        return {"pass": False, "score": 0.0, "details": f"數據不足{n+1}日"}

    price_t = float(close.iloc[-1])
    price_t_n = float(close.iloc[-n - 1])
    price_t_half = float(close.iloc[-n // 2 - 1])

    midpoint = (price_t_n + price_t) / 2
    is_accelerating = midpoint > price_t_half
    is_rising = price_t > price_t_n

    passed = is_accelerating and is_rising

    score = sum([
        0.5 if is_accelerating else 0.0,
        0.5 if is_rising else 0.0,
    ])

    ret_n = (price_t / price_t_n - 1) * 100
    details = (
        f"加速度:{'✓' if is_accelerating else '✗'}"
        f"(mid={midpoint:.2f} vs half={price_t_half:.2f}) | "
        f"{n}日漲幅:{ret_n:+.1f}%{'✓' if is_rising else '✗'}"
    )

    return {"pass": passed, "score": round(score, 2), "details": details}


class AccelerationStrategy(BaseScreenStrategy):
    """Registry 版: 加速度指標策略"""
    name = "acceleration"
    description = "均線曲率向上 = 越漲越快"
    category = "momentum"

    def screen(self, df: pd.DataFrame, info: dict) -> Dict:
        return screen_acceleration(df, n=20)


# ============================================================
# VectorBT 回測函式 — 向後相容
# ============================================================

def run_momentum_strategy(
    data: pd.DataFrame,
    lookback_period: int = 200,
    initial_cash: float = 10000.0
):
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

    if 'Close' not in data.columns:
        raise ValueError("數據必須包含 'Close' 列")

    close = data['Close']

    import vectorbt as vbt  # lazy import — 僅回測時需要

    rolling_high = close.rolling(window=lookback_period, min_periods=lookback_period).max()
    entries = close > rolling_high.shift(1)
    exits = close < rolling_high.shift(1)

    total_entries = entries.sum()
    total_exits = exits.sum()
    print(f"📊 信號統計:")
    print(f"   買入信號: {total_entries} 次")
    print(f"   賣出信號: {total_exits} 次")

    portfolio = vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        init_cash=initial_cash,
        fees=0.001,
        slippage=0.001
    )

    stats = portfolio.stats()
    print(f"\n📈 績效摘要:")
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
